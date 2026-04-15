"""プロセス内メモリレスポンスキャッシュ + DB 永続化バックエンド

`/api/analysis/*` の GET レスポンスをキャッシュするための軽量ストア。
- TTL ベースで自動失効（デフォルト 300 秒）
- LRU 方式で最大 256 エントリ
- `DATA_VERSION` をキーに組み込むことで、mutation 時の一括無効化を実現
- `PLAYER_VERSION` を選手スコープで持ち、特定選手のみ無効化も可能
- in-memory + DB (AnalysisCache テーブル) の 2 層構成。
  プロセス再起動後も DB から復元できるので、コールドスタート後の
  解析タブ初回描画も高速。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

# モジュールグローバル状態
MEMORY_CACHE: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
MAX_ENTRIES: int = 256
DATA_VERSION: int = 0
# 選手単位キャッシュ無効化用バージョン（pid -> 連番）
PLAYER_VERSION: dict[int, int] = {}
DEFAULT_TTL: float = 300.0

# スレッドセーフ用ロック
_LOCK = threading.Lock()

# build_key 用: query 文字列から player_id を拾う正規表現
_PLAYER_ID_RE = re.compile(r"player_id=(\d+)")

_logger = logging.getLogger(__name__)


def _session():
    """短命 DB セッションを返す（import 失敗時は None）。

    テスト環境等で database 層が import できない場合は全 DB 操作を
    no-op にするための軽量ガード。
    """
    try:
        from backend.db.database import SessionLocal  # noqa: WPS433
        return SessionLocal()
    except Exception as exc:
        _logger.debug("response_cache: SessionLocal import failed: %s", exc)
        return None


def _db_lookup(key: str) -> Optional[Any]:
    """DB から該当行を引き、有効なら value を返す。期限切れなら削除して None。"""
    s = _session()
    if s is None:
        return None
    try:
        from backend.db.models import AnalysisCache  # noqa: WPS433
        row = s.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first()
        if row is None:
            return None
        if row.expires_at is None or row.expires_at < datetime.utcnow():
            s.delete(row)
            s.commit()
            return None
        try:
            return json.loads(row.result_json)
        except Exception:
            return None
    except Exception as exc:
        _logger.debug("response_cache: DB lookup failed: %s", exc)
        return None
    finally:
        try:
            s.close()
        except Exception:
            pass


def _db_upsert(
    key: str,
    value: Any,
    ttl: float,
    player_id: Optional[int],
    analysis_type: str,
    filters_json: str,
) -> None:
    """DB に upsert（同一 cache_key が存在すれば更新、無ければ insert）。"""
    s = _session()
    if s is None:
        return
    try:
        from backend.db.models import AnalysisCache  # noqa: WPS433
        try:
            result_json = json.dumps(value, default=str)
        except Exception as exc:
            _logger.debug("response_cache: json.dumps failed: %s", exc)
            return
        now = datetime.utcnow()
        expires = now + timedelta(seconds=float(ttl))
        row = s.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first()
        pid_val = int(player_id) if player_id is not None else 0
        if row is None:
            row = AnalysisCache(
                cache_key=key,
                player_id=pid_val,
                analysis_type=analysis_type[:50] if analysis_type else "unknown",
                filters_json=filters_json or "{}",
                result_json=result_json,
                sample_size=0,
                confidence_level=0.0,
                computed_at=now,
                expires_at=expires,
            )
            s.add(row)
        else:
            row.player_id = pid_val
            row.analysis_type = (analysis_type or row.analysis_type or "unknown")[:50]
            row.filters_json = filters_json or row.filters_json or "{}"
            row.result_json = result_json
            row.computed_at = now
            row.expires_at = expires
        s.commit()
    except Exception as exc:
        _logger.debug("response_cache: DB upsert failed: %s", exc)
        try:
            s.rollback()
        except Exception:
            pass
    finally:
        try:
            s.close()
        except Exception:
            pass


def _db_delete_all() -> None:
    s = _session()
    if s is None:
        return
    try:
        from backend.db.models import AnalysisCache  # noqa: WPS433
        s.query(AnalysisCache).delete()
        s.commit()
    except Exception as exc:
        _logger.debug("response_cache: DB delete_all failed: %s", exc)
        try:
            s.rollback()
        except Exception:
            pass
    finally:
        try:
            s.close()
        except Exception:
            pass


def _db_delete_players(pids: list[int]) -> None:
    if not pids:
        return
    s = _session()
    if s is None:
        return
    try:
        from backend.db.models import AnalysisCache  # noqa: WPS433
        s.query(AnalysisCache).filter(AnalysisCache.player_id.in_(pids)).delete(synchronize_session=False)
        s.commit()
    except Exception as exc:
        _logger.debug("response_cache: DB delete_players failed: %s", exc)
        try:
            s.rollback()
        except Exception:
            pass
    finally:
        try:
            s.close()
        except Exception:
            pass


def get(key: str) -> Optional[Any]:
    """キャッシュ検索。

    1. in-memory を見る
    2. 無ければ DB を検索し、有効なら in-memory に復元して返す
    """
    with _LOCK:
        entry = MEMORY_CACHE.get(key)
        if entry is not None:
            expires_at, value = entry
            if expires_at < time.monotonic():
                MEMORY_CACHE.pop(key, None)
            else:
                MEMORY_CACHE.move_to_end(key)
                return value

    # in-memory ミス → DB fallback
    value = _db_lookup(key)
    if value is None:
        return None
    # DB ヒット時は残り TTL が不明なので DEFAULT_TTL で in-memory に載せ直す
    with _LOCK:
        expires_at = time.monotonic() + DEFAULT_TTL
        MEMORY_CACHE[key] = (expires_at, value)
        MEMORY_CACHE.move_to_end(key)
        while len(MEMORY_CACHE) > MAX_ENTRIES:
            MEMORY_CACHE.popitem(last=False)
    return value


def set(  # noqa: A001
    key: str,
    value: Any,
    ttl: float = DEFAULT_TTL,
    player_id: Optional[int] = None,
    analysis_type: str = "unknown",
    filters_json: str = "{}",
) -> None:
    """値をキャッシュに保存（in-memory + DB write-through）。

    - MAX_ENTRIES 超過時は先頭（最古）から evict
    - DB 書き込みは失敗しても in-memory キャッシュは有効
    """
    expires_at = time.monotonic() + float(ttl)
    with _LOCK:
        if key in MEMORY_CACHE:
            MEMORY_CACHE.move_to_end(key)
        MEMORY_CACHE[key] = (expires_at, value)
        while len(MEMORY_CACHE) > MAX_ENTRIES:
            MEMORY_CACHE.popitem(last=False)
    # write-through（ロック外で DB にアクセス）
    _db_upsert(key, value, ttl, player_id, analysis_type, filters_json)


def bump_version() -> int:
    """DATA_VERSION を 1 繰り上げ、既存キャッシュを実質無効化する。

    in-memory は明示的にクリアし、DB の analysis_cache も全削除する。
    """
    global DATA_VERSION
    with _LOCK:
        DATA_VERSION += 1
        MEMORY_CACHE.clear()
        new_version = DATA_VERSION
    _db_delete_all()
    return new_version


def bump_players(player_ids: Iterable[Optional[int]]) -> None:
    """指定選手の PLAYER_VERSION を +1 し、DB の該当行も削除する。

    None はスキップ。他選手のキャッシュは生き残る。
    """
    bumped: list[int] = []
    with _LOCK:
        for pid in player_ids:
            if pid is None:
                continue
            try:
                ipid = int(pid)
            except (TypeError, ValueError):
                continue
            PLAYER_VERSION[ipid] = PLAYER_VERSION.get(ipid, 0) + 1
            bumped.append(ipid)
    if bumped:
        _db_delete_players(bumped)


def player_version(pid: Optional[int]) -> int:
    """指定選手の PLAYER_VERSION を返す。未登録・None は 0。"""
    if pid is None:
        return 0
    try:
        ipid = int(pid)
    except (TypeError, ValueError):
        return 0
    with _LOCK:
        return PLAYER_VERSION.get(ipid, 0)


def clear() -> None:
    """キャッシュ全消去（API 無効化用）。DATA_VERSION も bump する。"""
    bump_version()


def _extract_player_id(params: dict) -> Optional[int]:
    """params から選手スコープ用 pid を推定する。

    優先順位:
    1. "pid" キー（X-Player-Id ヘッダ由来 / ミドルウェアがセット）
    2. "q" キー（query string）中の `player_id=N`
    どちらも取れなければ None。
    """
    raw_pid = params.get("pid")
    if raw_pid not in (None, ""):
        try:
            return int(raw_pid)
        except (TypeError, ValueError):
            pass
    q = params.get("q")
    if isinstance(q, str) and q:
        m = _PLAYER_ID_RE.search(q)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def build_key(prefix: str, params: dict) -> str:
    """プレフィックス + DATA_VERSION + PLAYER_VERSION + params ハッシュからキー生成。"""
    with _LOCK:
        gv = DATA_VERSION
    pid = _extract_player_id(params)
    pv = player_version(pid)
    raw = json.dumps(params, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()
    return f"{prefix}:gv{gv}:pv{pv}:{digest}"


def stats() -> dict:
    """デバッグ / モニタリング用の簡易統計"""
    with _LOCK:
        return {
            "entries": len(MEMORY_CACHE),
            "max_entries": MAX_ENTRIES,
            "data_version": DATA_VERSION,
            "player_versions": dict(PLAYER_VERSION),
        }

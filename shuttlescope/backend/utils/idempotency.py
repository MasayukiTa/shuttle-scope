"""Idempotency-Key ヘッダ対応 (Phase B2)。

X-Idempotency-Key ヘッダを受領し、同じキーでの 2 回目以降のリクエストは
保存済みレスポンスを返す（業務ロジックを再実行しない）。

対象操作 (副作用ありかつ二重実行が問題になるもの):
  - POST /api/matches/{id}/reissue_video_token
  - DELETE /api/matches/{id}
  - GET /api/export/package (二重ダウンロード時の access_log 重複防止)

設計:
  - 24 時間保持（_TTL_SECONDS）
  - **DB 永続化** + in-memory 短期キャッシュ
    Round 258 R9 V6 fix (deep audit): 旧 docstring は "in-memory + DB 永続化のハイブリッド"
    を主張していたが、実装は in-memory dict のみ。PM2 restart / NSSM 再起動で 24h
    dedup window が消し飛び、replay 攻撃 (token 再発行 / export 二重 access_log) が
    成立していた。本コミットで `IdempotencyRecord` テーブルを実体化し、process restart
    でも replay 防御が機能するようにする。in-memory dict は read 高速化用の短期キャッシュ。
  - キー形式: 任意の URL-safe 文字列、min 8 / max 128 文字
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TTL_SECONDS = 24 * 60 * 60
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")


@dataclass
class IdempotencyRecord:
    key: str
    user_id: Optional[int]
    endpoint: str
    response_json: str
    status_code: int
    created_at: float = field(default_factory=time.time)


_records: Dict[str, IdempotencyRecord] = {}
_lock = Lock()

# 予約中 (処理開始〜完了/失敗) のキーを保持する process-local なテーブル。
# key -> (user_id, endpoint, reserved_at)。
#
# なぜ必要か (2026-11-05 の穴):
#   `store()` は commit 成功後にしか呼ばれないため、commit より前に失敗した
#   リクエストは冪等レコードを残さない。レスポンス喪失後の自動再送は本処理を
#   最初からやり直し、(set_id, rally_num) の一意制約や strokes の重複を踏む。
#   予約を「処理の最初」に取り、完了するまで同じキーの近接再送を弾くことで、
#   二重処理そのものを入口で止める。
#
# 設計:
#   - 予約は in-memory のみ (完了レコードのような DB 永続化はしない)。守りたいのは
#     レスポンス喪失後の自動再送 = 同一プロセスへの近接再送であり、これは
#     in-memory で十分。プロセス再起動後の replay は従来どおり完了レコード
#     (_db_store) が担う。
#   - 予約には TTL を設け、クラッシュ等で release されなかった予約が永久に
#     キーを塞がないようにする (_RESERVATION_TTL_SECONDS)。
_reservations: Dict[str, "_Reservation"] = {}

# 予約の有効期間。これを過ぎた予約は「処理が落ちて release されなかった」と
# みなして上書き可能にする。batch_save_rally は数秒で終わるので短くてよいが、
# 遅い DB でも処理が終わるだけの余裕をみて 120 秒とする。
_RESERVATION_TTL_SECONDS = 120


@dataclass
class _Reservation:
    user_id: Optional[int]
    endpoint: str
    reserved_at: float = field(default_factory=time.time)

# Round 258 R9 V6 fix (deep audit): DB 永続化のために AnalysisCache テーブルを
# 流用する (idempotency 専用 model + alembic migration を別途用意するより軽量)。
# key プレフィクスで namespace を分ける: "idem:" + key
_IDEM_KEY_PREFIX = "idem:"


def is_valid_key(key: str) -> bool:
    """X-Idempotency-Key 形式検証。"""
    return bool(_KEY_RE.match(key or ""))


def _gc_expired() -> None:
    """期限切れエントリを破棄する (完了レコードと予約の両方)。"""
    now = time.time()
    expired = [k for k, r in _records.items() if now - r.created_at > _TTL_SECONDS]
    for k in expired:
        _records.pop(k, None)
    stale = [
        k
        for k, rv in _reservations.items()
        if now - rv.reserved_at > _RESERVATION_TTL_SECONDS
    ]
    for k in stale:
        _reservations.pop(k, None)


def _db_get(key: str) -> Optional[IdempotencyRecord]:
    """AnalysisCache から idempotency record を読む。

    Round 258 R10 P0 fix (regression audit): R9 で AnalysisCache.key / .payload と
    書いていたが実際の column 名は cache_key / result_json で、毎回 AttributeError
    で warning に落ちて in-memory-only に degrade していた (V6 fix が完全 noop)。
    正しい column 名 + NOT NULL 制約 (player_id / analysis_type / filters_json /
    expires_at) を満たす形で書き直す。
    """
    try:
        from datetime import datetime
        from backend.db.database import SessionLocal
        from backend.db.models import AnalysisCache
        with SessionLocal() as db:
            rec = (
                db.query(AnalysisCache)
                .filter(AnalysisCache.cache_key == _IDEM_KEY_PREFIX + key)
                .first()
            )
            if rec is None:
                return None
            if rec.expires_at and rec.expires_at < datetime.utcnow():
                try:
                    db.delete(rec)
                    db.commit()
                except Exception:
                    pass
                return None
            try:
                meta = json.loads(rec.result_json or "{}")
            except Exception:
                return None
            return IdempotencyRecord(
                key=key,
                user_id=meta.get("user_id"),
                endpoint=meta.get("endpoint", ""),
                response_json=meta.get("response_json", ""),
                status_code=int(meta.get("status_code", 200)),
                created_at=float(meta.get("created_at", time.time())),
            )
    except Exception as exc:
        logger.warning("idempotency DB read failed: %s", exc)
        return None


def _db_store(rec: IdempotencyRecord) -> None:
    try:
        from datetime import datetime, timedelta
        from backend.db.database import SessionLocal
        from backend.db.models import AnalysisCache
        meta = {
            "user_id": rec.user_id,
            "endpoint": rec.endpoint,
            "response_json": rec.response_json,
            "status_code": rec.status_code,
            "created_at": rec.created_at,
        }
        meta_json = json.dumps(meta, ensure_ascii=False)
        # Round 258 R10 P0 fix: cache_key / result_json + NOT NULL 列 (player_id /
        # analysis_type / filters_json) もすべて埋める。idempotency は player に
        # 紐付かないので player_id=0 (sentinel) を入れて区別。
        now = datetime.utcnow()
        expires = now + timedelta(seconds=_TTL_SECONDS)
        with SessionLocal() as db:
            existing = (
                db.query(AnalysisCache)
                .filter(AnalysisCache.cache_key == _IDEM_KEY_PREFIX + rec.key)
                .first()
            )
            if existing is not None:
                # Round 258 R18 P1 fix (R18a-2 P1-2): 旧コードは `existing` を盲目的に
                # 上書きしていたが、`get_cached` は `(key, user_id, endpoint)` ミスマッチ
                # 時に **None を返して通常実行を進める** ため、別ユーザの key と衝突
                # した場合に store() が ORIGINAL ユーザのレコードを silently 破壊する
                # 経路があった。結果、元ユーザの再 POST は replay されず再実行され、
                # 二重課金 / 二重副作用が起こり得た。
                # 修正: existing を読み直し、(user_id, endpoint) ペアが一致しない場合
                # は **書き込みを抑止して warn ログのみ**。元レコードの replay 情報を
                # 守り、衝突した別ユーザは "ただし replay 不能" な代償として
                # 通常実行 (副作用) のみが進む状態にする。
                try:
                    existing_meta = json.loads(existing.result_json or "{}")
                    if (
                        existing_meta.get("user_id") != rec.user_id
                        or existing_meta.get("endpoint") != rec.endpoint
                    ):
                        logger.warning(
                            "idempotency key collision across users/endpoints: "
                            "key=%s existing_user=%s requesting_user=%s — refusing overwrite",
                            rec.key, existing_meta.get("user_id"), rec.user_id,
                        )
                        # commit せず return (other branch の db.commit にも到達しない)
                        return
                except Exception:
                    # parse 失敗時は安全側 (上書きしない) に倒す
                    logger.warning("idempotency existing meta unparsable for key=%s; refusing overwrite", rec.key)
                    return
                existing.result_json = meta_json
                existing.expires_at = expires
                existing.computed_at = now
            else:
                db.add(AnalysisCache(
                    cache_key=_IDEM_KEY_PREFIX + rec.key,
                    player_id=0,  # idempotency 用 sentinel
                    analysis_type="idempotency",
                    filters_json="{}",
                    result_json=meta_json,
                    sample_size=0,
                    confidence_level=0.0,
                    computed_at=now,
                    expires_at=expires,
                ))
            db.commit()
    except Exception as exc:
        logger.warning("idempotency DB write failed: %s", exc)


def get_cached(key: str, user_id: Optional[int], endpoint: str) -> Optional[IdempotencyRecord]:
    """同じ (key, user_id, endpoint) の保存済みレコードを返す。

    Round 258 R9 V6 fix: process-local cache → 不在なら DB を読みに行く。
    PM2 restart / NSSM 再起動でも 24h dedup window が維持される。
    """
    with _lock:
        _gc_expired()
        rec = _records.get(key)
        if rec is None:
            # DB から hydrate
            rec = _db_get(key)
            if rec is not None:
                _records[key] = rec  # in-memory cache に取り込む
        if rec is None:
            return None
        if rec.user_id != user_id or rec.endpoint != endpoint:
            # キーが他ユーザー/他エンドポイントで使われている → 衝突
            return None
        if time.time() - rec.created_at > _TTL_SECONDS:
            _records.pop(key, None)
            return None
        return rec


def store(
    key: str,
    user_id: Optional[int],
    endpoint: str,
    response_obj: Any,
    status_code: int = 200,
) -> None:
    """新規レコードを保存する。Round 258 R9 V6: DB にも persist。"""
    with _lock:
        rec = IdempotencyRecord(
            key=key,
            user_id=user_id,
            endpoint=endpoint,
            response_json=json.dumps(response_obj, ensure_ascii=False),
            status_code=status_code,
        )
        _records[key] = rec
        _db_store(rec)
        # 完了したので予約を解放する (予約→完了への昇格)。
        _reservations.pop(key, None)


RESERVED = "reserved"
REPLAY = "replay"
IN_PROGRESS = "in_progress"


def reserve(
    key: str, user_id: Optional[int], endpoint: str
) -> tuple[str, Optional[IdempotencyRecord]]:
    """処理の最初にキーを予約する。

    戻り値 (status, record):
      - (REPLAY, rec): 同じ (key, user_id, endpoint) の **完了** レコードが既に
        ある。呼び出し側は replay_response(rec) を返すこと。
      - (IN_PROGRESS, None): 同じキーが別の処理で予約中 (まだ完了も失敗もして
        いない)。呼び出し側は 409 を返すこと。TTL 超過の予約は残骸とみなし、
        奪って (RESERVED, None) を返す。
      - (RESERVED, None): 予約に成功した。呼び出し側は本処理へ進み、
        成功時は store()、commit 前の失敗時は release() を呼ぶこと。

    別ユーザ/別エンドポイントが同じ key を使っている場合は衝突とみなし、
    予約を与えず IN_PROGRESS を返して本処理を進ませない (get_cached が
    ミスマッチ時に None を返して二重副作用を許していた穴と同じ轍を踏まない)。
    """
    with _lock:
        _gc_expired()
        # 既に完了レコードがあるなら replay させる (DB からも hydrate)。
        rec = _records.get(key)
        if rec is None:
            rec = _db_get(key)
            if rec is not None:
                _records[key] = rec
        if rec is not None:
            if rec.user_id == user_id and rec.endpoint == endpoint:
                if time.time() - rec.created_at <= _TTL_SECONDS:
                    return (REPLAY, rec)
                # 期限切れの完了レコードは捨てて、新規予約に進む。
                _records.pop(key, None)
            else:
                # 別ユーザ/別エンドポイントのキー衝突。予約を与えない。
                return (IN_PROGRESS, None)

        now = time.time()
        existing = _reservations.get(key)
        if existing is not None:
            if now - existing.reserved_at <= _RESERVATION_TTL_SECONDS:
                # 進行中の予約がある。自分が所有者かどうかに関わらず、まだ
                # 処理中なので本処理を二重に走らせない。
                return (IN_PROGRESS, None)
            # TTL 超過: release されずに残った残骸。奪ってよい。
        _reservations[key] = _Reservation(user_id=user_id, endpoint=endpoint)
        return (RESERVED, None)


def release(key: str, user_id: Optional[int], endpoint: str) -> None:
    """予約を解放し、同じキーでの再送を可能にする。

    commit 前に失敗した経路 (DB 一時エラーで 503 を返す等) で呼ぶ。自分が所有
    する予約のときだけ消す (別処理が奪った予約を誤って消さない)。完了レコード
    (store 済み) には触れない。
    """
    with _lock:
        existing = _reservations.get(key)
        if existing is None:
            return
        if existing.user_id == user_id and existing.endpoint == endpoint:
            _reservations.pop(key, None)


def replay_response(rec: IdempotencyRecord) -> Any:
    """保存済みレスポンスを返す。"""
    try:
        return json.loads(rec.response_json)
    except Exception:
        return {"success": True, "data": None, "_idempotent_replay": True}

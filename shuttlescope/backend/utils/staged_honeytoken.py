"""Depth-staged honeytoken (R43).

アイデア:
  通常 R42 の honeytoken は `.env.example` / DB seed / frontend bundle に
  「置いておく」静的なもので、攻撃者がそれを「読みに来た」段階を検知する。

  これに対して staged honeytoken は **攻撃が一定の深さまで到達したときだけ
  動的に出現する餌**。

  具体的には:
    - canary endpoint を踏んだ
    - honeytoken を 1 度使った
    - 認証連続失敗が閾値超え
    - 偽 admin DB row にアクセスした
  などの「黒に近いグレー」シグナルを蓄積し、そのクライアント (IP) を
  `suspicious` ステートに昇格させる。

  以降、そのクライアントへの **正常な JSON レスポンスにだけ** 動的に
  `__legacy_api_token` 風のフィールドを混入させる。値は固定 honeytoken なので、
  攻撃者が「お、見落としていた token が response に入ってる」と思って次の
  request で使った瞬間、R42 の honeytoken detector が catch する。

  正規ユーザは:
    - そもそも suspicious 状態にならない
    - 仮に response の余分フィールドが見えても、それを使うコードを書かない
  ので false positive は事実上ゼロ。

性質:
  - 自陣攻撃 (active exploit) ではない。「自分の管理下のレスポンスに餌を
    付け足すだけ」なので合法・安全。
  - in-memory ステート (process restart で消える) を採用。永続化が必要なら
    後で audit log table を直接 query する形に置換できる。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─── Suspicious IP ステート ───────────────────────────────────────────────
# value: (mark_at, reason_history)
_suspicious: dict[str, tuple[float, list[str]]] = {}
_suspicious_lock = threading.Lock()

# 一度マークされたら 24 時間は suspicious 扱い。
_TTL_SEC = 24 * 3600

# staged response に混入させる lure 値。R42 の HONEYTOKENS にも登録済み。
LURE_TOKEN = "ss_canary_lure_staged_R3sp0nseBait_2026_xY7zQ"


def mark_suspicious(ip: Optional[str], reason: str) -> None:
    """この IP を「これ以降、レスポンスに餌を仕込んでよい」状態にする。"""
    if not ip or ip == "?":
        return
    now = time.time()
    with _suspicious_lock:
        prev = _suspicious.get(ip)
        if prev is None:
            _suspicious[ip] = (now, [reason])
        else:
            # 既存 reason リストに追加 (最大 16 個まで保持)
            _, hist = prev
            hist = (hist + [reason])[-16:]
            _suspicious[ip] = (now, hist)
        # 軽量 GC
        if len(_suspicious) > 4000:
            cutoff = now - _TTL_SEC
            for k in list(_suspicious.keys()):
                if _suspicious[k][0] < cutoff:
                    del _suspicious[k]
    logger.warning(
        "[staged_honeytoken] suspicious=mark ip=%s reason=%s", ip, reason
    )


def is_suspicious(ip: Optional[str]) -> bool:
    if not ip or ip == "?":
        return False
    with _suspicious_lock:
        v = _suspicious.get(ip)
    if v is None:
        return False
    mark_at, _hist = v
    if (time.time() - mark_at) > _TTL_SEC:
        with _suspicious_lock:
            _suspicious.pop(ip, None)
        return False
    return True


def get_reasons(ip: Optional[str]) -> list[str]:
    if not ip or ip == "?":
        return []
    with _suspicious_lock:
        v = _suspicious.get(ip)
    return list(v[1]) if v else []


# ─── Response への餌混入 ──────────────────────────────────────────────────
# 混入対象は dict 型の JSON レスポンスのみ。配列ルートや巨大 payload は触らない。
_MAX_INJECT_BYTES = 256 * 1024

# 餌を仕込むキー名 (攻撃者が「使ってみたくなる」naming)。
_INJECT_FIELDS = (
    "__legacy_api_token",      # 1st depth: header に貼って試す系
    "__internal_backup_token", # 2nd depth: より美味しそうな名前
)


def maybe_inject_lure_into_dict(data: Any, *, depth: int = 0) -> bool:
    """data が JSON-like dict なら 1 つだけ lure フィールドを上書き挿入する。

    既に同名キーが存在する場合は上書きせず別キーを試す。挿入できたら True。
    """
    if not isinstance(data, dict):
        return False
    for k in _INJECT_FIELDS:
        if k not in data:
            data[k] = LURE_TOKEN
            return True
    # 全部すでに使われていれば諦める
    return False


def maybe_inject_lure_into_json_bytes(body: bytes) -> Optional[bytes]:
    """JSON body bytes を decode → dict なら lure を注入 → 再 serialize する。

    失敗 / 対象外なら None を返す (= 元 body を変えない)。
    """
    if not body or len(body) > _MAX_INJECT_BYTES:
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    # よくある envelope `{"success": True, "data": {...}}` の中の data dict も
    # 餌の対象にする (depth=1)
    injected = maybe_inject_lure_into_dict(data)
    inner = data.get("data")
    if isinstance(inner, dict):
        # data 内側にも仕込めると、攻撃者が data.* を fingerprint してる場合に
        # 引っかかりやすい。両方仕込まれてもよい。
        if maybe_inject_lure_into_dict(inner):
            injected = True
    if not injected:
        return None
    try:
        return json.dumps(data, ensure_ascii=False).encode("utf-8")
    except Exception:
        return None

"""カメラ signaling WS の一回限り入場券。

なぜ資格情報を直接 URL に載せないか:
  WebSocket はブラウザから任意の Authorization ヘッダを付けられないため、
  資格情報はクエリに載せるしかない。しかし URL はアクセスログ・プロキシログ・
  Referer に残る。長命の資格情報をそこに置くと、ログを読めた者が後から
  セッションへ入れる。

  そこで参加者トークン (2 時間) は REST の本文でだけ扱い、WS には有効期間
  30 秒・使い捨ての ticket だけを渡す。ログに残っても再利用できない。

ticket は発行時に「どのセッションの・どのロールの・どの ID か」を束縛する。
WS ハンドラはクライアントが送ってきた role / participant_id を信用せず、
ticket に刻まれた値を使う。これにより「セッションコードを知っていれば他の
participant_id を騙れる」経路が閉じる。

保存はプロセス内メモリ。バックエンドは単一プロセスで動作し、寿命 30 秒の
使い捨てを DB に書くのは無駄な書き込みでしかない。プロセス再起動で全て
無効になるが、クライアントは接続のたびに取り直すので問題ない。
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Optional

# 入場券の寿命。取得 → WS 接続はすぐ続くので短くてよい。
TICKET_TTL_SEC = 30
# 異常時に無制限に溜めないための上限 (期限切れ掃除が追いつかない場合の保険)。
_MAX_TICKETS = 4096


@dataclass(frozen=True)
class WsTicketClaim:
    """入場券に刻まれた、クライアントが改ざんできない事実。"""
    session_code: str
    role: str                        # "device" | "viewer"
    participant_id: str
    expires_at: float


_LOCK = threading.Lock()
_TICKETS: dict[str, WsTicketClaim] = {}


def _purge_expired(now: float) -> None:
    """呼び出し側で _LOCK を保持していること。"""
    expired = [t for t, c in _TICKETS.items() if c.expires_at <= now]
    for t in expired:
        _TICKETS.pop(t, None)


def issue_ws_ticket(session_code: str, role: str, participant_id: str) -> str:
    """入場券を発行して平文を返す。"""
    now = time.time()
    ticket = secrets.token_urlsafe(32)
    claim = WsTicketClaim(
        session_code=session_code,
        role=role,
        participant_id=str(participant_id),
        expires_at=now + TICKET_TTL_SEC,
    )
    with _LOCK:
        _purge_expired(now)
        if len(_TICKETS) >= _MAX_TICKETS:
            # 期限切れを掃除してなお上限なら、最も古いものから捨てる。
            for oldest in sorted(_TICKETS, key=lambda t: _TICKETS[t].expires_at)[:64]:
                _TICKETS.pop(oldest, None)
        _TICKETS[ticket] = claim
    return ticket


def consume_ws_ticket(ticket: str) -> Optional[WsTicketClaim]:
    """入場券を使い切って中身を返す。無効・期限切れ・二度目は None。"""
    if not ticket:
        return None
    now = time.time()
    with _LOCK:
        _purge_expired(now)
        claim = _TICKETS.pop(ticket, None)
    if claim is None or claim.expires_at <= now:
        return None
    return claim


def clear_ws_tickets() -> None:
    """テスト用。プロセス内の入場券を全て破棄する。"""
    with _LOCK:
        _TICKETS.clear()

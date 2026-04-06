"""R-001/R-002: 共有セッション管理API（/api/sessions）

セッションライフサイクル:
  POST /api/sessions              → セッション作成（analystが試合開始時に呼ぶ）
  GET  /api/sessions/{code}       → セッション情報取得
  GET  /api/sessions/{code}/state → ライブスナップショット（コーチビュー初期化用）
  POST /api/sessions/{code}/join  → 参加者登録
  POST /api/sessions/{code}/end   → セッション終了
  GET  /api/sessions/match/{mid}  → 試合に紐づくアクティブセッション一覧
  GET  /api/sessions/my-info      → LAN IP / ポート情報（共有URL生成用）
"""
import random
import socket
import string
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import Match, SharedSession, SessionParticipant

router = APIRouter()


# ─── ユーティリティ ──────────────────────────────────────────────────────────

def _generate_code(length: int = 6) -> str:
    """ランダムな英数字セッションコードを生成"""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def _get_lan_ips() -> list[str]:
    """ローカル LAN の IPv4 アドレスを返す"""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith(("192.168.", "10.", "172.")):
                ips.append(ip)
    except Exception:
        pass
    # フォールバック
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    return list(dict.fromkeys(ips))  # 重複排除


# ─── リクエストモデル ─────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    match_id: int
    created_by_role: str = "analyst"


class ParticipantJoin(BaseModel):
    role: str = "coach"
    device_name: Optional[str] = None


# ─── エンドポイント ───────────────────────────────────────────────────────────

@router.post("/sessions", status_code=201)
def create_session(body: SessionCreate, db: Session = Depends(get_db)):
    """試合に対する共有セッションを作成。既存アクティブセッションがあれば再利用。"""
    match = db.get(Match, body.match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    # 既存アクティブセッション確認
    existing = (
        db.query(SharedSession)
        .filter(SharedSession.match_id == body.match_id, SharedSession.is_active.is_(True))
        .first()
    )
    if existing:
        return {"success": True, "data": _session_to_dict(existing, db)}

    # 新規作成（コード重複回避）
    for _ in range(10):
        code = _generate_code()
        if not db.query(SharedSession).filter(SharedSession.session_code == code).first():
            break

    session = SharedSession(
        match_id=body.match_id,
        session_code=code,
        created_by_role=body.created_by_role,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"success": True, "data": _session_to_dict(session, db)}


@router.get("/sessions/my-info")
def my_server_info():
    """LAN IP / ポート情報を返す（コーチへの共有URL生成用）"""
    lan_ips = _get_lan_ips()
    port = settings.API_PORT
    lan_mode = settings.LAN_MODE
    return {
        "success": True,
        "data": {
            "lan_ips": lan_ips,
            "port": port,
            "lan_mode": lan_mode,
            "accessible": lan_mode and bool(lan_ips),
        },
    }


@router.get("/sessions/match/{match_id}")
def sessions_for_match(match_id: int, db: Session = Depends(get_db)):
    """試合に紐づくアクティブセッション一覧"""
    sessions = (
        db.query(SharedSession)
        .filter(SharedSession.match_id == match_id, SharedSession.is_active.is_(True))
        .all()
    )
    return {"success": True, "data": [_session_to_dict(s, db) for s in sessions]}


@router.get("/sessions/{code}")
def get_session(code: str, db: Session = Depends(get_db)):
    """セッション情報取得"""
    session = db.query(SharedSession).filter(SharedSession.session_code == code).first()
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    return {"success": True, "data": _session_to_dict(session, db)}


@router.get("/sessions/{code}/state")
def session_state(code: str, db: Session = Depends(get_db)):
    """コーチビュー初期化用のライブスナップショット（REST版）"""
    from backend.ws.live import _build_session_snapshot

    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つからないか終了しています")

    snapshot = _build_session_snapshot(session, db)
    return {"success": True, "data": snapshot}


@router.post("/sessions/{code}/join")
def join_session(code: str, body: ParticipantJoin, db: Session = Depends(get_db)):
    """参加者登録（コーチ・ビューワーが接続時に呼ぶ）"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つからないか終了しています")

    participant = SessionParticipant(
        session_id=session.id,
        role=body.role,
        device_name=body.device_name,
        is_connected=True,
    )
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return {
        "success": True,
        "data": {
            "participant_id": participant.id,
            "session_code": code,
            "role": participant.role,
        },
    }


@router.post("/sessions/{code}/end")
def end_session(code: str, db: Session = Depends(get_db)):
    """セッション終了"""
    session = db.query(SharedSession).filter(SharedSession.session_code == code).first()
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    session.is_active = False
    db.commit()
    return {"success": True}


# ─── 内部ヘルパー ─────────────────────────────────────────────────────────────

def _session_to_dict(session: SharedSession, db: Session) -> dict:
    from backend.ws.live import manager
    lan_ips = _get_lan_ips()
    port = settings.API_PORT
    lan_mode = settings.LAN_MODE

    # コーチ向けアクセスURL
    coach_urls = []
    if lan_mode and lan_ips:
        for ip in lan_ips:
            coach_urls.append(f"http://{ip}:{port}/coach/{session.session_code}")

    return {
        "id": session.id,
        "match_id": session.match_id,
        "session_code": session.session_code,
        "created_by_role": session.created_by_role,
        "is_active": session.is_active,
        "created_at": session.created_at.isoformat(),
        "ws_connected": manager.connection_count(session.session_code),
        "coach_urls": coach_urls,
        "ws_url_template": f"ws://{{LAN_IP}}:{port}/ws/live/{session.session_code}",
    }

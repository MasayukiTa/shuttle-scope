"""R-001/R-002: 共有セッション管理API（/api/sessions）

セッションライフサイクル:
  POST /api/sessions                              → セッション作成（パスワード自動生成）
  GET  /api/sessions/{code}                       → セッション情報取得
  GET  /api/sessions/{code}/state                 → ライブスナップショット（コーチビュー初期化用）
  POST /api/sessions/{code}/join                  → 参加者登録（パスワード検証あり）
  POST /api/sessions/{code}/end                   → セッション終了
  GET  /api/sessions/match/{mid}                  → 試合に紐づくアクティブセッション一覧
  GET  /api/sessions/my-info                      → LAN IP / ポート情報
  GET  /api/sessions/{code}/devices               → 接続デバイス一覧
  POST /api/sessions/{code}/devices/{pid}/set-role         → connection_role 変更
  POST /api/sessions/{code}/devices/{pid}/activate-camera  → カメラ有効化（1台制限）
  POST /api/sessions/{code}/devices/{pid}/deactivate-camera→ カメラ降格
  POST /api/sessions/{code}/regenerate-password            → パスワード再生成
"""
import hashlib
import os
import random
import secrets
import socket
import string
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import Match, SharedSession, SessionParticipant

router = APIRouter()


# ─── パスワードユーティリティ ────────────────────────────────────────────────

def _generate_password(length: int = 8) -> str:
    """ランダムな英数字パスワードを生成"""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _hash_password(plain: str) -> str:
    """PBKDF2-SHA256 でパスワードをハッシュ（stdlib のみ使用）"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 100_000)
    return salt.hex() + ":" + dk.hex()


def _verify_password(plain: str, stored_hash: str) -> bool:
    """ハッシュ検証"""
    try:
        salt_hex, dk_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 100_000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ─── セッションコードユーティリティ ─────────────────────────────────────────

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
    device_type: Optional[str] = None   # iphone/ipad/pc/usb_camera/builtin_camera
    session_password: Optional[str] = None


class SetRoleBody(BaseModel):
    connection_role: str  # viewer/coach/analyst/camera_candidate/active_camera


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

    # パスワード自動生成
    plain_password = _generate_password()
    hashed = _hash_password(plain_password)

    session = SharedSession(
        match_id=body.match_id,
        session_code=code,
        created_by_role=body.created_by_role,
        password_hash=hashed,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    data = _session_to_dict(session, db)
    data["session_password"] = plain_password  # 初回のみ平文で返す
    return {"success": True, "data": data}


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
    """参加者登録（コーチ・ビューワーが接続時に呼ぶ）。パスワードが設定されている場合は検証する。"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つからないか終了しています")

    # パスワード検証
    if session.password_hash:
        if not body.session_password:
            raise HTTPException(status_code=401, detail="パスワードが必要です")
        if not _verify_password(body.session_password, session.password_hash):
            raise HTTPException(status_code=401, detail="パスワードが正しくありません")

    # デバイスタイプから source_capability を推定
    source_cap = "none"
    if body.device_type in ("iphone", "ipad", "usb_camera", "builtin_camera"):
        source_cap = "camera"
    elif body.device_type == "pc":
        source_cap = "viewer"

    participant = SessionParticipant(
        session_id=session.id,
        role=body.role,
        device_name=body.device_name,
        device_type=body.device_type,
        connection_role="viewer",
        source_capability=source_cap,
        connection_state="idle",
        authenticated_at=datetime.utcnow(),
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
            "connection_role": participant.connection_role,
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


# ─── デバイス管理エンドポイント ──────────────────────────────────────────────

@router.get("/sessions/{code}/devices")
def list_devices(code: str, db: Session = Depends(get_db)):
    """接続デバイス（参加者）一覧を返す"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    participants = (
        db.query(SessionParticipant)
        .filter(SessionParticipant.session_id == session.id)
        .order_by(SessionParticipant.joined_at)
        .all()
    )
    return {"success": True, "data": [_participant_to_dict(p) for p in participants]}


@router.post("/sessions/{code}/devices/{participant_id}/set-role")
def set_device_role(
    code: str,
    participant_id: int,
    body: SetRoleBody,
    db: Session = Depends(get_db),
):
    """参加者の connection_role を変更"""
    participant = _get_participant(code, participant_id, db)

    valid_roles = {"viewer", "coach", "analyst", "camera_candidate", "active_camera"}
    if body.connection_role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"無効なロール: {body.connection_role}")

    participant.connection_role = body.connection_role
    db.commit()
    return {"success": True, "data": _participant_to_dict(participant)}


@router.post("/sessions/{code}/devices/{participant_id}/activate-camera")
def activate_camera(
    code: str,
    participant_id: int,
    db: Session = Depends(get_db),
):
    """指定デバイスをアクティブカメラに昇格。既存の active_camera は camera_candidate に降格。"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    # 既存の active_camera を降格（1台制限）
    existing_active = (
        db.query(SessionParticipant)
        .filter(
            SessionParticipant.session_id == session.id,
            SessionParticipant.connection_role == "active_camera",
        )
        .all()
    )
    for p in existing_active:
        p.connection_role = "camera_candidate"
        p.connection_state = "idle"

    # 対象デバイスを昇格
    target = db.get(SessionParticipant, participant_id)
    if not target or target.session_id != session.id:
        raise HTTPException(status_code=404, detail="参加者が見つかりません")

    target.connection_role = "active_camera"
    target.connection_state = "sending_video"
    db.commit()
    return {"success": True, "data": _participant_to_dict(target)}


@router.post("/sessions/{code}/devices/{participant_id}/deactivate-camera")
def deactivate_camera(
    code: str,
    participant_id: int,
    db: Session = Depends(get_db),
):
    """アクティブカメラを camera_candidate に降格"""
    participant = _get_participant(code, participant_id, db)
    participant.connection_role = "camera_candidate"
    participant.connection_state = "idle"
    db.commit()
    return {"success": True, "data": _participant_to_dict(participant)}


@router.post("/sessions/{code}/regenerate-password")
def regenerate_password(code: str, db: Session = Depends(get_db)):
    """セッションパスワードを再生成。新しい平文パスワードを返す。"""
    session = db.query(SharedSession).filter(SharedSession.session_code == code).first()
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    plain_password = _generate_password()
    session.password_hash = _hash_password(plain_password)
    db.commit()
    return {"success": True, "data": {"session_password": plain_password}}


# ─── 内部ヘルパー ─────────────────────────────────────────────────────────────

def _get_participant(code: str, participant_id: int, db: Session) -> SessionParticipant:
    """セッション確認 + 参加者取得（共通バリデーション）"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    participant = db.get(SessionParticipant, participant_id)
    if not participant or participant.session_id != session.id:
        raise HTTPException(status_code=404, detail="参加者が見つかりません")
    return participant


def _participant_to_dict(p: SessionParticipant) -> dict:
    return {
        "id": p.id,
        "session_id": p.session_id,
        "role": p.role,
        "device_name": p.device_name,
        "device_type": p.device_type,
        "connection_role": p.connection_role,
        "source_capability": p.source_capability,
        "video_receive_enabled": p.video_receive_enabled,
        "authenticated_at": p.authenticated_at.isoformat() if p.authenticated_at else None,
        "connection_state": p.connection_state,
        "joined_at": p.joined_at.isoformat(),
        "last_seen_at": p.last_seen_at.isoformat(),
        "is_connected": p.is_connected,
    }


def _session_to_dict(session: SharedSession, db: Session) -> dict:
    from backend.ws.live import manager
    lan_ips = _get_lan_ips()
    port = settings.API_PORT
    lan_mode = settings.LAN_MODE

    # コーチ向けアクセスURL
    coach_urls = []
    camera_sender_urls = []
    if lan_mode and lan_ips:
        for ip in lan_ips:
            coach_urls.append(f"http://{ip}:{port}/coach/{session.session_code}")
            camera_sender_urls.append(f"http://{ip}:{port}/#/camera/{session.session_code}")

    return {
        "id": session.id,
        "match_id": session.match_id,
        "session_code": session.session_code,
        "created_by_role": session.created_by_role,
        "is_active": session.is_active,
        "created_at": session.created_at.isoformat(),
        "ws_connected": manager.connection_count(session.session_code),
        "coach_urls": coach_urls,
        "camera_sender_urls": camera_sender_urls,
        "ws_url_template": f"ws://{{LAN_IP}}:{port}/ws/live/{session.session_code}",
        "has_password": session.password_hash is not None,
    }

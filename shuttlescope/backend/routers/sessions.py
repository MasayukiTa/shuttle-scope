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
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import Match, SharedSession, SessionParticipant, LiveSource
from backend.utils.source_quality import compute_suitability

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
    device_uid: Optional[str] = None    # デバイス固有 ID（再接続認識用）


class ViewerPermissionBody(BaseModel):
    viewer_permission: str  # allowed / blocked / default


class RegisterSourceBody(BaseModel):
    source_kind: str              # iphone_webrtc/usb_camera/builtin_camera/pc_local
    participant_id: Optional[int] = None
    source_resolution: Optional[str] = None  # "1280x720"
    source_fps: Optional[int] = None


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

    # デバイスタイプから source_capability / device_class を推定
    source_cap = "none"
    dev_class = "pc"
    if body.device_type in ("iphone", "ipad", "usb_camera", "builtin_camera"):
        source_cap = "camera"
    if body.device_type == "iphone":
        dev_class = "phone"
    elif body.device_type == "ipad":
        dev_class = "tablet"
    elif body.device_type in ("usb_camera", "builtin_camera"):
        dev_class = "camera"

    # device_uid で同一デバイスの再接続を認識
    existing = None
    if body.device_uid:
        existing = (
            db.query(SessionParticipant)
            .filter(
                SessionParticipant.session_id == session.id,
                SessionParticipant.device_uid == body.device_uid,
            )
            .first()
        )
    if existing:
        existing.is_connected = True
        existing.authenticated_at = datetime.utcnow()
        existing.last_heartbeat = datetime.utcnow()
        if body.device_name:
            existing.device_name = body.device_name
        db.commit()
        db.refresh(existing)
        return {
            "success": True,
            "data": {
                "participant_id": existing.id,
                "session_code": code,
                "role": existing.role,
                "connection_role": existing.connection_role,
                "reconnected": True,
            },
        }

    participant = SessionParticipant(
        session_id=session.id,
        role=body.role,
        device_name=body.device_name,
        device_type=body.device_type,
        device_uid=body.device_uid,
        device_class=dev_class,
        connection_role="viewer",
        source_capability=source_cap,
        connection_state="idle",
        approval_status="pending",
        viewer_permission="default",
        display_size_class="large_tablet" if body.device_type == "ipad" else "standard",
        authenticated_at=datetime.utcnow(),
        last_heartbeat=datetime.utcnow(),
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


# ─── ステールカメラ自動解放 ───────────────────────────────────────────────────

STALE_CAMERA_THRESHOLD_SECONDS = 90  # ハートビート 3 回分（30s × 3）


def _release_stale_active_cameras(session_id: int, db: Session) -> int:
    """last_heartbeat が閾値を超えた active_camera を camera_candidate に降格。
    降格した件数を返す。"""
    threshold = datetime.utcnow() - timedelta(seconds=STALE_CAMERA_THRESHOLD_SECONDS)
    stale = (
        db.query(SessionParticipant)
        .filter(
            SessionParticipant.session_id == session_id,
            SessionParticipant.connection_role == "active_camera",
            SessionParticipant.last_heartbeat < threshold,
        )
        .all()
    )
    for p in stale:
        p.connection_role = "camera_candidate"
        p.connection_state = "idle"
    if stale:
        db.commit()
    return len(stale)


# ─── デバイス管理エンドポイント ──────────────────────────────────────────────

@router.get("/sessions/{code}/devices")
def list_devices(code: str, db: Session = Depends(get_db)):
    """接続デバイス（参加者）一覧を返す。
    取得前にステールな active_camera を自動降格する。"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    _release_stale_active_cameras(session.id, db)

    participants = (
        db.query(SessionParticipant)
        .filter(
            SessionParticipant.session_id == session.id,
            SessionParticipant.is_connected.is_(True),
        )
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


@router.post("/sessions/{code}/devices/{participant_id}/approve")
def approve_device(code: str, participant_id: int, db: Session = Depends(get_db)):
    """デバイスを承認（approval_status → approved）"""
    participant = _get_participant(code, participant_id, db)
    participant.approval_status = "approved"
    db.commit()
    return {"success": True, "data": _participant_to_dict(participant)}


@router.post("/sessions/{code}/devices/{participant_id}/reject")
def reject_device(code: str, participant_id: int, db: Session = Depends(get_db)):
    """デバイスを拒否（approval_status → rejected）"""
    participant = _get_participant(code, participant_id, db)
    participant.approval_status = "rejected"
    db.commit()
    return {"success": True, "data": _participant_to_dict(participant)}


@router.delete("/sessions/{code}/devices/{participant_id}")
def delete_participant(code: str, participant_id: int, db: Session = Depends(get_db)):
    """参加者レコードを削除（切断済みデバイスのゴーストを除去）"""
    participant = _get_participant(code, participant_id, db)
    db.delete(participant)
    db.commit()
    return {"success": True}


@router.delete("/sessions/{code}/devices")
def purge_disconnected(code: str, db: Session = Depends(get_db)):
    """切断済み（is_connected=False）参加者を一括削除"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    deleted = (
        db.query(SessionParticipant)
        .filter(
            SessionParticipant.session_id == session.id,
            SessionParticipant.is_connected.is_(False),
        )
        .all()
    )
    count = len(deleted)
    for p in deleted:
        db.delete(p)
    db.commit()
    return {"success": True, "data": {"deleted": count}}


@router.post("/sessions/{code}/devices/{participant_id}/heartbeat")
def device_heartbeat(code: str, participant_id: int, db: Session = Depends(get_db)):
    """デバイスのハートビートを更新（30 秒ごとに呼ぶ）。
    同時に同セッション内のステール active_camera を自動降格する。"""
    participant = _get_participant(code, participant_id, db)
    participant.last_heartbeat = datetime.utcnow()
    participant.is_connected = True
    db.commit()
    _release_stale_active_cameras(participant.session_id, db)
    return {"success": True}


@router.post("/sessions/{code}/devices/{participant_id}/set-viewer-permission")
def set_viewer_permission(
    code: str,
    participant_id: int,
    body: ViewerPermissionBody,
    db: Session = Depends(get_db),
):
    """ビューワー映像受信許可を設定"""
    valid = {"allowed", "blocked", "default"}
    if body.viewer_permission not in valid:
        raise HTTPException(status_code=400, detail=f"無効な値: {body.viewer_permission}")
    participant = _get_participant(code, participant_id, db)
    participant.viewer_permission = body.viewer_permission
    # viewer_permission=blocked なら video_receive_enabled も無効化
    if body.viewer_permission == "blocked":
        participant.video_receive_enabled = False
    db.commit()
    return {"success": True, "data": _participant_to_dict(participant)}


# ─── ライブソース管理エンドポイント ──────────────────────────────────────────

@router.get("/sessions/{code}/sources")
def list_sources(code: str, db: Session = Depends(get_db)):
    """セッションのライブソース一覧（優先度順）"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    sources = (
        db.query(LiveSource)
        .filter(LiveSource.session_id == session.id)
        .order_by(LiveSource.source_priority, LiveSource.id)
        .all()
    )
    return {"success": True, "data": [_source_to_dict(s) for s in sources]}


@router.post("/sessions/{code}/sources", status_code=201)
def register_source(code: str, body: RegisterSourceBody, db: Session = Depends(get_db)):
    """ライブソースを登録（PC がローカルカメラや iOS を登録する）"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    # ソース種別・解像度・fps からデフォルト優先度と suitability を計算
    priority, suitability = compute_suitability(
        body.source_kind, body.source_resolution, body.source_fps
    )

    source = LiveSource(
        session_id=session.id,
        participant_id=body.participant_id,
        source_kind=body.source_kind,
        source_priority=priority,
        source_resolution=body.source_resolution,
        source_fps=body.source_fps,
        source_status="candidate",
        suitability=suitability,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return {"success": True, "data": _source_to_dict(source)}


@router.post("/sessions/{code}/sources/{source_id}/activate")
def activate_source(code: str, source_id: int, db: Session = Depends(get_db)):
    """ソースをアクティブ化（1 ソース制限 — 既存 active を inactive に降格）"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    # 既存 active を降格
    db.query(LiveSource).filter(
        LiveSource.session_id == session.id,
        LiveSource.source_status == "active",
    ).update({"source_status": "candidate"})

    # 対象ソースを昇格
    source = db.get(LiveSource, source_id)
    if not source or source.session_id != session.id:
        raise HTTPException(status_code=404, detail="ソースが見つかりません")
    source.source_status = "active"
    db.commit()
    return {"success": True, "data": _source_to_dict(source)}


@router.post("/sessions/{code}/sources/{source_id}/deactivate")
def deactivate_source(code: str, source_id: int, db: Session = Depends(get_db)):
    """ソースを candidate に降格"""
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    source = db.get(LiveSource, source_id)
    if not source or source.session_id != session.id:
        raise HTTPException(status_code=404, detail="ソースが見つかりません")
    source.source_status = "candidate"
    db.commit()
    return {"success": True, "data": _source_to_dict(source)}


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
        # migration 0004
        "device_uid": p.device_uid,
        "approval_status": p.approval_status,
        "last_heartbeat": p.last_heartbeat.isoformat() if p.last_heartbeat else None,
        "viewer_permission": p.viewer_permission,
        "device_class": p.device_class,
        "display_size_class": p.display_size_class,
    }


def _source_to_dict(s: LiveSource) -> dict:
    return {
        "id": s.id,
        "session_id": s.session_id,
        "participant_id": s.participant_id,
        "source_kind": s.source_kind,
        "source_priority": s.source_priority,
        "source_resolution": s.source_resolution,
        "source_fps": s.source_fps,
        "source_status": s.source_status,
        "suitability": s.suitability,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
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
            coach_urls.append(f"http://{ip}:{port}/#/annotator/{session.match_id}")
            camera_sender_urls.append(f"http://{ip}:{port}/#/camera/{session.session_code}")
    # localhost URL を末尾に追加（同一デバイスでの確実なアクセス用）
    # LAN_MODE 無効時でも同一PCからのアクセスは常に可能
    coach_urls.append(f"http://localhost:{port}/#/annotator/{session.match_id}")
    camera_sender_urls.append(f"http://localhost:{port}/#/camera/{session.session_code}")

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

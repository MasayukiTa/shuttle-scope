"""認証ルーター（Phase A-1）

エンドポイント:
  POST /api/auth/login         — ロール別ログイン → JWT 発行
  POST /api/auth/logout        — ログアウト（AccessLog 記録）
  GET  /api/auth/me            — 現在のユーザ情報
  GET  /api/auth/players       — player ロール候補一覧（選手選択用）
  GET  /api/auth/coaches       — coach ロール候補一覧
  GET  /api/auth/analysts      — analyst ロール候補一覧
"""
import logging
from typing import Optional

import bcrypt as _bcrypt_lib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import User, Player
from backend.utils.jwt_utils import create_access_token, verify_token
from backend.utils.access_log import log_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_password(password: str) -> str:
    return _bcrypt_lib.hashpw(password.encode("utf-8"), _bcrypt_lib.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return _bcrypt_lib.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _get_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── スキーマ ───────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    grant_type: str        # "password" | "select" | "pin"
    username: Optional[str] = None
    password: Optional[str] = None
    user_id: Optional[int] = None
    pin: Optional[str] = None
    role: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    player_id: Optional[int] = None
    team_name: Optional[str] = None
    display_name: Optional[str] = None


# ─── ヘルパー ────────────────────────────────────────────────────────────────

def _seed_admin_if_needed(db: Session) -> None:
    """admin ユーザが 0 件の場合、デフォルト admin をシードする。"""
    exists = db.query(User).filter(User.role == "admin").first()
    if not exists:
        hashed = _hash_password("shuttlescope2026")
        admin = User(
            username="admin",
            role="admin",
            display_name="管理者",
            hashed_credential=hashed,
        )
        db.add(admin)
        db.commit()
        logger.warning(
            "=== デフォルト admin ユーザを作成しました。"
            " パスワード 'shuttlescope2026' を変更してください ==="
        )


# ─── エンドポイント ──────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """ロール別ログイン。JWT を返す。"""
    ip = _get_ip(request)
    _seed_admin_if_needed(db)

    if req.grant_type == "password":
        # admin / analyst: username + password
        if not req.username or not req.password:
            raise HTTPException(status_code=422, detail="username と password が必要です")
        user = db.query(User).filter(User.username == req.username).first()
        if not user or not user.hashed_credential:
            log_access(db, "login_failed", details={"reason": "user_not_found", "username": req.username}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="認証に失敗しました")
        if not _verify_password(req.password, user.hashed_credential):
            log_access(db, "login_failed", user_id=user.id, details={"reason": "wrong_password"}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="認証に失敗しました")
        token = create_access_token(user.id, user.role, user.player_id)
        log_access(db, "login", user_id=user.id, ip_addr=ip)
        return LoginResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            player_id=user.player_id,
            team_name=user.team_name,
            display_name=user.display_name or user.username,
        )

    elif req.grant_type == "select":
        # coach / analyst: 選択式（無認証）
        allowed = {"analyst", "coach"}
        role = req.role
        if role not in allowed:
            raise HTTPException(status_code=422, detail=f"select grant は {allowed} のみ有効です")
        if req.user_id:
            user = db.get(User, req.user_id)
            # analyst タブから admin ユーザを選択した場合も許可（admin は analyst の上位権限）
            allowed_roles = {role, "admin"} if role == "analyst" else {role}
            if not user or user.role not in allowed_roles:
                raise HTTPException(status_code=404, detail="ユーザが見つかりません")
        else:
            # analyst は最初のアナリストユーザを使うか、専用ユーザなし → 仮ユーザ ID=0 扱い
            user = db.query(User).filter(User.role == role).first()
            if not user:
                # ユーザがいない場合は一時的に analyst として発行
                token = create_access_token(0, role)
                log_access(db, "login", details={"role": role, "method": "select"}, ip_addr=ip)
                return LoginResponse(access_token=token, role=role, user_id=0)
        token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name)
        log_access(db, "login", user_id=user.id, ip_addr=ip)
        return LoginResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            player_id=user.player_id,
            team_name=user.team_name,
            display_name=user.display_name or user.username,
        )

    elif req.grant_type == "pin":
        # player: 選手選択 + PIN
        if not req.user_id:
            raise HTTPException(status_code=422, detail="user_id が必要です")
        user = db.get(User, req.user_id)
        if not user or user.role != "player":
            log_access(db, "login_failed", details={"reason": "user_not_found", "user_id": req.user_id}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="認証に失敗しました")
        if user.hashed_credential and not _verify_password(req.pin or "", user.hashed_credential):
            log_access(db, "login_failed", user_id=user.id, details={"reason": "wrong_pin"}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="PIN が正しくありません")
        token = create_access_token(user.id, user.role, user.player_id)
        log_access(db, "login", user_id=user.id, ip_addr=ip)
        return LoginResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            player_id=user.player_id,
            team_name=user.team_name,
            display_name=user.display_name or user.username,
        )

    else:
        raise HTTPException(status_code=422, detail=f"未知の grant_type: {req.grant_type}")


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    """ログアウト（クライアント側でトークン削除）。AccessLog 記録のみ。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    log_access(db, "logout", user_id=getattr(ctx, "user_id", None))
    return {"success": True}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    """現在のトークンからユーザ情報を返す。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.role:
        raise HTTPException(status_code=401, detail="未ログインです")
    user_id = getattr(ctx, "user_id", None)
    user = db.get(User, user_id) if user_id else None
    return {
        "role": ctx.role,
        "player_id": ctx.player_id,
        "user_id": user_id,
        "team_name": ctx.team_name,
        "display_name": (user.display_name or user.username) if user else None,
    }


@router.get("/players")
def list_players_for_login(db: Session = Depends(get_db)):
    """player ロールのログイン候補一覧（選手名 + user_id + player_id）。"""
    users = db.query(User).filter(User.role == "player").all()
    result = []
    for u in users:
        player = db.get(Player, u.player_id) if u.player_id else None
        result.append({
            "user_id": u.id,
            "player_id": u.player_id,
            "display_name": u.display_name or (player.name if player else u.username),
            "has_pin": u.hashed_credential is not None,
        })
    return {"success": True, "data": result}


@router.get("/coaches")
def list_coaches_for_login(db: Session = Depends(get_db)):
    """coach ロールのログイン候補一覧。"""
    users = db.query(User).filter(User.role == "coach").all()
    return {
        "success": True,
        "data": [
            {"user_id": u.id, "display_name": u.display_name or u.username}
            for u in users
        ],
    }


@router.get("/analysts")
def list_analysts_for_login(db: Session = Depends(get_db)):
    """analyst ロールのログイン候補一覧。"""
    users = db.query(User).filter(User.role.in_(["analyst", "admin"])).all()
    return {
        "success": True,
        "data": [
            {"user_id": u.id, "display_name": u.display_name or u.username, "role": u.role}
            for u in users
        ],
    }


# ─── ユーザ管理（admin 専用） ──────────────────────────────────────────────────

def _require_admin(request: Request) -> None:
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not (ctx.is_admin or ctx.is_analyst):
        raise HTTPException(status_code=403, detail="管理者権限が必要です")


class UserCreate(BaseModel):
    role: str
    display_name: str
    username: Optional[str] = None
    password: Optional[str] = None
    pin: Optional[str] = None
    player_id: Optional[int] = None
    team_name: Optional[str] = None


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    password: Optional[str] = None
    pin: Optional[str] = None
    team_name: Optional[str] = None
    player_id: Optional[int] = None


@router.get("/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    """全ユーザ一覧（admin 専用）。"""
    _require_admin(request)
    users = db.query(User).order_by(User.id).all()
    result = []
    for u in users:
        player = db.get(Player, u.player_id) if u.player_id else None
        result.append({
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "display_name": u.display_name,
            "team_name": u.team_name,
            "player_id": u.player_id,
            "player_name": player.name if player else None,
            "has_credential": u.hashed_credential is not None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })
    return {"success": True, "data": result}


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    """ユーザ作成（admin 専用）。"""
    _require_admin(request)
    allowed_roles = {"admin", "analyst", "coach", "player"}
    if body.role not in allowed_roles:
        raise HTTPException(status_code=422, detail=f"無効なロール: {body.role}")
    # username 重複チェック
    if body.username:
        existing = db.query(User).filter(User.username == body.username).first()
        if existing:
            raise HTTPException(status_code=409, detail="このユーザ名は既に使用されています")
    # 認証情報ハッシュ
    hashed: Optional[str] = None
    if body.role in {"admin", "analyst"} and body.password:
        hashed = _hash_password(body.password)
    elif body.role == "player" and body.pin:
        hashed = _hash_password(body.pin)
    user = User(
        username=body.username or body.display_name,
        role=body.role,
        display_name=body.display_name,
        team_name=body.team_name,
        player_id=body.player_id,
        hashed_credential=hashed,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_access(db, "user_created", user_id=user.id, details={"role": body.role, "display_name": body.display_name})
    return {"success": True, "data": {"id": user.id, "role": user.role, "display_name": user.display_name}}


@router.put("/users/{target_id}")
def update_user(target_id: int, body: UserUpdate, request: Request, db: Session = Depends(get_db)):
    """ユーザ更新（admin 専用）。PIN / パスワードリセット含む。"""
    _require_admin(request)
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="ユーザが見つかりません")
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.team_name is not None:
        user.team_name = body.team_name
    if body.player_id is not None:
        user.player_id = body.player_id
    if body.password:
        user.hashed_credential = _hash_password(body.password)
    elif body.pin:
        user.hashed_credential = _hash_password(body.pin)
    db.commit()
    log_access(db, "user_updated", user_id=user.id)
    return {"success": True}


@router.delete("/users/{target_id}")
def delete_user(target_id: int, request: Request, db: Session = Depends(get_db)):
    """ユーザ削除（admin 専用）。自分自身は削除不可。"""
    _require_admin(request)
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if ctx.user_id == target_id:
        raise HTTPException(status_code=400, detail="自分自身は削除できません")
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="ユーザが見つかりません")
    db.delete(user)
    db.commit()
    log_access(db, "user_deleted", details={"deleted_user_id": target_id})
    return {"success": True}

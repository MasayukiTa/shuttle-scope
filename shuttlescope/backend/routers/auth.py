"""Authentication and user-management routes."""

import logging
from typing import Optional

import bcrypt as _bcrypt_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import Player, User
from backend.utils.access_log import log_access
from backend.utils.jwt_utils import create_access_token

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


class LoginRequest(BaseModel):
    grant_type: str
    username: Optional[str] = None
    identifier: Optional[str] = None
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


class BootstrapStatusResponse(BaseModel):
    has_admin: bool
    bootstrap_configured: bool
    bootstrap_username: Optional[str] = None
    bootstrap_display_name: Optional[str] = None


def _bootstrap_admin_status(db: Session) -> BootstrapStatusResponse:
    exists = db.query(User).filter(User.role == "admin").first()
    configured = bool((settings.BOOTSTRAP_ADMIN_PASSWORD or "").strip())
    return BootstrapStatusResponse(
        has_admin=exists is not None,
        bootstrap_configured=configured,
        bootstrap_username=(settings.BOOTSTRAP_ADMIN_USERNAME or "admin").strip() or "admin",
        bootstrap_display_name=(settings.BOOTSTRAP_ADMIN_DISPLAY_NAME or "Admin").strip() or "Admin",
    )


def _seed_admin_if_needed(db: Session) -> None:
    status = _bootstrap_admin_status(db)
    if status.has_admin:
        return

    password = (settings.BOOTSTRAP_ADMIN_PASSWORD or "").strip()
    if not password:
        logger.warning(
            "No admin user exists and BOOTSTRAP_ADMIN_PASSWORD is not set. "
            "Set BOOTSTRAP_ADMIN_PASSWORD before first admin login."
        )
        return

    conflicting_user = db.query(User).filter(User.username == status.bootstrap_username).first()
    if conflicting_user:
        logger.warning(
            "Cannot bootstrap initial admin user '%s' because that username already belongs to role '%s'.",
            status.bootstrap_username,
            conflicting_user.role,
        )
        return

    admin = User(
        username=status.bootstrap_username,
        role="admin",
        display_name=status.bootstrap_display_name,
        hashed_credential=_hash_password(password),
    )
    db.add(admin)
    db.commit()
    logger.warning(
        "Bootstrapped initial admin user '%s'. Change the password after first login.",
        status.bootstrap_username,
    )


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = _get_ip(request)
    _seed_admin_if_needed(db)

    if req.grant_type == "credential":
        identifier = (req.identifier or req.username or "").strip()
        secret = req.password if req.password is not None else req.pin
        if not identifier or not secret:
            raise HTTPException(status_code=422, detail="identifier and password are required")

        user = None
        if identifier.isdigit():
            user = db.get(User, int(identifier))

        if user is None:
            user = db.query(User).filter(User.username == identifier).first()

        if user is None:
            exact_display_name = db.query(User).filter(User.display_name == identifier).all()
            if len(exact_display_name) == 1:
                user = exact_display_name[0]

        if not user or not user.hashed_credential:
            log_access(db, "login_failed", details={"reason": "user_not_found", "identifier": identifier}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="login failed")

        if not _verify_password(secret, user.hashed_credential):
            log_access(db, "login_failed", user_id=user.id, details={"reason": "wrong_password"}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="login failed")

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

    if req.grant_type == "password":
        if not req.username or not req.password:
            raise HTTPException(status_code=422, detail="username and password are required")
        user = db.query(User).filter(User.username == req.username).first()
        if not user or not user.hashed_credential:
            log_access(db, "login_failed", details={"reason": "user_not_found", "username": req.username}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="login failed")
        if not _verify_password(req.password, user.hashed_credential):
            log_access(db, "login_failed", user_id=user.id, details={"reason": "wrong_password"}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="login failed")
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

    if req.grant_type == "select":
        allowed = {"analyst", "coach"}
        role = req.role
        if role not in allowed:
            raise HTTPException(status_code=422, detail=f"select grant supports only {sorted(allowed)}")
        if req.user_id:
            user = db.get(User, req.user_id)
            allowed_roles = {role, "admin"} if role == "analyst" else {role}
            if not user or user.role not in allowed_roles:
                raise HTTPException(status_code=404, detail="user not found")
        else:
            user = db.query(User).filter(User.role == role).first()
            if not user:
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

    if req.grant_type == "pin":
        if not req.user_id:
            raise HTTPException(status_code=422, detail="user_id is required")
        user = db.get(User, req.user_id)
        if not user or user.role != "player":
            log_access(db, "login_failed", details={"reason": "user_not_found", "user_id": req.user_id}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="login failed")
        if user.hashed_credential and not _verify_password(req.pin or "", user.hashed_credential):
            log_access(db, "login_failed", user_id=user.id, details={"reason": "wrong_pin"}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="PIN is incorrect")
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

    raise HTTPException(status_code=422, detail=f"unsupported grant_type: {req.grant_type}")


@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status(db: Session = Depends(get_db)):
    """Expose initial-admin bootstrap readiness without revealing secrets."""
    return _bootstrap_admin_status(db)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth

    ctx = get_auth(request)
    log_access(db, "logout", user_id=getattr(ctx, "user_id", None))
    return {"success": True}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth

    ctx = get_auth(request)
    if not ctx.role:
        raise HTTPException(status_code=401, detail="not logged in")
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
    users = db.query(User).filter(User.role == "player").all()
    result = []
    for user in users:
        player = db.get(Player, user.player_id) if user.player_id else None
        result.append(
            {
                "user_id": user.id,
                "player_id": user.player_id,
                "display_name": user.display_name or (player.name if player else user.username),
                "has_pin": user.hashed_credential is not None,
            }
        )
    return {"success": True, "data": result}


@router.get("/coaches")
def list_coaches_for_login(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.role == "coach").all()
    return {
        "success": True,
        "data": [{"user_id": user.id, "display_name": user.display_name or user.username} for user in users],
    }


@router.get("/analysts")
def list_analysts_for_login(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.role.in_(["analyst", "admin"])).all()
    return {
        "success": True,
        "data": [
            {"user_id": user.id, "display_name": user.display_name or user.username, "role": user.role}
            for user in users
        ],
    }


def _require_admin(request: Request) -> None:
    from backend.utils.auth import get_auth

    ctx = get_auth(request)
    if not (ctx.is_admin or ctx.is_analyst):
        raise HTTPException(status_code=403, detail="admin privileges required")


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
    _require_admin(request)
    users = db.query(User).order_by(User.id).all()
    result = []
    for user in users:
        player = db.get(Player, user.player_id) if user.player_id else None
        result.append(
            {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "display_name": user.display_name,
                "team_name": user.team_name,
                "player_id": user.player_id,
                "player_name": player.name if player else None,
                "has_credential": user.hashed_credential is not None,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
        )
    return {"success": True, "data": result}


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    allowed_roles = {"admin", "analyst", "coach", "player"}
    if body.role not in allowed_roles:
        raise HTTPException(status_code=422, detail=f"invalid role: {body.role}")
    if body.username:
        existing = db.query(User).filter(User.username == body.username).first()
        if existing:
            raise HTTPException(status_code=409, detail="username is already in use")

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
    _require_admin(request)
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
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
    _require_admin(request)
    from backend.utils.auth import get_auth

    ctx = get_auth(request)
    if ctx.user_id == target_id:
        raise HTTPException(status_code=400, detail="cannot delete your own user")
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    db.delete(user)
    db.commit()
    log_access(db, "user_deleted", details={"deleted_user_id": target_id})
    return {"success": True}

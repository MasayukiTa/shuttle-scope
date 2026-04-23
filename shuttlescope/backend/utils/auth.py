"""権限管理ユーティリティ（POCフェーズ：簡易実装）

- X-Role / X-Player-Id リクエストヘッダからロール情報を取得
- match / player リソースへのアクセスを role=player 時のみ player_id で制約
- 将来的にチーム単位のスコープ制御を追加予定

設計方針:
  ロール自体は自己申告（X-Role を信用）だが、player ロールの場合は
  X-Player-Id が実際にそのリソースに関連付けられているかを DB で検証する。
  これにより「ロールは正直に選ぶが ID を書き換えて覗こうとする」攻撃を防ぐ。
"""
from enum import Enum
from typing import Optional

from fastapi import HTTPException, Request, Depends
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, Player


class UserRole(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    COACH = "coach"
    PLAYER = "player"


# playerロールに見せてはいけないデータキー
PLAYER_SENSITIVE_KEYS = [
    "win_rate_vs_opponent",
    "epv",
    "weakness_zones",
    "rival_comparison",
    "bottom_patterns",  # EPV下位パターン
]


def filter_by_role(data: dict, role: str) -> dict:
    """ロールに応じてデータをフィルタリング"""
    if role == UserRole.PLAYER:
        return {k: v for k, v in data.items() if k not in PLAYER_SENSITIVE_KEYS}
    return data


# ─── リクエストコンテキスト取得 ───────────────────────────────────────────────

class AuthCtx:
    """リクエストから抽出した現在ユーザーのロール/ID。"""
    __slots__ = ("role", "player_id", "team_name", "user_id")

    def __init__(
        self,
        role: Optional[str],
        player_id: Optional[int],
        team_name: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        self.role = role
        self.player_id = player_id
        self.team_name = team_name
        self.user_id = user_id

    @property
    def is_player(self) -> bool:
        return self.role == UserRole.PLAYER.value

    @property
    def is_coach(self) -> bool:
        return self.role == UserRole.COACH.value

    @property
    def is_analyst(self) -> bool:
        return self.role == UserRole.ANALYST.value

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value


def get_auth(request: Request) -> AuthCtx:
    """Authorization: Bearer JWT からコンテキストを組み立てる。

    JWT が有効な場合はそこからロール/player_id/user_id を取得する。
    JWT なし / 無効の場合は X-Role ヘッダにフォールバック（開発互換）。
    制約の強制は require_match_access / require_player_access で行う。
    """
    # ── JWT 優先 ──────────────────────────────────────────────────────────────
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        from backend.utils.jwt_utils import verify_token
        payload = verify_token(token)
        if payload:
            role = payload.get("role")
            if role not in {r.value for r in UserRole}:
                role = None
            pid = payload.get("player_id")
            if pid is not None:
                try:
                    pid = int(pid) if int(pid) > 0 else None
                except (ValueError, TypeError):
                    pid = None
            uid_raw = payload.get("sub")
            uid: Optional[int] = None
            if uid_raw:
                try:
                    n = int(uid_raw)
                    uid = n if n > 0 else None
                except (ValueError, TypeError):
                    uid = None
            # team_name は JWT ペイロードから直接取得
            tn = payload.get("team_name")
            team_name: Optional[str] = tn.strip() if isinstance(tn, str) and tn.strip() else None
            return AuthCtx(role, pid, team_name, user_id=uid)

    # ── フォールバック: X-Role ヘッダ（ローカルのみ互換）────────────────────
    # loopback 以外からの X-Role ヘッダは信用しない。
    from backend.utils.control_plane import allow_legacy_header_auth
    if not allow_legacy_header_auth(request):
        return AuthCtx(None, None)

    role = request.headers.get("X-Role")
    if role not in {r.value for r in UserRole}:
        role = None
    pid_raw = request.headers.get("X-Player-Id")
    pid = None
    if pid_raw:
        try:
            n = int(pid_raw)
            if n > 0:
                pid = n
        except (ValueError, TypeError):
            pid = None
    team_raw = request.headers.get("X-Team-Name")
    team_name = None
    if team_raw:
        try:
            from urllib.parse import unquote
            team_name = unquote(team_raw).strip() or None
        except Exception:
            team_name = None
    return AuthCtx(role, pid, team_name)


# ─── アクセス制御ヘルパー ────────────────────────────────────────────────────

def _match_player_ids(m: Match) -> set[int]:
    """試合に関連する選手 ID 集合（4 ロール分）。None は除く。"""
    return {x for x in (m.player_a_id, m.partner_a_id, m.player_b_id, m.partner_b_id) if x}


def user_can_access_match(ctx: AuthCtx, m: Match) -> bool:
    """現在のユーザーがこの試合にアクセスしてよいか。"""
    if ctx.is_player:
        if not ctx.player_id:
            return False
        return ctx.player_id in _match_player_ids(m)
    # analyst / coach / 未ロールは現時点で全試合可（将来チーム制約で絞る）
    return True


def user_can_access_player(ctx: AuthCtx, player_id: int) -> bool:
    """選手個別データ（統計・履歴）にアクセスしてよいか。"""
    if ctx.is_player:
        return ctx.player_id is not None and ctx.player_id == player_id
    return True


def filter_matches_for_user(ctx: AuthCtx, matches: list[Match]) -> list[Match]:
    """試合一覧をロールに応じて絞り込む。"""
    if ctx.is_player:
        if not ctx.player_id:
            return []
        pid = ctx.player_id
        return [m for m in matches if pid in _match_player_ids(m)]
    return matches


def require_match_scope(request: Request, match: Match, db: Session) -> "AuthCtx":
    """match に対するアクセス権を検証する（共通ヘルパー）。
    - analyst / admin: 無条件許可
    - player: 出場試合のみ
    - coach: 同チーム所属選手が参加する試合のみ（team_name 必須）
    - 未ロール: 拒否

    comments / bookmarks / sessions ルータで共通利用する。"""
    ctx = get_auth(request)
    if ctx.is_admin or ctx.is_analyst:
        return ctx
    if ctx.is_player:
        if not user_can_access_match(ctx, match):
            raise HTTPException(status_code=403, detail="この試合へのアクセス権限がありません")
        return ctx
    if ctx.is_coach:
        team = (ctx.team_name or "").strip()
        if not team:
            raise HTTPException(status_code=403, detail="team_name 未設定")
        pids = _match_player_ids(match)
        players = db.query(Player).filter(Player.id.in_(pids)).all() if pids else []
        if not any((p.team or "").strip() == team for p in players):
            raise HTTPException(status_code=403, detail="この試合はあなたのチームではありません")
        return ctx
    raise HTTPException(status_code=403, detail="ロール未設定です")


def require_match_access(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> Match:
    """試合アクセスを強制する FastAPI 依存性。
    使用例: `m: Match = Depends(require_match_access)`
    """
    ctx = get_auth(request)
    m = db.get(Match, match_id)
    if not m:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if not user_can_access_match(ctx, m):
        raise HTTPException(
            status_code=403,
            detail="この試合へのアクセス権限がありません",
        )
    return m


# ─── エクスポート権限 ─────────────────────────────────────────────────────────

def require_analyst(request: Request) -> AuthCtx:
    """analyst / admin 限定操作（change_set / backup など）。"""
    ctx = get_auth(request)
    if not (ctx.is_analyst or ctx.is_admin):
        raise HTTPException(
            status_code=403,
            detail="この操作は analyst / admin ロールでのみ実行できます",
        )
    return ctx


def _team_of(player: Optional[Player]) -> Optional[str]:
    if not player:
        return None
    t = (player.team or "").strip()
    return t or None


def check_export_match_scope(
    ctx: AuthCtx, matches: list[Match], db: Session
) -> None:
    """試合エクスポートの権限チェック。

    - analyst: 無制限
    - player:  対象試合すべてに自分の player_id が含まれる必要あり
    - coach:   対象試合に参加する全選手のうち 1 人以上が自チーム所属であれば可
               (対戦相手はチーム外でも許可する — コーチは自チームの試合を抜く)
    - role未設定: 拒否
    """
    if ctx.is_analyst or ctx.is_admin:
        return
    if ctx.is_player:
        if not ctx.player_id:
            raise HTTPException(status_code=403, detail="player_id 未設定")
        for m in matches:
            if ctx.player_id not in _match_player_ids(m):
                raise HTTPException(
                    status_code=403,
                    detail=f"試合 id={m.id} はあなたの試合ではありません",
                )
        return
    if ctx.is_coach:
        team = (ctx.team_name or "").strip()
        if not team:
            raise HTTPException(status_code=403, detail="team_name 未設定")
        for m in matches:
            pids = _match_player_ids(m)
            if not pids:
                raise HTTPException(
                    status_code=403,
                    detail=f"試合 id={m.id} に選手情報がありません",
                )
            players = db.query(Player).filter(Player.id.in_(pids)).all()
            if not any(_team_of(p) == team for p in players):
                raise HTTPException(
                    status_code=403,
                    detail=f"試合 id={m.id} はあなたのチームの試合ではありません",
                )
        return
    raise HTTPException(status_code=403, detail="ロール未設定です")


def check_export_player_scope(
    ctx: AuthCtx, player_id: int, db: Session
) -> None:
    """選手エクスポートの権限チェック。"""
    if ctx.is_analyst or ctx.is_admin:
        return
    if ctx.is_player:
        if ctx.player_id != player_id:
            raise HTTPException(
                status_code=403,
                detail="他の選手データはエクスポートできません",
            )
        return
    if ctx.is_coach:
        team = (ctx.team_name or "").strip()
        if not team:
            raise HTTPException(status_code=403, detail="team_name 未設定")
        p = db.get(Player, player_id)
        if not p:
            raise HTTPException(status_code=404, detail="選手が見つかりません")
        if _team_of(p) != team:
            raise HTTPException(
                status_code=403,
                detail="この選手はあなたのチームに所属していません",
            )
        return
    raise HTTPException(status_code=403, detail="ロール未設定です")


def require_player_self_or_privileged(
    player_id: int,
    request: Request,
) -> AuthCtx:
    """選手個別データへのアクセスを強制する依存性。
    role=player は自分自身のみ。それ以外は常に許可。
    """
    ctx = get_auth(request)
    if not user_can_access_player(ctx, player_id):
        raise HTTPException(
            status_code=403,
            detail="この選手データへのアクセス権限がありません",
        )
    return ctx

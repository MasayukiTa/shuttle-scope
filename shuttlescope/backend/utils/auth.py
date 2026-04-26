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
    __slots__ = ("role", "player_id", "team_name", "team_id", "user_id")

    def __init__(
        self,
        role: Optional[str],
        player_id: Optional[int],
        team_name: Optional[str] = None,
        user_id: Optional[int] = None,
        team_id: Optional[int] = None,
    ):
        self.role = role
        self.player_id = player_id
        self.team_name = team_name
        self.team_id = team_id
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
            # team_name / team_id は JWT ペイロードから直接取得
            tn = payload.get("team_name")
            team_name: Optional[str] = tn.strip() if isinstance(tn, str) and tn.strip() else None
            tid_raw = payload.get("team_id")
            team_id: Optional[int] = None
            if tid_raw is not None:
                try:
                    n = int(tid_raw)
                    team_id = n if n > 0 else None
                except (ValueError, TypeError):
                    team_id = None
            return AuthCtx(role, pid, team_name, user_id=uid, team_id=team_id)

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
    """現在のユーザーがこの試合にアクセスしてよいか。

    Phase B-6: チーム境界で遮断する。
    - admin: 全試合可
    - player: 自分が登場する試合のみ
    - coach/analyst: owner_team_id 一致 OR is_public_pool OR 自チーム選手が登場
    """
    if ctx.is_admin:
        return True
    if ctx.is_player:
        if not ctx.player_id:
            return False
        return ctx.player_id in _match_player_ids(m)
    # coach / analyst（または未ロール扱いの内部呼び出し含む）
    owner_id = getattr(m, "owner_team_id", None)
    is_public = bool(getattr(m, "is_public_pool", False))
    if ctx.team_id is not None and owner_id is not None and owner_id == ctx.team_id:
        return True
    if is_public:
        return True
    # public でない場合に「自チーム選手が登場」する場合も閲覧可（解析対象として）
    if ctx.team_id is not None:
        from backend.db.database import SessionLocal
        from backend.db.models import Player
        ids = _match_player_ids(m)
        if not ids:
            return False
        try:
            with SessionLocal() as _db:
                hit = (
                    _db.query(Player.id)
                    .filter(Player.id.in_(ids), Player.team_id == ctx.team_id)
                    .first()
                )
            return hit is not None
        except Exception:
            return False
    return False


def apply_match_team_scope(query, ctx: AuthCtx):
    """Match クエリにチーム境界フィルタを適用する。

    admin は素通し。それ以外は次のいずれかを満たすもののみ:
      - owner_team_id == ctx.team_id
      - is_public_pool == True
      - 試合参加選手のいずれかが Player.team_id == ctx.team_id

    player ロールはより厳しく、自分が登場する試合のみ。
    """
    from sqlalchemy import or_, exists
    from backend.db.models import Match, Player
    if ctx.is_admin:
        return query
    if ctx.is_player:
        if not ctx.player_id:
            return query.filter(False)
        pid = ctx.player_id
        return query.filter(
            or_(
                Match.player_a_id == pid,
                Match.player_b_id == pid,
                Match.partner_a_id == pid,
                Match.partner_b_id == pid,
            )
        )
    # coach / analyst
    if ctx.team_id is None:
        # チーム未所属（移行期のみ）: public プールのみ
        return query.filter(Match.is_public_pool.is_(True))
    team_player_subq = (
        exists().where(
            (Player.team_id == ctx.team_id)
            & Player.id.in_(
                [Match.player_a_id, Match.player_b_id, Match.partner_a_id, Match.partner_b_id]
            )
        )
    )
    return query.filter(
        or_(
            Match.owner_team_id == ctx.team_id,
            Match.is_public_pool.is_(True),
            team_player_subq,
        )
    )


def require_match_access(match_id: int, request, db) -> "Match":
    """指定 match_id にアクセス可能か検証して Match を返す。

    アクセス不可の場合は 404 を返す（存在自体を隠してリーク防止）。
    """
    from fastapi import HTTPException
    from backend.db.models import Match as _Match
    ctx = get_auth(request)
    m = db.get(_Match, match_id)
    if not m or not user_can_access_match(ctx, m):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    return m


def can_access_player(ctx: AuthCtx, player_id: int, db) -> bool:
    """選手データへのアクセス可否（Phase B-6 拡張版）。

    - admin: 全可
    - player: 自分のみ
    - coach/analyst: 自チーム所属 player（Player.team_id == ctx.team_id）
      または「自チームから可視な試合に登場する player」
    """
    if ctx.is_admin:
        return True
    if ctx.is_player:
        return ctx.player_id is not None and ctx.player_id == player_id
    if ctx.team_id is None:
        return False
    from backend.db.models import Player, Match
    p = db.get(Player, player_id)
    if not p:
        return False
    if p.team_id is not None and p.team_id == ctx.team_id:
        return True
    # 自チームから見える match に登場するか
    q = db.query(Match.id).filter(
        (Match.player_a_id == player_id)
        | (Match.player_b_id == player_id)
        | (Match.partner_a_id == player_id)
        | (Match.partner_b_id == player_id)
    )
    q = apply_match_team_scope(q, ctx)
    return q.first() is not None


def resolve_owner_team_for_match_create(
    ctx: AuthCtx,
    *,
    requested_team_id: Optional[int] = None,
    requested_is_public_pool: bool = False,
) -> tuple[int, bool]:
    """試合登録時の owner_team_id と is_public_pool を決定する。

    - admin: requested_team_id を尊重（指定なしなら ctx.team_id）、is_public_pool 設定可
    - coach/analyst: ctx.team_id を強制注入、is_public_pool は無視（False）
    - その他ロール: 403
    """
    from fastapi import HTTPException
    if ctx.is_admin:
        team_id = requested_team_id if requested_team_id is not None else ctx.team_id
        if team_id is None:
            raise HTTPException(status_code=422, detail="owner_team_id を指定してください")
        return int(team_id), bool(requested_is_public_pool)
    if ctx.is_coach or ctx.is_analyst:
        if ctx.team_id is None:
            raise HTTPException(status_code=403, detail="チーム未所属のユーザは試合を登録できません")
        return int(ctx.team_id), False
    raise HTTPException(status_code=403, detail="この操作の権限がありません")


def user_can_access_player(ctx: AuthCtx, player_id: int) -> bool:
    """選手個別データ（統計・履歴）にアクセスしてよいか。"""
    if ctx.is_player:
        return ctx.player_id is not None and ctx.player_id == player_id
    return True


def filter_matches_for_user(ctx: AuthCtx, matches: list[Match], db: Optional[Session] = None) -> list[Match]:
    """試合一覧をロールに応じて絞り込む。

    - admin / analyst: 全件許可
    - player: 自 player_id が参加する試合のみ
    - coach: 自 team_name に所属する player が参加する試合のみ
      (team_name 未設定の coach は空配列 — 全件露出を防ぐ)
    """
    if ctx.is_player:
        if not ctx.player_id:
            return []
        pid = ctx.player_id
        return [m for m in matches if pid in _match_player_ids(m)]
    if ctx.is_coach:
        team = (ctx.team_name or "").strip()
        if not team:
            return []  # team_name 未設定 coach は閲覧不可 (全件露出 IDOR を防止)
        if db is None:
            # db が渡されない呼び出し元では保守的に空配列
            return []
        # 対象 matches に登場する player_id を一括で取得し、team 一致を確認
        pids = set()
        for m in matches:
            pids.update(_match_player_ids(m))
        if not pids:
            return []
        team_player_ids = {
            p.id for p in db.query(Player).filter(Player.id.in_(pids), Player.team == team).all()
        }
        return [m for m in matches if _match_player_ids(m) & team_player_ids]
    # admin / analyst は全件
    return matches


def require_admin(request: Request) -> "AuthCtx":
    """admin ロールのみ許可。player/coach/analyst は 403。"""
    ctx = get_auth(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")
    return ctx


def require_admin_or_analyst(request: Request) -> "AuthCtx":
    """admin または analyst のみ許可。player/coach は 403。"""
    ctx = get_auth(request)
    if not (ctx.is_admin or ctx.is_analyst):
        raise HTTPException(status_code=403, detail="admin または analyst のみアクセス可能です")
    return ctx


def require_non_player(request: Request) -> "AuthCtx":
    """player 以外 (admin/analyst/coach) のみ許可。"""
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この情報は player ロールでは参照できません")
    return ctx


def require_match_scope(request: Request, match: Match, db: Session) -> "AuthCtx":
    """match に対するアクセス権を検証する（共通ヘルパー）。
    - admin: 無条件許可
    - analyst: 同チーム所属選手が参加する試合のみ（team_name 必須）
    - coach: 同チーム所属選手が参加する試合のみ（team_name 必須）
    - player: 出場試合のみ
    - 未ロール: 拒否

    comments / bookmarks / sessions ルータで共通利用する。

    なお、loopback (Electron 同居/テスト) 経由の X-Role analyst で team_name 未設定の
    場合のみ、後方互換のため admin 同等扱いとする。production (JWT 必須) では
    必ず JWT 内の team_name で scope 判定される。"""
    ctx = get_auth(request)
    if ctx.is_admin:
        return ctx
    if ctx.is_player:
        if not user_can_access_match(ctx, match):
            raise HTTPException(status_code=403, detail="この試合へのアクセス権限がありません")
        return ctx
    if ctx.is_analyst or ctx.is_coach:
        team = (ctx.team_name or "").strip()
        if not team:
            # loopback (X-Role 互換) で team_name 未設定なら dev/test 用途として通す
            from backend.utils.control_plane import allow_legacy_header_auth
            if allow_legacy_header_auth(request):
                return ctx
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

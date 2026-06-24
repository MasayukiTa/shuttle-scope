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
from backend.db.models import Match, Player, User


class UserRole(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    COACH = "coach"
    PLAYER = "player"
    # demo: チュートリアル用デモ口座ロール（最小権限・read-only）。
    DEMO = "demo"
    # llm: 汎用 LLM チャット (/#/llm) 専用ロール。analyst/coach/player の role 判定に
    # 一致しないためバドミントン機能には到達できない (LLM 専用ユーザ)。
    LLM = "llm"


def is_demo_read(request: Request) -> bool:
    """検証済みの demo read かどうか。

    main.py の demo ゲート (`_try_demo_read`) が、リクエスト内の全対象が
    demo データであることを検証できた時だけ `request.state.demo_read=True` を
    立てる。client からは偽装不可能。
    これを見て team/player スコープ判定を bypass しても、実データが混ざる
    リクエストでは絶対にフラグが立たないため実データ漏洩は起きない。
    """
    try:
        return bool(getattr(request.state, "demo_read", False))
    except Exception:
        return False


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
    __slots__ = ("role", "player_id", "team_name", "team_id", "user_id",
                 "_admin_mfa_ok")

    def __init__(
        self,
        role: Optional[str],
        player_id: Optional[int],
        team_name: Optional[str] = None,
        user_id: Optional[int] = None,
        team_id: Optional[int] = None,
        admin_mfa_ok: bool = False,
    ):
        self.role = role
        self.player_id = player_id
        self.team_name = team_name
        self.team_id = team_id
        self.user_id = user_id
        # 2026-05-24 Round 281+: admin の MFA enrollment 状態。
        # is_admin プロパティで参照される。get_auth が JWT 検証時に DB
        # から totp_enabled を読み取って 1 回だけセットする (リクエストあたり
        # 1 回の DB lookup 程度)。/auth/me 等で role="admin" は維持する一方、
        # is_admin (authorization 用) は MFA enrollment と AND を取る。
        self._admin_mfa_ok = admin_mfa_ok

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
        # 2026-05-24 Round 281+: MFA 未 enroll の admin は authorization 用途で
        # admin として扱わない (config SS_REQUIRE_ADMIN_MFA=0 で disable 可)。
        # role 値は "admin" のまま維持されるので /auth/me 経由でフロントは
        # 通常通り main app をレンダーでき、ユーザは MFA setup 画面に誘導される。
        if self.role != UserRole.ADMIN.value:
            return False
        if self._admin_mfa_ok:
            return True
        # 2026-05-25: gate-aware fallback for AuthCtx constructed directly
        # (test mocks via dependency_overrides bypass get_auth, so the JWT
        # path can't set admin_mfa_ok). When the gate is globally disabled
        # via SS_REQUIRE_ADMIN_MFA=0, any admin role is treated as admin.
        try:
            from backend.config import settings as _ss
            if not getattr(_ss, "ss_require_admin_mfa", True):
                return True
        except Exception:
            pass
        return False


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
            # Round 258 R15 P2 fix (deep audit NEW-6): mfa_pending JWT は MFA 完了前の
            # 一時 token なので、access role としては絶対に honor しない。
            # GlobalAuthMiddleware (main.py) は path ベースで `/api/auth/mfa/*` のみ
            # 通すよう実装済だが、ここでは get_auth レイヤで AuthCtx を「未認証相当」
            # に倒すことで、middleware を bypass する経路 (将来的な追加 endpoint /
            # WS handler / scheduled job 内呼出 etc.) でも安全側に倒す。
            token_use = payload.get("token_use")
            payload_role = payload.get("role")
            if token_use == "mfa_pending" or payload_role == "mfa_pending":
                # 全部 None で返して downstream の `if ctx.role is None` で 401 にする
                return AuthCtx(None, None)
            role = payload_role
            if role not in {r.value for r in UserRole}:
                role = None
            # 2026-05-24 Round 281+ fix: admin role に MFA enrollment を必須化。
            # role 値そのものは "admin" を維持 (frontend が main app をレンダー
            # するため必要)。authorization は AuthCtx.is_admin プロパティが
            # admin_mfa_ok との AND で判定する。SS_REQUIRE_ADMIN_MFA=0 で
            # disable 可能。
            _admin_mfa_ok_calc = False
            if role == UserRole.ADMIN.value:
                try:
                    from backend.config import settings as _ss_cfg
                    if not getattr(_ss_cfg, "ss_require_admin_mfa", True):
                        # 強制 OFF 設定なら enrollment 状態を問わず admin 扱い
                        _admin_mfa_ok_calc = True
                    else:
                        uid_check = payload.get("sub")
                        uid_check_int = 0
                        if uid_check:
                            try:
                                uid_check_int = int(uid_check)
                            except (ValueError, TypeError):
                                uid_check_int = 0
                        if uid_check_int > 0:
                            from backend.db.database import SessionLocal
                            with SessionLocal() as _db_mfa:
                                _u_mfa = _db_mfa.get(User, uid_check_int)
                                if _u_mfa and getattr(_u_mfa, "totp_enabled", False):
                                    _admin_mfa_ok_calc = True
                except Exception:
                    # DB エラー時は fail-closed (admin 認可を与えない)
                    _admin_mfa_ok_calc = False
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
            return AuthCtx(role, pid, team_name, user_id=uid, team_id=team_id,
                           admin_mfa_ok=_admin_mfa_ok_calc)

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
    # 2026-05-25: X-Role fallback (loopback-only legacy header path) で admin を
    #   名乗った場合、MFA enrollment 状態をチェックする手段が無い。allow_legacy_header_auth
    #   が既に loopback 限定にしているので、ここに到達した時点で開発/テスト/同マシンの
    #   admin 補助用途と扱える。admin_mfa_ok=True を付与し、is_admin プロパティが
    #   True を返すようにする。JWT 経路は上で個別に MFA 検証済み。
    legacy_admin_ok = (role == UserRole.ADMIN.value)
    return AuthCtx(role, pid, team_name, admin_mfa_ok=legacy_admin_ok)


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


def require_match_access_or_404(match_id: int, request, db) -> "Match":
    """指定 match_id にアクセス可能か検証して Match を返す。

    routers #6 fix: 旧コードは同名の require_match_access を 2 回定義しており
    (404 / 403 で挙動分岐)、後勝ち上書きで前者は死コード化していた。
    名前を _or_404 にリネームして共存させる (404 隠蔽が必要なエンドポイント用)。
    既定の依存性版 (HTTP 403/404 を区別) は下の require_match_access を使う。
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
    db: Optional[Session] = None,
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
        # round131 fix: admin が指定した team_id が存在しないと FK 違反で 500
        if db is not None:
            from backend.db.models import Team as _Team
            if not db.query(_Team.id).filter(_Team.id == int(team_id),
                                              _Team.deleted_at.is_(None)).first():
                raise HTTPException(
                    status_code=422,
                    detail=f"owner_team_id={team_id} は存在しないか削除済みです",
                )
        return int(team_id), bool(requested_is_public_pool)
    if ctx.is_coach or ctx.is_analyst:
        if ctx.team_id is None:
            raise HTTPException(status_code=403, detail="チーム未所属のユーザは試合を登録できません")
        return int(ctx.team_id), False
    raise HTTPException(status_code=403, detail="この操作の権限がありません")


def user_can_access_player(ctx: AuthCtx, player_id: int, db: Optional[Session] = None) -> bool:
    """選手個別データ（統計・履歴）にアクセスしてよいか。

    routers #3 fix: 旧コードは non-player に対し team_scope を無視して常に True を
    返しており、`require_player_self_or_privileged` 経由でクロスチーム IDOR が
    成立していた (analyst が他チーム選手の個別統計を取得可能)。
    db を受け取れる場合は can_access_player に委譲、未提供時は admin / non-team
    のみ True、team scope を持つロールは「player_id 不明」扱いで False (caller 側で
    db 付き呼び出しに切り替える前提)。
    """
    if ctx.is_player:
        return ctx.player_id is not None and ctx.player_id == player_id
    if db is not None:
        return can_access_player(ctx, player_id, db)
    # db 未提供 → 安全側に倒す。admin だけ素通し、それ以外は False。
    return bool(getattr(ctx, "is_admin", False))


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
        # Phase B-15+: team 文字列カラム撤去後は teams.name JOIN で解決
        from backend.db.models import Team as _Team
        team_player_ids = {
            p.id for p in db.query(Player)
                .join(_Team, _Team.id == Player.team_id)
                .filter(Player.id.in_(pids), _Team.name == team, _Team.deleted_at.is_(None))
                .all()
        }
        return [m for m in matches if _match_player_ids(m) & team_player_ids]
    # admin / analyst は全件
    return matches


def require_admin(request: Request, db: Session = Depends(get_db)) -> "AuthCtx":
    """admin ロールのみ許可。player/coach/analyst は 403。

    Round 281+ fix: admin role には MFA enrollment を必須化する
    (config SS_REQUIRE_ADMIN_MFA、デフォルト true)。未 setup admin は
    `/api/auth/mfa/setup` `/api/auth/mfa/confirm` のみアクセス可能
    (これら endpoint は get_auth のみで gate しており require_admin を
    呼ばないため、本変更の影響を受けない)。

    admin token が漏洩しても、attacker は対応する TOTP デバイスを
    持たないため、refresh タイミングで MFA challenge を通過できず
    継続利用不可。
    """
    from backend.config import settings
    ctx = get_auth(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")
    if getattr(settings, "ss_require_admin_mfa", True):
        if not ctx.user_id:
            raise HTTPException(status_code=403, detail="admin role required")
        user = db.get(User, ctx.user_id)
        if not user or not getattr(user, "totp_enabled", False):
            raise HTTPException(
                status_code=403,
                detail=(
                    "admin role には MFA enrollment が必須です。"
                    "/api/auth/mfa/setup → /api/auth/mfa/confirm で設定してください。"
                ),
            )
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
        # Phase B: 公開プール / owner 一致 / 自チーム選手登場 のいずれかを満たせば許可
        if user_can_access_match(ctx, match):
            return ctx
        team = (ctx.team_name or "").strip()
        if not team:
            from backend.utils.control_plane import allow_legacy_header_auth
            if allow_legacy_header_auth(request):
                return ctx
            raise HTTPException(status_code=403, detail="team_name 未設定")
        # 旧ロジック（team_name 文字列ベース）も併用
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


# ─── クエリパラメータ経由 ID の team 境界強制 ────────────────────────────────────
# 解析系ルータ (analysis_*, reports, prediction, review, expert) は player_id /
# match_id / rally_id / set_id を **クエリパラメータ** で受けるため、path ベースの
# middleware では cross-team IDOR を捕捉できない。PlayerAccessControlMiddleware の
# query 検証も role=player にしか効かない。この依存性を router-level dependency と
# して付与し、analyst / coach / player すべてに team 境界を強制する (admin 素通り)。
_QS_PLAYER_PARAMS = (
    "player_id", "player_a_id", "player_b_id", "opponent_id",
    "partner_id", "anchor_player_id", "player_id_1", "player_id_2",
)
_QS_PLAYER_LIST_PARAMS = ("player_ids",)
_QS_MATCH_PARAMS = ("match_id",)
_QS_MATCH_LIST_PARAMS = ("match_ids",)


def _qs_int_values(request: Request, names, list_names) -> list[int]:
    """指定クエリパラメータ群から正の整数 ID を全部 (HPP/カンマ区切り両対応) 抽出する。"""
    out: list[int] = []
    for n in names:
        for raw in request.query_params.getlist(n):
            if not raw:
                continue
            try:
                v = int(raw)
            except (ValueError, TypeError):
                continue
            if v > 0:
                out.append(v)
    for n in list_names:
        for raw in request.query_params.getlist(n):
            if not raw:
                continue
            for part in str(raw).split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    v = int(part)
                except (ValueError, TypeError):
                    continue
                if v > 0:
                    out.append(v)
    return out


def require_query_scope(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
) -> AuthCtx:
    """クエリパラメータの player/match/rally/set ID を team 境界で検証する依存性。

    使用例: `APIRouter(dependencies=[Depends(require_query_scope)])`。
    - admin: 全通過
    - role 未設定 (未認証): 401
    - player: 自分の player_id / 自分が登場する試合のみ (can_access_player /
      user_can_access_match が role 境界を内包)
    - coach / analyst: 自チーム所属 or 自チームから可視な選手・試合のみ
    存在しない ID は 404、権限外は 403。

    ctx は Depends(get_auth) で受ける (テストの dependency_overrides[get_auth] を尊重し、
    本番では実 JWT を解決する)。
    """
    if ctx.is_admin:
        return ctx
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")

    from backend.db.models import Match, Rally, GameSet  # noqa: F401

    # player 系 ID (own team / 自分が登場する試合に出る player のみ可)
    for pid in _qs_int_values(request, _QS_PLAYER_PARAMS, _QS_PLAYER_LIST_PARAMS):
        if not can_access_player(ctx, pid, db):
            raise HTTPException(status_code=403, detail="この選手データへのアクセス権限がありません")

    # match 系 ID
    for mid in _qs_int_values(request, _QS_MATCH_PARAMS, _QS_MATCH_LIST_PARAMS):
        m = db.get(Match, mid)
        if m is None:
            raise HTTPException(status_code=404, detail="試合が見つかりません")
        if not user_can_access_match(ctx, m):
            raise HTTPException(status_code=403, detail="この試合へのアクセス権限がありません")

    # rally_id → set → match
    for rid in _qs_int_values(request, ("rally_id",), ()):
        r = db.get(Rally, rid)
        s = db.get(GameSet, r.set_id) if r is not None and getattr(r, "set_id", None) else None
        m = db.get(Match, s.match_id) if s is not None and getattr(s, "match_id", None) else None
        if m is None or not user_can_access_match(ctx, m):
            raise HTTPException(status_code=403, detail="このラリーへのアクセス権限がありません")

    # set_id → match
    for sid in _qs_int_values(request, ("set_id",), ()):
        s = db.get(GameSet, sid)
        m = db.get(Match, s.match_id) if s is not None and getattr(s, "match_id", None) else None
        if m is None or not user_can_access_match(ctx, m):
            raise HTTPException(status_code=403, detail="このセットへのアクセス権限がありません")

    return ctx


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

    - admin:   無制限
    - analyst: 自チーム選手が含まれる試合のみ (round126 V-5: 元実装は無制限で他チーム漏洩)
    - player:  対象試合すべてに自分の player_id が含まれる必要あり
    - coach:   対象試合に参加する全選手のうち 1 人以上が自チーム所属であれば可
               (対戦相手はチーム外でも許可する — コーチは自チームの試合を抜く)
    - role未設定: 拒否
    """
    if ctx.is_admin:
        return
    if ctx.is_analyst:
        # round126 V-5 fix: analyst にも team scope を強制
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
    if ctx.is_admin:
        return
    if ctx.is_analyst:
        # チーム未所属の analyst は他チーム選手を素通しでエクスポートできてしまうため拒否。
        # (旧実装は移行期 carve-out で team_id is None を通していた = cross-team 漏洩)
        if ctx.team_id is None:
            raise HTTPException(
                status_code=403,
                detail="チーム未所属のため選手データをエクスポートできません",
            )
        p = db.get(Player, player_id)
        if not p:
            raise HTTPException(status_code=404, detail="選手が見つかりません")
        if p.team_id != ctx.team_id:
            raise HTTPException(
                status_code=403,
                detail="この選手はあなたのチームに所属していません",
            )
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
    db: Session = Depends(get_db),
) -> AuthCtx:
    """選手個別データへのアクセスを強制する依存性。

    rereview NEW-N2 fix: 旧コードは `db` を持たず `user_can_access_player(ctx,
    player_id)` を db=None で呼んでおり、IDOR 修正の副作用で coach/analyst が
    全 403 になっていた。`Depends(get_db)` で db を受け取り team scope ベースの
    `can_access_player` 判定を経由させる。
    role=player は自分自身のみ。admin は常に許可。coach/analyst は team scope。
    """
    ctx = get_auth(request)
    if ctx.is_player:
        if ctx.player_id is None or ctx.player_id != player_id:
            raise HTTPException(
                status_code=403,
                detail="この選手データへのアクセス権限がありません",
            )
        return ctx
    if not can_access_player(ctx, player_id, db):
        raise HTTPException(
            status_code=403,
            detail="この選手データへのアクセス権限がありません",
        )
    return ctx

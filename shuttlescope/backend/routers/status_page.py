"""サーバ稼働状況 / 予定メンテ / 障害インシデント API。

- GET  /api/public/status            : 公開 (認証不要)。現在状態 + 予定メンテ + 直近インシデント
- POST /api/status/incidents         : インシデント作成 (admin)
- PATCH /api/status/incidents/{id}   : 更新/解決 (admin)
- POST /api/status/maintenance       : メンテ告知作成 (admin)
- PATCH /api/status/maintenance/{id} : 更新 (admin)
- POST /api/status/announcements      : 更新情報/お知らせ作成 (admin)
- PATCH /api/status/announcements/{id}: 更新 (admin)

「死活の時刻」= began_at/resolved_at、「理由」= reason に運用者が記す (自動判定しない)。
更新情報(announcements)は運用者がキュレーションした公開可の項目のみ掲載する
(内部 dev CHANGELOG は security/CV 詳細を含むため公開しない)。
公開ページ(Jinja)/トップバナーはこの API を読む。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Announcement, MaintenanceWindow, StatusIncident
from backend.utils.auth import get_auth

router = APIRouter()

_SEVERITY = {"minor", "major", "critical"}
_INC_STATUS = {"investigating", "identified", "monitoring", "resolved"}
_MNT_STATUS = {"scheduled", "in_progress", "completed", "canceled"}
_ANN_STATUS = {"published", "draft"}

# ── 公開コンポーネントへの射影 (F-T001-06) ─────────────────────────────────
# muse F-T001-06: 匿名の閲覧者に内部コンポーネント名 (公開トンネル/GPU/解析ワーカー/
# サーバ時刻…) と生インフラ数値 (CPU%/RAM%/VRAM/GPU%/edge 接続数/時刻ズレ秒) を
# そのまま見せていた。公開ページには「利用者が意味を取れる」粒度のコンポーネントだけを
# 平易な名前で出し、状態色と最終確認時刻、劣化時の平易な一文のみを示す。
# 内部キー/ホスト名/生メトリクスは公開出力から除く (認証付き admin ビューは存在しないため
# compute_public_status 側で射影する。内部集計 compute_components は不変)。
#
# 各公開コンポーネントは複数の内部コンポーネントを束ね、状態は「最も悪い」ものを採る。
_PUBLIC_COMPONENTS = [
    {"key": "web",      "ja": "ウェブサイト", "en": "Web site",       "members": ("api", "tunnel"),
     "degraded_ja": "一部でアクセスしづらい状態が発生しています。",
     "degraded_en": "Some visitors may have trouble reaching the site.",
     "down_ja": "サイトに接続できない状態が発生しています。",
     "down_en": "The site is currently unreachable for some visitors."},
    {"key": "signin",   "ja": "サインイン",   "en": "Sign-in",        "members": ("clock",),
     "degraded_ja": "サインインが一時的に失敗する場合があります。",
     "degraded_en": "Signing in may intermittently fail.",
     "down_ja": "サインインできない状態が発生しています。",
     "down_en": "Signing in is currently unavailable."},
    {"key": "database", "ja": "データベース", "en": "Database",       "members": ("database",),
     "degraded_ja": "データの読み込みが遅くなる場合があります。",
     "degraded_en": "Data may load more slowly than usual.",
     "down_ja": "データの読み込みに問題が発生しています。",
     "down_en": "We are having trouble loading data."},
    {"key": "analysis", "ja": "映像解析",     "en": "Video analysis", "members": ("gpu", "worker"),
     "degraded_ja": "映像の解析に通常より時間がかかる場合があります。",
     "degraded_en": "Video analysis may take longer than usual.",
     "down_ja": "映像の解析が一時的に利用できない状態です。",
     "down_en": "Video analysis is temporarily unavailable."},
]
# 内部コンポーネントキー -> 公開コンポーネントキー (incident バッジの射影に使う)。
_PUBLIC_OF_MEMBER = {m: pc["key"] for pc in _PUBLIC_COMPONENTS for m in pc["members"]}
_PUBLIC_LABEL = {pc["key"]: (pc["ja"], pc["en"]) for pc in _PUBLIC_COMPONENTS}

_STATUS_RANK = {"operational": 0, "degraded": 1, "down": 2}


def _worst_status(statuses) -> str:
    """内部コンポーネント状態群の「最も悪い」状態を返す。
    観測のある (operational/degraded/down) もののみで判定し、
    1 つも観測が無ければ 'unknown' を返す。"""
    known = [s for s in statuses if s in _STATUS_RANK]
    if not known:
        return "unknown"
    return max(known, key=lambda s: _STATUS_RANK[s])


def _public_component_label(internal_component: Optional[str], *, en: bool = False) -> Optional[str]:
    """内部コンポーネントキー (incident.component) を公開ラベルへ写す。
    公開グループに属さない / 未知のキーは None (= 公開ページに出さない)。"""
    if not internal_component:
        return None
    pub = _PUBLIC_OF_MEMBER.get(internal_component)
    if pub is None:
        return None
    ja, en_label = _PUBLIC_LABEL[pub]
    return en_label if en else ja


def public_components(internal_components: list) -> list:
    """内部コンポーネント集計 (compute_components の戻り) を、公開ページ用の
    利用者向けコンポーネントへ射影する。

    - 状態 (status) は束ねた内部コンポーネントの最悪値。
    - 稼働率 (uptime_24h) は観測のある内部コンポーネントの平均。
    - 最終確認 (sampled_at) は束ねた中で最新。
    - 生インフラ数値 (detail/metric) は一切含めない。劣化/停止のときだけ
      平易な一文 (note_ja/note_en) を付ける。
    内部キー・ホスト名・生メトリクスは出力に含めない。"""
    by_key = {c.get("key"): c for c in (internal_components or [])}
    out = []
    for pc in _PUBLIC_COMPONENTS:
        members = [by_key[m] for m in pc["members"] if m in by_key]
        status = _worst_status([m.get("status") for m in members])
        uptimes = [m.get("uptime_24h") for m in members if m.get("uptime_24h") is not None]
        uptime = round(sum(uptimes) / len(uptimes), 2) if uptimes else None
        sampled = [m.get("sampled_at") for m in members if m.get("sampled_at")]
        sampled_at = max(sampled) if sampled else None
        note_ja = note_en = None
        if status == "down":
            note_ja, note_en = pc["down_ja"], pc["down_en"]
        elif status == "degraded":
            note_ja, note_en = pc["degraded_ja"], pc["degraded_en"]
        out.append({
            "key": pc["key"],
            "name_ja": pc["ja"], "name_en": pc["en"],
            "status": status,
            "note_ja": note_ja, "note_en": note_en,
            "uptime_24h": uptime,
            "sampled_at": sampled_at,
        })
    return out


_DAY_RANK = {"operational": 0, "degraded": 1, "down": 2}
_RANK_DAY = {0: "operational", 1: "degraded", 2: "down"}


def public_component_history(internal_history: dict) -> dict:
    """compute_component_history (内部キー -> {days, uptime_pct}) を、公開コンポーネント
    キー (web/signin/database/analysis) へ合成する。

    各日のステータスは束ねた内部コンポーネントの「最も悪い」もの (observed のみ;
    全て nodata の日は nodata)。色はその最悪日の内部 color をそのまま採る。
    uptime_pct は観測のある内部コンポーネントの平均。公開キーだけを返す
    (内部キー・内部 detail は出さない)。"""
    out = {}
    for pc in _PUBLIC_COMPONENTS:
        members = [internal_history.get(m) for m in pc["members"] if internal_history.get(m)]
        if not members:
            out[pc["key"]] = {"days": [], "uptime_pct": None}
            continue
        n_days = max(len(m.get("days", [])) for m in members)
        days = []
        for i in range(n_days):
            worst_rank = -1
            worst_cell = None
            date_label = None
            for m in members:
                mdays = m.get("days", [])
                if i >= len(mdays):
                    continue
                cell = mdays[i]
                date_label = date_label or cell.get("d")
                st = cell.get("st")
                if st in _DAY_RANK and _DAY_RANK[st] > worst_rank:
                    worst_rank = _DAY_RANK[st]
                    worst_cell = cell
            if worst_cell is None:
                days.append({"d": date_label, "st": "nodata", "sev": None, "color": None})
            else:
                days.append({
                    "d": worst_cell.get("d", date_label),
                    "st": _RANK_DAY[worst_rank],
                    "sev": worst_cell.get("sev"),
                    "color": worst_cell.get("color"),
                })
        uptimes = [m.get("uptime_pct") for m in members if m.get("uptime_pct") is not None]
        uptime = round(sum(uptimes) / len(uptimes), 2) if uptimes else None
        out[pc["key"]] = {"days": days, "uptime_pct": uptime}
    return out


# 公開コンポーネントキー -> 内部メンバーキー集合 (/api/public/status/day のフィルタ用)。
def public_members(public_key: str) -> tuple:
    for pc in _PUBLIC_COMPONENTS:
        if pc["key"] == public_key:
            return pc["members"]
    return ()


PUBLIC_COMPONENT_KEYS = [pc["key"] for pc in _PUBLIC_COMPONENTS]


def _require_admin(request: Request):
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return ctx


def _inc_dict(i: StatusIncident) -> dict:
    return {
        "id": i.id, "title": i.title, "reason": i.reason, "severity": i.severity,
        "component": i.component, "status": i.status,
        "source": getattr(i, "source", "manual"),
        "began_at": i.began_at.isoformat() if i.began_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
    }


# ── 公開用: incident タイトル/本文の内部用語を平易語へ写す (F-T001-06 続き) ──
# 障害履歴に保存済みのタイトルには 'GPU が利用できません' のような内部コンポーネント名
# (GPU/VRAM/CPU/RAM/tunnel/トンネル) がそのまま入っていることがある。保存データは変えず、
# 公開ページに出すときだけ利用者が意味を取れる平易な表現へ写す。まず既知フレーズを
# 完全一致で写し、無ければ内部キーワードを含むタイトルを種類ごとの汎用文へ写す。
# どれにも当たらなければ原文のまま返す (運用者が書いた平易なタイトルを壊さない)。

# 既知フレーズの完全一致マップ (前後空白は呼び出し側で strip 済み)。
_PUBLIC_TITLE_EXACT = {
    "GPU が利用できません": ("映像解析が利用できません", "Video analysis was unavailable"),
}

# 内部キーワード (大小無視) -> 公開カテゴリの平易文 (ja, en)。
# 上から順に最初に含まれたものを採用する。
_PUBLIC_TITLE_KEYWORDS = [
    (("gpu", "vram"), ("映像解析が利用できません", "Video analysis was unavailable")),
    (("tunnel", "トンネル"), ("サイトに接続しづらい状態が発生しました", "The site was hard to reach")),
    (("cpu", "ram"), ("サーバーに負荷がかかっていました", "The service was under heavy load")),
]


def _map_public_title(text: Optional[str]) -> tuple:
    """内部用語を含みうる incident タイトルを (ja, en) の平易表現へ写す。

    - None/空はそのまま (そのままの値, None) を返す。
    - 既知フレーズ完全一致を最優先。
    - 次に内部キーワード (GPU/VRAM/CPU/RAM/tunnel/トンネル) の包含で種類別の汎用文へ。
    - どれにも当たらなければ原文を ja/en 共通で返す (平易な運用者入力を壊さない)。
    保存データは変更しない。表示時のみの写像。"""
    if not text:
        return text, text
    stripped = text.strip()
    exact = _PUBLIC_TITLE_EXACT.get(stripped)
    if exact is not None:
        return exact
    low = stripped.lower()
    for keywords, (ja, en) in _PUBLIC_TITLE_KEYWORDS:
        if any(k in low for k in keywords):
            return ja, en
    return text, text


def _public_inc_dict(i: StatusIncident) -> dict:
    """公開ページ用の incident 射影。_inc_dict と同形だが、内部コンポーネントキー
    (例 'tunnel'/'gpu') を公開ラベルへ写し、内部キーそのものは出さない (F-T001-06)。
    公開グループに属さない component は None にして公開ページに出さない。
    reason/title は運用者入力か公開用 auto 文言なのでそのまま公開する。"""
    d = _inc_dict(i)
    d.pop("component", None)
    d["component_ja"] = _public_component_label(i.component, en=False)
    d["component_en"] = _public_component_label(i.component, en=True)
    # 保存済みタイトルに内部用語 (GPU/VRAM/CPU/RAM/tunnel/トンネル) が
    # 含まれる場合は平易語へ写す。公開側では表示 (status.html.j2) も公開 API
    # (/api/public/status) もこの辞書を使うので、内部用語が公開出力に漏れないよう
    # title も ja の平易語で上書きする (元の title は admin 用 _inc_dict 側に残る)。
    # 保存データ (StatusIncident.title) 自体は変更しない — 表示時の写像のみ。
    ja, en = _map_public_title(i.title)
    d["title"] = ja
    d["title_ja"] = ja
    d["title_en"] = en
    return d


def _mnt_dict(m: MaintenanceWindow) -> dict:
    return {
        "id": m.id, "title": m.title, "body": m.body, "status": m.status,
        "scheduled_start": m.scheduled_start.isoformat() if m.scheduled_start else None,
        "scheduled_end": m.scheduled_end.isoformat() if m.scheduled_end else None,
    }


def _ann_dict(a: Announcement) -> dict:
    return {
        "id": a.id, "title": a.title, "body": a.body, "status": a.status,
        "title_en": a.title_en, "body_en": a.body_en,
        "pinned": bool(a.pinned),
        "published_at": a.published_at.isoformat() if a.published_at else None,
    }


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    reason: Optional[str] = None
    severity: str = Field(default="minor", max_length=20)
    component: Optional[str] = Field(default=None, max_length=50)
    began_at: Optional[datetime] = None


class IncidentPatch(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    reason: Optional[str] = None
    resolved: Optional[bool] = None


class MaintenanceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None


class MaintenancePatch(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    body: Optional[str] = None
    scheduled_end: Optional[datetime] = None


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: Optional[str] = None
    pinned: bool = False
    published_at: Optional[datetime] = None


class AnnouncementPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    body: Optional[str] = None
    status: Optional[str] = Field(default=None, max_length=20)
    pinned: Optional[bool] = None


def compute_public_status(db: Session) -> dict:
    """公開ステータスの集計ロジック (API と Jinja `/status` ページで共有)。

    - overall: 未解決 incident の severity から算出 (critical→down / それ以外の未解決→degraded)。
    - active_incidents: 未解決 (status != resolved) を began_at 降順。
    - recent_incidents: 直近 20 件 (解決済み含む、履歴用)。
    - maintenance: scheduled/in_progress かつ終了が未来 (or 未定) のものを開始昇順 (= 進行中/予定)。
    - recent_maintenance: 終了済み (scheduled_end が過去) または completed/canceled の
      メンテナンス枠を開始降順 (直近 10 件)。「メンテナンス履歴」セクション用。
      終了時刻が過ぎたら maintenance(予定) から外れて自動的にこちらへ移る。
    - announcements: published のみ、pinned 優先 → published_at 降順 (直近 10 件)。
    """
    unresolved = (
        db.query(StatusIncident)
        .filter(StatusIncident.status != "resolved")
        .order_by(StatusIncident.began_at.desc())
        .all()
    )
    if any(i.severity in ("critical", "major") for i in unresolved):
        overall = "down" if any(i.severity == "critical" for i in unresolved) else "degraded"
    elif unresolved:
        overall = "degraded"
    else:
        overall = "operational"
    recent = (
        db.query(StatusIncident).order_by(StatusIncident.began_at.desc()).limit(20).all()
    )
    now = datetime.utcnow()
    maint = (
        db.query(MaintenanceWindow)
        .filter(MaintenanceWindow.status.in_(["scheduled", "in_progress"]),
                ((MaintenanceWindow.scheduled_end == None) | (MaintenanceWindow.scheduled_end >= now)))  # noqa: E711
        .order_by(MaintenanceWindow.scheduled_start.asc())
        .all()
    )
    # メンテナンス履歴: 終了済み (scheduled_end が過去) または completed/canceled。
    # 進行中/予定 (上の maint) と重複しないよう scheduled_end < now を条件にする。
    recent_maint = (
        db.query(MaintenanceWindow)
        .filter(
            or_(
                and_(MaintenanceWindow.scheduled_end != None,  # noqa: E711
                     MaintenanceWindow.scheduled_end < now),
                MaintenanceWindow.status.in_(["completed", "canceled"]),
            )
        )
        .order_by(MaintenanceWindow.scheduled_start.desc())
        .limit(10)
        .all()
    )
    announcements = (
        db.query(Announcement)
        .filter(Announcement.status == "published")
        .order_by(Announcement.pinned.desc(), Announcement.published_at.desc())
        .limit(10)
        .all()
    )
    try:
        from backend.services.status_monitor import compute_components
        components = public_components(compute_components(db, now))
    except Exception:  # noqa: BLE001 — 監視未初期化でも公開ステータスは返す
        components = []
    return {
        "overall": overall,
        "components": components,
        "active_incidents": [_public_inc_dict(i) for i in unresolved],
        "recent_incidents": [_public_inc_dict(i) for i in recent],
        "maintenance": [_mnt_dict(m) for m in maint],
        "recent_maintenance": [_mnt_dict(m) for m in recent_maint],
        "announcements": [_ann_dict(a) for a in announcements],
        "checked_at": now.isoformat(),
    }


@router.get("/public/status")
def public_status(db: Session = Depends(get_db)):
    """公開ステータス。認証不要 (/api/public/* は anon 許可)。"""
    return compute_public_status(db)


@router.post("/status/incidents", status_code=201)
def create_incident(body: IncidentCreate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    if body.severity not in _SEVERITY:
        raise HTTPException(status_code=422, detail="invalid severity")
    inc = StatusIncident(
        title=body.title, reason=body.reason, severity=body.severity,
        component=body.component, began_at=body.began_at or datetime.utcnow(),
        status="investigating",
    )
    db.add(inc); db.commit()
    return _inc_dict(inc)


@router.patch("/status/incidents/{inc_id}")
def patch_incident(inc_id: int, body: IncidentPatch, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    inc = db.get(StatusIncident, inc_id)
    if not inc:
        raise HTTPException(status_code=404, detail="incident not found")
    if body.status is not None:
        if body.status not in _INC_STATUS:
            raise HTTPException(status_code=422, detail="invalid status")
        inc.status = body.status
    if body.reason is not None:
        inc.reason = body.reason
    if body.resolved:
        inc.status = "resolved"
        inc.resolved_at = datetime.utcnow()
    db.commit()
    return _inc_dict(inc)


@router.post("/status/maintenance", status_code=201)
def create_maintenance(body: MaintenanceCreate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    m = MaintenanceWindow(
        title=body.title, body=body.body, scheduled_start=body.scheduled_start,
        scheduled_end=body.scheduled_end, status="scheduled",
    )
    db.add(m); db.commit()
    return _mnt_dict(m)


@router.patch("/status/maintenance/{mnt_id}")
def patch_maintenance(mnt_id: int, body: MaintenancePatch, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    m = db.get(MaintenanceWindow, mnt_id)
    if not m:
        raise HTTPException(status_code=404, detail="maintenance not found")
    if body.status is not None:
        if body.status not in _MNT_STATUS:
            raise HTTPException(status_code=422, detail="invalid status")
        m.status = body.status
    if body.body is not None:
        m.body = body.body
    if body.scheduled_end is not None:
        m.scheduled_end = body.scheduled_end
    db.commit()
    return _mnt_dict(m)


@router.post("/status/announcements", status_code=201)
def create_announcement(body: AnnouncementCreate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    a = Announcement(
        title=body.title, body=body.body, pinned=body.pinned,
        published_at=body.published_at or datetime.utcnow(), status="published",
    )
    db.add(a); db.commit()
    return _ann_dict(a)


@router.patch("/status/announcements/{ann_id}")
def patch_announcement(ann_id: int, body: AnnouncementPatch, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    a = db.get(Announcement, ann_id)
    if not a:
        raise HTTPException(status_code=404, detail="announcement not found")
    if body.status is not None:
        if body.status not in _ANN_STATUS:
            raise HTTPException(status_code=422, detail="invalid status")
        a.status = body.status
    if body.title is not None:
        a.title = body.title
    if body.body is not None:
        a.body = body.body
    if body.pinned is not None:
        a.pinned = body.pinned
    db.commit()
    return _ann_dict(a)

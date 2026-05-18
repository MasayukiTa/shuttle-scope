"""製品テレメトリ + admin Analytics + チュートリアル進行 + 開示 export。

エンドポイント:
  POST /api/_telemetry/ingest                   — 認証ユーザのイベントバッチを受領
  GET  /api/admin/analytics/overview            — admin: KPI 5 セクション一括
  GET  /api/admin/analytics/funnel              — admin: アノテーションファネル
  GET  /api/admin/analytics/dwell               — admin: 機能別 dwell ランキング
  GET  /api/admin/analytics/learning            — admin: 学習曲線 (per-user)
  GET  /api/admin/analytics/condition_quality   — admin: 体調入力品質
  GET  /api/tutorials/state                     — 自分のチュートリアル進行
  POST /api/tutorials/{tutorial_id}/step        — チュートリアルステップ更新
  POST /api/tutorials/{tutorial_id}/replay      — チュートリアル再生 (replay_count++)
  GET  /api/me/data_export                      — GDPR Art 15 / APPI 第28条 自分のデータ DL (ZIP)

法的根拠 / 設計詳細は PRIVACY.md §テレメトリ章を参照。
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import (
    Match,
    ProductEvent,
    TutorialCompletion,
    User,
    UserConsent,
)
from backend.utils.auth import AuthCtx, get_auth, require_admin
from backend.utils.telemetry import (
    ALLOWED_EVENT_TYPES,
    MAX_EVENTS_PER_BATCH,
    insert_events,
)

router = APIRouter(tags=["telemetry"])


# ─── イベント ingest ─────────────────────────────────────────────────────

class IngestEvent(BaseModel):
    event_id: Optional[str] = None
    event_type: str = Field(..., max_length=40)
    props: Optional[dict] = None
    client_ts: Optional[Any] = None  # ms epoch or ISO string

    model_config = {"extra": "ignore"}


class IngestBatch(BaseModel):
    events: list[IngestEvent] = Field(default_factory=list, max_length=MAX_EVENTS_PER_BATCH)
    platform: Optional[str] = Field(None, max_length=20)
    app_version: Optional[str] = Field(None, max_length=40)

    model_config = {"extra": "ignore"}


@router.post("/_telemetry/ingest")
def telemetry_ingest(
    payload: IngestBatch,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    """イベントバッチを受領。

    認証必須 (未認証は静かに 0 件処理して 200 を返す、telemetry がアプリの
    機能を壊さない原則)。テレメトリは「止めない」が最優先なので、内部例外も
    握りつぶして 200 を返す。
    """
    if not ctx.user_id:
        return {"success": True, "inserted": 0, "skipped": "no_user"}

    raw_events = [e.model_dump() for e in payload.events]
    try:
        inserted = insert_events(
            db,
            events=raw_events,
            user_id=ctx.user_id,
            team_id=ctx.team_id,
            role=ctx.role,
            platform=payload.platform,
            app_version=payload.app_version,
        )
    except Exception:
        # telemetry 失敗でアプリ機能を壊さない
        try:
            db.rollback()
        except Exception:
            pass
        return {"success": True, "inserted": 0, "skipped": "internal"}
    return {"success": True, "inserted": inserted}


# ─── Admin Analytics ─────────────────────────────────────────────────────

def _props_value_sql(key: str) -> str:
    """JSON 内の値を文字列で取り出す SQL 断片。PG/SQLite 両対応。"""
    # 簡易: PG は props->>'key'、SQLite は json_extract(props, '$.key')
    # SQLAlchemy で dialect 別に書くのが面倒なので両方使える式を用意
    return key  # 実コードでは dialect で分岐 (下記関数で抽象化)


def _is_pg(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _prop_get(db: Session, key: str) -> str:
    """props JSON から key の値を文字列で取り出す SQL 式 (dialect 依存)。"""
    if _is_pg(db):
        return f"(props->>'{key}')"
    return f"json_extract(props, '$.{key}')"


@router.get("/admin/analytics/overview")
def admin_overview(
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_admin),
):
    """KPI 一括取得 — 直近 7d/30d の WAU/MAU/イベント数 + ファネル先頭。"""
    now = datetime.utcnow()
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)

    # WAU/MAU = 期間内に session_start を 1 回以上記録したユニーク user_id_hash 数
    wau = (
        db.query(func.count(func.distinct(ProductEvent.user_id_hash)))
        .filter(ProductEvent.event_type == "session_start", ProductEvent.server_ts >= d7)
        .scalar()
        or 0
    )
    mau = (
        db.query(func.count(func.distinct(ProductEvent.user_id_hash)))
        .filter(ProductEvent.event_type == "session_start", ProductEvent.server_ts >= d30)
        .scalar()
        or 0
    )
    total_events_7d = (
        db.query(func.count(ProductEvent.event_id))
        .filter(ProductEvent.server_ts >= d7)
        .scalar()
        or 0
    )

    # role 別 WAU
    by_role_rows = (
        db.query(ProductEvent.role, func.count(func.distinct(ProductEvent.user_id_hash)))
        .filter(ProductEvent.event_type == "session_start", ProductEvent.server_ts >= d7)
        .group_by(ProductEvent.role)
        .all()
    )
    wau_by_role = {(r or "unknown"): c for r, c in by_role_rows}

    # platform 別 WAU
    plat_rows = (
        db.query(ProductEvent.platform, func.count(func.distinct(ProductEvent.user_id_hash)))
        .filter(ProductEvent.event_type == "session_start", ProductEvent.server_ts >= d7)
        .group_by(ProductEvent.platform)
        .all()
    )
    wau_by_platform = {(p or "unknown"): c for p, c in plat_rows}

    return {
        "success": True,
        "data": {
            "wau": wau,
            "mau": mau,
            "total_events_7d": total_events_7d,
            "wau_by_role": wau_by_role,
            "wau_by_platform": wau_by_platform,
            "as_of": now.isoformat(),
        },
    }


@router.get("/admin/analytics/funnel")
def admin_funnel(
    days: int = 30,
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_admin),
):
    """アノテーションファネル: pass1 開始 → 完了 → pass2 開始 → … を集計。"""
    days = max(1, min(365, days))
    since = datetime.utcnow() - timedelta(days=days)
    pg_key = _prop_get(db, "pass_no")

    # event_type ごとに pass_no (1/2/3) で集計
    rows = db.execute(
        text(
            f"""
            SELECT event_type, {pg_key} AS pass_no, platform,
                   COUNT(*) AS cnt,
                   COUNT(DISTINCT user_id_hash) AS unique_users
            FROM product_events
            WHERE event_type IN ('pass_started','pass_completed','pass_abandoned')
              AND server_ts >= :since
            GROUP BY event_type, {pg_key}, platform
            """
        ),
        {"since": since},
    ).fetchall()

    funnel: dict = {"desktop": {}, "mobile_web": {}, "mobile_pwa": {}, "unknown": {}}
    for et, pass_no, platform, cnt, uniq in rows:
        p = platform or "unknown"
        if p not in funnel:
            funnel[p] = {}
        key = f"pass{pass_no}"
        funnel[p].setdefault(key, {"started": 0, "completed": 0, "abandoned": 0,
                                    "unique_users_started": 0})
        if et == "pass_started":
            funnel[p][key]["started"] += int(cnt)
            funnel[p][key]["unique_users_started"] += int(uniq)
        elif et == "pass_completed":
            funnel[p][key]["completed"] += int(cnt)
        elif et == "pass_abandoned":
            funnel[p][key]["abandoned"] += int(cnt)

    # 離脱直前 last_input_type top
    li_key = _prop_get(db, "last_input_type")
    last_input_rows = db.execute(
        text(
            f"""
            SELECT {li_key} AS last_input, COUNT(*) AS cnt
            FROM product_events
            WHERE event_type = 'pass_abandoned'
              AND server_ts >= :since
              AND {li_key} IS NOT NULL
            GROUP BY {li_key}
            ORDER BY cnt DESC
            LIMIT 20
            """
        ),
        {"since": since},
    ).fetchall()
    last_input_top = [{"last_input_type": li, "count": int(c)} for li, c in last_input_rows]

    return {
        "success": True,
        "data": {
            "funnel": funnel,
            "abandonment_last_input_top": last_input_top,
            "days": days,
        },
    }


@router.get("/admin/analytics/dwell")
def admin_dwell(
    days: int = 30,
    limit: int = 50,
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_admin),
):
    """分析画面ごとの実需 (view_id × unique_user × median_dwell)。"""
    days = max(1, min(365, days))
    limit = max(1, min(200, limit))
    since = datetime.utcnow() - timedelta(days=days)
    vid = _prop_get(db, "view_id")
    dwell = _prop_get(db, "dwell_ms")
    cast_int = "::int" if _is_pg(db) else ""

    rows = db.execute(
        text(
            f"""
            SELECT {vid} AS view_id,
                   COUNT(*) AS view_count,
                   COUNT(DISTINCT user_id_hash) AS unique_users,
                   AVG(CAST({dwell} AS INTEGER)) AS avg_dwell_ms,
                   SUM(CAST({dwell} AS INTEGER)) AS total_dwell_ms
            FROM product_events
            WHERE event_type = 'analysis_dwell'
              AND server_ts >= :since
              AND {vid} IS NOT NULL
            GROUP BY {vid}
            ORDER BY total_dwell_ms DESC NULLS LAST
            LIMIT :lim
            """
        ),
        {"since": since, "lim": limit},
    ).fetchall()

    items = []
    for view_id, vc, uu, avg_d, tot_d in rows:
        items.append({
            "view_id": view_id,
            "view_count": int(vc or 0),
            "unique_users": int(uu or 0),
            "avg_dwell_ms": int(avg_d or 0),
            "total_dwell_minutes": int((tot_d or 0) / 60000),
        })
    return {"success": True, "data": {"items": items, "days": days}}


@router.get("/admin/analytics/learning")
def admin_learning(
    weeks: int = 8,
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_admin),
):
    """学習曲線: ユーザーごとの週次 median time-per-input。"""
    weeks = max(1, min(52, weeks))
    since = datetime.utcnow() - timedelta(weeks=weeks)
    elapsed = _prop_get(db, "elapsed_since_prev_ms")

    if _is_pg(db):
        bucket_sql = "date_trunc('week', server_ts)"
    else:
        bucket_sql = "strftime('%Y-%W', server_ts)"

    rows = db.execute(
        text(
            f"""
            SELECT {bucket_sql} AS week,
                   user_id_hash,
                   AVG(CAST({elapsed} AS INTEGER)) AS avg_ms,
                   COUNT(*) AS n
            FROM product_events
            WHERE event_type = 'input_event'
              AND server_ts >= :since
              AND {elapsed} IS NOT NULL
            GROUP BY week, user_id_hash
            HAVING COUNT(*) >= 5
            ORDER BY week, user_id_hash
            """
        ),
        {"since": since},
    ).fetchall()

    series: dict[str, list[dict]] = {}
    for week, uid, avg_ms, n in rows:
        key = str(uid)[:8] if uid else "anon"
        series.setdefault(key, []).append({
            "week": str(week),
            "avg_input_ms": int(avg_ms or 0),
            "sample": int(n or 0),
        })
    return {"success": True, "data": {"series": series, "weeks": weeks}}


@router.get("/admin/analytics/condition_quality")
def admin_condition_quality(
    days: int = 30,
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_admin),
):
    """質問票の項目別 入力時間 + 変更回数。"""
    days = max(1, min(365, days))
    since = datetime.utcnow() - timedelta(days=days)
    qid = _prop_get(db, "question_id")
    elapsed = _prop_get(db, "elapsed_ms")
    changes = _prop_get(db, "value_changed_count")

    rows = db.execute(
        text(
            f"""
            SELECT {qid} AS question_id,
                   COUNT(*) AS n,
                   AVG(CAST({elapsed} AS INTEGER)) AS avg_ms,
                   AVG(CAST({changes} AS INTEGER)) AS avg_changes
            FROM product_events
            WHERE event_type = 'condition_input'
              AND server_ts >= :since
              AND {qid} IS NOT NULL
            GROUP BY {qid}
            ORDER BY avg_ms DESC NULLS LAST
            LIMIT 100
            """
        ),
        {"since": since},
    ).fetchall()

    items = [
        {
            "question_id": qid_,
            "n": int(n or 0),
            "avg_ms": int(avg_ms or 0),
            "avg_changes": float(avg_changes or 0),
        }
        for qid_, n, avg_ms, avg_changes in rows
    ]
    return {"success": True, "data": {"items": items, "days": days}}


# ─── チュートリアル ─────────────────────────────────────────────────────

class TutorialStepBody(BaseModel):
    step: int = Field(..., ge=0, le=200)
    status: Optional[str] = Field(None, pattern=r"^(in_progress|completed|skipped)$")

    model_config = {"extra": "forbid"}


@router.get("/tutorials/state")
def tutorial_state(
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="auth required")
    rows = db.query(TutorialCompletion).filter(TutorialCompletion.user_id == ctx.user_id).all()
    return {
        "success": True,
        "data": [
            {
                "tutorial_id": r.tutorial_id,
                "status": r.status,
                "last_step": r.last_step,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "replay_count": r.replay_count,
            }
            for r in rows
        ],
    }


@router.post("/tutorials/{tutorial_id}/step")
def tutorial_step(
    tutorial_id: str,
    body: TutorialStepBody,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="auth required")
    if not tutorial_id or len(tutorial_id) > 64 or not tutorial_id.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="bad tutorial_id")

    rec = (
        db.query(TutorialCompletion)
        .filter(
            TutorialCompletion.user_id == ctx.user_id,
            TutorialCompletion.tutorial_id == tutorial_id,
        )
        .first()
    )
    if rec is None:
        rec = TutorialCompletion(
            user_id=ctx.user_id,
            tutorial_id=tutorial_id,
            status="in_progress",
            last_step=body.step,
        )
        db.add(rec)
    else:
        rec.last_step = max(rec.last_step, body.step)
    if body.status:
        rec.status = body.status
        if body.status == "completed" and rec.completed_at is None:
            rec.completed_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.post("/tutorials/{tutorial_id}/replay")
def tutorial_replay(
    tutorial_id: str,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="auth required")
    if not tutorial_id or len(tutorial_id) > 64:
        raise HTTPException(status_code=400, detail="bad tutorial_id")
    rec = (
        db.query(TutorialCompletion)
        .filter(
            TutorialCompletion.user_id == ctx.user_id,
            TutorialCompletion.tutorial_id == tutorial_id,
        )
        .first()
    )
    if rec is None:
        rec = TutorialCompletion(
            user_id=ctx.user_id, tutorial_id=tutorial_id,
            status="in_progress", last_step=0, replay_count=1,
        )
        db.add(rec)
    else:
        rec.replay_count = (rec.replay_count or 0) + 1
        rec.status = "in_progress"
        rec.last_step = 0
    db.commit()
    return {"success": True, "replay_count": rec.replay_count}


# ─── 開示 export (GDPR Art 15 / APPI 第28条) ──────────────────────────────

@router.get("/me/data_export")
def me_data_export(
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    """自分のデータを ZIP 1 本にまとめて DL。

    含むもの:
      - profile.json (User の自分のレコード、機密フィールドは伏字)
      - consents.jsonl (UserConsent)
      - matches.jsonl (Match のうち自分が annotator のもの)
      - tutorial_completion.jsonl
      - events.jsonl (自分の user_id_hash のテレメトリ全件)
      - README.txt (項目説明)
    """
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="auth required")

    from backend.utils.telemetry import hash_id
    uid_h = hash_id(ctx.user_id)

    me = db.query(User).filter(User.id == ctx.user_id).first()
    if me is None:
        raise HTTPException(status_code=404, detail="user not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # profile
        zf.writestr("profile.json", json.dumps({
            "id": me.id,
            "username": me.username,
            "role": me.role,
            "team_name": me.team_name,
            "team_id": me.team_id,
            "email": me.email,
            "date_of_birth": me.date_of_birth.isoformat() if me.date_of_birth else None,
            "created_at": me.created_at.isoformat() if me.created_at else None,
        }, ensure_ascii=False, indent=2))

        # consents
        consents = db.query(UserConsent).filter(UserConsent.user_id == ctx.user_id).all()
        with io.StringIO() as s:
            for c in consents:
                s.write(json.dumps({
                    "consent_type": c.consent_type,
                    "consent_given": c.consent_given,
                    "privacy_policy_version": c.privacy_policy_version,
                    "terms_version": c.terms_version,
                    "given_at": c.given_at.isoformat() if c.given_at else None,
                    "withdrawn_at": c.withdrawn_at.isoformat() if c.withdrawn_at else None,
                }, ensure_ascii=False) + "\n")
            zf.writestr("consents.jsonl", s.getvalue())

        # matches (自分が annotator として登録した試合)
        matches = db.query(Match).filter(Match.annotator_id == ctx.user_id).limit(10000).all()
        with io.StringIO() as s:
            for m in matches:
                s.write(json.dumps({
                    "id": m.id,
                    "uuid": m.uuid,
                    "tournament": m.tournament,
                    "round": m.round,
                    "date": m.date.isoformat() if m.date else None,
                    "format": m.format,
                    "result": m.result,
                    "annotation_status": m.annotation_status,
                    "captured_minor_flag": m.captured_minor_flag,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }, ensure_ascii=False) + "\n")
            zf.writestr("matches.jsonl", s.getvalue())

        # tutorial completion
        tuts = db.query(TutorialCompletion).filter(TutorialCompletion.user_id == ctx.user_id).all()
        with io.StringIO() as s:
            for t in tuts:
                s.write(json.dumps({
                    "tutorial_id": t.tutorial_id,
                    "status": t.status,
                    "last_step": t.last_step,
                    "started_at": t.started_at.isoformat() if t.started_at else None,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    "replay_count": t.replay_count,
                }, ensure_ascii=False) + "\n")
            zf.writestr("tutorial_completion.jsonl", s.getvalue())

        # events (自分のテレメトリ)
        evts = (
            db.query(ProductEvent)
            .filter(ProductEvent.user_id_hash == uid_h)
            .order_by(ProductEvent.server_ts.desc())
            .limit(100000)
            .all()
        )
        with io.StringIO() as s:
            for e in evts:
                s.write(json.dumps({
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "props": _safe_json_loads(e.props),
                    "client_ts": e.client_ts.isoformat() if e.client_ts else None,
                    "server_ts": e.server_ts.isoformat() if e.server_ts else None,
                    "platform": e.platform,
                    "app_version": e.app_version,
                }, ensure_ascii=False) + "\n")
            zf.writestr("events.jsonl", s.getvalue())

        zf.writestr("README.txt", _EXPORT_README)

    buf.seek(0)
    fname = f"shuttlescope_export_user{ctx.user_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _safe_json_loads(s: Optional[str]) -> Any:
    if not s:
        return {}
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return {"_raw": s}


_EXPORT_README = """ShuttleScope — Personal Data Export (GDPR Art. 15 / APPI 第28条)

Generated: """ + datetime.utcnow().isoformat() + """ UTC

Contents:
  profile.json              — Your account profile.
  consents.jsonl            — All consent records (given / withdrawn).
  matches.jsonl             — Matches you registered as the annotator.
  tutorial_completion.jsonl — Your tutorial progress.
  events.jsonl              — Product telemetry events tied to your account
                              (pseudonymised user_id_hash, no raw user id).

Format: One JSON object per line for .jsonl files.

Questions / corrections / deletion requests:
  contact@shuttle-scope.com
"""

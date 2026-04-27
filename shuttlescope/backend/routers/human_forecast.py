"""
Phase S2: ヒューマンベンチマーク — コーチ/アナリスト試合前予測の収集・比較 API

エンドポイント:
  POST /prediction/human_forecast          — 試合前予測を保存
  GET  /prediction/human_forecast/{match_id} — 特定試合の予測一覧
  DELETE /prediction/human_forecast/{id}   — 予測削除
  GET  /prediction/benchmark/{player_id}   — プレイヤー別 人間 vs モデル ベンチマーク集計
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import HumanForecast, Match, Player
from backend.utils.auth import get_auth, AuthCtx
from fastapi import HTTPException as _HTTPException


def _require_auth(request: Request) -> AuthCtx:
    ctx = get_auth(request)
    if ctx.role is None:
        raise _HTTPException(status_code=401, detail="認証が必要です")
    return ctx
from backend.utils.sync_meta import touch_sync_metadata, get_device_id
from backend.analysis.prediction_engine import (
    get_matches_for_player,
    compute_win_probability,
    compute_feature_win_prob,
    compute_recent_form,
    get_observation_context,
    _player_wins_match,
)

router = APIRouter()


# ── リクエストスキーマ ─────────────────────────────────────────────────────────

class HumanForecastCreate(BaseModel):
    # SQLite/PostgreSQL の INTEGER は 32-bit。範囲外を Pydantic で 422 拒否する
    match_id: int = Field(..., ge=1, le=2_147_483_647)
    player_id: int = Field(..., ge=1, le=2_147_483_647)
    forecaster_role: str = Field(..., pattern="^(coach|analyst)$")
    forecaster_name: Optional[str] = None
    predicted_outcome: str = Field(..., pattern="^(win|loss)$")
    predicted_set_path: Optional[str] = Field(
        None, pattern="^(2-0|2-1|1-2|0-2)$"
    )
    predicted_win_probability: Optional[int] = Field(None, ge=0, le=100)
    confidence_level: Optional[str] = Field(
        None, pattern="^(high|medium|low)$"
    )
    notes: Optional[str] = None


# ── エンドポイント ────────────────────────────────────────────────────────────

@router.post("/prediction/human_forecast")
def create_human_forecast(
    body: HumanForecastCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """試合前の人間予測を保存する"""
    # 試合存在確認
    m = db.get(Match, body.match_id)
    if not m:
        raise HTTPException(status_code=404, detail="Match not found")
    if not db.get(Player, body.player_id):
        raise HTTPException(status_code=404, detail="Player not found")

    ctx = get_auth(request)
    # Phase B: チーム境界チェック (4-1)
    from backend.utils.auth import user_can_access_match
    if not user_can_access_match(ctx, m):
        raise HTTPException(status_code=404, detail="Match not found")
    forecast = HumanForecast(
        match_id=body.match_id,
        player_id=body.player_id,
        forecaster_role=body.forecaster_role,
        forecaster_name=body.forecaster_name,
        predicted_outcome=body.predicted_outcome,
        predicted_set_path=body.predicted_set_path,
        predicted_win_probability=body.predicted_win_probability,
        confidence_level=body.confidence_level,
        notes=body.notes,
        team_id=ctx.team_id,
    )
    db.add(forecast)
    payload = {
        "match_id": body.match_id,
        "player_id": body.player_id,
        "predicted_outcome": body.predicted_outcome,
        "predicted_win_probability": body.predicted_win_probability,
    }
    touch_sync_metadata(forecast, payload_like=payload, device_id=get_device_id(db))
    db.commit()
    db.refresh(forecast)

    return {
        "success": True,
        "data": _forecast_to_dict(forecast),
    }


@router.get("/prediction/human_forecast/{match_id}")
def get_human_forecasts(
    request: Request,
    match_id: int = Path(..., ge=1, le=2_147_483_647),
    player_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
    db: Session = Depends(get_db),
    _auth: AuthCtx = Depends(_require_auth),
):
    """特定試合の人間予測一覧を返す"""
    ctx = get_auth(request)
    q = db.query(HumanForecast).filter(HumanForecast.match_id == match_id, HumanForecast.deleted_at.is_(None))
    if not ctx.is_admin:
        q = q.filter(or_(HumanForecast.team_id.is_(None), HumanForecast.team_id == ctx.team_id))
    if player_id is not None:
        q = q.filter(HumanForecast.player_id == player_id)
    forecasts = q.order_by(HumanForecast.created_at.desc()).all()

    return {
        "success": True,
        "data": [_forecast_to_dict(f) for f in forecasts],
    }


@router.delete("/prediction/human_forecast/{forecast_id}")
def delete_human_forecast(
    forecast_id: int = Path(..., ge=1, le=2_147_483_647),
    *,
    request: Request,
    db: Session = Depends(get_db),
    _auth: AuthCtx = Depends(_require_auth),
):
    """人間予測を論理削除する（tombstone）"""
    f = db.get(HumanForecast, forecast_id)
    if not f or f.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Forecast not found")
    # Phase B: チーム境界チェック (4-1)
    ctx = get_auth(request)
    if not ctx.is_admin:
        # 自チーム作成（team_id 一致）か、互換 NULL のみ削除可
        if f.team_id is not None and f.team_id != ctx.team_id:
            raise HTTPException(status_code=404, detail="Forecast not found")
        m = db.get(Match, f.match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="Forecast not found")
        from backend.utils.auth import user_can_access_match
        if not user_can_access_match(ctx, m):
            raise HTTPException(status_code=404, detail="Forecast not found")
    touch_sync_metadata(f, device_id=get_device_id(db))
    db.commit()
    return {"success": True}


@router.get("/prediction/benchmark/{player_id}")
def get_prediction_benchmark(
    player_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _auth: AuthCtx = Depends(_require_auth),
):
    """
    プレイヤー別のヒューマン vs モデル ベンチマーク集計。
    結果が確定している試合（result が win/loss）のみ評価対象。
    各ロール別の予測精度（accuracy, Brier score）を返す。
    """
    # このプレイヤーについての全人間予測を取得
    forecasts = (
        db.query(HumanForecast)
        .filter(HumanForecast.player_id == player_id, HumanForecast.deleted_at.is_(None))
        .all()
    )
    if not forecasts:
        return {
            "success": True,
            "data": {
                "summary": [],
                "match_comparisons": [],
                "total_forecasts": 0,
            },
        }

    # 試合ごとに集計
    match_ids = list({f.match_id for f in forecasts})
    matches_by_id: dict[int, Match] = {
        m.id: m
        for m in db.query(Match).filter(Match.id.in_(match_ids)).all()
        if m.result in ('win', 'loss')
    }

    # モデル予測（全試合の事前計算）
    all_player_matches = get_matches_for_player(db, player_id)

    comparisons: list[dict] = []
    for f in forecasts:
        m = matches_by_id.get(f.match_id)
        if not m:
            continue  # 未確定試合はスキップ

        actual_outcome = 'win' if _player_wins_match(m, player_id) else 'loss'
        human_correct = (f.predicted_outcome == actual_outcome)

        # モデル予測: この試合を除いた上での勝率
        prior_matches = [x for x in all_player_matches if x.id != m.id]
        recent = compute_recent_form(prior_matches, player_id)
        h2h_m = [x for x in prior_matches
                 if (x.player_a_id == player_id and x.player_b_id in (m.player_a_id, m.player_b_id)
                     and x.id != m.id)
                 or (x.player_b_id == player_id and x.player_a_id in (m.player_a_id, m.player_b_id)
                     and x.id != m.id)]
        obs = get_observation_context(db, player_id, match_id=m.id)
        model_prob, _ = compute_feature_win_prob(prior_matches, player_id, h2h_m, recent, obs)
        model_predicted = 'win' if model_prob >= 0.5 else 'loss'
        model_correct = (model_predicted == actual_outcome)

        # Brier 寄与
        actual_bin = 1.0 if actual_outcome == 'win' else 0.0
        model_brier = (model_prob - actual_bin) ** 2
        human_prob = (f.predicted_win_probability or (70 if f.predicted_outcome == 'win' else 30)) / 100
        human_brier = (human_prob - actual_bin) ** 2

        comparisons.append({
            'match_id': m.id,
            'match_date': m.date.isoformat() if hasattr(m.date, 'isoformat') else str(m.date),
            'tournament_level': m.tournament_level or '—',
            'actual_outcome': actual_outcome,
            'forecaster_role': f.forecaster_role,
            'forecaster_name': f.forecaster_name,
            'human_predicted': f.predicted_outcome,
            'human_set_path': f.predicted_set_path,
            'human_win_prob': f.predicted_win_probability,
            'human_correct': human_correct,
            'human_brier': round(human_brier, 4),
            'model_win_prob': round(model_prob * 100),
            'model_predicted': model_predicted,
            'model_correct': model_correct,
            'model_brier': round(model_brier, 4),
        })

    # ロール別サマリー
    role_stats: dict[str, dict] = {}
    for c in comparisons:
        role = c['forecaster_role']
        if role not in role_stats:
            role_stats[role] = {
                'role': role,
                'n': 0,
                'human_correct': 0,
                'model_correct': 0,
                'human_brier_sum': 0.0,
                'model_brier_sum': 0.0,
            }
        s = role_stats[role]
        s['n'] += 1
        s['human_correct'] += int(c['human_correct'])
        s['model_correct'] += int(c['model_correct'])
        s['human_brier_sum'] += c['human_brier']
        s['model_brier_sum'] += c['model_brier']

    summary = []
    for s in role_stats.values():
        n = s['n']
        if n == 0:
            continue
        summary.append({
            'role': s['role'],
            'n': n,
            'human_accuracy': round(s['human_correct'] / n, 4),
            'model_accuracy': round(s['model_correct'] / n, 4),
            'human_brier': round(s['human_brier_sum'] / n, 4),
            'model_brier': round(s['model_brier_sum'] / n, 4),
            'model_advantage': round(
                (s['human_brier_sum'] - s['model_brier_sum']) / n, 4
            ),
        })

    return {
        "success": True,
        "data": {
            "summary": summary,
            "match_comparisons": comparisons,
            "total_forecasts": len(forecasts),
        },
    }


# ── ヘルパー ─────────────────────────────────────────────────────────────────

def _forecast_to_dict(f: HumanForecast) -> dict:
    return {
        'id': f.id,
        'match_id': f.match_id,
        'player_id': f.player_id,
        'forecaster_role': f.forecaster_role,
        'forecaster_name': f.forecaster_name,
        'predicted_outcome': f.predicted_outcome,
        'predicted_set_path': f.predicted_set_path,
        'predicted_win_probability': f.predicted_win_probability,
        'confidence_level': f.confidence_level,
        'notes': f.notes,
        'created_at': f.created_at.isoformat() if f.created_at else None,
    }

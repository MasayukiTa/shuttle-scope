"""包括レポート生成 — 選手単位で「現在 role が見られる解析全て」を集約。

エンドポイント設計の意図:
  - PDF: 印刷して選手 + コーチが机に並べて議論できるレポート。展開項目も
    含め、視覚的に追えるよう section + table + 短いナラティブ。
  - JSON: 数値ベースの完全 dump (試合単位データ込み)。差分解析・外部処理用。

実装方針:
  - 既存の router 関数を直接 import して call する (HTTP loopback 不要)。
  - 各 section は try/except で囲み、1 つコケても他は出る。
  - role に応じて section をフィルタ。player には raw EPV / 勝率を出さない
    (CLAUDE.md non-negotiable rule)。

拡張:
  - 新規 section を追加するには `_SECTIONS` に dict 1 個追加するだけ。
"""
from __future__ import annotations

import logging
from datetime import date as DateType
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from backend.utils.auth import AuthCtx

log = logging.getLogger(__name__)


def _safe_call(label: str, fn: Callable, *args, **kwargs) -> dict:
    """関数を呼び、例外を section_error に変換して返す。"""
    try:
        result = fn(*args, **kwargs)
        # FastAPI handler は dict を返すか、HTTPException を投げる
        return {"ok": True, "data": result}
    except Exception as e:
        log.warning("comprehensive_report section %s failed: %s", label, e)
        return {"ok": False, "error": str(e)[:200]}


def gather_player_report(
    db: Session,
    player_id: int,
    ctx: AuthCtx,
    *,
    date_from: Optional[DateType] = None,
    date_to: Optional[DateType] = None,
    tournament_level: Optional[str] = None,
    include_per_match: bool = False,
) -> dict:
    """全 section を順次収集して dict を返す。

    role に応じてフィルタ。include_per_match=True なら matches[] に
    試合単位データを追加 (JSON 用)。
    """
    from backend.db.models import Match, Player, Rally, GameSet, Stroke
    role = ctx.role or "analyst"

    # ── 0. ヘッダ ────────────────────────────────────────────────────
    player = db.get(Player, player_id)
    if not player:
        return {"success": False, "error": "player not found"}

    header = {
        "player": {
            "id": player.id,
            "name": player.name,
            "name_en": player.name_en,
            "team": player.team,
            "dominant_hand": player.dominant_hand,
            "birth_year": player.birth_year,
        },
        "generated_at_utc": __import__("datetime").datetime.utcnow().isoformat(),
        "generated_for_role": role,
        "filters": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "tournament_level": tournament_level,
        },
    }

    sections: dict[str, dict] = {}

    # ── 1. Descriptive ───────────────────────────────────────────────
    from backend.routers.analysis_stable import (
        get_descriptive,
        get_heatmap,
        get_shot_types,
        get_shot_win_loss,
        get_set_comparison,
        get_first_return_analysis,
        get_tournament_level_comparison,
        get_pre_loss_patterns,
        get_pre_win_patterns,
    )
    sections["descriptive"] = _safe_call(
        "descriptive", get_descriptive,
        player_id=player_id, result=None,
        tournament_level=tournament_level,
        date_from=date_from, date_to=date_to, db=db,
    )
    sections["heatmap_hit"] = _safe_call(
        "heatmap_hit", get_heatmap,
        player_id=player_id, type="hit",
        match_id=None, match_ids=None, db=db,
    )
    sections["heatmap_land"] = _safe_call(
        "heatmap_land", get_heatmap,
        player_id=player_id, type="land",
        match_id=None, match_ids=None, db=db,
    )
    sections["shot_types"] = _safe_call(
        "shot_types", get_shot_types,
        player_id=player_id,
        match_id=None, match_ids=None, db=db,
    )
    sections["shot_win_loss"] = _safe_call(
        "shot_win_loss", get_shot_win_loss,
        player_id=player_id, db=db,
    )
    sections["set_comparison"] = _safe_call(
        "set_comparison", get_set_comparison,
        player_id=player_id, db=db,
    )
    sections["first_return"] = _safe_call(
        "first_return", get_first_return_analysis,
        player_id=player_id, db=db,
    )
    sections["tournament_comparison"] = _safe_call(
        "tournament_comparison", get_tournament_level_comparison,
        player_id=player_id, db=db,
    )
    sections["pre_win_patterns"] = _safe_call(
        "pre_win_patterns", get_pre_win_patterns,
        player_id=player_id, db=db,
    )
    sections["pre_loss_patterns"] = _safe_call(
        "pre_loss_patterns", get_pre_loss_patterns,
        player_id=player_id, db=db,
    )

    # ── 2. Advanced (rally length / pressure / transition) ──────────
    from backend.routers.analysis_advanced import (
        get_rally_length_vs_winrate,
        get_pressure_performance,
        get_shot_transition_matrix,
        get_opponent_stats,
        get_temporal_performance,
    )
    sections["rally_length_winrate"] = _safe_call(
        "rally_length_winrate", get_rally_length_vs_winrate,
        player_id=player_id, db=db,
    )
    sections["pressure_performance"] = _safe_call(
        "pressure_performance", get_pressure_performance,
        player_id=player_id, db=db,
    )
    sections["shot_transition_matrix"] = _safe_call(
        "shot_transition_matrix", get_shot_transition_matrix,
        player_id=player_id, db=db,
    )
    sections["opponent_stats"] = _safe_call(
        "opponent_stats", get_opponent_stats,
        player_id=player_id, db=db,
    )
    sections["temporal_performance"] = _safe_call(
        "temporal_performance", get_temporal_performance,
        player_id=player_id, db=db,
    )

    # ── 3. Prediction (player には sanitize: 数値はぼかす) ──────────
    if role != "player":
        from backend.routers.prediction import (
            get_match_preview,
            get_fatigue_risk,
        )
        sections["fatigue_risk"] = _safe_call(
            "fatigue_risk", get_fatigue_risk,
            player_id=player_id, tournament_level=None, db=db,
        )
        # match_preview は対戦相手指定なので skip 可

    # ── 4. Growth ───────────────────────────────────────────────────
    try:
        from backend.routers.analysis_advanced import get_opponent_card  # noqa
    except ImportError:
        pass

    # ── 5. 試合単位 raw (JSON のみ) ─────────────────────────────────
    if include_per_match:
        matches = (
            db.query(Match)
            .filter(
                (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
            )
            .order_by(Match.date.desc().nullslast(), Match.id.desc())
            .limit(500)
            .all()
        )
        per_match: list[dict] = []
        for m in matches:
            mset_ids = [s.id for s in db.query(GameSet).filter(GameSet.match_id == m.id).all()]
            r_count = (
                db.query(Rally).filter(Rally.set_id.in_(mset_ids)).count()
                if mset_ids else 0
            )
            per_match.append({
                "id": m.id,
                "uuid": m.uuid,
                "date": m.date.isoformat() if m.date else None,
                "tournament": m.tournament,
                "tournament_level": m.tournament_level,
                "round": m.round,
                "format": m.format,
                "player_a_id": m.player_a_id,
                "player_b_id": m.player_b_id,
                "partner_a_id": m.partner_a_id,
                "partner_b_id": m.partner_b_id,
                "result": m.result,
                "final_score": m.final_score,
                "rally_count": r_count,
                "set_count": len(mset_ids),
                "annotation_status": m.annotation_status,
                "annotation_progress": m.annotation_progress,
                "captured_minor_flag": m.captured_minor_flag,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            })
        header["matches_included"] = len(per_match)
    else:
        per_match = []

    return {
        "success": True,
        "header": header,
        "sections": sections,
        "matches": per_match,
    }

"""analysis_simple.py — 簡易分析（要望8 / SD-08）

«細かい分析»（analysis_stable / advanced / research）とは別オプションの、
軽い «簡易分析» を置く。最初のエンドポイントは «打球の高さ差»。

計算の本体は backend.analysis.simple_height_diff にあり、DB も FastAPI も
読み込まない純粋関数。このルータは試合の打球を取り出して渡すだけの薄い層。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke
from backend.analysis.simple_height_diff import summarize_height_diffs

router = APIRouter()


@router.get("/analysis/simple/height_diff")
def get_simple_height_diff(match_id: int, db: Session = Depends(get_db)):
    """試合全体の «打球の高さ差» の簡易集計を返す。

    打った側と受けた側（連続する別チームの 2 球）の高さを 0〜3 に写し、差の絶対値を取る。
    高さが片方でも未入力の組は除く。ダブルスの隊形上の «味方への繋ぎ» は返球関係では
    ないので数えない（チーム判定は role_view.stroke_side）。
    """
    match = db.get(Match, match_id)
    if not match:
        return {"success": False, "error": "試合が見つかりません"}

    # match -> sets -> rallies -> strokes をラリー単位でまとめる
    rally_ids = (
        db.query(Rally.id)
        .join(GameSet, Rally.set_id == GameSet.id)
        .filter(GameSet.match_id == match_id)
        .all()
    )
    rally_ids = [rid for (rid,) in rally_ids]

    rallies_strokes: list[list[Stroke]] = []
    if rally_ids:
        strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id.in_(rally_ids))
            .order_by(Stroke.rally_id, Stroke.stroke_num)
            .all()
        )
        by_rally: dict[int, list[Stroke]] = {}
        for s in strokes:
            by_rally.setdefault(s.rally_id, []).append(s)
        rallies_strokes = list(by_rally.values())

    summary = summarize_height_diffs(rallies_strokes)
    return {
        "success": True,
        "data": {
            "match_id": match_id,
            **summary,
        },
    }

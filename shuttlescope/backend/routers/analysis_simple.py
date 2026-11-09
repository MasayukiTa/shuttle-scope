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
from backend.analysis.simple_height_diff import (
    summarize_height_diffs,
    top_height_diff_rallies,
)

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

    # match -> sets -> rallies -> strokes をラリー単位でまとめる。
    # set_num / rally_num も取り、«差が大きかったラリー» の表示に添える。
    rally_rows = (
        db.query(Rally.id, Rally.rally_num, GameSet.set_num)
        .join(GameSet, Rally.set_id == GameSet.id)
        .filter(GameSet.match_id == match_id)
        .order_by(GameSet.set_num, Rally.rally_num)
        .all()
    )
    rally_ids = [rid for (rid, _rn, _sn) in rally_rows]
    rally_meta: dict[int, dict] = {
        rid: {"set_num": sn, "rally_num": rn} for (rid, rn, sn) in rally_rows
    }

    by_rally: dict[int, list[Stroke]] = {}
    if rally_ids:
        strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id.in_(rally_ids))
            .order_by(Stroke.rally_id, Stroke.stroke_num)
            .all()
        )
        for s in strokes:
            by_rally.setdefault(s.rally_id, []).append(s)

    # set_num -> rally_num の順を保ってラリー列を組む
    ordered_rids = [rid for rid in rally_ids if rid in by_rally]
    rallies_strokes: list[list[Stroke]] = [by_rally[rid] for rid in ordered_rids]

    summary = summarize_height_diffs(rallies_strokes)

    # «差が大きかったラリー» の一覧（最大差の降順、上位 5 件）。
    top_rows = top_height_diff_rallies(
        ((rid, by_rally[rid]) for rid in ordered_rids),
        limit=5,
    )
    top_rallies = [
        {
            "set_num": rally_meta.get(row["rally"], {}).get("set_num"),
            "rally_num": rally_meta.get(row["rally"], {}).get("rally_num"),
            "max_diff": row["max_diff"],
            "pairs": row["pairs"],
        }
        for row in top_rows
    ]

    return {
        "success": True,
        "data": {
            "match_id": match_id,
            **summary,
            "top_rallies": top_rallies,
        },
    }

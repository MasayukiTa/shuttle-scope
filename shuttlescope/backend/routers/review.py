"""レビュー支援 API

B — 高速レビュー導線:
  GET /api/review/playlist?match_id=X[&winner=...&end_type=...&set_num=...]
    → タイムスタンプ付きラリー一覧（動画ジャンプ用）

D — セット間・試合中支援:
  GET /api/review/quick_summary?match_id=X&as_of_set=N[&as_of_rally=R]
    → ルールベースのコーチ向け一言カード
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke

router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# B — playlist
# ─────────────────────────────────────────────────────────────────

@router.get("/review/playlist")
def get_playlist(
    match_id: int,
    winner: Optional[str] = None,        # player_a / player_b
    end_type: Optional[str] = None,       # forced_error / unforced_error / ace / ...
    set_num: Optional[int] = None,
    has_timestamp_only: bool = False,     # True で timestamp_start が null のラリーを除外
    db: Session = Depends(get_db),
):
    """タイムスタンプ付きラリー一覧を返す。

    video_timestamp_start が設定されているラリーのみ動画ジャンプに使える。
    has_timestamp_only=false（デフォルト）の場合は全ラリーを返し、
    フロントがタイムスタンプ有無で表示を切り替える。
    """
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    # セット一覧
    sets_q = db.query(GameSet).filter(GameSet.match_id == match_id)
    if set_num is not None:
        sets_q = sets_q.filter(GameSet.set_num == set_num)
    sets = sets_q.order_by(GameSet.set_num).all()
    set_ids = [s.id for s in sets]
    set_map = {s.id: s.set_num for s in sets}

    if not set_ids:
        return {
            "success": True,
            "has_timestamps": False,
            # Phase 1: 生パスは露出させず、不透明トークンと URL のみ返す
            "video_token": match.video_token,
            "video_url": match.video_url,
            "rallies": [],
        }

    # ラリー取得
    q = db.query(Rally).filter(
        Rally.set_id.in_(set_ids),
        Rally.deleted_at.is_(None),
    )
    if winner:
        q = q.filter(Rally.winner == winner)
    if end_type:
        q = q.filter(Rally.end_type == end_type)
    if has_timestamp_only:
        q = q.filter(Rally.video_timestamp_start.isnot(None))

    rallies = q.order_by(Rally.set_id, Rally.rally_num).all()

    has_timestamps = any(r.video_timestamp_start is not None for r in rallies)

    return {
        "success": True,
        "has_timestamps": has_timestamps,
        # Phase 1: 生パスは露出させず、不透明トークンと URL のみ返す
        "video_token": match.video_token,
        "video_url": match.video_url,
        "rallies": [_rally_to_playlist_item(r, set_map) for r in rallies],
    }


def _rally_to_playlist_item(r: Rally, set_map: dict) -> dict:
    return {
        "id": r.id,
        "set_num": set_map.get(r.set_id, 0),
        "rally_num": r.rally_num,
        "server": r.server,
        "winner": r.winner,
        "end_type": r.end_type,
        "rally_length": r.rally_length,
        "duration_sec": r.duration_sec,
        "score_a_before": r.score_a_before,
        "score_b_before": r.score_b_before,
        "score_a_after": r.score_a_after,
        "score_b_after": r.score_b_after,
        "video_timestamp_start": r.video_timestamp_start,
        "video_timestamp_end": r.video_timestamp_end,
        "is_skipped": r.is_skipped,
    }


# ─────────────────────────────────────────────────────────────────
# D — quick_summary (コーチ向け一言カード)
# ─────────────────────────────────────────────────────────────────

# 直近何ラリーを見るか
_WINDOW = 5
# 連続失点検知閾値
_CONSECUTIVE_LOSS_THRESHOLD = 3
# ゾーン偏り検知閾値（直近 _WINDOW ラリー中 N 回以上）
_ZONE_BIAS_THRESHOLD = 3
# 強制エラー多発閾値
_FORCED_ERROR_THRESHOLD = 3


@router.get("/review/quick_summary")
def get_quick_summary(
    match_id: int,
    as_of_set: int = 1,
    as_of_rally: Optional[int] = None,   # None = セット全体
    player_side: str = "player_a",        # 自軍サイド
    db: Session = Depends(get_db),
):
    """ルールベースのコーチ向けサマリーカードを返す。

    Returns:
        {
          "cards": [
            { "level": "warn"|"info"|"good", "title": str, "body": str }
          ],
          "window": int,       # 分析対象ラリー数
          "total_rallies": int
        }
    """
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    # 対象セット取得
    game_set = (
        db.query(GameSet)
        .filter(GameSet.match_id == match_id, GameSet.set_num == as_of_set)
        .first()
    )
    if not game_set:
        return {"success": True, "cards": [], "window": 0, "total_rallies": 0}

    # ラリー取得（as_of_rally 以前のみ）
    q = db.query(Rally).filter(
        Rally.set_id == game_set.id,
        Rally.deleted_at.is_(None),
    ).order_by(Rally.rally_num)
    if as_of_rally is not None:
        q = q.filter(Rally.rally_num <= as_of_rally)
    rallies = q.all()

    if not rallies:
        return {"success": True, "cards": [], "window": 0, "total_rallies": 0}

    total = len(rallies)
    # 直近 _WINDOW ラリー
    recent = rallies[-_WINDOW:]
    window = len(recent)

    cards = []
    opponent_side = "player_b" if player_side == "player_a" else "player_a"

    # ── ルール 1: 連続失点 ────────────────────────────────────────
    consecutive_loss = 0
    max_consecutive = 0
    for r in reversed(rallies):
        if r.winner == opponent_side:
            consecutive_loss += 1
            max_consecutive = max(max_consecutive, consecutive_loss)
        else:
            break
    if max_consecutive >= _CONSECUTIVE_LOSS_THRESHOLD:
        cards.append({
            "level": "warn",
            "title": f"連続失点 {max_consecutive} ポイント中",
            "body": "タイムアウトを検討してください。配球・陣形の変化が有効な場合があります。",
        })

    # ── ルール 2: 自軍の強制エラー急増 ───────────────────────────
    forced_errors = sum(
        1 for r in recent
        if r.winner == opponent_side and r.end_type in ("forced_error", "net_error", "out_error")
    )
    if forced_errors >= _FORCED_ERROR_THRESHOLD:
        cards.append({
            "level": "warn",
            "title": f"直近 {window} 本で強制エラー {forced_errors} 回",
            "body": "守備が崩れている可能性があります。返球を安全コースに変えることを検討してください。",
        })

    # ── ルール 3: 相手配球ゾーン偏り ─────────────────────────────
    # ラリー内の最終ストロークゾーンを取得
    recent_rally_ids = [r.id for r in recent]
    if recent_rally_ids:
        # 相手の最終打球 (最大 stroke_num) のゾーンを集計
        from sqlalchemy import func
        last_stroke_subq = (
            db.query(
                Stroke.rally_id,
                func.max(Stroke.stroke_num).label("max_stroke_num"),
            )
            .filter(
                Stroke.rally_id.in_(recent_rally_ids),
                Stroke.player.in_([opponent_side, opponent_side.replace("player_", "partner_")]),
            )
            .group_by(Stroke.rally_id)
            .subquery()
        )
        last_strokes = (
            db.query(Stroke)
            .join(
                last_stroke_subq,
                (Stroke.rally_id == last_stroke_subq.c.rally_id)
                & (Stroke.stroke_num == last_stroke_subq.c.max_stroke_num),
            )
            .all()
        )
        zone_counts: dict[str, int] = {}
        for s in last_strokes:
            if s.land_zone:
                zone_counts[s.land_zone] = zone_counts.get(s.land_zone, 0) + 1

        if zone_counts:
            top_zone, top_count = max(zone_counts.items(), key=lambda x: x[1])
            if top_count >= _ZONE_BIAS_THRESHOLD:
                cards.append({
                    "level": "info",
                    "title": f"相手が {top_zone} ゾーンへ集中配球",
                    "body": f"直近 {window} 本中 {top_count} 本が {top_zone} へ。このゾーンの対応を意識してください。",
                })

    # ── ルール 4: 自軍好調（得点率 60%+）────────────────────────
    self_wins = sum(1 for r in recent if r.winner == player_side)
    if self_wins >= round(window * 0.6) and window >= 3:
        cards.append({
            "level": "good",
            "title": f"直近 {window} 本で {self_wins} 勝 — 好調",
            "body": "現在の戦術を維持してください。相手のパターン変化に注意。",
        })

    # ── ルール 5: サービスポイント偏り ───────────────────────────
    self_serve_rallies = [r for r in recent if r.server == player_side]
    if self_serve_rallies:
        serve_wins = sum(1 for r in self_serve_rallies if r.winner == player_side)
        serve_win_rate = serve_wins / len(self_serve_rallies)
        if serve_win_rate < 0.4 and len(self_serve_rallies) >= 3:
            cards.append({
                "level": "warn",
                "title": f"自サービスゲームの勝率低下 ({round(serve_win_rate*100)}%)",
                "body": "サービスコースの変化や、サービス後の配球パターン見直しを検討してください。",
            })

    # カードがなければ「特筆事項なし」を返す
    if not cards:
        cards.append({
            "level": "info",
            "title": "現在特筆すべき偏りなし",
            "body": f"直近 {window} ラリーで明確な偏りは検出されていません。",
        })

    return {
        "success": True,
        "cards": cards,
        "window": window,
        "total_rallies": total,
    }

"""tracknet_shuttle_track 成果物の「どこまで覆っているか」のメタ情報。

書き手が 2 つある（ラリー窓だけの TrackNet バッチ / 動画全体の video_import）。
後者の全体走査結果を、前者が数十秒分に置き換えてしまうのを防ぐため、
成果物の summary に coverage / sample_fps / 覆う時間範囲を残す。
data（フレーム配列）の形は変えない。

coverage:
  "full"          動画全体を一定間隔で走査した（video_import）
  "rally_windows" Rally の窓だけを走査した（tracknet バッチ）
"""
from __future__ import annotations

import json
from typing import Any, Optional, Sequence

COVERAGE_FULL = "full"
COVERAGE_RALLY_WINDOWS = "rally_windows"


def build_track_meta(
    track: Sequence[dict],
    *,
    coverage: str,
    sample_fps: Optional[float],
) -> dict:
    """summary に入れるメタ。時間範囲は track の timestamp_sec の最小/最大。"""
    ts = [
        float(p["timestamp_sec"]) for p in track
        if isinstance(p, dict) and isinstance(p.get("timestamp_sec"), (int, float))
    ]
    return {
        "coverage": coverage,
        "sample_fps": round(float(sample_fps), 3) if sample_fps else None,
        "covered_start_sec": min(ts) if ts else None,
        "covered_end_sec": max(ts) if ts else None,
        "point_count": len(track),
    }


def merge_summary(existing_summary: Optional[str], meta: dict, **extra: Any) -> str:
    """既存 summary の他キーを保ったまま meta を差し込んだ JSON 文字列を返す。"""
    base: dict = {}
    if existing_summary:
        try:
            parsed = json.loads(existing_summary)
            if isinstance(parsed, dict):
                base = parsed
        except Exception:
            base = {}
    base.update(meta)
    base.update(extra)
    return json.dumps(base, ensure_ascii=False)


def existing_coverage(summary: Optional[str], data: Optional[str]) -> Optional[str]:
    """既存成果物の coverage を返す。分からなければ None。

    summary に coverage があればそれを使う。無い旧成果物は、video_import だけが
    付ける `frame_idx` キーが先頭点にあれば "full" とみなす（ラリー窓バッチの点には無い）。
    """
    if summary:
        try:
            parsed = json.loads(summary)
            if isinstance(parsed, dict) and parsed.get("coverage") in (
                COVERAGE_FULL, COVERAGE_RALLY_WINDOWS,
            ):
                return parsed["coverage"]
        except Exception:
            pass
    if data:
        try:
            pts = json.loads(data)
            if isinstance(pts, list) and pts and isinstance(pts[0], dict) and "frame_idx" in pts[0]:
                return COVERAGE_FULL
        except Exception:
            pass
    return None

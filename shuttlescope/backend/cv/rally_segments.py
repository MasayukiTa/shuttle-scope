"""ラリー境界の時間軸ヘルパーと、start/end を組にした区間 (segments) の派生。

全て純関数。DB・動画・env に触れない。

- estimate_sample_fps: 成果物の timestamp_sec 中央値間隔から実効サンプルレートを出す。
  検出器のカウンタは「成果物のサンプル 1 つにつき 1 進む」ので、秒閾値を
  サンプル数へ換算するときは動画 fps ではなくこの値を使う。
- build_rally_segments: 時刻順に start/end を組にして区間にする。

出力は「候補」であり Rally / Stroke 行は作らない（人が確認するまで確定しない）。
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable, List, Optional, Sequence

# サンプル間隔を推定するのに必要な最小サンプル数（間隔が 2 つ以上欲しい）
MIN_SAMPLES_FOR_RATE = 3

# 区間内のサンプルがこれ未満なら「データ不足」とする
MIN_SEGMENT_SAMPLES = 5
# 区間の期待サンプル数に対する実サンプル数の比がこれ未満なら「データ不足」
MIN_SEGMENT_COVERAGE = 0.5

# 成果物全体のサンプル数がこれ未満なら区間を作らず「データ不足」と明示する
MIN_TOTAL_SAMPLES_FOR_SEGMENTS = 10

CONFIDENCE_BASIS = "signals_fired/3"


def estimate_sample_fps(timestamps: Iterable[float]) -> Optional[float]:
    """timestamp_sec の中央値間隔から実効サンプルレート (samples/sec) を返す。

    中央値なので、ラリー窓だけのサンプリング（窓の間に大きな隙間がある成果物）でも
    窓内の刻み幅が取れる。推定できない（サンプル不足・間隔が全て 0 以下）なら None。
    """
    ts = sorted(
        float(t) for t in timestamps
        if isinstance(t, (int, float)) and math.isfinite(float(t))
    )
    if len(ts) < MIN_SAMPLES_FOR_RATE:
        return None
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b - a > 0]
    if len(gaps) < MIN_SAMPLES_FOR_RATE - 1:
        return None
    med = statistics.median(gaps)
    if med <= 0:
        return None
    return 1.0 / med


def _segment_from(start: Optional[dict], end: Optional[dict]) -> dict:
    start_sec = start["timestamp_sec"] if start else None
    end_sec = end["timestamp_sec"] if end else None
    duration = (
        round(end_sec - start_sec, 3)
        if start_sec is not None and end_sec is not None else None
    )
    confs = [b["confidence"] for b in (start, end) if b is not None and b.get("confidence") is not None]
    open_side = None
    if start is None:
        open_side = "start_missing"
    elif end is None:
        open_side = "end_missing"
    return {
        "start_sec": start_sec,
        "end_sec": end_sec,
        "duration": duration,
        "signals": {
            "start": list(start.get("signals_fired", [])) if start else [],
            "end": list(end.get("signals_fired", [])) if end else [],
        },
        "confidence_basis": CONFIDENCE_BASIS,
        "signal_score": round(sum(confs) / len(confs), 3) if confs else None,
        "open_ended": open_side is not None,
        "open_side": open_side,
        "coverage_ratio": None,
        "sample_count": None,
        "data_status": "unverified",
    }


def build_rally_segments(
    boundaries: Sequence[dict],
    *,
    shuttle_timestamps: Optional[Sequence[float]] = None,
    sample_fps: Optional[float] = None,
) -> List[dict]:
    """境界 (kind=start|end, timestamp_sec, signals_fired, confidence) を区間にする。

    - 時刻順（同時刻は start を先）に並べ、start のあとに来た最初の end と組にする。
    - 対応する end が無い start / start が無い end は open_ended=True で残す
      （捨てない、end_sec / start_sec は None）。
    - shuttle_timestamps と sample_fps が渡れば、閉じた区間ごとに区間内のサンプル数と
      coverage_ratio（実サンプル数 / 期待サンプル数、上限 1）を付ける。
      サンプルが少ない / 比が低い区間は data_status="data_insufficient" とし、
      signal_score は None にする（0 という数字で「確度ゼロ」に見せない）。
    - 空入力は空リスト。エラーにしない。

    signal_score は「発火した信号数 / 3」の平均で、統計的な確からしさではない。
    """
    if not boundaries:
        return []

    order = {"start": 0, "end": 1}
    ordered = sorted(
        (b for b in boundaries if b.get("kind") in order and b.get("timestamp_sec") is not None),
        key=lambda b: (b["timestamp_sec"], order[b["kind"]]),
    )

    pairs: List[tuple] = []
    open_start: Optional[dict] = None
    for b in ordered:
        if b["kind"] == "start":
            if open_start is not None:
                pairs.append((open_start, None))
            open_start = b
        else:
            if open_start is not None:
                pairs.append((open_start, b))
                open_start = None
            else:
                pairs.append((None, b))
    if open_start is not None:
        pairs.append((open_start, None))

    segments = [_segment_from(s, e) for s, e in pairs]

    if shuttle_timestamps is not None and sample_fps and sample_fps > 0:
        ts = sorted(float(t) for t in shuttle_timestamps if isinstance(t, (int, float)))
        for seg in segments:
            if seg["open_ended"] or seg["duration"] is None:
                continue
            n = sum(1 for t in ts if seg["start_sec"] <= t <= seg["end_sec"])
            expected = max(1.0, seg["duration"] * sample_fps)
            ratio = round(min(1.0, n / expected), 3)
            seg["sample_count"] = n
            seg["coverage_ratio"] = ratio
            if n < MIN_SEGMENT_SAMPLES or ratio < MIN_SEGMENT_COVERAGE:
                seg["data_status"] = "data_insufficient"
                seg["signal_score"] = None
            else:
                seg["data_status"] = "ok"
    return segments

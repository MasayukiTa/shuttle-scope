"""Phase 1+2 の PersonTracker を試合動画区間に当てて debug video を出力する。

設計書: private_docs/2026-05-27_person_tracking_design.md
使用例:
    python shuttlescope/scripts/generate_tracking_debug_video.py \
        --video .../fd425688-...mp4 \
        --start-sec 120 --duration-sec 30 \
        --match-type doubles \
        --out C:/Users/kiyus/Desktop/person_tracking_debug.mp4
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# backend を import path に追加
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.cv.person_tracker import PersonTracker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# track_id 色 palette (BGR)
_PALETTE = [
    (255, 64, 64),   (64, 255, 64),   (64, 64, 255),  (255, 255, 64),
    (255, 64, 255),  (64, 255, 255),  (255, 128, 0),  (128, 0, 255),
    (0, 128, 255),   (128, 255, 0),   (255, 0, 128),  (0, 255, 128),
]


def _color_for(track_id: int) -> tuple[int, int, int]:
    if track_id < 0:
        return (180, 180, 180)
    return _PALETTE[hash(track_id) % len(_PALETTE)]


def _parse_corners(s: str | None, width: int, height: int) -> list[tuple[float, float]] | None:
    """コート 4 隅 JSON parse。

    None の場合は **画面全体を court と見なす fallback** (TL/TR/BR/BL = 画面 4 隅)。
    こうすると adjudicator は常に何らかの象限を返す (Phase 1 観察用)。
    """
    if s is None:
        # 画面 4 隅 fallback
        return [(0.0, 0.0), (float(width), 0.0), (float(width), float(height)), (0.0, float(height))]
    obj = json.loads(s)
    # 期待: [[x,y], [x,y], [x,y], [x,y]] (TL, TR, BR, BL)
    return [(float(p[0]), float(p[1])) for p in obj]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--start-sec", type=float, default=60.0)
    p.add_argument("--duration-sec", type=int, default=30)
    p.add_argument("--match-type", choices=["singles", "doubles"], required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--court-corners", default=None, help='JSON: [[x,y],...] TL,TR,BR,BL pixel')
    p.add_argument("--model", default=None, help="YOLO model path (default: env or yolov8n.onnx)")
    p.add_argument("--device", default=None)
    p.add_argument("--match-id", type=int, default=None,
                   help="DB の court_calibration から 4 隅を取得する。--court-corners 優先。")
    p.add_argument("--set-idx", type=int, default=0,
                   help="開始 set index。奇数なら side swap 有効。")
    p.add_argument("--reid", choices=["on", "off"], default="on",
                   help="Phase 4 ReID Tier 3 recovery を有効化 (default: on)")
    p.add_argument("--reid-thresh", type=float, default=None,
                   help="ReID cosine sim 閾値 (default: SS_PERSON_REID_THRESH or 0.85)")
    args = p.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        logger.error("動画が開けません: %s", args.video)
        return 2
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start_frame = int(args.start_sec * fps)
    end_frame = start_frame + int(args.duration_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    logger.info("動画 %dx%d @ %.2f fps、frame %d → %d 処理", width, height, fps, start_frame, end_frame)

    # 優先順: --court-corners (明示) > --match-id (DB) > 画面全体 fallback
    if args.court_corners is not None:
        corners = _parse_corners(args.court_corners, width, height)
        match_id_arg = None
    elif args.match_id is not None:
        corners = None  # PersonTracker が DB から取る
        match_id_arg = args.match_id
    else:
        corners = _parse_corners(None, width, height)  # 画面 4 隅 fallback
        match_id_arg = None

    tracker = PersonTracker(
        match_type=args.match_type,
        court_corners=corners,
        model_path=args.model,
        device=args.device,
        match_id=match_id_arg,
        frame_size=(width, height),
        use_reid=(args.reid == "on"),
        reid_threshold=args.reid_thresh,
    )
    logger.info("ReID Tier 3: %s (threshold=%s)", args.reid, args.reid_thresh or "default")
    # set_idx 反映 (side swap)
    if args.set_idx:
        tracker.reset_for_new_set(args.set_idx)
    # 描画用に実コート 4 隅を取り出す (HUD 用)
    if tracker._adjudicator is not None:
        # 内部の court polygon を取り出す
        drawn_corners = tracker._adjudicator._court_polygon
    else:
        drawn_corners = corners

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    # mp4v fallback。XVID は mp4 拡張子と相性悪い
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.out, fourcc, fps, (width, height))
    if not writer.isOpened():
        logger.error("出力 mp4 が開けません: %s", args.out)
        return 3

    # ID switch カウンタ用 (track_id ごとの寿命 frame 数の概算)
    id_first_seen: dict[int, int] = {}
    id_last_seen: dict[int, int] = {}
    total_unique_ids: set[int] = set()
    # court_id (in-court 採用後) ごとの track_id 集計
    per_court_ids: dict[int, set[int]] = {0: set(), 1: set(), 2: set(), 3: set()}

    frame_idx = start_frame
    processed = 0
    t0 = time.time()
    while frame_idx < end_frame:
        ok, frame = cap.read()
        if not ok:
            logger.warning("read 失敗 @ frame %d、終了", frame_idx)
            break

        tracks = tracker.update(frame, frame_idx)
        # コート (corners) を薄く描画
        if drawn_corners is not None:
            pts = np.array(drawn_corners, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(frame, [pts], isClosed=True, color=(80, 80, 80), thickness=1)

        for t in tracks:
            x1, y1, x2, y2 = [int(v) for v in t.bbox]
            color = _color_for(t.track_id)
            in_court = t.court_id is not None
            thickness = 2 if in_court else 1
            if not in_court:
                color = (160, 160, 160)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
            pl = t.player_label or "-"
            rec_tag = "*R" if t.is_recovered else ""
            label = f"ID:{t.track_id}{rec_tag} Q:{t.court_id} {pl} c:{t.confidence:.2f}"
            cv2.putText(frame, label, (x1, max(y1 - 6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
            # 足元 dot
            fx = int((x1 + x2) / 2)
            cv2.circle(frame, (fx, y2), 4, color, -1)

            if t.track_id >= 0:
                total_unique_ids.add(t.track_id)
                id_first_seen.setdefault(t.track_id, frame_idx)
                id_last_seen[t.track_id] = frame_idx
                if t.court_id is not None and t.court_id in per_court_ids:
                    per_court_ids[t.court_id].add(t.track_id)

        # HUD
        elapsed = (frame_idx - start_frame) / fps
        hud = f"frame {frame_idx}  t+{elapsed:5.2f}s  tracks:{len(tracks)}  unique_ids:{len(total_unique_ids)}"
        cv2.putText(frame, hud, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)

        writer.write(frame)
        frame_idx += 1
        processed += 1
        if processed % 30 == 0:
            logger.info("  処理 %d frames (%.1f fps)", processed, processed / max(time.time() - t0, 1e-3))

    cap.release()
    writer.release()
    dt = time.time() - t0
    logger.info("完了: %d frames, %.1f s, %.1f fps", processed, dt, processed / max(dt, 1e-3))
    logger.info("unique track_ids 出現数: %d", len(total_unique_ids))
    # 寿命 sort
    lifespans = sorted(
        [(tid, id_last_seen[tid] - id_first_seen[tid] + 1) for tid in total_unique_ids],
        key=lambda kv: -kv[1],
    )
    for tid, span in lifespans[:20]:
        logger.info("  track_id %d: %d frames (%.1f s)", tid, span, span / fps)
    label_map = {0: "FL/PlayerA", 1: "FR/PlayerB", 2: "BL/PlayerC", 3: "BR/PlayerD"}
    for cid in (0, 1, 2, 3):
        logger.info(
            "  court_id %d (%s): %d unique track_ids %s",
            cid, label_map[cid], len(per_court_ids[cid]), sorted(per_court_ids[cid])[:8],
        )
    logger.info("出力: %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

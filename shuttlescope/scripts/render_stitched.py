"""Stable-ID で色分けした debug video を出力する。

collect と同じ batch 検出経路で per-frame の raw track を取得し、stitch_mapping.json
の raw_track_id -> stable_id でラベル/色を付け替える。各選手が 1 色/1 文字を
クリップ通して保つことを目視確認する。
"""
from __future__ import annotations
import argparse, json, logging, os, sys, time
from pathlib import Path
import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]  # scripts/ の親 = shuttlescope/
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from backend.cv.person_tracker import PersonTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STABLE_LABEL = {0: "A", 1: "B", 2: "C", 3: "D", -1: "?"}
STABLE_COLOR = {0: (255, 80, 80), 1: (80, 220, 80), 2: (60, 60, 235), 3: (40, 200, 235), -1: (150, 150, 150)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--start-sec", type=float, default=120.0)
    p.add_argument("--duration-sec", type=int, default=30)
    p.add_argument("--match-id", type=int, default=33)
    p.add_argument("--mapping", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    mp = json.loads(Path(args.mapping).read_text(encoding="utf-8"))["mapping"]
    mapping = {int(k): int(v) for k, v in mp.items()}

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start_frame = int(args.start_sec * fps); end_frame = start_frame + int(args.duration_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    tracker = PersonTracker(match_type="doubles", court_corners=None, match_id=args.match_id,
                            frame_size=(W, H), use_reid=True)
    drawn = tracker._adjudicator._court_polygon if tracker._adjudicator is not None else None

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))

    BATCH = 32
    buf_f, buf_i = [], []
    seen_ids = set()
    t0 = time.time(); processed = 0

    def flush():
        nonlocal processed
        if not buf_f:
            return
        results = tracker.update_batch(buf_f, buf_i)
        for frame, fidx, tracks in zip(buf_f, buf_i, results):
            if drawn is not None:
                pts = np.array(drawn, dtype=np.int32).reshape(-1, 1, 2)
                cv2.polylines(frame, [pts], True, (80, 80, 80), 1)
            for t in tracks:
                sid = mapping.get(t.track_id, -1)
                if sid < 0:
                    continue  # 背景は描かない (player のみ表示)
                seen_ids.add(sid)
                x1, y1, x2, y2 = [int(v) for v in t.bbox]
                col = STABLE_COLOR[sid]
                cv2.rectangle(frame, (x1, y1), (x2, y2), col, 3)
                lab = STABLE_LABEL[sid]
                # 大きな A/B/C/D ラベル (白縁取りで濃色背景でも可読)
                org = (x1, max(y1 - 10, 40))
                cv2.putText(frame, lab, org, cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 6, cv2.LINE_AA)
                cv2.putText(frame, lab, org, cv2.FONT_HERSHEY_SIMPLEX, 1.4, col, 3, cv2.LINE_AA)
                cv2.circle(frame, (int((x1 + x2) / 2), y2), 5, col, -1)
            hud = "frame %d  t+%5.2fs  stable players: %s" % (
                fidx, (fidx - start_frame) / fps, "".join(STABLE_LABEL[s] for s in sorted(seen_ids)))
            cv2.putText(frame, hud, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            writer.write(frame)
            processed += 1

    fidx = start_frame
    while fidx < end_frame:
        ok, frame = cap.read()
        if not ok:
            break
        buf_f.append(frame); buf_i.append(fidx); fidx += 1
        if len(buf_f) >= BATCH:
            flush(); buf_f, buf_i = [], []
            logger.info("  %d frames (%.1f fps)", processed, processed / max(time.time() - t0, 1e-3))
    flush()
    cap.release(); writer.release()
    logger.info("done %d frames -> %s ; stable ids seen=%s", processed, args.out, sorted(seen_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())

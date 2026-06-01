"""Offline tracklet collection for ShuttleScope tracklet-stitching post-processor.

PersonTracker (config-F, ReID on) をクリップに 1 度だけ通し、出力 track ごとに
per-frame の情報 (frame_idx, centroid, bbox, court_id) を記録する。さらに各
tracklet (= 連続した 1 track_id の run) の代表 ReID embedding (Phase4 OSNet
embedder で box crop を埋め込み平均) を計算する。

結果を npz + json に保存し、stitching のチューニングで再検出を避ける。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.cv.person_tracker import PersonTracker  # noqa: E402
from backend.cv.reid_embedder import get_default_embedder  # noqa: E402
from backend.cv import reid as reid_fallback  # noqa: E402  HSV+LBP appearance descriptor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _centroid(bbox):
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _foot(bbox):
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


def _crop_bbox(frame, bbox):
    """abs px bbox (x1,y1,x2,y2) で frame を crop。BGR uint8 を返す。退化時 None。"""
    h, w = frame.shape[:2]
    x1 = max(0, int(round(bbox[0]))); y1 = max(0, int(round(bbox[1])))
    x2 = min(w, int(round(bbox[2]))); y2 = min(h, int(round(bbox[3])))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    return crop


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--start-sec", type=float, default=120.0)
    p.add_argument("--duration-sec", type=int, default=30)
    p.add_argument("--match-type", default="doubles")
    p.add_argument("--match-id", type=int, default=33)
    p.add_argument("--reid-thresh", type=float, default=None)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        logger.error("video open failed: %s", args.video)
        return 2
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start_frame = int(args.start_sec * fps)
    end_frame = start_frame + int(args.duration_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    logger.info("video %dx%d @ %.2f fps, frame %d -> %d", width, height, fps, start_frame, end_frame)

    tracker = PersonTracker(
        match_type=args.match_type,
        court_corners=None,
        match_id=args.match_id,
        frame_size=(width, height),
        use_reid=True,
        reid_threshold=args.reid_thresh,
    )
    embedder = get_default_embedder()
    osnet_ok = embedder is not None and embedder.available
    # OSNet が無い (外部 weight 未配置) 場合は reid.py の HSV+LBP fallback descriptor を
    # 使う。色ヒストが主成分 → 異ユニフォーム相手には強い、同ユニフォーム teammate には弱い。
    use_fallback_app = not osnet_ok
    logger.info("ReID OSNet available=%s ; using HSV+LBP fallback=%s", osnet_ok, use_fallback_app)

    per_track = defaultdict(list)
    EMB_CAP = 40
    per_track_emb = defaultdict(list)

    # config-F は offline batch 検出 (384x640 dynamic 1-class model) を使う。
    # update() の predict_frame は別の前処理で finetuned model に 0 det となるため、
    # update_batch() を使う。ReID embedding は frame ごとに crop して埋め込む。
    BATCH = 32
    frame_idx = start_frame
    processed = 0
    t0 = time.time()
    buf_frames: list = []
    buf_idxs: list = []

    def _flush(buf_frames, buf_idxs):
        nonlocal processed
        if not buf_frames:
            return
        batch_results = tracker.update_batch(buf_frames, buf_idxs)
        for frame, fidx, tracks in zip(buf_frames, buf_idxs, batch_results):
            crop_list = []
            crop_owner = []
            for t in tracks:
                if t.track_id < 0:
                    continue
                cx, cy = _centroid(t.bbox)
                fx, fy = _foot(t.bbox)
                per_track[t.track_id].append({
                    "frame": int(fidx),
                    "cx": float(cx), "cy": float(cy),
                    "fx": float(fx), "fy": float(fy),
                    "x1": float(t.bbox[0]), "y1": float(t.bbox[1]),
                    "x2": float(t.bbox[2]), "y2": float(t.bbox[3]),
                    "court_id": (int(t.court_id) if t.court_id is not None else -1),
                    "conf": float(t.confidence),
                })
                if t.confidence >= 0.3 and len(per_track_emb[t.track_id]) < EMB_CAP:
                    if use_fallback_app:
                        # bbox を正規化座標に変換して HSV+LBP descriptor を抽出
                        fh, fw = frame.shape[:2]
                        bbox_n = (t.bbox[0] / fw, t.bbox[1] / fh, t.bbox[2] / fw, t.bbox[3] / fh)
                        vec = reid_fallback.extract_embedding(frame, bbox_n, fw, fh)
                        v = np.asarray(vec, dtype=np.float32)
                        if v.size and float(np.linalg.norm(v)) > 1e-9:
                            per_track_emb[t.track_id].append(v)
                    else:
                        crop = _crop_bbox(frame, t.bbox)
                        if crop is not None:
                            crop_list.append(crop)
                            crop_owner.append(t.track_id)
            if crop_list:
                feats = embedder.embed_batch(crop_list)
                for owner, f in zip(crop_owner, feats):
                    per_track_emb[owner].append(f.astype(np.float32))
            processed += 1

    while frame_idx < end_frame:
        ok, frame = cap.read()
        if not ok:
            logger.warning("read fail @ frame %d", frame_idx)
            break
        buf_frames.append(frame)
        buf_idxs.append(frame_idx)
        frame_idx += 1
        if len(buf_frames) >= BATCH:
            _flush(buf_frames, buf_idxs)
            buf_frames, buf_idxs = [], []
            logger.info("  %d frames (%.1f fps) uniq=%d",
                        processed, processed / max(time.time() - t0, 1e-3), len(per_track))
    _flush(buf_frames, buf_idxs)
    cap.release()
    dt = time.time() - t0
    logger.info("detect done %d frames %.1fs (%.1f fps), unique raw track_id=%d",
                processed, dt, processed / max(dt, 1e-3), len(per_track))

    # descriptor 次元を実データから決定 (fallback=315, osnet=512)
    emb_dim = 512
    for embs in per_track_emb.values():
        if embs:
            emb_dim = int(embs[0].shape[0])
            break
    any_emb = any(len(e) > 0 for e in per_track_emb.values())

    tracklets = []
    for tid, recs in per_track.items():
        recs.sort(key=lambda r: r["frame"])
        frames = np.array([r["frame"] for r in recs], dtype=np.int64)
        embs = per_track_emb.get(tid, [])
        if embs:
            arr = np.stack(embs, axis=0)
            mean = arr.mean(axis=0)
            nrm = float(np.linalg.norm(mean))
            rep = (mean / nrm).astype(np.float32) if nrm > 1e-9 else np.zeros(arr.shape[1], np.float32)
        else:
            rep = np.zeros(emb_dim, np.float32)
        cids = [r["court_id"] for r in recs if r["court_id"] >= 0]
        if cids:
            vals, counts = np.unique(np.array(cids), return_counts=True)
            dom_court = int(vals[int(np.argmax(counts))])
        else:
            dom_court = -1
        tracklets.append({
            "track_id": int(tid),
            "start_frame": int(frames.min()),
            "end_frame": int(frames.max()),
            "n_frames": int(len(recs)),
            "dom_court": dom_court,
            "n_emb": int(len(embs)),
            "records": recs,
            "rep_embedding": rep,
        })
    tracklets.sort(key=lambda t: t["start_frame"])

    out_dir = Path(args.out_dir)
    meta = {
        "video": args.video, "match_id": args.match_id, "match_type": args.match_type,
        "fps": fps, "width": width, "height": height,
        "start_frame": start_frame, "end_frame": end_frame,
        "n_processed": processed, "n_raw_tracks": len(per_track),
        "reid_available": bool(any_emb),
        "reid_kind": ("osnet" if osnet_ok else ("hsv_lbp_fallback" if any_emb else "none")),
        "emb_dim": int(emb_dim),
        "tracklets": [{k: v for k, v in t.items() if k != "rep_embedding"} for t in tracklets],
    }
    (out_dir / "tracklets.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    emb_mat = np.stack([t["rep_embedding"] for t in tracklets], axis=0) if tracklets else np.zeros((0, 512), np.float32)
    emb_ids = np.array([t["track_id"] for t in tracklets], dtype=np.int64)
    np.savez(out_dir / "tracklet_embeddings.npz", embeddings=emb_mat, track_ids=emb_ids)
    logger.info("saved: %s (tracklets=%d)", out_dir / "tracklets.json", len(tracklets))

    per_court = defaultdict(set)
    for t in tracklets:
        if t["dom_court"] >= 0:
            per_court[t["dom_court"]].add(t["track_id"])
    for cid in (0, 1, 2, 3):
        logger.info("  court %d: %d raw tracklets", cid, len(per_court[cid]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

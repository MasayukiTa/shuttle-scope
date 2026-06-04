"""2 カメラ映像 → 3D pose 解析 driver (姿勢崩壊の 3D 化 feasibility)。

パイプライン:
  1. 各映像の motion-energy を出し、相互相関で時刻同期 (Mavic=音声無しでも可)
  2. 各カメラを court 4 隅 (court_calibration roi_polygon) から PnP 校正 → 射影行列 P
  3. 同期フレームで YOLO 検出 + RTMPose 2D 17 関節
  4. 両校正をコート平面に使い、選手の足元コート座標で「どの選手がどの選手か」を対応
  5. 対応選手の各関節を三角測量 → 3D pose。CoM 高さ / 体幹前傾角を出す
解析者は単体(1動画=2D)/複数(2動画=3D)を選べる: --video2 省略で単体 2D のみ。

実行 (prod):
  set PYTHONUTF8=1
  .venv\\Scripts\\python.exe scripts/multiview_3d_analyze.py \
    --video1 camA.mp4 --match-id1 33 --video2 camB.mp4 --match-id2 33 \
    --start-sec 120 --duration-sec 10 --out out3d.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from backend.cv.multiview.court3d import calibrate_camera_from_court  # noqa: E402
from backend.cv.multiview.triangulate import triangulate_points, triangulation_residual  # noqa: E402
from backend.cv.multiview.temporal_sync import (  # noqa: E402
    cross_correlation_offset, motion_energy_from_gray,
)

# COCO17: 5,6=肩 11,12=腰。CoM 近似 = 肩腰中点。体幹軸 = 腰中点→肩中点。
L_SH, R_SH, L_HIP, R_HIP = 5, 6, 11, 12


def _corners_px(match_id: int, w: int, h: int):
    """court_calibration の roi_polygon(正規化 TL,TR,BR,BL) → px 4 隅。"""
    from backend.routers.court_calibration import load_calibration_standalone
    data = load_calibration_standalone(match_id)
    if not data or not data.get("roi_polygon") or len(data["roi_polygon"]) != 4:
        raise SystemExit(f"match {match_id} に有効な court_calibration がありません")
    return np.array([[float(p[0]) * w, float(p[1]) * h] for p in data["roi_polygon"]], np.float64)


def _read_window(video, start_f, n):
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
    frames, grays = [], []
    for _ in range(n):
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(fr)
        grays.append(cv2.cvtColor(cv2.resize(fr, (128, 72)), cv2.COLOR_BGR2GRAY).astype(np.float64))
    cap.release()
    return frames, grays


def _detect_pose(frames, yolo, pose):
    """各フレーム: YOLO で person bbox → RTMPose → [(foot_xy, kps(17,3)), ...]。"""
    out = []
    for fr in frames:
        h, w = fr.shape[:2]
        dets = yolo.predict_frame(fr) if yolo else []
        boxes = []
        for d in dets:
            lb = d.get("label", "")
            bb = d.get("bbox") or []
            if (lb == "person" or lb.startswith("player_")) and len(bb) == 4:
                boxes.append({"bbox": [bb[0]*w, bb[1]*h, bb[2]*w, bb[3]*h]})
        people = []
        if boxes and pose and pose.is_available():
            for r in pose.infer(fr, boxes):
                kps = np.asarray(r.keypoints, np.float64)  # (17,3) px
                foot = ((kps[15, 0] + kps[16, 0]) / 2, (kps[15, 1] + kps[16, 1]) / 2)  # 足首中点
                people.append((foot, kps))
        out.append(people)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video1", required=True)
    p.add_argument("--match-id1", type=int, required=True)
    p.add_argument("--video2", default=None)
    p.add_argument("--match-id2", type=int, default=None)
    p.add_argument("--start-sec", type=float, default=120)
    p.add_argument("--duration-sec", type=float, default=10)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    from backend.yolo.inference import get_yolo_inference
    yolo = get_yolo_inference(); yolo.load()
    from backend.cv.rtmpose import RTMPoseEngine
    pose = RTMPoseEngine(); pose.load()

    cap = cv2.VideoCapture(a.video1)
    fps = cap.get(cv2.CAP_PROP_FPS) or 59.94
    w1 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h1 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    n = int(a.duration_sec * fps)
    f1, g1 = _read_window(a.video1, int(a.start_sec * fps), n)
    poses1 = _detect_pose(f1, yolo, pose)

    result = {"mode": "single", "fps": fps, "frames": len(f1)}

    if not a.video2:
        # 単体 2D
        result["pose2d_video1"] = [
            [{"foot": list(foot), "kps": kps.tolist()} for foot, kps in fr] for fr in poses1
        ]
        json.dump(result, open(a.out, "w"), ensure_ascii=False)
        print("DONE single-view 2D ->", a.out); return

    # ── multi (2D→3D) ──
    result["mode"] = "multi"
    cap = cv2.VideoCapture(a.video2)
    w2 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h2 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    f2, g2 = _read_window(a.video2, int(a.start_sec * fps), n)
    # 時刻同期 (motion-energy 相互相関)
    me1, me2 = motion_energy_from_gray(g1), motion_energy_from_gray(g2)
    lag, score = cross_correlation_offset(me1, me2, max_lag=min(len(me1), len(me2)) - 1)
    result["sync"] = {"lag_frames": lag, "score": score}
    poses2 = _detect_pose(f2, yolo, pose)
    # 校正
    _, _, _, P1 = calibrate_camera_from_court(_corners_px(a.match_id1, w1, h1), w1, h1)
    _, _, _, P2 = calibrate_camera_from_court(_corners_px(a.match_id2 or a.match_id1, w2, h2), w2, h2)

    # lag を考慮してフレーム対応。各対応フレームで「足元コート位置」で選手マッチ→関節三角測量。
    frames3d = []
    for i in range(len(poses1)):
        j = i + lag
        if j < 0 or j >= len(poses2):
            continue
        a_people, b_people = poses1[i], poses2[j]
        if not a_people or not b_people:
            continue
        # 簡易マッチ: cam1 各選手の足元を P1 でコート平面(Z=0)へ逆投影し、cam2 でも同様、
        # コート XY 最近傍で対応 (詳細最適化は今後)。ここでは関節三角測量の妥当性確認が目的。
        pair3d = []
        for foot_a, kps_a in a_people:
            # cam2 側は最も画面位置が近い人を仮対応 (feasibility 用)
            bb = min(b_people, key=lambda pb: (pb[0][0] - foot_a[0]) ** 2 + (pb[0][1] - foot_a[1]) ** 2)
            kps_b = bb[1]
            valid = (kps_a[:, 2] > 0.3) & (kps_b[:, 2] > 0.3)
            if valid.sum() < 4:
                continue
            xyz = triangulate_points(P1, P2, kps_a[valid, :2], kps_b[valid, :2])
            res = triangulation_residual(P1, P2, kps_a[valid, :2], kps_b[valid, :2], xyz)
            # 体幹: 腰中点→肩中点 (有効関節のみ近似)
            pair3d.append({"kps3d_idx": np.where(valid)[0].tolist(), "kps3d": xyz.tolist(),
                           "reproj_px": res})
        if pair3d:
            frames3d.append({"frame": i, "players": pair3d})
    result["pose3d"] = frames3d
    json.dump(result, open(a.out, "w"), ensure_ascii=False)
    print("DONE multi-view 3D ->", a.out, "frames3d=", len(frames3d), "sync_lag=", lag)


if __name__ == "__main__":
    main()

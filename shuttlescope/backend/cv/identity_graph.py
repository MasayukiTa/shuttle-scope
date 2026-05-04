"""Track A3: 試合全体での選手 identity 追跡 (`_track_identities` 抽出)。

`backend/routers/yolo.py::_track_identities` (元 L1407-1801, 約 400 行) の
ロジックをそのまま `track_identities()` 関数 + `IdentityGraph` クラスに
抽出。**ロジックは一切変更しない** ことが目的（テスト可能性の獲得のみ）。

主な要素:
  - 速度予測付き双方向追跡 (forward + backward)
  - ByteTrack track_id による強一致 (BT_MATCH_COST ≒ 0)
  - Hungarian (scipy linear_sum_assignment) または貪欲フォールバックで
    全トラック同時最適割当
  - REACQ_THRESH=15 連続 lost で reacquisition モード (拡大検索半径 0.45)
  - REID gallery (max 25 サンプル) でマルチサンプル外観マッチ
  - ネガティブギャラリー (観客/審判) で混同防止

Forward-compat (Track B/C 接続点):
  - `IdentityGraph.get_confidence(label)` → ConfidenceCalibrator 入力
  - `IdentityGraph.inject_pose_features(label, kp)` → RTMPose キーポイント注入口
"""
from __future__ import annotations

import copy as _copy_ti
import logging
import math as _math_ti
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── 純粋関数ヘルパー (routers/yolo.py から移送、後方互換のため re-export 可能) ─

def bbox_iou(b1: list, b2: list) -> float:
    """正規化座標 bbox の IoU。"""
    if len(b1) != 4 or len(b2) != 4:
        return 0.0
    ix1, iy1 = max(b1[0], b2[0]), max(b1[1], b2[1])
    ix2, iy2 = min(b1[2], b2[2]), min(b1[3], b2[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
    union = a1 + a2 - inter
    return inter / union if union > 0 else 0.0


def cos_sim(a: list[float], b: list[float]) -> float:
    """2 本の L1 正規化ヒストの cos 類似度。片方が空なら 0.5。"""
    if not a or not b or len(a) != len(b):
        return 0.5
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na <= 0 or nb <= 0:
        return 0.5
    return max(0.0, min(1.0, dot / (na * nb)))


def cos_sim_gallery(gallery: list, b: list[float]) -> float:
    """ギャラリー (hist リスト or 単一 hist) との最大類似度。"""
    if not gallery or not b:
        return 0.5
    if gallery and isinstance(gallery[0], (int, float)):
        return cos_sim(gallery, b)  # type: ignore[arg-type]
    best = 0.0
    for g in gallery:
        s = cos_sim(g, b)
        if s > best:
            best = s
    return best if best > 0 else 0.5


def foot_in_roi(bbox: list[float], roi: dict | None, margin: float = 0.03) -> bool:
    """bbox 足元が ROI に含まれるか。ROI 未指定なら True。"""
    if not roi or not bbox or len(bbox) != 4:
        return True
    rx = roi.get("x", 0.0)
    ry = roi.get("y", 0.0)
    rw = roi.get("w", 1.0)
    rh = roi.get("h", 1.0)
    foot_x = (bbox[0] + bbox[2]) / 2.0
    foot_y = bbox[3]
    return (
        (rx - margin) <= foot_x <= (rx + rw + margin)
        and (ry - margin) <= foot_y <= (ry + rh + margin)
    )


# ─── Track A3 forward-compat dataclass ────────────────────────────────────────

@dataclass
class IdentityState:
    """1 player identity の追跡状態 (Track B/C 接続用の forward-compat)。"""
    label: str
    last_bbox: Optional[list[float]] = None
    cx_n: float = 0.5
    cy_n: float = 0.5
    vel_cx: float = 0.0
    vel_cy: float = 0.0
    lost_count: int = 0
    gallery: list = field(default_factory=list)
    bt_track_id: Optional[int] = None
    pose_keypoints: Optional[Any] = None  # Track C: RTMPose 注入口


# ─── メイン関数: routers/yolo.py から移送 ────────────────────────────────────

def track_identities(
    yolo_frames: list[dict],
    seed_ts: float,
    assignments: list[dict],
    extra_galleries: dict[str, list[list[float]]] | None = None,
    court_roi: dict | None = None,
    *,
    _REID_MIN_SIM: float = 0.60,
) -> list[dict]:
    """シードフレームの割り当てをもとに全フレームへ速度予測付き双方向追跡を行う。

    routers/yolo.py::_track_identities から **ロジック完全互換で抽出** した関数。
    呼び出し側 (router) は thin wrapper で本関数を使う。

    設計思想:
        - 連続フレーム間の位置変化から速度 (vel_cx, vel_cy) を推定
        - ロスト時は速度に基づいて予測位置へ bbox を移動 (位置固定しない)
        - 予測位置を中心に探索するため、ロスト後の再捕捉が容易
        - ロストが続くほど探索半径を拡大し、再捕捉チャンスを高める
    """
    if not yolo_frames:
        return []

    seed_i = min(range(len(yolo_frames)), key=lambda i: abs(yolo_frames[i]["timestamp_sec"] - seed_ts))
    seed_players = yolo_frames[seed_i]["players"]

    # ── 初期識別リスト構築 ─────────────────────────────────────────────────
    init: list[dict] = []
    for a in assignments:
        bbox_from_ui = a.get("bbox")
        matched_p: dict | None = None

        if bbox_from_ui and len(bbox_from_ui) == 4:
            best_iou = 0.05
            for sp in seed_players:
                iou = bbox_iou(bbox_from_ui, sp.get("bbox", []))
                if iou > best_iou:
                    best_iou = iou
                    matched_p = sp

            if matched_p is None and seed_players:
                ui_cx = (bbox_from_ui[0] + bbox_from_ui[2]) / 2
                ui_cy = (bbox_from_ui[1] + bbox_from_ui[3]) / 2
                best_dist = 0.30
                for sp in seed_players:
                    sb = sp.get("bbox", [])
                    if len(sb) == 4:
                        scx = (sb[0] + sb[2]) / 2
                        scy = (sb[1] + sb[3]) / 2
                        dist = _math_ti.sqrt((scx - ui_cx) ** 2 + (scy - ui_cy) ** 2)
                        if dist < best_dist:
                            best_dist = dist
                            matched_p = sp

        if matched_p is None:
            idx = a["detection_index"]
            if idx < len(seed_players):
                matched_p = seed_players[idx]

        if matched_p is not None:
            bbox = matched_p.get("bbox", [0, 0, 0, 0])
            init.append({
                "player_key": a["player_key"],
                "bbox": bbox,
                "cx_n": matched_p.get("cx_n") or (bbox[0] + bbox[2]) / 2,
                "cy_n": matched_p.get("cy_n") or (bbox[1] + bbox[3]) / 2,
                "hist": matched_p.get("hist") or a.get("hist") or [],
                "lost": False,
            })
        elif bbox_from_ui and len(bbox_from_ui) == 4:
            logger.warning(
                "track_identities: seed frame players=%d, using UI bbox directly for %s",
                len(seed_players), a.get("player_key", "?"),
            )
            init.append({
                "player_key": a["player_key"],
                "bbox": list(bbox_from_ui),
                "cx_n": (bbox_from_ui[0] + bbox_from_ui[2]) / 2,
                "cy_n": (bbox_from_ui[1] + bbox_from_ui[3]) / 2,
                "hist": a.get("hist") or [],
                "lost": False,
            })

    if not init:
        return []

    # ── 速度予測付き伝播 ───────────────────────────────────────────────────
    def _propagate(frames_slice: list[dict], direction: int) -> dict[int, dict]:
        state: dict[str, dict] = {}
        for e in init:
            pk = e["player_key"]
            bbox = list(e["bbox"])
            cx = e["cx_n"] if e["cx_n"] is not None else (bbox[0] + bbox[2]) / 2
            cy = e["cy_n"] if e["cy_n"] is not None else (bbox[1] + bbox[3]) / 2
            seed_h = (bbox[3] - bbox[1]) if len(bbox) == 4 else 0.0
            primary_hist = list(e.get("hist") or [])
            gallery_list: list[list[float]] = []
            if primary_hist:
                gallery_list.append(primary_hist)
            if extra_galleries and pk in extra_galleries:
                for g in extra_galleries[pk]:
                    if g:
                        gallery_list.append(list(g))
            if gallery_list and yolo_frames:
                sample_hist_len = 0
                for f in yolo_frames[:10]:
                    for p in f.get("players", []):
                        h = p.get("hist")
                        if h:
                            sample_hist_len = len(h)
                            break
                    if sample_hist_len:
                        break
                if sample_hist_len:
                    valid = [g for g in gallery_list if len(g) == sample_hist_len]
                    if len(valid) < len(gallery_list):
                        logger.warning(
                            "track_identities: feature dim mismatch: dropped %d/%d "
                            "gallery entries (expected dim=%d)",
                            len(gallery_list) - len(valid), len(gallery_list), sample_hist_len,
                        )
                    gallery_list = valid
            state[pk] = {
                "bbox": bbox,
                "cx_n": cx,
                "cy_n": cy,
                "vel_cx": 0.0,
                "vel_cy": 0.0,
                "lost_count": 0,
                "gallery": gallery_list,
                "seed_h": seed_h,
                "bt_track_id": None,
            }

        result: dict[int, dict] = {}
        neg_gallery: list[list[float]] = []

        # 定数 (元 routers/yolo.py のローカル定数を維持)
        VEL_MAX = 0.05
        VEL_DECAY = 0.85
        REACQ_THRESH = 15
        REACQ_MAX_R = 0.45
        REACQ_MIN_SIM = 0.70
        PERM_LOST = 300
        GALLERY_MAX = 25
        UPDATE_SIM_TH = 0.75
        INF_COST = 1e6
        NEG_GALLERY_MAX = 120
        NEG_SIM_THRESH = 0.82
        BT_MATCH_COST = 0.001

        try:
            from scipy.optimize import linear_sum_assignment as _lsa  # type: ignore
            _has_lsa = True
        except Exception:
            _lsa = None
            _has_lsa = False

        for frame in frames_slice:
            curr = frame["players"]
            frame_players: list[dict] = []
            track_keys = list(state.keys())
            T = len(track_keys)
            D = len(curr)

            preds: dict[str, tuple[float, float, float]] = {}
            for pk, st in state.items():
                if abs(st["vel_cx"]) > VEL_MAX:
                    st["vel_cx"] = VEL_MAX if st["vel_cx"] > 0 else -VEL_MAX
                if abs(st["vel_cy"]) > VEL_MAX:
                    st["vel_cy"] = VEL_MAX if st["vel_cy"] > 0 else -VEL_MAX
                if st["lost_count"] > 0:
                    st["vel_cx"] *= VEL_DECAY
                    st["vel_cy"] *= VEL_DECAY
                if st["lost_count"] >= PERM_LOST:
                    st["vel_cx"] = 0.0
                    st["vel_cy"] = 0.0
                pred_cx = max(0.0, min(1.0, st["cx_n"] + st["vel_cx"] * direction))
                pred_cy = max(0.0, min(1.0, st["cy_n"] + st["vel_cy"] * direction))
                if st["lost_count"] >= REACQ_THRESH:
                    search_r = REACQ_MAX_R
                else:
                    search_r = 0.20 + 0.03 * st["lost_count"]
                preds[pk] = (pred_cx, pred_cy, search_r)

            track_costs: list[list[float]] = [[INF_COST] * max(D, 1) for _ in range(max(T, 1))]
            track_sims: list[list[float]] = [[0.5] * max(D, 1) for _ in range(max(T, 1))]
            track_ious: list[list[float]] = [[0.0] * max(D, 1) for _ in range(max(T, 1))]

            neg_blocked: set[int] = set()
            if neg_gallery:
                neg_dim = len(neg_gallery[0])
                for di, p in enumerate(curr):
                    ph = p.get("hist") or []
                    if ph and len(ph) == neg_dim:
                        if cos_sim_gallery(neg_gallery, ph) >= NEG_SIM_THRESH:
                            neg_blocked.add(di)

            for ti, pk in enumerate(track_keys):
                st = state[pk]
                pred_cx, pred_cy, search_r = preds[pk]
                min_sim_local = REACQ_MIN_SIM if st["lost_count"] >= REACQ_THRESH else _REID_MIN_SIM
                for di, p in enumerate(curr):
                    if di in neg_blocked:
                        continue
                    pb = p.get("bbox", [])
                    if not foot_in_roi(pb, court_roi):
                        continue
                    p_bt_id = p.get("track_id")
                    if p_bt_id is not None and st.get("bt_track_id") == p_bt_id:
                        track_costs[ti][di] = BT_MATCH_COST
                        track_sims[ti][di] = 1.0
                        track_ious[ti][di] = 1.0
                        continue
                    iou = bbox_iou(st["bbox"], pb)
                    if len(pb) == 4:
                        cx = (pb[0] + pb[2]) / 2
                        cy = (pb[1] + pb[3]) / 2
                        det_h = pb[3] - pb[1]
                    else:
                        cx = p.get("cx_n", 0.5)
                        cy = p.get("cy_n", 0.5)
                        det_h = 0.0
                    pos_dist = _math_ti.sqrt((cx - pred_cx) ** 2 + (cy - pred_cy) ** 2)
                    sim = cos_sim_gallery(st["gallery"], p.get("hist") or []) if st["gallery"] else 0.5
                    track_sims[ti][di] = sim
                    track_ious[ti][di] = iou
                    if iou > 0.1:
                        track_costs[ti][di] = max(0.0, 0.3 - iou)
                        continue
                    if pos_dist >= search_r:
                        continue
                    if st["gallery"] and sim < min_sim_local:
                        continue
                    if st["seed_h"] > 0.01 and det_h > 0:
                        size_diff = min(abs(det_h - st["seed_h"]) / st["seed_h"], 1.0)
                    else:
                        size_diff = 0.0
                    track_costs[ti][di] = pos_dist + 0.6 * (1.0 - sim) + 0.25 * size_diff

            track_to_det: dict[int, int] = {}
            if T > 0 and D > 0:
                if _has_lsa:
                    import numpy as _np_ti
                    cm = _np_ti.array(track_costs, dtype=_np_ti.float32)
                    rows, cols = _lsa(cm)
                    for ri, ci in zip(rows, cols):
                        if cm[ri, ci] < INF_COST - 1:
                            track_to_det[int(ri)] = int(ci)
                else:
                    pairs = [
                        (track_costs[ti][di], ti, di)
                        for ti in range(T) for di in range(D)
                        if track_costs[ti][di] < INF_COST - 1
                    ]
                    pairs.sort(key=lambda x: x[0])
                    used_t: set[int] = set()
                    used_d: set[int] = set()
                    for _c, ti, di in pairs:
                        if ti in used_t or di in used_d:
                            continue
                        track_to_det[ti] = di
                        used_t.add(ti)
                        used_d.add(di)

            for ti, pk in enumerate(track_keys):
                st = state[pk]
                pred_cx, pred_cy, _ = preds[pk]
                if ti in track_to_det:
                    di = track_to_det[ti]
                    p = curr[di]
                    pb = p.get("bbox", [])
                    new_cx = (pb[0] + pb[2]) / 2 if len(pb) == 4 else p.get("cx_n", pred_cx)
                    new_cy = (pb[1] + pb[3]) / 2 if len(pb) == 4 else p.get("cy_n", pred_cy)
                    if st["lost_count"] >= REACQ_THRESH:
                        st["vel_cx"] = 0.0
                        st["vel_cy"] = 0.0
                    else:
                        alpha = 0.5
                        nvx = alpha * (new_cx - st["cx_n"]) + (1 - alpha) * st["vel_cx"]
                        nvy = alpha * (new_cy - st["cy_n"]) + (1 - alpha) * st["vel_cy"]
                        st["vel_cx"] = max(-VEL_MAX, min(VEL_MAX, nvx))
                        st["vel_cy"] = max(-VEL_MAX, min(VEL_MAX, nvy))
                    st["cx_n"] = new_cx
                    st["cy_n"] = new_cy
                    st["bbox"] = list(pb) if len(pb) == 4 else st["bbox"]
                    st["lost_count"] = 0
                    if p.get("track_id") is not None:
                        st["bt_track_id"] = p["track_id"]
                    p_hist = p.get("hist") or []
                    iou_mv = track_ious[ti][di]
                    sim_mv = track_sims[ti][di]
                    cost_mv = track_costs[ti][di]
                    high_conf = (iou_mv > 0.3) or (cost_mv < 0.3 and sim_mv > UPDATE_SIM_TH)
                    if p_hist and st["gallery"] and high_conf:
                        if len(p_hist) == len(st["gallery"][0]):
                            st["gallery"].append(list(p_hist))
                            if len(st["gallery"]) > GALLERY_MAX:
                                seed_count = min(11, len(st["gallery"]))
                                st["gallery"] = (
                                    st["gallery"][:seed_count]
                                    + st["gallery"][-(GALLERY_MAX - seed_count):]
                                )
                    frame_players.append({
                        "player_key": pk,
                        "bbox": st["bbox"],
                        "cx_n": new_cx,
                        "cy_n": new_cy,
                        "lost": False,
                    })
                else:
                    bw = (st["bbox"][2] - st["bbox"][0]) if len(st["bbox"]) == 4 else 0.1
                    bh = (st["bbox"][3] - st["bbox"][1]) if len(st["bbox"]) == 4 else 0.2
                    pred_bbox = [
                        pred_cx - bw / 2, pred_cy - bh / 2,
                        pred_cx + bw / 2, pred_cy + bh / 2,
                    ]
                    st["cx_n"] = pred_cx
                    st["cy_n"] = pred_cy
                    st["bbox"] = pred_bbox
                    st["lost_count"] += 1
                    frame_players.append({
                        "player_key": pk,
                        "bbox": pred_bbox,
                        "cx_n": pred_cx,
                        "cy_n": pred_cy,
                        "lost": True,
                    })

            matched_det_indices = set(track_to_det.values())
            neg_dim = len(neg_gallery[0]) if neg_gallery else 0
            for di, p in enumerate(curr):
                if di in matched_det_indices:
                    continue
                ph = p.get("hist") or []
                if not ph:
                    continue
                if neg_gallery and len(ph) != neg_dim:
                    continue
                neg_gallery.append(list(ph))
                if not neg_dim:
                    neg_dim = len(ph)
            if len(neg_gallery) > NEG_GALLERY_MAX:
                neg_gallery = neg_gallery[-NEG_GALLERY_MAX:]

            result[frame["frame_idx"]] = {
                "frame_idx": frame["frame_idx"],
                "timestamp_sec": frame["timestamp_sec"],
                "players": frame_players,
            }

        return result

    forward = _propagate(yolo_frames[seed_i:], direction=1)
    backward = _propagate(list(reversed(yolo_frames[:seed_i])), direction=-1)

    merged = {**backward, **forward}
    return sorted(merged.values(), key=lambda f: f["frame_idx"])


# ─── Forward-compat: クラス wrapper (Track B/C 接続点) ─────────────────────────

class IdentityGraph:
    """match_id 単位の identity 追跡 wrapper。

    Track A3 段階では `track_identities()` の thin facade。
    Track B (ConfidenceCalibrator) や Track C (RTMPose 注入) で拡張する余地を残す。
    """

    def __init__(
        self,
        *,
        court_roi: dict | None = None,
        reid_min_sim: float = 0.60,
    ) -> None:
        self.court_roi = court_roi
        self.reid_min_sim = reid_min_sim
        self._identities: Dict[str, IdentityState] = {}
        self._frame_count: int = 0

    def track(
        self,
        yolo_frames: list[dict],
        seed_ts: float,
        assignments: list[dict],
        extra_galleries: dict[str, list[list[float]]] | None = None,
    ) -> list[dict]:
        """`track_identities` への facade。返り値は同じ形式。"""
        return track_identities(
            yolo_frames=yolo_frames,
            seed_ts=seed_ts,
            assignments=assignments,
            extra_galleries=extra_galleries,
            court_roi=self.court_roi or {},
            _REID_MIN_SIM=self.reid_min_sim,
        )

    # ─ Track B 接続点 ─
    def get_confidence(self, label: str) -> float:
        """Identity tracking confidence (Track B ConfidenceCalibrator 入力)。

        現状は identity_state.lost_count から線形に算出。Track B で
        Platt scaling 後の calibrated probability を返すよう拡張可能。
        """
        ident = self._identities.get(label)
        if ident is None:
            return 0.0
        # lost_count=0 → 1.0、=15 → 0.0 に線形減衰
        return max(0.0, 1.0 - ident.lost_count / 15.0)

    # ─ Track C 接続点 ─
    def inject_pose_features(self, label: str, keypoints) -> None:
        """RTMPose 17 関節を注入 (Track C SwingDetector 入力)。

        現状は IdentityState に保存するだけ (no-op for identity tracking)。
        """
        if label not in self._identities:
            self._identities[label] = IdentityState(label=label)
        self._identities[label].pose_keypoints = keypoints

    def reset(self) -> None:
        self._identities.clear()
        self._frame_count = 0

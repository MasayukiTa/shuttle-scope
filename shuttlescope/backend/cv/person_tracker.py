"""Phase 1 + Phase 2 + Phase 3 (簡易版) + Phase 3.5 TRT refactor の Person Tracker。

設計書: private_docs/2026-05-27_person_tracking_design.md

Phase 3.5 (2026-05-27): 検出と追跡を分離する 2-stage 設計に refactor。
- 検出: backend.yolo.inference.get_yolo_inference().predict_frame()
        (TRT / CUDA / OpenVINO / CPU 経路を自動選択、court filter 内包)
- 追跡: backend.cv.byte_tracker.ByteTracker (scratch, MIT)
これにより ultralytics の素 ONNX 経由 12 fps → TRT 経路で 1000+ fps を期待。

- Tier 1: standalone ByteTracker (Kalman + IoU + 2-pass Hungarian)
- Tier 2: Court 4 隅 → 4 象限 polygon を作って bbox 足元を象限テスト
- Tier 3 (Phase 3 簡易版): court_id → player_label ("PlayerA".."PlayerD") の
  固定マップ。set 間 side swap 検知 (奇数 set で FL⇄BL / FR⇄BR)。
  DB の player_uuid bind は Phase 4 で。本 phase では player_uuid は常に None。

match_id を渡すと DB の court_calibration から court 4 隅を取得する。
渡さなければ court_corners 引数 fallback (テスト用)。

検出 backend (get_yolo_inference) は遅延 import — CI 軽量 venv でも
quadrant adjudicator / ByteTracker 単体テストが回る。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── 環境変数 ─────────────────────────────────────────────────────────────
DEFAULT_MODEL_PATH = os.environ.get(
    "SS_PERSON_TRACKER_MODEL",
    "backend/models/yolov8n.onnx",  # 80-class COCO、person だけ拾う
)
DEFAULT_CONF = float(os.environ.get("SS_PERSON_TRACKER_CONF", "0.25"))
DEFAULT_IOU = float(os.environ.get("SS_PERSON_TRACKER_IOU", "0.45"))
DEFAULT_TRACKER_YAML = os.environ.get("SS_PERSON_TRACKER_YAML", "bytetrack.yaml")
DEFAULT_IMGSZ = int(os.environ.get("SS_PERSON_TRACKER_IMGSZ", "640"))
PERSON_CLASS_ID = 0  # COCO の person


# ── 公開 dataclass ───────────────────────────────────────────────────────
@dataclass
class TrackedPerson:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 (pixel)
    track_id: int            # raw ByteTrack ID。未付与時は -1
    court_id: Optional[int]  # 0=FL, 1=FR, 2=BL, 3=BR、コート外は None
    player_uuid: Optional[str]  # Phase 4 で bind 予定、本 phase では常に None
    confidence: float
    is_recovered: bool = False  # Tier 3 (Phase 4) 用、本 phase では常に False
    player_label: Optional[str] = None  # Phase 3 簡易: "PlayerA"/"B"/"C"/"D"


# court_id → 簡易 player_label の固定マップ
# 0=FL → PlayerA, 1=FR → PlayerB, 2=BL → PlayerC, 3=BR → PlayerD
_COURT_TO_LABEL: dict[int, str] = {
    0: "PlayerA",
    1: "PlayerB",
    2: "PlayerC",
    3: "PlayerD",
}

# side swap 時の court_id 入れ替えマップ (奇数 set で適用)
# FL(0) ⇄ BL(2)、FR(1) ⇄ BR(3) — 同サイドの前後を入れ替えるのではなく
# 「コートサイドが入れ替わる」= front/back が反転するため。
_SIDE_SWAP_MAP: dict[int, int] = {0: 2, 1: 3, 2: 0, 3: 1}


def court_id_to_player_label(court_id: Optional[int]) -> Optional[str]:
    """court_id (0..3) → 簡易 player_label。コート外 (None) は None。"""
    if court_id is None:
        return None
    return _COURT_TO_LABEL.get(court_id)


# ── Court Quadrant Adjudicator ───────────────────────────────────────────
class _QuadrantAdjudicator:
    """Court 4 隅 → 4 象限 polygon を作って bbox 足元を象限テスト。

    入力 4 隅は image pixel 座標で TL, TR, BR, BL の順序を想定。
    象限割り当て:
        front = ネット側 (画面の上 = y 小)
        back  = ベースライン側 (画面の下 = y 大)
        left  = 画面左 (x 小)
        right = 画面右 (x 大)
        0=FL (front-left)  1=FR (front-right)
        2=BL (back-left)   3=BR (back-right)

    実装メモ: コート 4 隅から中央線 2 本を作り、各 quadrant を 4 点 polygon として
    保持。bbox 足元の (cx, y2) を ray-casting で polygon-in テストする。
    """

    def __init__(self, court_corners: list[tuple[float, float]]):
        if len(court_corners) != 4:
            raise ValueError(f"court_corners は 4 点必須、got {len(court_corners)}")
        tl, tr, br, bl = [tuple(map(float, p)) for p in court_corners]
        # 中央線エンドポイント (top/bottom 辺の中点、left/right 辺の中点)
        top_mid = ((tl[0] + tr[0]) / 2.0, (tl[1] + tr[1]) / 2.0)
        bot_mid = ((bl[0] + br[0]) / 2.0, (bl[1] + br[1]) / 2.0)
        left_mid = ((tl[0] + bl[0]) / 2.0, (tl[1] + bl[1]) / 2.0)
        right_mid = ((tr[0] + br[0]) / 2.0, (tr[1] + br[1]) / 2.0)
        # コート中心 (対角線交点の近似 = 4 隅の重心)
        center = (
            (tl[0] + tr[0] + br[0] + bl[0]) / 4.0,
            (tl[1] + tr[1] + br[1] + bl[1]) / 4.0,
        )
        # 4 象限 polygon (反時計回り)
        # FL: tl - top_mid - center - left_mid
        # FR: top_mid - tr - right_mid - center
        # BL: left_mid - center - bot_mid - bl
        # BR: center - right_mid - br - bot_mid
        self._quadrants: list[list[tuple[float, float]]] = [
            [tl, top_mid, center, left_mid],
            [top_mid, tr, right_mid, center],
            [left_mid, center, bot_mid, bl],
            [center, right_mid, br, bot_mid],
        ]
        # コート全体 polygon (外周) — bbox がコート外かの判定用
        self._court_polygon: list[tuple[float, float]] = [tl, tr, br, bl]

    @staticmethod
    def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
        """Ray casting."""
        n = len(polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            ):
                inside = not inside
            j = i
        return inside

    def classify(self, bbox: tuple[float, float, float, float]) -> Optional[int]:
        """bbox 足元 (center_x, y2) からどの象限かを返す。コート外は None。"""
        x1, _y1, x2, y2 = bbox
        foot_x = (x1 + x2) / 2.0
        foot_y = y2
        if not self._point_in_polygon(foot_x, foot_y, self._court_polygon):
            return None
        for qid, poly in enumerate(self._quadrants):
            if self._point_in_polygon(foot_x, foot_y, poly):
                return qid
        return None


def adjudicate_court(
    tracks: list[TrackedPerson],
    adjudicator: _QuadrantAdjudicator,
    match_type: Literal["singles", "doubles"],
) -> list[TrackedPerson]:
    """match_type に応じて象限ごとの整合性を取った上で court_id を割り当てる。

    singles: 同一象限に 2 track_id 居る → conf 低い方を court_id=None に降格。
    doubles: 同一象限 2 まで OK、3 以上は warning log を出す (drop しない)。
    """
    # まず素朴に classify
    raw_qids: list[Optional[int]] = [adjudicator.classify(t.bbox) for t in tracks]

    # 象限ごとの track index リスト
    by_q: dict[int, list[int]] = {}
    for idx, qid in enumerate(raw_qids):
        if qid is None:
            continue
        by_q.setdefault(qid, []).append(idx)

    if match_type == "singles":
        max_per_q = 1
    else:
        max_per_q = 2

    for qid, idxs in by_q.items():
        if len(idxs) <= max_per_q:
            continue
        # conf 降順 sort
        idxs_sorted = sorted(idxs, key=lambda i: tracks[i].confidence, reverse=True)
        # 上位 max_per_q だけ残し、それ以外は court_id=None に降格
        for demote in idxs_sorted[max_per_q:]:
            raw_qids[demote] = None
        if match_type == "doubles" and len(idxs) >= 3:
            logger.warning(
                "doubles で同一象限 %s に %d tracks 検出 (>=3) — 上位 %d 採用",
                qid, len(idxs), max_per_q,
            )

    # 反映した新 TrackedPerson list を返す
    out: list[TrackedPerson] = []
    for t, qid in zip(tracks, raw_qids):
        out.append(
            TrackedPerson(
                bbox=t.bbox,
                track_id=t.track_id,
                court_id=qid,
                player_uuid=None,
                confidence=t.confidence,
                is_recovered=t.is_recovered,
            )
        )
    return out


# ── PersonTracker (Tier 1 + Tier 2 統合) ─────────────────────────────────
class PersonTracker:
    def __init__(
        self,
        match_type: Literal["singles", "doubles"],
        court_corners: Optional[list[tuple[float, float]]] = None,
        model_path: Optional[str] = None,
        device: Optional[str] = None,
        match_id: Optional[int] = None,
        frame_size: Optional[tuple[int, int]] = None,
    ):
        """Person tracker.

        Args:
            match_type: "singles" / "doubles"
            court_corners: pixel 座標で TL,TR,BR,BL の 4 隅。match_id 優先。
            model_path: YOLO model path。env SS_PERSON_TRACKER_MODEL fallback。
            device: torch device 名 (例 "cuda:0")。None なら ultralytics 任せ。
            match_id: 指定時は DB の court_calibration から 4 隅を取得して
                court_corners を上書きする。frame_size (w,h) が必要 (roi_polygon は
                正規化座標で保存されているため pixel に戻すのに使う)。
            frame_size: (width, height) pixel。match_id を使う場合は必須。
        """
        if match_type not in ("singles", "doubles"):
            raise ValueError(f"match_type は singles/doubles、got {match_type}")
        self.match_type = match_type
        self.match_id = match_id
        self._frame_size = frame_size

        resolved_corners: Optional[list[tuple[float, float]]] = court_corners
        if match_id is not None:
            db_corners = self._load_corners_from_db(match_id, frame_size)
            if db_corners is not None:
                resolved_corners = db_corners

        self._adjudicator: Optional[_QuadrantAdjudicator] = (
            _QuadrantAdjudicator(resolved_corners) if resolved_corners else None
        )
        self._model_path = model_path or DEFAULT_MODEL_PATH
        self._device = device
        # Phase 3.5: 検出器は backend.yolo.inference の singleton、追跡器は scratch ByteTracker
        self._detector = None  # YOLOInference singleton、遅延 init
        self._tracker = None   # ByteTracker、遅延 init
        # side swap 状態 (奇数 set で True)
        self._side_swapped: bool = False
        self._current_set_idx: int = 0

    @staticmethod
    def _load_corners_from_db(
        match_id: int,
        frame_size: Optional[tuple[int, int]],
    ) -> Optional[list[tuple[float, float]]]:
        """DB の court_calibration から 4 隅 pixel 座標を取得する。

        court_calibration.roi_polygon は **正規化座標** (0-1) で保存されている。
        frame_size=(w,h) で pixel に戻す。frame_size が None なら正規化のまま返す
        (テスト用)。失敗時は None。
        """
        try:
            from backend.routers.court_calibration import load_calibration_standalone
            data = load_calibration_standalone(match_id)
        except Exception as exc:
            logger.warning("court_calibration load failed (match_id=%s): %s", match_id, exc)
            return None
        if not data:
            return None
        roi = data.get("roi_polygon")
        if not roi or len(roi) != 4:
            return None
        # 退化キャリブ (全点が 0.5,0.5 等) を弾く
        xs = {round(float(p[0]), 4) for p in roi}
        ys = {round(float(p[1]), 4) for p in roi}
        if len(xs) < 2 or len(ys) < 2:
            logger.warning("court_calibration roi_polygon is degenerate (match_id=%s)", match_id)
            return None
        if frame_size is None:
            return [(float(p[0]), float(p[1])) for p in roi]
        w, h = frame_size
        return [(float(p[0]) * w, float(p[1]) * h) for p in roi]

    def _ensure_components(self):
        """Phase 3.5: 検出器と追跡器を遅延 init。"""
        if self._detector is None:
            # backend.yolo.inference の singleton を使う。
            # SS_PERSON_TRACKER_MODEL は debugging 用に保持するが、実際は
            # YOLOInference 内部の backend 自動選択 (OpenVINO → ultralytics PT → ONNX (TRT/CUDA))
            # が走るため、ここでは model_path を渡せない。代わりに env で制御:
            #   SS_YOLO_USE_TRT=0 で TRT スキップ等。
            from backend.yolo.inference import get_yolo_inference  # type: ignore
            self._detector = get_yolo_inference()
            # 明示 load — 失敗時は update() で空 list を返す挙動になる
            if not self._detector.load():
                logger.warning(
                    "PersonTracker: YOLO detector load 失敗、空 detection で動作"
                )
            else:
                logger.info(
                    "PersonTracker: detector backend=%s, model_path_hint=%s",
                    self._detector.backend_name(), self._model_path,
                )
        if self._tracker is None:
            from backend.cv.byte_tracker import ByteTracker  # type: ignore
            self._tracker = ByteTracker(
                track_high_thresh=DEFAULT_CONF,
                track_low_thresh=max(0.05, DEFAULT_CONF * 0.4),
                new_track_thresh=DEFAULT_CONF,
                track_buffer=120,
                match_thresh_high=0.8,
                match_thresh_low=0.5,
                match_thresh_unconfirmed=0.7,
            )
            logger.info("PersonTracker: standalone ByteTracker 初期化")

    def update(self, frame: np.ndarray, frame_idx: int) -> list[TrackedPerson]:
        """1 frame 処理。検出 (YOLOInference) + 追跡 (ByteTracker) の 2-stage。"""
        self._ensure_components()

        # 検出: full-frame 推論。predict_frame は **正規化座標** で返るので pixel に戻す。
        h, w = frame.shape[:2]
        detections_n = self._detector.predict_frame(frame) if self._detector is not None else []

        # ByteTracker は pixel 座標 + score を受け取る。
        # YOLOInference の出力は person / player_a..d / player_other 等の混在ラベル。
        # ここでは person 系全部を検出として扱う (court filter は YOLOInference 側で
        # 適用済み = 二重適用しない)。
        from backend.cv.byte_tracker import Detection  # type: ignore
        bt_dets: list[Detection] = []
        for d in detections_n:
            label = d.get("label", "")
            if not (label == "person" or label.startswith("player_")):
                continue
            bb = d.get("bbox") or []
            if len(bb) != 4:
                continue
            x1 = float(bb[0]) * w
            y1 = float(bb[1]) * h
            x2 = float(bb[2]) * w
            y2 = float(bb[3]) * h
            score = float(d.get("confidence", 0.0))
            bt_dets.append(Detection(bbox=(x1, y1, x2, y2), score=score))

        # 追跡: ByteTracker.update — Kalman 予測 + 2-pass Hungarian
        stracks = self._tracker.update(bt_dets, frame_id=frame_idx)

        raw_tracks: list[TrackedPerson] = []
        for st in stracks:
            x1, y1, x2, y2 = st.xyxy
            raw_tracks.append(
                TrackedPerson(
                    bbox=(float(x1), float(y1), float(x2), float(y2)),
                    track_id=int(st.track_id),
                    court_id=None,
                    player_uuid=None,
                    confidence=float(st.score),
                )
            )

        # Tier 2: court 象限割り当て
        if self._adjudicator is None:
            # passthrough、court_id はすべて None なので player_label も None
            return raw_tracks
        adjudicated = adjudicate_court(raw_tracks, self._adjudicator, self.match_type)

        # Tier 3 (Phase 3 簡易): side swap 反映 + court_id → player_label マップ
        return [self._attach_player_label(t) for t in adjudicated]

    def _attach_player_label(self, t: TrackedPerson) -> TrackedPerson:
        """side swap を考慮して court_id を補正し、player_label を付ける。

        side swap 中は player 視点での court_id を返す (例: FL の人物は side swap
        中の set では PlayerC として扱う = FL→BL に swap)。返却 court_id 自体も
        swap 後の値に揃え、下流の player_label と一致させる。
        """
        if t.court_id is None:
            return t
        effective_cid = _SIDE_SWAP_MAP[t.court_id] if self._side_swapped else t.court_id
        label = court_id_to_player_label(effective_cid)
        return TrackedPerson(
            bbox=t.bbox,
            track_id=t.track_id,
            court_id=effective_cid,
            player_uuid=None,
            confidence=t.confidence,
            is_recovered=t.is_recovered,
            player_label=label,
        )

    def reset_for_new_set(self, set_idx: int) -> None:
        """セット間の side swap 対応。

        - set_idx 偶数 (0, 2, 4 ...) → side swap 無し (1st, 3rd, 5th set)
        - set_idx 奇数 (1, 3 ...)    → side swap 有り (2nd, 4th set)
        - ByteTrack 内部 state はリセット (set 間で人物が完全に入れ替わるため
          ID 継続させると誤マッピングが残る)
        """
        self._current_set_idx = int(set_idx)
        self._side_swapped = (self._current_set_idx % 2 == 1)
        # Phase 3.5: standalone ByteTracker の内部 state を完全リセット
        if self._tracker is not None:
            try:
                self._tracker.reset()
            except Exception as exc:
                logger.warning("reset_for_new_set: ByteTracker reset failed: %s", exc)
        logger.info(
            "PersonTracker reset for set %s (side_swapped=%s)",
            set_idx, self._side_swapped,
        )

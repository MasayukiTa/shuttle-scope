"""Phase 1 + Phase 2 の Person Tracker。

設計書: private_docs/2026-05-27_person_tracking_design.md

- Tier 1: ultralytics ByteTrack (`model.track(...)` per-frame, persist=True)
- Tier 2: Court 4 隅 → 4 象限 polygon を作って bbox 足元を象限テスト
- Tier 3 / Player labeler は本 phase ではスコープ外 (player_uuid は常に None)

ultralytics / torch が import できない実行環境 (CI 軽量 venv 等) でも
quadrant adjudicator 単体をテストできるよう、依存は遅延 import する。
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
    player_uuid: Optional[str]  # Phase 3 で bind 予定、本 phase では常に None
    confidence: float
    is_recovered: bool = False  # Tier 3 (Phase 4) 用、本 phase では常に False


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
    ):
        if match_type not in ("singles", "doubles"):
            raise ValueError(f"match_type は singles/doubles、got {match_type}")
        self.match_type = match_type
        self._adjudicator: Optional[_QuadrantAdjudicator] = (
            _QuadrantAdjudicator(court_corners) if court_corners else None
        )
        self._model_path = model_path or DEFAULT_MODEL_PATH
        self._device = device
        self._model = None  # 遅延 import

    def _ensure_model(self):
        if self._model is not None:
            return
        # ultralytics は torch / opencv の重い依存を引き、CI 軽量 venv では import エラー。
        # update() が呼ばれた時のみロードする。
        from ultralytics import YOLO  # type: ignore
        self._model = YOLO(self._model_path)
        logger.info("PersonTracker: loaded model %s", self._model_path)

    def update(self, frame: np.ndarray, frame_idx: int) -> list[TrackedPerson]:
        """1 frame 処理。ByteTrack persist=True で frame またぎ ID を維持する。"""
        self._ensure_model()
        # ultralytics の track API — persist=True で内部 tracker state を保持
        kwargs = dict(
            source=frame,
            persist=True,
            tracker=DEFAULT_TRACKER_YAML,
            conf=DEFAULT_CONF,
            iou=DEFAULT_IOU,
            imgsz=DEFAULT_IMGSZ,
            classes=[PERSON_CLASS_ID],
            verbose=False,
        )
        if self._device:
            kwargs["device"] = self._device
        results = self._model.track(**kwargs)
        if not results:
            return []
        r = results[0]
        boxes = getattr(r, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return []

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy() if boxes.conf is not None else np.ones(len(xyxy))
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else np.full(len(xyxy), -1, dtype=int)

        raw_tracks: list[TrackedPerson] = []
        for i in range(len(xyxy)):
            x1, y1, x2, y2 = [float(v) for v in xyxy[i]]
            raw_tracks.append(
                TrackedPerson(
                    bbox=(x1, y1, x2, y2),
                    track_id=int(ids[i]),
                    court_id=None,
                    player_uuid=None,
                    confidence=float(confs[i]),
                )
            )

        # Tier 2: court 象限割り当て
        if self._adjudicator is None:
            return raw_tracks  # passthrough、court_id はすべて None
        return adjudicate_court(raw_tracks, self._adjudicator, self.match_type)

    def reset_for_new_set(self, set_idx: int) -> None:
        """セット間の side swap 対応 (Phase 3 で利用)。

        本 phase ではトラッカ内部 state を破棄するだけ。
        """
        if self._model is not None:
            # ultralytics の track state は predictor.trackers に乗っている。
            # 一旦 None にして次回 _ensure_model でリロード。
            try:
                trackers = getattr(self._model.predictor, "trackers", None)
                if trackers:
                    for tr in trackers:
                        if hasattr(tr, "reset"):
                            tr.reset()
            except Exception as exc:
                logger.warning("reset_for_new_set: tracker reset failed: %s", exc)
        logger.info("PersonTracker reset for set %s", set_idx)

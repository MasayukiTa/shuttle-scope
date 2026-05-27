"""Phase 1 + Phase 2 + Phase 3 (簡易版) の Person Tracker。

設計書: private_docs/2026-05-27_person_tracking_design.md

- Tier 1: ultralytics ByteTrack (`model.track(...)` per-frame, persist=True)
- Tier 2: Court 4 隅 → 4 象限 polygon を作って bbox 足元を象限テスト
- Tier 3 (Phase 3 簡易版): court_id → player_label ("PlayerA".."PlayerD") の
  固定マップ。set 間 side swap 検知 (奇数 set で FL⇄BL / FR⇄BR)。
  DB の player_uuid bind は Phase 4 で。本 phase では player_uuid は常に None。

match_id を渡すと DB の court_calibration から court 4 隅を取得する。
渡さなければ court_corners 引数 fallback (テスト用)。

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
        self._model = None  # 遅延 import
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
        if self._model is not None:
            # ultralytics の track state は predictor.trackers に乗っている。
            try:
                trackers = getattr(self._model.predictor, "trackers", None)
                if trackers:
                    for tr in trackers:
                        if hasattr(tr, "reset"):
                            tr.reset()
            except Exception as exc:
                logger.warning("reset_for_new_set: tracker reset failed: %s", exc)
        logger.info(
            "PersonTracker reset for set %s (side_swapped=%s)",
            set_idx, self._side_swapped,
        )

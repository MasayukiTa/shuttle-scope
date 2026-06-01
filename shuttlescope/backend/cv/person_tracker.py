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
from collections import deque
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Phase 4 ReID 既定値 ──────────────────────────────────────────────────
# env 経由でも上書き可。テスト容易性のため module 定数として持つ。
REID_ENABLED_DEFAULT = os.environ.get("SS_PERSON_REID_ENABLED", "1") != "0"
REID_THRESH_DEFAULT = float(os.environ.get("SS_PERSON_REID_THRESH", "0.85"))
REID_HISTORY_LEN = int(os.environ.get("SS_PERSON_REID_HISTORY", "30"))
# 復帰猶予 (frame 数)。30 fps で 300 = 10 秒。設計書は 5 秒だがバドミントンの
# rally 単位 occlusion (約 3-7 秒) を確実に救う安全側で 10 秒に振る。env で調整可。
REID_LOST_GRACE_FRAMES = int(os.environ.get("SS_PERSON_REID_LOST_GRACE", "300"))

# ── Swap Guard 既定値 (同ユニフォーム teammate の track_id 入れ替わり防止) ──
# 既定 OFF (env 未設定で挙動完全不変)。SS_PERSON_SWAP_GUARD=1 で有効化。
# motion-only: 各 track_id の直近 K centroid から等速予測し、近接ペアについて
# 「現状の ID 割当」 vs 「swap 後の割当」の予測誤差合計を比較。swap の方が
# margin 以上小さければ ByteTrack が crossover で取り違えたと判断し alias で補正。
SWAP_GUARD_ENABLED_DEFAULT = os.environ.get("SS_PERSON_SWAP_GUARD", "0") == "1"
# swap を採用する相対マージン: swapped_err < current_err * (1 - margin) で発火。
SWAP_GUARD_MARGIN = float(os.environ.get("SS_PERSON_SWAP_GUARD_MARGIN", "0.30"))
# 等速予測に使う直近 centroid 数。
SWAP_GUARD_HISTORY = int(os.environ.get("SS_PERSON_SWAP_GUARD_HISTORY", "5"))
# ペアを「近接 (= swap 候補)」と見なす最大予測位置間距離 (pixel)。これ以上
# 離れていれば crossover の可能性が無いので評価しない (誤補正防止)。
SWAP_GUARD_MAX_PAIR_DIST = float(os.environ.get("SS_PERSON_SWAP_GUARD_MAX_DIST", "250.0"))

# ── 環境変数 ─────────────────────────────────────────────────────────────
DEFAULT_MODEL_PATH = os.environ.get(
    "SS_PERSON_TRACKER_MODEL",
    "backend/models/yolov8n.onnx",  # 80-class COCO、person だけ拾う
)
# batch infer 用 dynamic-shape model (Phase 3.6 で追加、1-class fine-tuned 384×640 FP16)
DEFAULT_BATCH_MODEL_PATH = os.environ.get(
    "SS_PERSON_TRACKER_BATCH_MODEL",
    "backend/models/yolov8n_v2_finetuned_dyn.onnx",
)
DEFAULT_CONF = float(os.environ.get("SS_PERSON_TRACKER_CONF", "0.25"))
DEFAULT_IOU = float(os.environ.get("SS_PERSON_TRACKER_IOU", "0.45"))
DEFAULT_TRACKER_YAML = os.environ.get("SS_PERSON_TRACKER_YAML", "bytetrack.yaml")
DEFAULT_IMGSZ = int(os.environ.get("SS_PERSON_TRACKER_IMGSZ", "640"))

# ── ByteTracker churn-tuning knobs (env-overridable) ─────────────────────
# 旧ハードコード値: high=DEFAULT_CONF(0.25) low=max(0.05,CONF*0.4) new=DEFAULT_CONF
#   buffer=120 match_high=0.8 match_low=0.5 match_unconf=0.7
# match_thresh_* は cost=1-IoU に対する受理 IoU 下限。0.8 は IoU>=0.8 を要求し、
# 高速移動する badminton 選手では再関連付けに失敗 → track_id 乱立の主因だった。
# これを緩めて IoU>=BT_MATCH_HIGH で再関連付けする。
# churn-tuning 2026-05-29 winning config "F" を新既定値に採用。
# match33 30s/4players: unique track_id 363 -> 47 (per-court 48/52/58/55 -> 2/5/5/5)。
# 旧既定値 (env で復元可): TRACK_HIGH=DEFAULT_CONF(0.25) NEW_TRACK=DEFAULT_CONF(0.25)
#                          MATCH_HIGH=0.8 TRACK_BUFFER=120
# 主因は MATCH_HIGH=0.8 (IoU>=0.8 を要求) で高速移動選手の再関連付けが失敗し
# track_id が乱立していたこと。MATCH_HIGH=0.3 へ緩和が最大効果。
BT_TRACK_HIGH = float(os.environ.get("SS_PERSON_BT_TRACK_HIGH", "0.20"))
BT_TRACK_LOW = float(os.environ.get("SS_PERSON_BT_TRACK_LOW", str(max(0.05, DEFAULT_CONF * 0.4))))
BT_NEW_TRACK = float(os.environ.get("SS_PERSON_BT_NEW_TRACK", "0.30"))
BT_TRACK_BUFFER = int(os.environ.get("SS_PERSON_BT_TRACK_BUFFER", "150"))
BT_MATCH_HIGH = float(os.environ.get("SS_PERSON_BT_MATCH_HIGH", "0.3"))
BT_MATCH_LOW = float(os.environ.get("SS_PERSON_BT_MATCH_LOW", "0.5"))
BT_MATCH_UNCONF = float(os.environ.get("SS_PERSON_BT_MATCH_UNCONF", "0.7"))
PERSON_CLASS_ID = 0  # COCO の person

# ── Native fast path (person_tracker_native_ext .pyd) ────────────────
# OPT-IN: SS_PERSON_USE_NATIVE=1 で C++/ONNXRuntime+TensorRT の batch detector を
# 使う。既定 OFF → 既存 Python ONNX 経路で完全に同一振る舞い (ゼロ behavior change)。
# .pyd / DLL が無い dev/CI 機ではどんな理由で失敗しても Python 経路へ fallback。
PERSON_USE_NATIVE = os.environ.get("SS_PERSON_USE_NATIVE", "0") != "0"
# DLL 探索 dir は env で上書き可 (prod path を hardcode しない)。
# test_native_import.py と同じ load 順序 (ORT → CUDA → TRT → build/Release)。
_NATIVE_ORT_LIB = os.environ.get(
    "SS_NATIVE_ORT_LIB", r"C:/onnxruntime/onnxruntime-win-x64-gpu-1.24.4/lib"
)
_NATIVE_CUDA_BIN = os.environ.get(
    "SS_NATIVE_CUDA_BIN",
    r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8/bin",
)
_NATIVE_TRT_BIN = os.environ.get(
    "SS_NATIVE_TRT_BIN", r"C:/TensorRT/TensorRT-10.16.1.11/bin"
)
# build/Release dir (.pyd 本体)。既定はこの module からの相対。
_NATIVE_PYD_DIR = os.environ.get(
    "SS_NATIVE_PYD_DIR",
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "person_tracker_native", "build", "Release",
    ),
)
# 1-class fine-tuned model path env (SS_PT_MODEL 優先)。
_NATIVE_MODEL_ENV = "SS_PT_MODEL"
# 入力解像度 / conf。native constructor 引数。
_NATIVE_IN_H = int(os.environ.get("SS_NATIVE_IN_H", "384"))
_NATIVE_IN_W = int(os.environ.get("SS_NATIVE_IN_W", "640"))

# module 級 cache: 一度だけ import を試みる。失敗は None で記憶し再試行しない。
_native_ext = None  # type: ignore
_native_import_tried = False


def _load_native_ext():
    """person_tracker_native_ext を遅延 import。DLL 探索 dir を test_native_import.py
    と同じ順序で追加してから import する。失敗時は None を返し warning を出す。"""
    global _native_ext, _native_import_tried
    if _native_import_tried:
        return _native_ext
    _native_import_tried = True
    try:
        try:
            import torch  # noqa: F401
        except Exception:
            pass
        for d in (_NATIVE_ORT_LIB, _NATIVE_CUDA_BIN, _NATIVE_TRT_BIN, _NATIVE_PYD_DIR):
            try:
                if d and os.path.isdir(d):
                    os.add_dll_directory(d)
            except Exception as exc:
                logger.debug("native: add_dll_directory(%s) skip: %s", d, exc)
        import sys as _sys
        if _NATIVE_PYD_DIR and _NATIVE_PYD_DIR not in _sys.path:
            _sys.path.insert(0, _NATIVE_PYD_DIR)
        import person_tracker_native_ext as ext  # type: ignore
        _native_ext = ext
        logger.info("PersonTracker native ext loaded: %s", getattr(ext, "__file__", "?"))
    except Exception as exc:
        logger.warning(
            "PersonTracker native ext unavailable (%s) — Python 経路へ fallback", exc
        )
        _native_ext = None
    return _native_ext


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
        use_reid: Optional[bool] = None,
        reid_embedder=None,  # type: ignore[no-untyped-def]
        reid_threshold: Optional[float] = None,
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

        # ── Phase 4 ReID Recovery 用 state ───────────────────────────────
        # use_reid 指定なし → env 既定値。reid_embedder 指定なら lazy load しない。
        self._reid_enabled: bool = REID_ENABLED_DEFAULT if use_reid is None else bool(use_reid)
        self._reid_threshold: float = (
            REID_THRESH_DEFAULT if reid_threshold is None else float(reid_threshold)
        )
        self._reid_embedder = reid_embedder  # None なら _ensure_components で lazy
        self._reid_embedder_init_tried = False
        # court_id ごとの最近 N frame の embedding (deque[np.ndarray])
        self._reid_history: dict[int, deque] = {}
        # track_id → court_id (前 frame までに確定したもの)。lost 検知に使う。
        self._track_to_court: dict[int, int] = {}
        # 「失われた court_id」(直前まで埋まってたが今 frame で見えない)
        # court_id → (last_seen_frame_idx, embedding_avg) を保持
        self._lost_court: dict[int, tuple[int, np.ndarray]] = {}
        # ReID 復帰で court_id を引き継いだ際の (track_id → recovered court_id) 上書き
        self._reid_overrides: dict[int, int] = {}
        # 観客/ref 候補 (grace 越え): track_id を drop 対象に
        self._dropped_track_ids: set[int] = set()

        # ── Swap Guard 用 state ──────────────────────────────────────────
        self._swap_guard_enabled: bool = SWAP_GUARD_ENABLED_DEFAULT
        self._swap_guard_margin: float = SWAP_GUARD_MARGIN
        # 出力 track_id ごとの直近 centroid 履歴 (deque[(cx, cy)])。
        # ここで言う「出力 track_id」は alias 適用後の安定 ID。
        self._swap_centroid_hist: dict[int, deque] = {}
        # ByteTrack raw track_id → 出力 track_id の alias map。
        # crossover を検知したら 2 つの raw id を相互に張り替える。
        self._swap_alias: dict[int, int] = {}

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
                track_high_thresh=BT_TRACK_HIGH,
                track_low_thresh=BT_TRACK_LOW,
                new_track_thresh=BT_NEW_TRACK,
                track_buffer=BT_TRACK_BUFFER,
                match_thresh_high=BT_MATCH_HIGH,
                match_thresh_low=BT_MATCH_LOW,
                match_thresh_unconfirmed=BT_MATCH_UNCONF,
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

        # Swap Guard: ByteTrack 付与後・court 割当前に motion-only で取り違え補正
        if self._swap_guard_enabled:
            raw_tracks = self._apply_swap_guard(raw_tracks)

        # Tier 2: court 象限割り当て
        if self._adjudicator is None:
            # passthrough、court_id はすべて None なので player_label も None
            return raw_tracks
        adjudicated = adjudicate_court(raw_tracks, self._adjudicator, self.match_type)

        # Tier 3 (Phase 4): ReID Recovery — orphan track の court_id を復帰
        if self._reid_enabled:
            adjudicated = self._reid_recover(frame, adjudicated, frame_idx)

        # Phase 3 簡易: side swap 反映 + court_id → player_label マップ
        return [self._attach_player_label(t) for t in adjudicated]

    # ─── Phase 3.6: batch 推論 (offline 用) ───────────────────────────────
    # 検出を batch でまとめて投げる → ONNX/TRT が真の throughput を発揮 (1000+ fps)。
    # ByteTracker は state machine なので frame ごとに直列処理 (CPU 軽量)。

    def _ensure_batch_detector(self) -> None:
        """batch ONNX session を遅延 init。CI 軽量 venv では skip 可能。"""
        if getattr(self, "_batch_sess", None) is not None:
            return
        try:
            # TRT lib path を ORT に見せる (bench script と同じパターン)
            try:
                import torch  # noqa: F401
                os.add_dll_directory(
                    os.path.join(os.path.dirname(__import__("torch").__file__), "lib")
                )
            except Exception:
                pass
            try:
                import tensorrt_libs  # noqa: F401
                os.add_dll_directory(os.path.dirname(tensorrt_libs.__file__))
            except Exception:
                pass
            import onnxruntime as ort  # type: ignore
        except Exception as exc:
            logger.warning("batch detector: ORT import 失敗 — update_batch 無効: %s", exc)
            self._batch_sess = None
            return

        # モデル path の解決: env 経由 or デフォルト相対path → repo root から
        model_path = os.environ.get(
            "SS_PERSON_TRACKER_BATCH_MODEL", DEFAULT_BATCH_MODEL_PATH
        )
        if not os.path.isabs(model_path):
            # repo root を逆引き: backend/ の親が repo root
            from pathlib import Path as _P
            here = _P(__file__).resolve()
            # cv/person_tracker.py → cv → backend → shuttlescope (= repo root にあたる)
            for parent in here.parents:
                cand = parent / model_path
                if cand.exists():
                    model_path = str(cand)
                    break
            else:
                logger.warning("batch detector: model not found at %s", model_path)
                self._batch_sess = None
                return

        # providers: TRT FP16 → CUDA → CPU
        providers: list = []
        avail = set(ort.get_available_providers())
        if "TensorrtExecutionProvider" in avail:
            trt_cache = os.path.join(
                os.path.dirname(model_path), "trt_cache_person_batch"
            )
            os.makedirs(trt_cache, exist_ok=True)
            providers.append(("TensorrtExecutionProvider", {
                "device_id": 0,
                "trt_engine_cache_enable": True,
                "trt_engine_cache_path": trt_cache,
                "trt_fp16_enable": True,
            }))
        if "CUDAExecutionProvider" in avail:
            providers.append(("CUDAExecutionProvider", {"device_id": 0}))
        providers.append("CPUExecutionProvider")

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        try:
            self._batch_sess = ort.InferenceSession(model_path, sess_opts, providers=providers)
            self._batch_input_name = self._batch_sess.get_inputs()[0].name
            self._batch_input_dtype = (
                np.float16
                if "float16" in self._batch_sess.get_inputs()[0].type
                else np.float32
            )
            logger.info(
                "PersonTracker batch detector loaded: %s providers=%s",
                model_path, self._batch_sess.get_providers()[0],
            )
        except Exception as exc:
            logger.error("batch detector: session create failed: %s", exc)
            self._batch_sess = None

    def _detect_batch(self, frames: list[np.ndarray]) -> list[list[tuple[float, float, float, float, float]]]:
        """N frame をまとめて推論し、frame ごとの [(x1,y1,x2,y2,conf), ...] を返す。
        座標は **入力 frame の pixel** (1920×1080 想定)。
        """
        import cv2  # type: ignore
        self._ensure_batch_detector()
        if self._batch_sess is None or not frames:
            return [[] for _ in frames]

        # 全 frame を 384×640 にリサイズ → stack
        H_in, W_in = 384, 640
        src_shapes = [f.shape[:2] for f in frames]
        # 高速 path: torch GPU で resize + normalize → ORT IObinding で CUDA buffer
        # 直接渡し (GPU↔CPU copy を完全排除)
        use_gpu_preproc = os.environ.get("SS_PERSON_TRACKER_GPU_PREPROC", "1") != "0"
        out = None
        if use_gpu_preproc:
            try:
                import torch  # type: ignore
                if torch.cuda.is_available() and len({s for s in src_shapes}) == 1:
                    np_stack = np.stack(frames, axis=0)
                    t = torch.as_tensor(np_stack, device="cuda")
                    t = t.permute(0, 3, 1, 2).contiguous()
                    t = t[:, [2, 1, 0], :, :]
                    t = torch.nn.functional.interpolate(
                        t.float() / 255.0, size=(H_in, W_in), mode="bilinear", align_corners=False,
                    )
                    if self._batch_input_dtype == np.float16:
                        t = t.half().contiguous()
                    else:
                        t = t.contiguous()
                    # ORT IObinding: CUDA buffer を直接 ORT に渡す (copy なし)
                    io = self._batch_sess.io_binding()
                    io.bind_input(
                        name=self._batch_input_name,
                        device_type="cuda",
                        device_id=0,
                        element_type=self._batch_input_dtype,
                        shape=tuple(t.shape),
                        buffer_ptr=t.data_ptr(),
                    )
                    out_name = self._batch_sess.get_outputs()[0].name
                    io.bind_output(name=out_name, device_type="cuda", device_id=0)
                    self._batch_sess.run_with_iobinding(io)
                    out = io.get_outputs()[0].numpy()  # 出力だけ CPU に (小さい)
                    # keep tensor alive until run done
                    del t
            except Exception as exc:
                logger.debug("GPU preproc / IObinding fallback to CPU: %s", exc)
                out = None
        if out is None:
            # CPU fallback path (cv2.resize loop)
            batch_arr = np.empty((len(frames), 3, H_in, W_in), dtype=self._batch_input_dtype)
            for i, f in enumerate(frames):
                r = cv2.resize(f, (W_in, H_in))
                r = r[:, :, ::-1].transpose(2, 0, 1).astype(self._batch_input_dtype) / 255.0
                batch_arr[i] = r
            out = self._batch_sess.run(None, {self._batch_input_name: batch_arr})[0]
        # out: (B, 5, A) for 1-class 384×640
        if out.ndim != 3 or out.shape[1] not in (5, 84):
            logger.warning("batch detector: unexpected output shape %s", out.shape)
            return [[] for _ in frames]
        n_ch = out.shape[1]
        per_frame: list[list[tuple[float, float, float, float, float]]] = []
        # 各 frame について parse (numpy vectorize 版、Python for-row ループを排除)
        conf_min = float(os.environ.get("SS_PERSON_TRACKER_CONF", "0.25"))
        # out: (B, 5, A) — を (B, A, 5) に転置
        out_t = out.transpose(0, 2, 1).astype(np.float32, copy=False)
        # 列定義: 0=cx, 1=cy, 2=bw, 3=bh, 4=conf (or class0)
        cxs = out_t[:, :, 0]
        cys = out_t[:, :, 1]
        bws = out_t[:, :, 2]
        bhs = out_t[:, :, 3]
        confs = out_t[:, :, 4]
        # x1/y1/x2/y2 を input scale (W_in, H_in) で先に計算
        x1_in = cxs - bws / 2
        y1_in = cys - bhs / 2
        x2_in = cxs + bws / 2
        y2_in = cys + bhs / 2

        for i in range(out_t.shape[0]):
            mask = confs[i] >= conf_min
            if not np.any(mask):
                per_frame.append([])
                continue
            src_h, src_w = src_shapes[i]
            sx, sy = src_w / W_in, src_h / H_in
            x1s = np.clip(x1_in[i][mask] * sx, 0.0, float(src_w))
            y1s = np.clip(y1_in[i][mask] * sy, 0.0, float(src_h))
            x2s = np.clip(x2_in[i][mask] * sx, 0.0, float(src_w))
            y2s = np.clip(y2_in[i][mask] * sy, 0.0, float(src_h))
            cs = confs[i][mask]
            valid = (x2s > x1s) & (y2s > y1s)
            dets = list(zip(
                x1s[valid].tolist(),
                y1s[valid].tolist(),
                x2s[valid].tolist(),
                y2s[valid].tolist(),
                cs[valid].tolist(),
            ))
            per_frame.append(dets)
        return per_frame

    def update_batch(
        self,
        frames: list[np.ndarray],
        frame_idxs: list[int],
    ) -> list[list[TrackedPerson]]:
        """N frame batch update の公開 entrypoint。

        SS_PERSON_USE_NATIVE=1 のときだけ C++ native fast path
        (update_batch_native) を試す。native が使えなければ自動で Python 経路
        (_update_batch_python) へ fallback する。既定 (env unset) では native を
        一切触らず Python 経路のみ — ゼロ behavior change。
        """
        if PERSON_USE_NATIVE:
            return self.update_batch_native(frames, frame_idxs)
        return self._update_batch_python(frames, frame_idxs)

    def _update_batch_python(
        self,
        frames: list[np.ndarray],
        frame_idxs: list[int],
    ) -> list[list[TrackedPerson]]:
        """N frame をまとめて検出 → frame ごとに ByteTracker / court / label 順に処理。

        Offline 用。realtime には latency が batch サイズに比例して増えるため不向き。
        ByteTracker は state machine なので順序保持必須。
        """
        assert len(frames) == len(frame_idxs), "frames と frame_idxs の長さが不一致"
        self._ensure_components()
        from backend.cv.byte_tracker import Detection  # type: ignore

        all_dets = self._detect_batch(frames)

        results: list[list[TrackedPerson]] = []
        for i, dets in enumerate(all_dets):
            bt_dets = [
                Detection(bbox=(d[0], d[1], d[2], d[3]), score=d[4]) for d in dets
            ]
            stracks = self._tracker.update(bt_dets, frame_id=frame_idxs[i])
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
            # Swap Guard: online と同じく court 割当前に補正 (batch でも一貫適用)
            if self._swap_guard_enabled:
                raw_tracks = self._apply_swap_guard(raw_tracks)
            if self._adjudicator is None:
                results.append(raw_tracks)
                continue
            adjudicated = adjudicate_court(raw_tracks, self._adjudicator, self.match_type)
            results.append([self._attach_player_label(t) for t in adjudicated])
        return results

    # ─── Native (C++) batch path ───────────────────────────────────────
    def _ensure_native_detector(self) -> None:
        """C++ pybind11 ext (person_tracker_native_ext.BatchDetector) を init。
        OPT-IN: PERSON_USE_NATIVE が False なら何もしない (Python 経路維持)。
        .pyd import / session 作成がどんな理由で失敗しても self._native_detector
        は None のままにし、呼び出し側で Python 経路へ fallback させる。"""
        if getattr(self, "_native_detector", "unset") != "unset":
            return  # 既に init 済 (None も含む)。再試行しない。
        if not PERSON_USE_NATIVE:
            self._native_detector = None
            return
        ext = _load_native_ext()
        if ext is None:
            self._native_detector = None
            return
        # model path: SS_PT_MODEL > batch model env > default。相対なら repo root 解決。
        model_path = os.environ.get(
            _NATIVE_MODEL_ENV,
            os.environ.get("SS_PERSON_TRACKER_BATCH_MODEL", DEFAULT_BATCH_MODEL_PATH),
        )
        if not os.path.isabs(model_path):
            from pathlib import Path as _P
            here = _P(__file__).resolve()
            for parent in here.parents:
                cand = parent / model_path
                if cand.exists():
                    model_path = str(cand)
                    break
            else:
                logger.warning("native detector: model not found at %s — fallback", model_path)
                self._native_detector = None
                return
        try:
            conf = float(os.environ.get("SS_PERSON_TRACKER_CONF", "0.25"))
            use_trt = os.environ.get("SS_PT_NATIVE_NO_TRT", "0") == "0"
            # 実 .pyd の binding は positional:
            #   BatchDetector(model_path, batch, use_trt, use_cuda, device_id,
            #                 in_h, in_w, conf_thresh)
            self._native_detector = ext.BatchDetector(
                model_path, 32, use_trt, True, 0,
                _NATIVE_IN_H, _NATIVE_IN_W, conf,
            )
            logger.info("PersonTracker native BatchDetector ready: %s (trt=%s)",
                        model_path, use_trt)
        except Exception as exc:
            logger.warning("native detector: init failed (%s) — Python 経路へ fallback", exc)
            self._native_detector = None

    def update_batch_native(
        self,
        frames: list[np.ndarray],
        frame_idxs: list[int],
    ) -> list[list[TrackedPerson]]:
        """C++ pybind11 ext 経由の batch update (native fast path)。
        ext 未配備 / SS_PERSON_USE_NATIVE 未設定の場合は Python core に fallback。

        ext 側は preprocess (CUDA) + detector (ORT) + ByteTracker を一気通貫で
        実行する。Python 側では court adjudication と player_label 付与のみ行う。
        """
        assert len(frames) == len(frame_idxs), "frames と frame_idxs の長さが不一致"
        self._ensure_native_detector()
        if getattr(self, "_native_detector", None) is None:
            # native 不在 / init 失敗 → Python core へ fallback (dispatcher は呼ばない)
            return self._update_batch_python(frames, frame_idxs)
        if not frames:
            return []

        # 全フレーム同一形状を仮定 (1080p)。違えば fallback。
        shapes = {f.shape for f in frames}
        if len(shapes) != 1 or frames[0].ndim != 3 or frames[0].shape[2] != 3:
            logger.debug("native batch: frame shape mismatch, fallback to python")
            return self._update_batch_python(frames, frame_idxs)

        # numpy (B, H, W, 3) uint8 にスタック (contiguous)
        np_stack = np.ascontiguousarray(np.stack(frames, axis=0), dtype=np.uint8)

        try:
            raw_results = self._native_detector.detect_and_track(np_stack, frame_idxs)
        except Exception as exc:
            logger.warning("native batch: detect_and_track failed (%s) — fallback", exc)
            return self._update_batch_python(frames, frame_idxs)

        # court adjudicator のためにのみ Python 経路を踏む
        results: list[list[TrackedPerson]] = []
        for raw in raw_results:
            raw_tracks: list[TrackedPerson] = []
            for tup in raw:
                # (x1, y1, x2, y2, score, track_id)
                x1, y1, x2, y2, score, tid = tup
                raw_tracks.append(
                    TrackedPerson(
                        bbox=(float(x1), float(y1), float(x2), float(y2)),
                        track_id=int(tid),
                        court_id=None,
                        player_uuid=None,
                        confidence=float(score),
                    )
                )
            if self._adjudicator is None:
                results.append(raw_tracks)
                continue
            adjudicated = adjudicate_court(raw_tracks, self._adjudicator, self.match_type)
            results.append([self._attach_player_label(t) for t in adjudicated])
        return results
    # ─── Phase 4 ReID Recovery ───────────────────────────────────────────
    def _ensure_reid_embedder(self):
        """ReID embedder を遅延 init。失敗時は _reid_enabled = False に降格。"""
        if self._reid_embedder is not None or self._reid_embedder_init_tried:
            return
        self._reid_embedder_init_tried = True
        try:
            from backend.cv.reid_embedder import get_default_embedder  # type: ignore
            emb = get_default_embedder()
            if emb is None or not emb.available:
                logger.info(
                    "ReID: embedder unavailable (model not deployed?) — Tier 3 disabled"
                )
                self._reid_enabled = False
                return
            self._reid_embedder = emb
            logger.info("ReID: Tier 3 recovery enabled (thresh=%.2f, history=%d, grace=%d frames)",
                        self._reid_threshold, REID_HISTORY_LEN, REID_LOST_GRACE_FRAMES)
        except Exception as exc:
            logger.warning("ReID embedder init failed: %s — Tier 3 disabled", exc)
            self._reid_enabled = False

    @staticmethod
    def _crop_bbox(frame: np.ndarray, bbox: tuple[float, float, float, float]) -> Optional[np.ndarray]:
        """frame から bbox crop を返す。退化サイズは None。"""
        h, w = frame.shape[:2]
        x1 = max(0, int(bbox[0]))
        y1 = max(0, int(bbox[1]))
        x2 = min(w, int(bbox[2]))
        y2 = min(h, int(bbox[3]))
        if x2 - x1 < 8 or y2 - y1 < 16:
            return None
        return frame[y1:y2, x1:x2]

    def _court_history_mean(self, court_id: int) -> Optional[np.ndarray]:
        """court_id の history 内 embedding を平均 → L2 正規化したベクトル。空なら None。"""
        h = self._reid_history.get(court_id)
        if not h:
            return None
        arr = np.stack(list(h), axis=0)  # (N, 512)
        mean = arr.mean(axis=0)
        n = float(np.linalg.norm(mean))
        if n < 1e-9:
            return None
        return (mean / n).astype(np.float32)

    def _reid_recover(
        self,
        frame: np.ndarray,
        tracks: list[TrackedPerson],
        frame_idx: int,
    ) -> list[TrackedPerson]:
        """Tier 3: court_id None の track に対して、過去 court embedding と
        cosine sim ≥ threshold で match すれば court_id を復帰する。

        副作用: 確定 track の embedding を court_id ごとの history に追記、
                lost court_id の avg を _lost_court に保存、grace 越えで drop。
        """
        self._ensure_reid_embedder()
        if not self._reid_enabled or self._reid_embedder is None:
            return tracks

        from backend.cv.reid_embedder import cosine_similarity_matrix  # type: ignore

        # 1) 確定 track (court_id 持ち) と orphan (court_id=None) を分離
        confirmed_idx: list[int] = []
        orphan_idx: list[int] = []
        for i, t in enumerate(tracks):
            if t.court_id is not None:
                confirmed_idx.append(i)
            else:
                orphan_idx.append(i)

        # 2) batch crop → embed (確定 + orphan まとめて 1 回の推論)
        all_idx = confirmed_idx + orphan_idx
        crops: list[np.ndarray] = []
        crop_valid: list[bool] = []
        for i in all_idx:
            c = self._crop_bbox(frame, tracks[i].bbox)
            if c is None:
                crops.append(np.zeros((32, 16, 3), dtype=np.uint8))
                crop_valid.append(False)
            else:
                crops.append(c)
                crop_valid.append(True)

        feats = self._reid_embedder.embed_batch(crops) if crops else np.zeros((0, 512), dtype=np.float32)

        # 3) 確定 track の embedding を history に append
        n_conf = len(confirmed_idx)
        for k, i in enumerate(confirmed_idx):
            if not crop_valid[k]:
                continue
            cid = tracks[i].court_id
            if cid is None:
                continue
            hist = self._reid_history.setdefault(cid, deque(maxlen=REID_HISTORY_LEN))
            hist.append(feats[k])
            # track→court マップ更新
            self._track_to_court[tracks[i].track_id] = cid

        # 4) 「今 frame に居ない court_id」 を lost に積む (history が空でない court が対象)
        present_courts = {tracks[i].court_id for i in confirmed_idx if tracks[i].court_id is not None}
        for cid in list(self._reid_history.keys()):
            if cid in present_courts:
                # 復帰した → lost から除外
                self._lost_court.pop(cid, None)
                continue
            # まだ lost に積んでない → 平均 embedding を保存
            if cid not in self._lost_court:
                mean = self._court_history_mean(cid)
                if mean is not None:
                    self._lost_court[cid] = (frame_idx, mean)

        # 5) orphan の各 track と lost_court avg を cosine sim → match
        recovered: dict[int, int] = {}  # orphan track index → court_id
        if orphan_idx and self._lost_court:
            lost_ids = list(self._lost_court.keys())
            gallery = np.stack([self._lost_court[c][1] for c in lost_ids], axis=0)  # (L, 512)
            orphan_feats = feats[n_conf:]
            valid_mask = np.array([crop_valid[n_conf + k] for k in range(len(orphan_idx))], dtype=bool)
            if valid_mask.any():
                sim = cosine_similarity_matrix(orphan_feats[valid_mask], gallery)  # (M, L)
                used_lost: set[int] = set()
                valid_orphan_local_idx = [k for k, v in enumerate(valid_mask) if v]
                # 貪欲: sim 降順でペア確定
                pairs = []
                for r_local in range(sim.shape[0]):
                    for c_local in range(sim.shape[1]):
                        pairs.append((sim[r_local, c_local], r_local, c_local))
                pairs.sort(reverse=True, key=lambda p: p[0])
                used_orphan_local: set[int] = set()
                for s, r_local, c_local in pairs:
                    if s < self._reid_threshold:
                        break
                    if r_local in used_orphan_local or c_local in used_lost:
                        continue
                    used_orphan_local.add(r_local)
                    used_lost.add(c_local)
                    orphan_local_idx = valid_orphan_local_idx[r_local]
                    track_idx = orphan_idx[orphan_local_idx]
                    cid = lost_ids[c_local]
                    recovered[track_idx] = cid
                    logger.debug(
                        "ReID recovery: track_id %d → court_id %d (sim=%.3f, frame=%d)",
                        tracks[track_idx].track_id, cid, s, frame_idx,
                    )

        # 6) grace 越えた lost を drop
        expired = [
            cid for cid, (last_f, _) in self._lost_court.items()
            if frame_idx - last_f > REID_LOST_GRACE_FRAMES
        ]
        for cid in expired:
            logger.info(
                "ReID: court_id %d の復帰 grace (%d frames) 超過 → drop",
                cid, REID_LOST_GRACE_FRAMES,
            )
            self._lost_court.pop(cid, None)
            self._reid_history.pop(cid, None)

        # 7) 復帰結果を tracks に反映
        if not recovered:
            return tracks
        out: list[TrackedPerson] = []
        for i, t in enumerate(tracks):
            if i in recovered:
                cid = recovered[i]
                # history にも今 frame の embedding を append (復帰直後の安定化)
                k = all_idx.index(i)
                if crop_valid[k]:
                    self._reid_history.setdefault(cid, deque(maxlen=REID_HISTORY_LEN)).append(feats[k])
                self._track_to_court[t.track_id] = cid
                out.append(TrackedPerson(
                    bbox=t.bbox,
                    track_id=t.track_id,
                    court_id=cid,
                    player_uuid=None,
                    confidence=t.confidence,
                    is_recovered=True,
                ))
            else:
                out.append(t)
        return out

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

    # ─── Swap Guard (motion-only, 同ユニフォーム teammate 取り違え防止) ────
    @staticmethod
    def _centroid(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @staticmethod
    def _predict_centroid(hist: "deque") -> Optional[tuple[float, float]]:
        """直近 centroid 履歴から等速 (constant-velocity) で次位置を予測。

        履歴 1 点 → その点をそのまま返す (速度不明)。
        2 点以上 → 直近 2 点の差分を速度として外挿。
        空 → None。
        """
        if not hist:
            return None
        pts = list(hist)
        if len(pts) == 1:
            return pts[-1]
        (px, py), (cx, cy) = pts[-2], pts[-1]
        return (cx + (cx - px), cy + (cy - py))

    def _apply_swap_guard(
        self, raw_tracks: list[TrackedPerson]
    ) -> list[TrackedPerson]:
        """ByteTrack 付与済みの track_id を motion-only で検証し、crossover で
        取り違えられた同サイド teammate ペアを alias で相互補正する。

        手順:
          1. alias map を適用して各 track の「出力 track_id」を決める。
          2. 出力 track_id ごとの予測 centroid (等速外挿) を計算。
          3. 近接ペアについて、現状割当 vs swap 後割当の予測誤差合計を比較。
             swap が margin 以上小さければ alias を張り替える (= 取り違え補正)。
          4. 補正後の track_id で centroid 履歴を更新。

        OFF 時は呼ばれない (= 既定挙動不変)。
        """
        if not raw_tracks:
            return raw_tracks

        def out_id(raw_id: int) -> int:
            return self._swap_alias.get(raw_id, raw_id)

        tracks = list(raw_tracks)
        cur_centroids: dict[int, tuple[float, float]] = {}
        for t in tracks:
            cur_centroids[out_id(t.track_id)] = self._centroid(t.bbox)

        # 各出力 ID の予測位置 (履歴ベース、今 frame の観測は使わない)
        preds: dict[int, Optional[tuple[float, float]]] = {
            oid: self._predict_centroid(self._swap_centroid_hist.get(oid))
            for oid in cur_centroids
        }

        oids = list(cur_centroids.keys())

        def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
            return float(np.hypot(a[0] - b[0], a[1] - b[1]))

        # 近接ペアの swap 判定
        for i in range(len(oids)):
            for j in range(i + 1, len(oids)):
                a, b = oids[i], oids[j]
                pa, pb = preds[a], preds[b]
                # 両者とも予測 (履歴 >=2) が無いと crossover 判定不能
                if pa is None or pb is None:
                    continue
                ca, cb = cur_centroids[a], cur_centroids[b]
                # 予測同士が十分近い = 経路交差の可能性があるペアのみ評価
                if dist(pa, pb) > SWAP_GUARD_MAX_PAIR_DIST:
                    continue
                # 現状割当の誤差: a の観測 ↔ a の予測、b ↔ b
                err_cur = dist(ca, pa) + dist(cb, pb)
                # swap 後: a の観測 ↔ b の予測、b ↔ a
                err_swap = dist(ca, pb) + dist(cb, pa)
                if err_swap < err_cur * (1.0 - self._swap_guard_margin):
                    self._swap_two(a, b)
                    logger.debug(
                        "swap guard: out_id %d <-> %d 補正 "
                        "(err_cur=%.1f err_swap=%.1f)",
                        a, b, err_cur, err_swap,
                    )

        # alias 再適用 (張り替え反映) して最終 track を構築 + 履歴更新
        out: list[TrackedPerson] = []
        for t in tracks:
            oid = out_id(t.track_id)
            c = self._centroid(t.bbox)
            hist = self._swap_centroid_hist.setdefault(
                oid, deque(maxlen=SWAP_GUARD_HISTORY)
            )
            hist.append(c)
            if oid == t.track_id:
                out.append(t)
            else:
                out.append(TrackedPerson(
                    bbox=t.bbox,
                    track_id=oid,
                    court_id=t.court_id,
                    player_uuid=t.player_uuid,
                    confidence=t.confidence,
                    is_recovered=t.is_recovered,
                    player_label=t.player_label,
                ))
        return out

    def _swap_two(self, oid_a: int, oid_b: int) -> None:
        """出力 ID a と b を相互に張り替える。

        alias map は raw_id → out_id。a / b に解決される raw_id 群を入れ替え、
        centroid 履歴も同時に swap して予測の連続性を保つ。
        """
        raws_to_a = [r for r, o in self._swap_alias.items() if o == oid_a]
        raws_to_b = [r for r, o in self._swap_alias.items() if o == oid_b]
        # 恒等 (alias 未登録で raw==out のまま) も拾う
        if self._swap_alias.get(oid_a, oid_a) == oid_a:
            raws_to_a.append(oid_a)
        if self._swap_alias.get(oid_b, oid_b) == oid_b:
            raws_to_b.append(oid_b)
        for r in raws_to_a:
            self._swap_alias[r] = oid_b
        for r in raws_to_b:
            self._swap_alias[r] = oid_a
        # 履歴を入れ替え
        ha = self._swap_centroid_hist.get(oid_a)
        hb = self._swap_centroid_hist.get(oid_b)
        if ha is not None:
            self._swap_centroid_hist[oid_b] = ha
        else:
            self._swap_centroid_hist.pop(oid_b, None)
        if hb is not None:
            self._swap_centroid_hist[oid_a] = hb
        else:
            self._swap_centroid_hist.pop(oid_a, None)

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
        # Phase A3: native ext 内の ByteTracker も reset
        native = getattr(self, "_native_detector", None)
        if native is not None:
            try:
                native.reset_tracker()
            except Exception as exc:
                logger.warning("reset_for_new_set: native reset failed: %s", exc)
        # Phase 4: ReID 履歴も set 境界でクリア (player 同一性は維持されるが side swap で
        # court_id ↔ player の対応が反転するため、古い embedding を court_id key で
        # 引き継ぐと誤マッチを生む)
        self._reid_history.clear()
        self._track_to_court.clear()
        self._lost_court.clear()
        self._reid_overrides.clear()
        self._dropped_track_ids.clear()
        # Swap Guard 履歴/alias も set 境界でクリア (人物配置が入れ替わるため)
        self._swap_centroid_hist.clear()
        self._swap_alias.clear()
        logger.info(
            "PersonTracker reset for set %s (side_swapped=%s)",
            set_idx, self._side_swapped,
        )

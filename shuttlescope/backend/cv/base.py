"""CV 推論の共通型定義 / Protocol。

INFRA Phase A:
    - トップレベルで torch / mediapipe / numpy 等を import しない。
    - 純 Python の dataclass と typing.Protocol のみで定義する。
    - 実装（CUDA / CPU / Mock）はこの Protocol に準拠して差し替え可能にする。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol, runtime_checkable


@dataclass
class ShuttleSample:
    """シャトル (羽根) 1 フレーム分の推定位置サンプル。

    座標は画像座標系 (px) を想定。confidence は 0.0〜1.0。
    """

    frame: int
    ts_sec: float
    x: float
    y: float
    confidence: float


@dataclass
class PoseSample:
    """選手 1 人・1 フレーム分の姿勢サンプル。

    side: "a" / "b" のどちらの選手か。
    landmarks: 33 点 (MediaPipe Pose) を想定した list。各点は dict or tuple を許容する。
    Phase A では中身を検証せず、pass-through。
    """

    frame: int
    ts_sec: float
    side: str
    landmarks: list = field(default_factory=list)


@runtime_checkable
class TrackNetInferencer(Protocol):
    """シャトル軌跡推論器の共通インタフェース。"""

    def run(self, video_path: str) -> List[ShuttleSample]:  # pragma: no cover - protocol
        ...


@runtime_checkable
class PoseInferencer(Protocol):
    """姿勢推論器の共通インタフェース。"""

    def run(self, video_path: str) -> List[PoseSample]:  # pragma: no cover - protocol
        ...

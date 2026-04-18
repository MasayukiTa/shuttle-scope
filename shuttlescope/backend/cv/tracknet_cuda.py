"""TrackNet の CUDA 実装。

Phase A (現状):
    - 本物の TrackNet 学習済み重みは同梱していないため、CPU 実装と同じ
      classical CV パイプラインを torch tensor / cv2.cuda で加速する形で提供する。
    - 5060 Ti 到着後に、下記「# TODO(5060Ti): 本物の TrackNet 重みロード」の位置で
      torch モデル (例: TrackNetV2) をロードしてフレーム推論に差し替える想定。

import 方針:
    - torch は必ず __init__ / run 内で関数スコープ import する。
    - torch 未インストール時はコンストラクタで ImportError を raise し、
      factory 側で CPU / Mock にフォールバックさせる。
    - cv2.cuda が使えない環境では CPU 版の CpuTrackNet に委譲する。
"""
from __future__ import annotations

import logging
from typing import List

from backend.cv.base import ShuttleSample, TrackNetInferencer

logger = logging.getLogger(__name__)


class CudaTrackNet(TrackNetInferencer):
    """CUDA (PyTorch / cv2.cuda) 経由の TrackNet 推論器。"""

    def __init__(self, device_index: int = 0) -> None:
        # 関数スコープで torch を遅延 import。未インストール時は ImportError を投げる。
        try:
            import torch  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "torch が未インストールです。scripts/setup_gpu.ps1 を参照してください。"
            ) from exc

        import torch

        if not torch.cuda.is_available():
            # CUDA ランタイムが無ければ factory が CPU にフォールバックできるよう明示。
            raise RuntimeError("CUDA が利用できません。GPU ドライバを確認してください。")

        self._device_index = int(device_index)
        self._device = torch.device(f"cuda:{self._device_index}")

        # TODO(5060Ti): 本物の TrackNet 重みロード
        # -------------------------------------------------------------
        # ここで TrackNetV2 等のアーキテクチャを構築し、state_dict を
        # ロードして self._model に保持する。例:
        #   self._model = TrackNetV2().to(self._device).eval()
        #   sd = torch.load("models/tracknet_v2.pt", map_location=self._device)
        #   self._model.load_state_dict(sd)
        # Phase A ではモデル重みを同梱しないため None のままとし、
        # run() では classical CV (cv2.cuda 加速あり) にフォールバックする。
        # -------------------------------------------------------------
        self._model = None

        # cv2.cuda が使えるかを判定。モデル重みもなく cv2.cuda もなければ
        # factory が CPU/OpenVINO にフォールバックできるよう RuntimeError を投げる。
        self._cv_cuda_available = self._probe_cv_cuda()
        if not self._cv_cuda_available and self._model is None:
            raise RuntimeError(
                "cv2.cuda が利用不可かつ TrackNet モデル重みが未ロードです。"
                " opencv-python-cuda または TrackNet 重みファイルが必要です。"
            )

    # ------------------------------------------------------------------
    def run(self, video_path: str) -> List[ShuttleSample]:
        """動画からシャトル軌跡を推定。

        現状は classical CV を CPU 実装に委譲する (cv2.cuda で加速可能な場合は
        本来 GPU 前処理を挟むが、Phase A では実装の重複を避けて CpuTrackNet を
        そのまま呼び出す)。5060 Ti 到着後に self._model != None のパスで差し替える。
        """
        # self._model に重みがロードされていれば torch 推論、未ロードなら CPU 実装に委譲。
        # 5060 Ti 受領後は __init__ 側で self._model に state_dict をロードすることで
        # この分岐が自動的に GPU 推論経路に切り替わる。
        if self._model is not None:
            return self._run_torch(video_path)

        from backend.cv.tracknet_cpu import CpuTrackNet

        return CpuTrackNet().run(video_path)

    def _run_torch(self, video_path: str) -> List[ShuttleSample]:
        """self._model がロードされているときの torch 推論パス。

        Phase A では self._model が常に None のためここには到達しないが、
        将来重みをロードしたときに classical CV と同じ `ShuttleSample` 列を
        返せるように最小構成のフレームループを用意しておく。
        """
        import cv2  # ローカル import (モジュールトップで cv2 未ロードの環境向け)
        import numpy as np
        import torch

        samples: List[ShuttleSample] = []
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_idx = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                tensor = (
                    torch.from_numpy(np.ascontiguousarray(rgb))
                    .permute(2, 0, 1)
                    .unsqueeze(0)
                    .float()
                    .to(self._device)
                    / 255.0
                )
                with torch.no_grad():
                    heatmap = self._model(tensor)
                # heatmap -> 座標 (argmax)。モデル出力形状に応じて実装側で調整。
                flat = heatmap.view(heatmap.shape[0], -1)
                idx = int(flat.argmax(dim=1).item())
                h, w = heatmap.shape[-2], heatmap.shape[-1]
                y, x = divmod(idx, w)
                conf = float(flat.max().item())
                samples.append(
                    ShuttleSample(
                        frame=frame_idx,
                        ts_sec=frame_idx / fps,
                        x=float(x) / w,
                        y=float(y) / h,
                        confidence=conf,
                    )
                )
                frame_idx += 1
        finally:
            cap.release()
        return samples

    # ------------------------------------------------------------------
    @staticmethod
    def _probe_cv_cuda() -> bool:
        """cv2.cuda が利用可能かを安全に判定する。"""
        try:
            import cv2  # noqa: F401

            # cv2.cuda は OpenCV のビルドオプションに依存するため属性チェック。
            cuda_mod = getattr(cv2, "cuda", None)
            if cuda_mod is None:
                return False
            count_fn = getattr(cuda_mod, "getCudaEnabledDeviceCount", None)
            if count_fn is None:
                return False
            return int(count_fn()) > 0
        except Exception:  # pragma: no cover - 環境依存
            return False

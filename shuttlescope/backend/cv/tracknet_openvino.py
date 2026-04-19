"""TrackNet の OpenVINO バックエンドラッパー。

`tracknet/inference.py` の TrackNetInference を `TrackNetInferencer` Protocol に
適合させる薄いラッパー。CUDA 未使用環境（K10 含む）で OpenVINO iGPU / CPU 推論を
提供する。

優先順位（factory.py より呼ばれる）:
    CudaTrackNet (torch) → OpenVINOTrackNet (本クラス) → CpuTrackNet

メモリ設計:
    `tracknet/inference.py` の predict_frames() は全フレームを一度に受け取る API
    だが、長尺動画（30分 ×30fps = 54,000フレーム）では全フレームをメモリに
    持つと数百 GB になる。
    そのため CHUNK_SIZE フレームずつ処理し、3フレームスタック境界を
    FRAME_STACK-1 フレームのオーバーラップで連続させる。
"""
from __future__ import annotations

import logging
from typing import List

import numpy as np

from backend.cv.base import ShuttleSample, TrackNetInferencer

logger = logging.getLogger(__name__)

# 1回に処理するフレーム数（VRAM / RAM に応じて調整可能）
_CHUNK_SIZE = 300
# TrackNet の入力スタック幅（境界の連続性を保つオーバーラップ量）
_FRAME_STACK = 3
_OVERLAP = _FRAME_STACK - 1


class OpenVINOTrackNet(TrackNetInferencer):
    """OpenVINO バックエンドで TrackNet 推論を行うラッパー。

    内部で `backend.tracknet.inference.TrackNetInference` を使う。
    openvino パッケージが未インストール、または重みファイルが見つからない場合は
    コンストラクタで ImportError / RuntimeError を raise して factory が
    CpuTrackNet にフォールバックできるようにする。
    """

    def __init__(self) -> None:
        # openvino の有無を確認（未インストール時は factory がフォールバック）
        try:
            import openvino  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "openvino が未インストールです。pip install openvino>=2024.0 を実行してください。"
            ) from exc

        # TrackNetInference を初期化（重み探索 + バックエンド選択）
        from backend.tracknet.inference import TrackNetInference

        self._impl = TrackNetInference()
        ok = self._impl.load()
        if not ok:
            raise RuntimeError(
                f"TrackNetInference のロードに失敗しました: {self._impl.get_load_error()}"
            )

        # backend_name() で実際にロードされたバックエンド名を取得
        logger.info(
            "[OpenVINOTrackNet] バックエンド=%s でロード完了",
            self._impl.backend_name(),
        )

    def backend_name(self) -> str:
        """ロードされたバックエンド名を返す（ログ・デバッグ用）。"""
        return self._impl.backend_name()

    # ------------------------------------------------------------------
    def run_frames(self, frames: List[np.ndarray], fps: float = 30.0) -> List[ShuttleSample]:
        """numpy フレームリストから直接推論する（ビデオI/O不要）。

        ベンチマーク等でビデオデコードのオーバーヘッドを除き
        純粋な推論スループットを計測したい場合に使用する。
        """
        if len(frames) < 3:
            return []
        return self._process_chunk(list(frames), 0, fps)

    # ------------------------------------------------------------------
    def run(self, video_path: str) -> List[ShuttleSample]:
        """動画からシャトル軌跡を推定。

        長尺動画でもメモリを使い切らないよう CHUNK_SIZE フレームずつ
        チャンク処理し、チャンク境界は _OVERLAP フレームで連続させる。
        """
        import cv2

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"動画を開けません: {video_path}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)

        samples: List[ShuttleSample] = []
        # チャンク境界の連続性を保つためのオーバーラップバッファ
        buf: List[np.ndarray] = []
        global_frame_offset = 0  # バッファ先頭がビデオ全体で何フレーム目か

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                buf.append(frame)

                if len(buf) >= _CHUNK_SIZE + _OVERLAP:
                    samples.extend(
                        self._process_chunk(buf, global_frame_offset, fps)
                    )
                    # 処理済みフレームを捨て、末尾 _OVERLAP 枚だけ保持して次チャンクに繋げる
                    global_frame_offset += len(buf) - _OVERLAP
                    buf = buf[-_OVERLAP:]
        finally:
            cap.release()

        # 残りフレームを処理
        if len(buf) >= _FRAME_STACK:
            samples.extend(
                self._process_chunk(buf, global_frame_offset, fps)
            )

        logger.info("[OpenVINOTrackNet] %d サンプル取得", len(samples))
        return samples

    # ------------------------------------------------------------------
    def _process_chunk(
        self,
        frames: List[np.ndarray],
        global_offset: int,
        fps: float,
    ) -> List[ShuttleSample]:
        """フレームのリストを推論してチャンク分の ShuttleSample を返す。

        predict_frames() が返す frame_idx は「チャンク内での中間フレーム番号」
        なので、global_offset を加算してビデオ全体での絶対フレーム番号に変換する。
        """
        raw = self._impl.predict_frames(frames)
        chunk_samples: List[ShuttleSample] = []
        for r in raw:
            # frame_idx はチャンク内座標（1-based, 3フレームスタックの中間）
            local_idx = int(r.get("frame_idx") or 0)
            abs_idx = global_offset + local_idx
            chunk_samples.append(
                ShuttleSample(
                    frame=abs_idx,
                    ts_sec=abs_idx / fps,
                    x=float(r.get("x_norm") or 0.0),
                    y=float(r.get("y_norm") or 0.0),
                    confidence=float(r.get("confidence") or 0.0),
                )
            )
        return chunk_samples

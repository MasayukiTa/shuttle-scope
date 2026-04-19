"""Ray リモートタスク関数 (INFRA Phase D)

K10 ワーカーノード上で実行される推論関数群。
K10 には ShuttleScope コードベースが存在しないため、
onnxruntime / mediapipe / numpy を直接使用して推論を実装する。

設計方針:
- @ray.remote デコレータは使用しない（インポート時に ray が必要になるため）
- ray.remote(fn).remote(...) パターンで呼び出し時に動的に Ray リモート化する
- ray は遅延インポートする（ImportError 時はエラーを返す）
- K10 では backend.* モジュールを import しない
"""
from __future__ import annotations

import io
import json
import logging
import time
from typing import Any, Dict

import numpy as np

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# ワーカー上で実行される純粋関数（ray デコレータなし）
# ────────────────────────────────────────────────────────────────────────────

def _run_benchmark_tracknet(model_path: str, n_iters: int, use_gpu: bool) -> dict:
    """TrackNet ONNX ベンチマーク。

    K10 上でローカル実行される。onnxruntime を直接使用する。
    戻り値: {"fps": float, "avg_ms": float, "p95_ms": float} または {"error": str}
    """
    try:
        import onnxruntime as ort
        import numpy as np
        import time
        import os

        if not os.path.exists(model_path):
            return {"error": f"モデルファイルが見つかりません: {model_path}"}

        # EP 選択: GPU フラグに応じて DirectML → CPU にフォールバック
        available = ort.get_available_providers()
        if use_gpu and "DmlExecutionProvider" in available:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif use_gpu and "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        try:
            sess = ort.InferenceSession(model_path, providers=providers)
        except Exception as exc:
            return {"error": f"ONNX セッション初期化失敗: {exc}"}

        # TrackNet 入力: (1, 9, H, W) または (1, 3, H, W) — モデルシェイプを動的取得
        input_info = sess.get_inputs()[0]
        input_name = input_info.name
        shape = input_info.shape  # 例: [1, 9, 288, 512]
        # None / 動的次元は固定値で置換
        fixed_shape = []
        for i, dim in enumerate(shape):
            if dim is None or (isinstance(dim, str)):
                # バッチ次元は 1、それ以外はデフォルト値
                fixed_shape.append(1 if i == 0 else (9 if i == 1 else (288 if i == 2 else 512)))
            else:
                fixed_shape.append(int(dim))

        dummy = np.zeros(fixed_shape, dtype=np.float32)

        latencies = []
        # ウォームアップ
        try:
            sess.run(None, {input_name: dummy})
        except Exception:
            pass

        for _ in range(n_iters):
            t0 = time.perf_counter()
            sess.run(None, {input_name: dummy})
            latencies.append(time.perf_counter() - t0)

        if not latencies:
            return {"error": "計測データなし"}

        arr = np.array(latencies) * 1000.0  # ms に変換
        avg_ms = float(np.mean(arr))
        p95_ms = float(np.percentile(arr, 95))
        fps = 1000.0 / avg_ms if avg_ms > 0 else 0.0
        return {
            "fps": round(fps, 2),
            "avg_ms": round(avg_ms, 2),
            "p95_ms": round(p95_ms, 2),
        }

    except ImportError as exc:
        return {"error": f"onnxruntime 未インストール: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def _run_benchmark_pose(n_iters: int) -> dict:
    """MediaPipe Pose ベンチマーク（モデルファイル不要）。

    K10 上でローカル実行される。mediapipe を直接使用する。
    戻り値: {"fps": float, "avg_ms": float, "p95_ms": float} または {"error": str}
    """
    try:
        import mediapipe as mp
        import numpy as np
        import time

        mp_pose = mp.solutions.pose  # type: ignore[attr-defined]

        # 合成フレームを生成 (480x270 BGR)
        dummy_frame = np.zeros((270, 480, 3), dtype=np.uint8)
        # 中央に白い円を描いてポーズ検出しやすくする
        try:
            import cv2
            cv2.circle(dummy_frame, (240, 135), 50, (255, 255, 255), -1)
        except ImportError:
            pass

        latencies = []

        with mp_pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            enable_segmentation=False,
            min_detection_confidence=0.3,
        ) as pose:
            # ウォームアップ
            try:
                pose.process(dummy_frame)
            except Exception:
                pass

            for _ in range(n_iters):
                t0 = time.perf_counter()
                pose.process(dummy_frame)
                latencies.append(time.perf_counter() - t0)

        if not latencies:
            return {"error": "計測データなし"}

        arr = np.array(latencies) * 1000.0
        avg_ms = float(np.mean(arr))
        p95_ms = float(np.percentile(arr, 95))
        fps = 1000.0 / avg_ms if avg_ms > 0 else 0.0
        return {
            "fps": round(fps, 2),
            "avg_ms": round(avg_ms, 2),
            "p95_ms": round(p95_ms, 2),
        }

    except ImportError as exc:
        return {"error": f"mediapipe 未インストール: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def _run_benchmark_yolo(model_path: str, n_iters: int, use_gpu: bool) -> dict:
    """YOLO ONNX ベンチマーク。

    K10 上でローカル実行される。onnxruntime を直接使用する。
    戻り値: {"fps": float, "avg_ms": float, "p95_ms": float} または {"error": str}
    """
    try:
        import onnxruntime as ort
        import numpy as np
        import time
        import os

        if not os.path.exists(model_path):
            return {"error": f"モデルファイルが見つかりません: {model_path}"}

        # EP 選択
        available = ort.get_available_providers()
        if use_gpu and "DmlExecutionProvider" in available:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif use_gpu and "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        try:
            sess = ort.InferenceSession(model_path, providers=providers)
        except Exception as exc:
            return {"error": f"ONNX セッション初期化失敗: {exc}"}

        # YOLO 標準入力: (1, 3, 384, 640)
        input_info = sess.get_inputs()[0]
        input_name = input_info.name
        shape = input_info.shape
        fixed_shape = []
        for i, dim in enumerate(shape):
            if dim is None or isinstance(dim, str):
                defaults = [1, 3, 384, 640]
                fixed_shape.append(defaults[i] if i < len(defaults) else 1)
            else:
                fixed_shape.append(int(dim))

        dummy = np.zeros(fixed_shape, dtype=np.float32)

        latencies = []
        try:
            sess.run(None, {input_name: dummy})
        except Exception:
            pass

        for _ in range(n_iters):
            t0 = time.perf_counter()
            sess.run(None, {input_name: dummy})
            latencies.append(time.perf_counter() - t0)

        if not latencies:
            return {"error": "計測データなし"}

        arr = np.array(latencies) * 1000.0
        avg_ms = float(np.mean(arr))
        p95_ms = float(np.percentile(arr, 95))
        fps = 1000.0 / avg_ms if avg_ms > 0 else 0.0
        return {
            "fps": round(fps, 2),
            "avg_ms": round(avg_ms, 2),
            "p95_ms": round(p95_ms, 2),
        }

    except ImportError as exc:
        return {"error": f"onnxruntime 未インストール: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def _infer_tracknet_frames(model_path: str, frames_npy: bytes) -> bytes:
    """TrackNet 推論をシリアライズされた numpy フレームに対して実行する。

    K10 上でローカル実行される。
    Args:
        model_path: ONNX モデルファイルのパス
        frames_npy: np.ndarray.tobytes() でシリアライズされた float32 フレームデータ
                    shape 情報はフレームバイト列の先頭 4 つの int32 に埋め込まれる
                    フォーマット: [N, C, H, W, ...data...]
    Returns:
        推論結果を np.ndarray.tobytes() でシリアライズしたバイト列
        エラー時は JSON エンコードされたエラー dict の bytes を返す
    """
    try:
        import onnxruntime as ort
        import numpy as np
        import os

        if not os.path.exists(model_path):
            err = {"error": f"モデルファイルが見つかりません: {model_path}"}
            return json.dumps(err).encode("utf-8")

        # フレームデシリアライズ: 先頭 16 バイトが shape (4 x int32)
        shape_arr = np.frombuffer(frames_npy[:16], dtype=np.int32)
        n, c, h, w = int(shape_arr[0]), int(shape_arr[1]), int(shape_arr[2]), int(shape_arr[3])
        frames = np.frombuffer(frames_npy[16:], dtype=np.float32).reshape(n, c, h, w)

        # EP 選択（DirectML 優先）
        available = ort.get_available_providers()
        if "DmlExecutionProvider" in available:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        sess = ort.InferenceSession(model_path, providers=providers)
        input_name = sess.get_inputs()[0].name

        result = sess.run(None, {input_name: frames})
        output = result[0]  # 最初の出力テンソル

        # シリアライズ: shape を先頭に付加
        shape_bytes = np.array(output.shape, dtype=np.int32).tobytes()
        data_bytes = output.astype(np.float32).tobytes()
        return shape_bytes + data_bytes

    except ImportError as exc:
        err = {"error": f"onnxruntime 未インストール: {exc}"}
        return json.dumps(err).encode("utf-8")
    except Exception as exc:
        err = {"error": str(exc)}
        return json.dumps(err).encode("utf-8")


# ────────────────────────────────────────────────────────────────────────────
# ディスパッチ関数（ray は遅延インポート）
# ────────────────────────────────────────────────────────────────────────────

def dispatch_benchmark(fn_name: str, **kwargs) -> Dict[str, Any]:
    """ベンチマーク関数を Ray 経由でワーカーノードに dispatch する。

    ray.remote() を呼び出し時に動的に適用する（インポート時に ray は不要）。
    head ノード（PC1）は除外し、ワーカーノード（K10 等）のみに投入する。

    Args:
        fn_name: "_run_benchmark_tracknet" / "_run_benchmark_pose" / "_run_benchmark_yolo"
        **kwargs: 各ベンチマーク関数に渡すキーワード引数

    Returns:
        {"worker_device_id": result_dict, ...} のマッピング
        Ray 未接続時は {"error": "Ray未接続"} を返す
    """
    # bootstrap.is_ray_connected() で接続確認（subprocess 接続フラグも考慮）
    try:
        from backend.cluster.bootstrap import is_ray_connected
        if not is_ray_connected():
            return {"error": "Ray未接続 — 先にRay起動ボタンを押してください"}
    except Exception:
        pass

    try:
        import ray  # type: ignore
    except ImportError:
        return {"error": "ray 未インストール"}

    # ray.is_initialized() でなく ray.is_initialized OR subprocess フラグで判定済みだが
    # ray.remote() を使うには ray.init() が完了している必要がある。
    # 未 init の場合は ray.nodes() が NameError → except で捕捉される。
    if not ray.is_initialized():
        return {"error": "Ray初期化未完了 — しばらく待ってから再試行してください（バックグラウンドでray.init()中）"}

    # 関数名からローカル関数を解決
    fn_map = {
        "_run_benchmark_tracknet": _run_benchmark_tracknet,
        "_run_benchmark_pose": _run_benchmark_pose,
        "_run_benchmark_yolo": _run_benchmark_yolo,
    }
    fn = fn_map.get(fn_name)
    if fn is None:
        return {"error": f"未知のベンチマーク関数: {fn_name}"}

    try:
        # head ノード IP を取得してワーカーのみに絞り込む
        try:
            from backend.cluster.topology import get_primary_ip
            head_ip = get_primary_ip()
        except Exception:
            head_ip = ""

        nodes = ray.nodes()
        # Alive かつ head ノード以外 = ワーカーノード
        worker_nodes = [
            n for n in nodes
            if n.get("Alive")
            and n.get("NodeManagerAddress", "") != head_ip
        ]

        if not worker_nodes:
            # ワーカーが未参加 or IP が不明な場合はすべての Alive ノードで実行
            logger.warning("dispatch_benchmark: ワーカーノードが見つからないためすべてのノードで実行")
            worker_nodes = [n for n in nodes if n.get("Alive")]

        if not worker_nodes:
            return {"error": "Alive なノードが見つかりません"}

        remote_fn = ray.remote(fn)

        futures = {}
        for node in worker_nodes:
            node_id = node.get("NodeID", "unknown")
            node_ip = node.get("NodeManagerAddress", "unknown")
            future = remote_fn.remote(**kwargs)
            futures[f"ray_{node_ip}_{node_id[:8]}"] = future

        # 結果を収集（タイムアウト 120 秒）
        results: Dict[str, Any] = {}
        for device_id, future in futures.items():
            try:
                result = ray.get(future, timeout=120)
                results[device_id] = result
            except ray.exceptions.GetTimeoutError:
                results[device_id] = {"error": "タイムアウト (120s)"}
            except Exception as exc:
                results[device_id] = {"error": str(exc)}

        return results

    except Exception as exc:
        logger.warning("dispatch_benchmark 失敗: %s", exc)
        return {"error": str(exc)}


def dispatch_tracknet_inference(frames_npy: bytes, model_path: str, device_id: str) -> bytes:
    """TrackNet 推論を特定の Ray ワーカーに dispatch する。

    Args:
        frames_npy: シリアライズされた numpy フレームデータ
                    フォーマット: 先頭 16 バイト = shape (N,C,H,W) as int32x4、
                                残り = float32 フレームデータ
        model_path: ワーカー上の ONNX モデルパス
        device_id:  ターゲットデバイス ID（"ray_igpu_..." で GPU 使用）

    Returns:
        推論結果バイト列（_infer_tracknet_frames と同形式）
        エラー時は JSON エンコードされたエラー dict の bytes
    """
    try:
        import ray  # type: ignore
    except ImportError:
        return json.dumps({"error": "ray 未インストール"}).encode("utf-8")

    if not ray.is_initialized():
        return json.dumps({"error": "Ray初期化未完了 — バックグラウンドでray.init()中"}).encode("utf-8")

    try:
        remote_fn = ray.remote(_infer_tracknet_frames)
        future = remote_fn.remote(model_path=model_path, frames_npy=frames_npy)
        result = ray.get(future, timeout=60)
        return result
    except Exception as exc:
        return json.dumps({"error": str(exc)}).encode("utf-8")

"""TrackNet Pareto スイープ: confidence_threshold × batch_size。

各組み合わせについて以下を計測する:
  - fps         : 推論スループット（フレーム/秒）
  - detect_rate : confidence >= threshold のフレーム割合（精度の代理指標）
  - skip_rate   : inference skip が有効な場合の スキップ割合（将来拡張用）

使い方:
    cd shuttlescope
    SS_TRACKNET_PROFILE=1 python -m backend.benchmark.pareto_sweep

オプション環境変数:
    SS_BENCH_TIME_BUDGET_SEC : 各セルの計測予算（秒、既定 5）
    SS_PARETO_N_FRAMES       : 1 回の run_frames() に渡すフレーム数（既定 30）
    SS_PARETO_BATCH_SIZES    : カンマ区切りバッチサイズ（既定 1,2,4,8,16）
    SS_PARETO_THRESHOLDS     : カンマ区切り信頼度閾値（既定 0.3,0.4,0.5,0.6,0.7,0.8）
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

# shuttlescope/ を sys.path に追加
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pareto_sweep")


def _parse_env_list(key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(key, "").strip()
    return [s.strip() for s in raw.split(",") if s.strip()] if raw else default


def _make_synthetic_frames(n: int, w: int = 512, h: int = 288) -> list[np.ndarray]:
    rng = np.random.default_rng(42)
    return [rng.integers(0, 255, (h, w, 3), dtype=np.uint8) for _ in range(n)]


def _measure_cell(
    inferencer,
    frames: list[np.ndarray],
    threshold: float,
    batch_size: int,
    budget_sec: float,
) -> dict[str, Any]:
    """1 セル（threshold × batch）を計測して指標 dict を返す。"""
    # max_batch を一時的にこのセルの batch_size に固定
    orig_max = getattr(inferencer, "_max_batch", 4)
    inferencer._max_batch = batch_size

    latencies: list[float] = []
    detect_counts: list[int] = []
    total_counts: list[int] = []

    # ウォームアップ
    for _ in range(3):
        try:
            inferencer.predict_frames(frames)
        except Exception:
            break

    t_start = time.perf_counter()
    min_iters, max_iters = 5, 300
    while True:
        if len(latencies) >= max_iters:
            break
        elapsed = time.perf_counter() - t_start
        if len(latencies) >= min_iters and elapsed >= budget_sec:
            break
        t0 = time.perf_counter()
        try:
            results = inferencer.predict_frames(frames)
        except Exception as exc:
            logger.warning("推論失敗 threshold=%.2f batch=%d: %s", threshold, batch_size, exc)
            break
        latencies.append(time.perf_counter() - t0)
        if results:
            detected = sum(1 for r in results if (r.get("confidence") or 0.0) >= threshold)
            detect_counts.append(detected)
            total_counts.append(len(results))

    # 復元
    inferencer._max_batch = orig_max

    if not latencies:
        return {"error": "計測失敗"}

    n_triplets = max(len(frames) - 2, 1)  # FRAME_STACK=3
    arr = np.array(latencies, dtype=np.float64)
    avg_ms = float(np.mean(arr)) * 1000.0
    fps = n_triplets * 1000.0 / avg_ms if avg_ms > 0 else 0.0
    detect_rate = (
        sum(detect_counts) / max(sum(total_counts), 1) if total_counts else 0.0
    )

    return {
        "fps": round(fps, 2),
        "avg_ms": round(avg_ms / n_triplets, 2),
        "p95_ms": round(float(np.percentile(arr, 95)) / n_triplets * 1000, 2),
        "detect_rate": round(detect_rate, 3),
        "iters": len(latencies),
        "batch": batch_size,
        "threshold": threshold,
    }


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    thresholds = sorted({r["threshold"] for r in rows})
    batches = sorted({r["batch"] for r in rows})
    cell = {(r["threshold"], r["batch"]): r for r in rows}

    # fps テーブル
    print("\n=== fps (フレーム/秒) ===")
    header = f"{'thresh':>8}" + "".join(f"  batch={b:>2}" for b in batches)
    print(header)
    for th in thresholds:
        line = f"{th:>8.2f}"
        for b in batches:
            c = cell.get((th, b), {})
            line += f"  {c.get('fps', '-'):>9.2f}" if "fps" in c else f"  {'?':>9}"
        print(line)

    # detect_rate テーブル
    print("\n=== detect_rate (confidence >= threshold のフレーム割合) ===")
    print(header)
    for th in thresholds:
        line = f"{th:>8.2f}"
        for b in batches:
            c = cell.get((th, b), {})
            line += f"  {c.get('detect_rate', '-'):>9.3f}" if "detect_rate" in c else f"  {'?':>9}"
        print(line)

    # Pareto 候補（detect_rate ≥ 0.5、fps 降順 top-5）
    valid = [r for r in rows if r.get("detect_rate", 0) >= 0.5 and "fps" in r]
    if valid:
        valid.sort(key=lambda r: -r["fps"])
        print("\n=== Pareto 候補 (detect_rate ≥ 0.5, fps 降順 top-5) ===")
        print(f"{'fps':>8}  {'detect_rate':>12}  {'threshold':>10}  {'batch':>6}  {'avg_ms':>8}")
        for r in valid[:5]:
            print(
                f"{r['fps']:>8.2f}  {r['detect_rate']:>12.3f}  "
                f"{r['threshold']:>10.2f}  {r['batch']:>6}  {r['avg_ms']:>8.2f}"
            )


def main() -> None:
    budget_sec = float(os.environ.get("SS_BENCH_TIME_BUDGET_SEC", "5"))
    n_frames = int(os.environ.get("SS_PARETO_N_FRAMES", "30"))
    batch_sizes = [int(x) for x in _parse_env_list("SS_PARETO_BATCH_SIZES", ["1", "2", "4", "8", "16"])]
    thresholds = [float(x) for x in _parse_env_list("SS_PARETO_THRESHOLDS", ["0.3", "0.4", "0.5", "0.6", "0.7", "0.8"])]

    logger.info(
        "Pareto スイープ開始: n_frames=%d batch_sizes=%s thresholds=%s budget=%.1fs",
        n_frames, batch_sizes, thresholds, budget_sec,
    )

    # SS_TRACKNET_PROFILE を有効化
    os.environ["SS_TRACKNET_PROFILE"] = "1"
    # 推論モジュールを再ロードして _PROFILE_ENABLED を反映
    import importlib
    import backend.tracknet.inference as _inf_mod
    importlib.reload(_inf_mod)

    from backend.cv import factory
    inferencer_cv = factory.get_tracknet()
    # TrackNetInference 本体を取得
    inferencer = getattr(inferencer_cv, "_impl", inferencer_cv)

    if not getattr(inferencer, "load", lambda: False)():
        logger.error("TrackNet モデルをロードできませんでした。weights/ を確認してください。")
        sys.exit(1)

    frames = _make_synthetic_frames(n_frames)
    rows: list[dict] = []
    total_cells = len(thresholds) * len(batch_sizes)
    done = 0

    for threshold in thresholds:
        for batch_size in batch_sizes:
            logger.info(
                "[%d/%d] threshold=%.2f batch=%d ...",
                done + 1, total_cells, threshold, batch_size,
            )
            if hasattr(inferencer, "reset_stage_timings"):
                inferencer.reset_stage_timings()

            result = _measure_cell(inferencer, frames, threshold, batch_size, budget_sec)

            if "error" not in result and hasattr(inferencer, "get_stage_timings"):
                stage = inferencer.get_stage_timings()
                if stage.get("n_chunks", 0) > 0:
                    result["stage_timings"] = stage
                    logger.info(
                        "  ステージ: pre=%.2fms stack=%.2fms infer=%.2fms post=%.2fms",
                        stage["preprocess_ms"], stage["stack_ms"],
                        stage["infer_ms"], stage["postproc_ms"],
                    )

            rows.append(result)
            logger.info("  → fps=%.2f detect_rate=%.3f", result.get("fps", 0), result.get("detect_rate", 0))
            done += 1

    _print_table(rows)

    # JSON 保存
    out_path = Path(__file__).parent / "pareto_results.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("結果を %s に保存しました", out_path)


if __name__ == "__main__":
    main()

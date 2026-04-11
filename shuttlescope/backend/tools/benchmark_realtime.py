"""
リアルタイム解析可能性ベンチマーク
使い方:
  cd shuttlescope/backend
  .venv/Scripts/python tools/benchmark_realtime.py

60fps x 30秒 = 1800フレームを合成して TrackNet / YOLO の処理速度・安定性を計測する。
"""
import sys
import os
import time
import numpy as np

# backend/ の親ディレクトリ（shuttlescope/）を path に追加
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)           # .../backend
_ROOT_DIR = os.path.dirname(_BACKEND_DIR)       # .../shuttlescope
for _p in [_ROOT_DIR, _BACKEND_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─── 合成フレーム生成 ──────────────────────────────────────────────────────────
# 1分 x 60fps = 3600フレーム相当の安定性計測
# 全フレームを実推論するとTrackNetが数時間かかるため統計サンプリングで代替
FPS = 60
DURATION_SEC = 60
FRAME_W, FRAME_H = 1920, 1080

TN_SAMPLES  = 200   # TrackNet: 200回（約53秒分 @ 3.7fps）
YO_SAMPLES  = 300   # YOLO: 300回（安定性・熱スロットリング確認に十分）
POOL_SIZE   = 60    # フレームプール: 60枚（キャッシュヒット防止に多様性確保）
FRAME_COUNT = POOL_SIZE


def make_frames(n: int) -> list[np.ndarray]:
    """POOL_SIZE枚のユニークフレームを生成し、循環して返す。
    各フレームに異なるノイズを乗せるためキャッシュヒットは起きない。
    """
    import cv2
    rng = np.random.default_rng(42)
    pool_count = min(n, POOL_SIZE)
    print(f"  フレームプール {pool_count} 枚 ({FRAME_W}x{FRAME_H}) 生成中…", end="", flush=True)
    base = np.full((FRAME_H, FRAME_W, 3), [40, 120, 40], dtype=np.uint8)
    pool = []
    for i in range(pool_count):
        # フレームごとに異なるノイズ（キャッシュ防止）
        noise = rng.integers(0, 60, (FRAME_H, FRAME_W, 3), dtype=np.uint8)
        frame = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        # フレーム番号を右下に焼き込み（確実に異なる入力にする）
        cv2.putText(frame, str(i), (FRAME_W - 120, FRAME_H - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        pool.append(frame)
    frames = [pool[i % pool_count] for i in range(n)]
    print(f" 完了（{pool_count}枚プール）")
    return frames


# ─── TrackNet ベンチマーク ────────────────────────────────────────────────────

def bench_tracknet(frames: list[np.ndarray]) -> dict:
    print("\n[TrackNet] モデルロード中…")
    from backend.tracknet.inference import get_inference

    inf = get_inference("auto")
    if not inf.load():
        return {"error": inf.get_load_error() or "ロード失敗"}

    print(f"  バックエンド: {inf.backend_name()}")
    print(f"  3フレームトリプレット x {TN_SAMPLES} 回 推論開始…")

    latencies = []
    report_interval = 40
    t_total_start = time.perf_counter()

    for i in range(TN_SAMPLES):
        triplet = [frames[j % POOL_SIZE] for j in range(i, i + 3)]
        t0 = time.perf_counter()
        inf.predict_frames(triplet)
        latencies.append(time.perf_counter() - t0)

        if (i + 1) % report_interval == 0:
            elapsed = time.perf_counter() - t_total_start
            chunk = latencies[-report_interval:]
            print(f"    {i+1}/{TN_SAMPLES} ({elapsed:.0f}s経過): "
                  f"avg={np.mean(chunk)*1000:.1f}ms  "
                  f"p95={np.percentile(chunk,95)*1000:.1f}ms  "
                  f"fps={1/np.mean(chunk):.1f}")

    elapsed_total = time.perf_counter() - t_total_start
    avg_ms = np.mean(latencies) * 1000
    p50_ms = np.percentile(latencies, 50) * 1000
    p95_ms = np.percentile(latencies, 95) * 1000
    p99_ms = np.percentile(latencies, 99) * 1000
    infer_per_sec = 1.0 / np.mean(latencies)
    # 分散（安定性指標）
    std_ms = np.std(latencies) * 1000

    return {
        "backend": inf.backend_name(),
        "inferences": len(latencies),
        "elapsed_sec": round(elapsed_total, 1),
        "avg_ms": round(avg_ms, 1),
        "p50_ms": round(p50_ms, 1),
        "p95_ms": round(p95_ms, 1),
        "p99_ms": round(p99_ms, 1),
        "std_ms": round(std_ms, 1),
        "infer_per_sec": round(infer_per_sec, 2),
    }


# ─── YOLO ベンチマーク ────────────────────────────────────────────────────────

def bench_yolo(frames: list[np.ndarray], sample_every: int = 1) -> dict:
    label = f"全フレーム(1/{sample_every})" if sample_every > 1 else "全フレーム(1/1)"
    print(f"\n[YOLO] モデルロード中… [{label}]")
    from backend.yolo.inference import get_yolo_inference

    inf = get_yolo_inference()
    if not inf.load():
        return {"error": "ロード失敗"}

    targets = [frames[i % POOL_SIZE] for i in range(YO_SAMPLES)]
    print(f"  バックエンド: {inf.backend_name()}")
    print(f"  {YO_SAMPLES} フレームを推論開始…")

    latencies = []
    report_interval = 60
    t_total_start = time.perf_counter()

    for idx in range(YO_SAMPLES):
        frame = frames[idx % POOL_SIZE]
        t0 = time.perf_counter()
        inf.predict_frame(frame)
        latencies.append(time.perf_counter() - t0)

        if (idx + 1) % report_interval == 0:
            elapsed = time.perf_counter() - t_total_start
            chunk = latencies[-report_interval:]
            print(f"    {idx+1}/{YO_SAMPLES} ({elapsed:.0f}s経過): "
                  f"avg={np.mean(chunk)*1000:.1f}ms  "
                  f"p95={np.percentile(chunk,95)*1000:.1f}ms  "
                  f"fps={1/np.mean(chunk):.1f}")

    elapsed_total = time.perf_counter() - t_total_start
    avg_ms = np.mean(latencies) * 1000
    p50_ms = np.percentile(latencies, 50) * 1000
    p95_ms = np.percentile(latencies, 95) * 1000
    p99_ms = np.percentile(latencies, 99) * 1000
    std_ms = np.std(latencies) * 1000
    infer_per_sec = 1.0 / np.mean(latencies)

    return {
        "backend": inf.backend_name(),
        "sample_every": sample_every,
        "inferences": len(latencies),
        "elapsed_sec": round(elapsed_total, 1),
        "avg_ms": round(avg_ms, 1),
        "p50_ms": round(p50_ms, 1),
        "p95_ms": round(p95_ms, 1),
        "p99_ms": round(p99_ms, 1),
        "std_ms": round(std_ms, 1),
        "infer_per_sec": round(infer_per_sec, 2),
    }


# ─── 結果レポート ──────────────────────────────────────────────────────────────

def judge(fps: float, label: str) -> str:
    if fps >= 60:
        return f"✅ 60fps リアルタイム対応可"
    elif fps >= 30:
        return f"✅ 30fps リアルタイム対応可"
    elif fps >= 15:
        return f"⚡ 15fps程度（間引き併用で実用）"
    elif fps >= 5:
        return f"⚠ {fps:.1f}fps（方向転換前後絞り込みなら可）"
    else:
        return f"❌ {fps:.1f}fps（バックグラウンド処理推奨）"


def print_report(tracknet: dict, yolo_1: dict, yolo_6: dict, yolo_30: dict):
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  ベンチマーク結果 - 60fps x {DURATION_SEC}s = {FRAME_COUNT}フレーム")
    print(sep)

    def row(d: dict, label: str):
        if "error" in d:
            print(f"\n▶ {label}")
            print(f"  ✗ {d['error']}")
            return
        fps = d['infer_per_sec']
        budget_ms = 1000.0 / FPS  # 60fps = 16.7ms/frame
        headroom = budget_ms / d['avg_ms']
        print(f"\n▶ {label}")
        print(f"  バックエンド    : {d['backend']}")
        print(f"  推論数          : {d['inferences']} 回 / 実測{d['elapsed_sec']}秒")
        print(f"  avg / p50 / p95 / p99 : "
              f"{d['avg_ms']}ms / {d['p50_ms']}ms / {d['p95_ms']}ms / {d['p99_ms']}ms")
        print(f"  標準偏差（安定性）: ±{d['std_ms']}ms")
        print(f"  実効fps         : {fps:.2f} fps")
        print(f"  60fps予算余裕度  : {headroom:.2f}x  ({budget_ms:.1f}ms / {d['avg_ms']}ms)")
        print(f"  判定            : {judge(fps, label)}")

    row(tracknet, "TrackNet - シャトル追跡（3フレームトリプレット）")
    row(yolo_1,   "YOLO - プレイヤー検出（1/1 全フレーム）")
    row(yolo_6,   "YOLO - プレイヤー検出（1/6 = 10fps@60fps）")
    row(yolo_30,  "YOLO - プレイヤー検出（1/30 = 2fps@60fps）")

    print(f"\n{sep}")
    print("  推奨戦略サマリー")
    print(sep)

    tn_fps = tracknet.get('infer_per_sec', 0)
    yo_fps = yolo_1.get('infer_per_sec', 0)
    yo6_fps = yolo_6.get('infer_per_sec', 0)

    # TrackNet は 3フレーム毎に1推論 → 実効fps = infer_per_sec（スライド1フレームずつ）
    # ただし実運用では「方向転換前後Nフレーム」のみ処理するため大幅削減可能
    print(f"\n  TrackNet:")
    if tn_fps >= 60:
        print("    → 全フレームリアルタイム処理可能")
    elif tn_fps >= 10:
        print(f"    → 方向転換検出時のみ処理（バースト）で実用的")
        print(f"       例: 1ラリー平均5~8回の方向転換 x 前後10フレーム = {8*20}フレーム/ラリー")
        print(f"       {tn_fps:.1f}fps なら {8*20/tn_fps:.1f}秒で処理可（ラリー長より短い）")
    else:
        print(f"    → 試合後バッチ処理推奨（{tn_fps:.1f}fps はリアルタイム不足）")

    print(f"\n  YOLO（ダブルス位置解析）:")
    if yo_fps >= 30:
        print("    → 全フレームリアルタイム可")
    elif yo6_fps > 0:
        budget_ms_6 = 1000.0 * 6 / FPS  # 6フレームごとの予算
        margin = budget_ms_6 / yolo_6.get('avg_ms', 999)
        print(f"    → 6フレームに1回（10fps）サンプリングで余裕度{margin:.1f}x")
        print(f"       ダブルスポジション把握には1~2fps程度で十分")
    print(f"\n  並列処理（TrackNet + YOLO 同時）:")
    combined_ms = tracknet.get('avg_ms', 0) + yolo_1.get('avg_ms', 0)
    print(f"    シリアル合計: {combined_ms:.1f}ms/フレーム → {1000/combined_ms:.1f}fps")
    print(f"    スレッド分離で並列実行すれば max(TN, YO) で動作可能")
    print(sep)


if __name__ == "__main__":
    print(f"=== 60fps x {DURATION_SEC}s realtime benchmark ===")
    print(f"TrackNet: {TN_SAMPLES} inferences / YOLO: {YO_SAMPLES} frames / pool: {POOL_SIZE}")
    frames = make_frames(FRAME_COUNT)

    tracknet_result = bench_tracknet(frames)
    yolo_result_all  = bench_yolo(frames, sample_every=1)
    yolo_result_6    = bench_yolo(frames, sample_every=6)
    yolo_result_30   = bench_yolo(frames, sample_every=30)

    print_report(tracknet_result, yolo_result_all, yolo_result_6, yolo_result_30)

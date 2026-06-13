"""Phase 1+2 の PersonTracker を試合動画区間に当てて debug video を出力する。

設計書: private_docs/2026-05-27_person_tracking_design.md
使用例:
    python shuttlescope/scripts/generate_tracking_debug_video.py \
        --video .../fd425688-...mp4 \
        --start-sec 120 --duration-sec 30 \
        --match-type doubles \
        --out C:/Users/kiyus/Desktop/person_tracking_debug.mp4

Swap Guard 評価 (ground-truth 不要 proxy 指標):
    # OFF / ON 両方走らせて proxy 指標を比較 JSON に出す
    python shuttlescope/scripts/generate_tracking_debug_video.py \
        --video .../fd425688-...mp4 \
        --start-sec 120 --duration-sec 30 --match-type doubles --match-id 33 \
        --swap-guard both --eval-metrics \
        --out C:/Users/kiyus/Desktop/swapguard_debug.mp4 \
        --metrics-json C:/Users/kiyus/Desktop/swapguard_metrics.json

--swap-guard on|off|both:
    on  = Swap Guard を有効化して 1 回実行
    off = 無効 (既定挙動) で 1 回実行
    both= OFF→ON の 2 回実行し proxy 指標を比較。動画は ON 側を --out に出す
          (OFF 側は <out>.off.<ext> に出す)。
--eval-metrics: proxy 指標 (per_court_unique_ids / swap events / proxy_idsw) を集計し
    --metrics-json (未指定なら <out>.metrics.json) に書き出す。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# backend を import path に追加
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.cv.person_tracker import PersonTracker  # noqa: E402
from backend.cv import track_evaluator  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# track_id 色 palette (BGR)
_PALETTE = [
    (255, 64, 64),   (64, 255, 64),   (64, 64, 255),  (255, 255, 64),
    (255, 64, 255),  (64, 255, 255),  (255, 128, 0),  (128, 0, 255),
    (0, 128, 255),   (128, 255, 0),   (255, 0, 128),  (0, 255, 128),
]


def _color_for(track_id: int) -> tuple[int, int, int]:
    if track_id < 0:
        return (180, 180, 180)
    return _PALETTE[hash(track_id) % len(_PALETTE)]


def _parse_corners(s: str | None, width: int, height: int) -> list[tuple[float, float]] | None:
    """コート 4 隅 JSON parse。

    None の場合は **画面全体を court と見なす fallback** (TL/TR/BR/BL = 画面 4 隅)。
    こうすると adjudicator は常に何らかの象限を返す (Phase 1 観察用)。
    """
    if s is None:
        # 画面 4 隅 fallback
        return [(0.0, 0.0), (float(width), 0.0), (float(width), float(height)), (0.0, float(height))]
    obj = json.loads(s)
    # 期待: [[x,y], [x,y], [x,y], [x,y]] (TL, TR, BR, BL)
    return [(float(p[0]), float(p[1])) for p in obj]


def _out_with_suffix(out_path: str, suffix: str) -> str:
    """<dir>/<stem><suffix><ext> を作る (例: foo.mp4 + .off → foo.off.mp4)。"""
    base, ext = os.path.splitext(out_path)
    return f"{base}{suffix}{ext}"


def _run_pass(
    args,
    *,
    swap_guard: bool,
    out_path: str | None,
    fps: float,
    width: int,
    height: int,
    corners,
    match_id_arg,
) -> dict:
    """1 回の追跡 pass を実行する。

    swap_guard=True/False で Swap Guard の有効/無効を切り替える。out_path が
    None の場合は動画書き出しを行わず proxy 指標の収集のみ行う (eval 専用 pass)。

    返り値: {
        "records": [{"frame","track_id","court_id"}, ...],  # proxy 指標用
        "swap_stats": {"swap_detected","swap_applied"},
        "frames": int, "seconds": float,
        "per_court_ids": {court_id: [track_id,...]},  # ログ用
        "out": out_path or None,
    }
    動画 writer を開けない等の致命エラーでは RuntimeError を送出する。
    """
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"動画が開けません: {args.video}")
    start_frame = int(args.start_sec * fps)
    end_frame = start_frame + int(args.duration_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    tracker = PersonTracker(
        match_type=args.match_type,
        court_corners=corners,
        model_path=args.model,
        device=args.device,
        match_id=match_id_arg,
        frame_size=(width, height),
        use_reid=(args.reid == "on"),
        reid_threshold=args.reid_thresh,
    )
    # Swap Guard の有効/無効をこの pass 用に明示設定 (env 既定を上書き)。
    tracker._swap_guard_enabled = bool(swap_guard)
    # set_idx 反映 (side swap)。Swap Guard 計測カウンタもここでクリアされる前提なし
    # (reset_for_new_set はカウンタをリセットしない) なので pass 単位で常に 0 起点。
    if args.set_idx:
        tracker.reset_for_new_set(args.set_idx)

    if tracker._adjudicator is not None:
        drawn_corners = tracker._adjudicator._court_polygon
    else:
        drawn_corners = corners

    writer = None
    if out_path is not None:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))
        if not writer.isOpened():
            cap.release()
            raise RuntimeError(f"出力 mp4 が開けません: {out_path}")

    id_first_seen: dict[int, int] = {}
    id_last_seen: dict[int, int] = {}
    total_unique_ids: set[int] = set()
    per_court_ids: dict[int, set[int]] = {0: set(), 1: set(), 2: set(), 3: set()}
    records: list[dict] = []

    frame_idx = start_frame
    processed = 0
    t0 = time.time()
    while frame_idx < end_frame:
        ok, frame = cap.read()
        if not ok:
            logger.warning("read 失敗 @ frame %d、終了", frame_idx)
            break

        tracks = tracker.update(frame, frame_idx)

        if writer is not None and drawn_corners is not None:
            pts = np.array(drawn_corners, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(frame, [pts], isClosed=True, color=(80, 80, 80), thickness=1)

        for t in tracks:
            # proxy 指標用レコード (描画とは独立に常に収集)
            records.append(
                {"frame": frame_idx, "track_id": t.track_id, "court_id": t.court_id}
            )
            if writer is not None:
                x1, y1, x2, y2 = [int(v) for v in t.bbox]
                color = _color_for(t.track_id)
                in_court = t.court_id is not None
                thickness = 2 if in_court else 1
                if not in_court:
                    color = (160, 160, 160)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
                pl = t.player_label or "-"
                rec_tag = "*R" if t.is_recovered else ""
                label = f"ID:{t.track_id}{rec_tag} Q:{t.court_id} {pl} c:{t.confidence:.2f}"
                cv2.putText(frame, label, (x1, max(y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
                fx = int((x1 + x2) / 2)
                cv2.circle(frame, (fx, y2), 4, color, -1)

            if t.track_id >= 0:
                total_unique_ids.add(t.track_id)
                id_first_seen.setdefault(t.track_id, frame_idx)
                id_last_seen[t.track_id] = frame_idx
                if t.court_id is not None and t.court_id in per_court_ids:
                    per_court_ids[t.court_id].add(t.track_id)

        if writer is not None:
            elapsed = (frame_idx - start_frame) / fps
            sg = "ON" if swap_guard else "OFF"
            hud = (f"frame {frame_idx}  t+{elapsed:5.2f}s  tracks:{len(tracks)}  "
                   f"unique_ids:{len(total_unique_ids)}  swapguard:{sg}")
            cv2.putText(frame, hud, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 2, cv2.LINE_AA)
            writer.write(frame)

        frame_idx += 1
        processed += 1
        if processed % 30 == 0:
            logger.info("  処理 %d frames (%.1f fps)",
                        processed, processed / max(time.time() - t0, 1e-3))

    cap.release()
    if writer is not None:
        writer.release()
    dt = time.time() - t0
    sg = "ON" if swap_guard else "OFF"
    logger.info("[swap-guard=%s] 完了: %d frames, %.1f s, %.1f fps",
                sg, processed, dt, processed / max(dt, 1e-3))

    return {
        "records": records,
        "swap_stats": tracker.swap_guard_stats(),
        "frames": processed,
        "seconds": dt,
        "per_court_ids": {c: sorted(ids) for c, ids in per_court_ids.items()},
        "out": out_path,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--start-sec", type=float, default=60.0)
    p.add_argument("--duration-sec", type=int, default=30)
    p.add_argument("--match-type", choices=["singles", "doubles"], required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--court-corners", default=None, help='JSON: [[x,y],...] TL,TR,BR,BL pixel')
    p.add_argument("--model", default=None, help="YOLO model path (default: env or yolov8n.onnx)")
    p.add_argument("--device", default=None)
    p.add_argument("--match-id", type=int, default=None,
                   help="DB の court_calibration から 4 隅を取得する。--court-corners 優先。")
    p.add_argument("--set-idx", type=int, default=0,
                   help="開始 set index。奇数なら side swap 有効。")
    p.add_argument("--reid", choices=["on", "off"], default="on",
                   help="Phase 4 ReID Tier 3 recovery を有効化 (default: on)")
    p.add_argument("--reid-thresh", type=float, default=None,
                   help="ReID cosine sim 閾値 (default: SS_PERSON_REID_THRESH or 0.85)")
    p.add_argument("--swap-guard", choices=["on", "off", "both"], default="off",
                   help="Swap Guard を on/off/both で実行。both は OFF→ON 両方走らせ "
                        "proxy 指標を比較 (default: off=既定挙動)")
    p.add_argument("--eval-metrics", action="store_true",
                   help="ground-truth 不要の proxy 指標を集計し JSON 出力する")
    p.add_argument("--metrics-json", default=None,
                   help="proxy 指標 JSON の出力先 (未指定なら <out>.metrics.json)")
    args = p.parse_args()

    # 動画メタを 1 回だけ覗く (fps / 解像度の確定)。pass 本体は _run_pass が
    # 自前で VideoCapture を開く (both で 2 回読むため)。
    probe = cv2.VideoCapture(args.video)
    if not probe.isOpened():
        logger.error("動画が開けません: %s", args.video)
        return 2
    fps = probe.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
    probe.release()
    start_frame = int(args.start_sec * fps)
    end_frame = start_frame + int(args.duration_sec * fps)
    logger.info("動画 %dx%d @ %.2f fps、frame %d → %d 処理",
                width, height, fps, start_frame, end_frame)
    logger.info("ReID Tier 3: %s (threshold=%s)", args.reid, args.reid_thresh or "default")

    # 優先順: --court-corners (明示) > --match-id (DB) > 画面全体 fallback
    if args.court_corners is not None:
        corners = _parse_corners(args.court_corners, width, height)
        match_id_arg = None
    elif args.match_id is not None:
        corners = None  # PersonTracker が DB から取る
        match_id_arg = args.match_id
    else:
        corners = _parse_corners(None, width, height)  # 画面 4 隅 fallback
        match_id_arg = None

    label_map = {0: "FL/PlayerA", 1: "FR/PlayerB", 2: "BL/PlayerC", 3: "BR/PlayerD"}

    def _log_pass(tag: str, res: dict) -> None:
        per_court = res["per_court_ids"]
        logger.info("[swap-guard=%s] swap_stats=%s", tag, res["swap_stats"])
        for cid in (0, 1, 2, 3):
            ids = per_court.get(cid, [])
            logger.info("  court_id %d (%s): %d unique track_ids %s",
                        cid, label_map[cid], len(ids), ids[:8])

    # ── 実行する pass を決定 ──────────────────────────────────────────────
    # both: OFF を <out>.off.<ext>、ON を <out> に書き出す。
    # on/off: その 1 モードだけを <out> に書き出す。
    eval_results: dict[str, dict] = {}
    try:
        if args.swap_guard == "both":
            off_out = _out_with_suffix(args.out, ".off")
            logger.info("=== pass 1/2: Swap Guard OFF → %s ===", off_out)
            off_res = _run_pass(args, swap_guard=False, out_path=off_out, fps=fps,
                                width=width, height=height, corners=corners,
                                match_id_arg=match_id_arg)
            _log_pass("OFF", off_res)
            logger.info("=== pass 2/2: Swap Guard ON → %s ===", args.out)
            on_res = _run_pass(args, swap_guard=True, out_path=args.out, fps=fps,
                               width=width, height=height, corners=corners,
                               match_id_arg=match_id_arg)
            _log_pass("ON", on_res)
            eval_results["off"] = off_res
            eval_results["on"] = on_res
        else:
            sg_on = args.swap_guard == "on"
            tag = "ON" if sg_on else "OFF"
            logger.info("=== pass: Swap Guard %s → %s ===", tag, args.out)
            res = _run_pass(args, swap_guard=sg_on, out_path=args.out, fps=fps,
                            width=width, height=height, corners=corners,
                            match_id_arg=match_id_arg)
            _log_pass(tag, res)
            eval_results["on" if sg_on else "off"] = res
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 3

    logger.info("出力: %s", args.out)

    # ── proxy 指標 (--eval-metrics) ──────────────────────────────────────
    if args.eval_metrics:
        metrics: dict = {
            "video": args.video,
            "match_type": args.match_type,
            "match_id": args.match_id,
            "start_sec": args.start_sec,
            "duration_sec": args.duration_sec,
            "swap_guard": args.swap_guard,
            "fps": fps,
        }
        evals: dict[str, dict] = {}
        for key, res in eval_results.items():
            evals[key] = track_evaluator.evaluate_run(
                res["records"],
                swap_stats=res["swap_stats"],
                frames=res["frames"],
                seconds=res["seconds"],
            )
        metrics["runs"] = evals
        # both のときは OFF/ON の比較も出す
        if "off" in evals and "on" in evals:
            metrics["comparison"] = track_evaluator.compare_runs(
                evals["off"], evals["on"]
            )

        # 既定: <out のディレクトリ+stem>.metrics.json
        metrics_json = args.metrics_json or (
            os.path.splitext(args.out)[0] + ".metrics.json"
        )
        os.makedirs(os.path.dirname(os.path.abspath(metrics_json)) or ".", exist_ok=True)
        with open(metrics_json, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        logger.info("proxy 指標 JSON: %s", metrics_json)
        for key, ev in evals.items():
            logger.info(
                "[%s] unique_ids_total=%s proxy_idsw_total=%s "
                "swap_detected=%s swap_applied=%s",
                key, ev["unique_ids_total"], ev["proxy_idsw_total"],
                ev["swap_detected"], ev["swap_applied"],
            )
        if "comparison" in metrics:
            d = metrics["comparison"]["delta"]
            logger.info("[ON - OFF] Δunique_ids_total=%+.0f Δproxy_idsw_total=%+.0f",
                        d["unique_ids_total"], d["proxy_idsw_total"])

    return 0


if __name__ == "__main__":
    sys.exit(main())

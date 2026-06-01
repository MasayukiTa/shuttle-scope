"""Offline tracklet-stitching post-processor (ShuttleScope, badminton doubles).

オンライン ByteTrack (config-F) は 30s doubles クリップで ~200+ の raw track_id を
吐き、1 選手の ID が何度も切り替わる。本モジュールはクリップ全体を見渡して
fragment を 4 つの安定 identity (2 per side) に集約する OFFLINE pass。

依存: numpy のみ (CPU)。検出/ReID は collect_tracklets.py が事前に npz/json へ保存済み。

アルゴリズム
------------
1. 背景除去: 各 tracklet について「court 内 (court_id>=0) frame 比率」と「足元座標の
   分散 (motion)」を計算。観客/スコアボード等の静止誤検出は court 外かつほぼ不動
   なので閾値で落とす。
2. side / quadrant anchor: 残った player-fragment の代表 court_id (多数決) を取る。
   court_id 0=FL,1=FR (far side / 上半分)、2=BL,3=BR (near side / 下半分)。
   これが HARD constraint。net を跨ぐ統合は一切しない。
3. 同 quadrant 内の貪欲連結: 各 fragment を開始 frame 順に並べ、既存 identity の
   「最後の fragment」に対し
     - 時間ギャップ  gap = B.start - A.end  <= max_gap_frames
     - 空間連続性    A の終端 centroid を等速外挿した予測点と B.start centroid の距離
                     <= max_jump_px (+ gap に比例した許容)
     - 外見類似      ReID/HSV cosine >= app_thresh (descriptor 利用可能時のみ)
   を満たせば attach。複数候補は cost 最小を採用。
   各 quadrant は最終的に 1 identity に collapse する (hard cap 4)。同サイド 2 選手の
   分離は quadrant が担保する (FL≠BL, FR≠BR)。
4. 出力: raw_track_id -> stable_id (0..3) の dict。背景は -1。

注意: 同ユニフォーム teammate (例 FL と FR が同色) を appearance だけで分けるのは
不可能。本実装は court quadrant (= 物理的な前後左右) で分離するためその限界を回避する。
ただし選手が quadrant を大きく跨いで動く (前後ローテーション) と court_id が
振動するため、多数決 anchor + 連結で吸収する。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

# court_id → stable_id は恒等。0=FL,1=FR,2=BL,3=BR。
N_IDENTITIES = 4
# far side (上半分) = {0,1}, near side (下半分) = {2,3}
SIDE_OF_COURT = {0: 0, 1: 0, 2: 1, 3: 1}


@dataclass
class StitchConfig:
    # 背景除去
    min_court_frac: float = 0.12       # court 内 frame 比率の下限
    min_motion_px: float = 14.0        # 足元座標 std(x)+std(y) の下限 (静止誤検出を落とす)
    # 連結 (同 quadrant 内)
    max_gap_frames: int = 90           # A.end → B.start の最大ギャップ (≈1.5s @60fps)
    max_jump_px: float = 220.0         # 等速外挿予測点と B.start の最大距離
    jump_per_gap_px: float = 1.2       # gap 1 frame あたり許容を加算
    app_thresh: float = 0.55           # appearance cosine 下限 (descriptor 有効時)
    use_appearance: bool = True
    extrap_history: int = 8            # 等速外挿に使う終端 centroid 数


@dataclass
class _Tracklet:
    track_id: int
    start_frame: int
    end_frame: int
    n_frames: int
    dom_court: int
    court_frac: float
    motion: float
    # 時系列 centroid (frame 昇順)
    frames: np.ndarray
    cxs: np.ndarray
    cys: np.ndarray
    rep_emb: Optional[np.ndarray] = None
    is_background: bool = False


def _dominant_court(records) -> tuple[int, float]:
    cids = [r["court_id"] for r in records]
    in_court = [c for c in cids if c >= 0]
    frac = len(in_court) / max(len(cids), 1)
    if not in_court:
        return -1, frac
    vals, counts = np.unique(np.array(in_court), return_counts=True)
    return int(vals[int(np.argmax(counts))]), frac


def load_tracklets(json_path: str | Path, npz_path: Optional[str | Path] = None) -> list[_Tracklet]:
    meta = json.loads(Path(json_path).read_text(encoding="utf-8"))
    emb_by_id: dict[int, np.ndarray] = {}
    if npz_path is not None and Path(npz_path).exists():
        z = np.load(npz_path)
        ids = z["track_ids"]
        embs = z["embeddings"]
        for i, tid in enumerate(ids.tolist()):
            emb_by_id[int(tid)] = embs[i]
    out: list[_Tracklet] = []
    for t in meta["tracklets"]:
        recs = sorted(t["records"], key=lambda r: r["frame"])
        frames = np.array([r["frame"] for r in recs], dtype=np.int64)
        cxs = np.array([r["cx"] for r in recs], dtype=np.float64)
        cys = np.array([r["cy"] for r in recs], dtype=np.float64)
        fxs = np.array([r["fx"] for r in recs], dtype=np.float64)
        fys = np.array([r["fy"] for r in recs], dtype=np.float64)
        dom, frac = _dominant_court(recs)
        motion = float(np.std(fxs) + np.std(fys)) if len(recs) > 1 else 0.0
        out.append(_Tracklet(
            track_id=int(t["track_id"]), start_frame=int(frames.min()),
            end_frame=int(frames.max()), n_frames=len(recs),
            dom_court=dom, court_frac=frac, motion=motion,
            frames=frames, cxs=cxs, cys=cys,
            rep_emb=emb_by_id.get(int(t["track_id"])),
        ))
    return out


def _mark_background(tracklets: list[_Tracklet], cfg: StitchConfig) -> None:
    for t in tracklets:
        # court にほぼ入らない & 動かない → 背景 (観客/固定誤検出)
        if t.dom_court < 0:
            t.is_background = True
        elif t.court_frac < cfg.min_court_frac and t.motion < cfg.min_motion_px:
            t.is_background = True
        elif t.motion < cfg.min_motion_px and t.court_frac < cfg.min_court_frac * 1.5:
            t.is_background = True


def _extrap_end(t: _Tracklet, history: int) -> tuple[float, float, float, float]:
    """終端の (cx, cy) と等速速度 (vx, vy)。frame 単位。"""
    n = len(t.frames)
    if n == 1:
        return t.cxs[-1], t.cys[-1], 0.0, 0.0
    k = min(history, n)
    fr = t.frames[-k:].astype(np.float64)
    cx = t.cxs[-k:]
    cy = t.cys[-k:]
    span = max(fr[-1] - fr[0], 1.0)
    vx = (cx[-1] - cx[0]) / span
    vy = (cy[-1] - cy[0]) / span
    return float(cx[-1]), float(cy[-1]), float(vx), float(vy)


def _cosine(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> Optional[float]:
    if a is None or b is None:
        return None
    a = np.asarray(a, np.float32).ravel(); b = np.asarray(b, np.float32).ravel()
    if a.shape != b.shape or a.size == 0:
        return None
    na = float(np.linalg.norm(a)); nb = float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return None
    return float(np.dot(a, b) / (na * nb))


def stitch(tracklets: list[_Tracklet], cfg: Optional[StitchConfig] = None) -> dict:
    """raw_track_id -> stable_id(0..3) の mapping と診断情報を返す。"""
    cfg = cfg or StitchConfig()
    _mark_background(tracklets, cfg)
    players = [t for t in tracklets if not t.is_background]

    # quadrant ごとに開始 frame 順で貪欲連結。各 identity = 1 quadrant。
    mapping: dict[int, int] = {}
    per_quad_chains: dict[int, list[list[int]]] = {q: [] for q in range(N_IDENTITIES)}

    for q in range(N_IDENTITIES):
        frags = sorted([t for t in players if t.dom_court == q], key=lambda t: t.start_frame)
        # 各 chain は最後尾 fragment を持つ。greedy: fragment を順に既存 chain へ attach。
        chains: list[dict] = []  # {"tail": _Tracklet, "members": [track_id,...]}
        for frag in frags:
            best = None
            best_cost = None
            for ch in chains:
                tail: _Tracklet = ch["tail"]
                gap = frag.start_frame - tail.end_frame
                if gap < 0:
                    continue  # 時間的に重なる別 fragment は同一 chain に繋がない
                if gap > cfg.max_gap_frames:
                    continue
                ex, ey, vx, vy = _extrap_end(tail, cfg.extrap_history)
                px = ex + vx * gap
                py = ey + vy * gap
                dist = float(np.hypot(frag.cxs[0] - px, frag.cys[0] - py))
                allow = cfg.max_jump_px + cfg.jump_per_gap_px * gap
                if dist > allow:
                    continue
                cos = None
                if cfg.use_appearance:
                    cos = _cosine(tail.rep_emb, frag.rep_emb)
                    if cos is not None and cos < cfg.app_thresh:
                        continue
                # cost: 距離 (正規化) + 外見不一致 + gap ペナルティ
                cost = dist / max(allow, 1.0) + (0.0 if cos is None else (1.0 - cos)) + gap / (cfg.max_gap_frames + 1)
                if best_cost is None or cost < best_cost:
                    best_cost = cost
                    best = ch
            if best is None:
                chains.append({"tail": frag, "members": [frag.track_id]})
            else:
                best["members"].append(frag.track_id)
                # tail 更新: より後ろまで延びる fragment を tail に
                if frag.end_frame > best["tail"].end_frame:
                    best["tail"] = frag
        # quadrant 内の全 chain を 1 identity に collapse (hard cap 4)。
        # → quadrant = 物理的な選手位置なので全 fragment は同一選手と見なす。
        for ch in chains:
            per_quad_chains[q].append(ch["members"])
            for tid in ch["members"]:
                mapping[tid] = q

    # 背景は -1
    for t in tracklets:
        if t.is_background and t.track_id not in mapping:
            mapping[t.track_id] = -1

    # 診断
    stable_ids = sorted(set(v for v in mapping.values() if v >= 0))
    per_side = {0: set(), 1: set()}
    for sid in stable_ids:
        per_side[SIDE_OF_COURT[sid]].add(sid)
    diag = {
        "n_tracklets": len(tracklets),
        "n_background": sum(1 for t in tracklets if t.is_background),
        "n_players": len(players),
        "stable_ids": stable_ids,
        "n_stable_ids": len(stable_ids),
        "far_side_ids": sorted(per_side[0]),
        "near_side_ids": sorted(per_side[1]),
        "fragments_per_identity": {q: sum(len(m) for m in per_quad_chains[q]) for q in range(N_IDENTITIES)},
        "n_chains_per_identity": {q: len(per_quad_chains[q]) for q in range(N_IDENTITIES)},
    }
    return {"mapping": mapping, "diag": diag, "config": cfg.__dict__}


# stable_id → 表示用ラベル/色 (A/B/C/D)
STABLE_LABEL = {0: "A", 1: "B", 2: "C", 3: "D"}
STABLE_COLOR_BGR = {
    0: (255, 80, 80),    # A 青系
    1: (80, 220, 80),    # B 緑系
    2: (60, 60, 235),    # C 赤系
    3: (40, 200, 235),   # D 黄系
    -1: (150, 150, 150),
}

"""2 視点のシャトル 2D 追跡 → コート座標系の 3D 軌跡。

入力は「カメラごとの (時刻, 画像座標) の列」。欠測は NaN。
- 2 台のクロックのずれ (offset_sec) を吸収して、カメラ 1 の各時刻にカメラ 2 の点を補間で合わせる
- 補間は前後の両サンプルが有効で、間隔が max_gap_sec 以内の時だけ (欠測をまたいで補間しない)
- 三角測量した点は、再投影誤差・2 本の視線のなす角・コート周辺の範囲で棄却する
  (2 視点は視線が交わる保証が無い。誤検出は再投影誤差に出る。視線がほぼ平行だと奥行きが不安定)
物理 (放物運動) による平滑化や打球点での区間分割は、この上に載せる別段階。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from backend.cv.multiview.court3d import COURT_LENGTH_M, COURT_WIDTH_M
from backend.cv.multiview.triangulate import triangulate_points


@dataclass(frozen=True)
class Shuttle3DPoint:
    t_sec: float          # カメラ 1 の時計
    x: float              # コート座標 (m)。原点 = コート一隅、X=幅、Y=長さ、Z=上
    y: float
    z: float
    residual_px: float    # 2 視点への再投影の平均誤差
    angle_deg: float      # 2 本の視線のなす角


@dataclass
class Shuttle3DResult:
    points: List[Shuttle3DPoint] = field(default_factory=list)
    rejected: Dict[str, int] = field(default_factory=dict)
    candidates: int = 0   # カメラ 1 に有効点があった時刻の数


def camera_center(P: np.ndarray) -> np.ndarray:
    """射影行列 P = [M | p4] のカメラ中心 C = -M^-1 p4。"""
    P = np.asarray(P, dtype=np.float64)
    return -np.linalg.solve(P[:, :3], P[:, 3])


def _project(P: np.ndarray, xyz: np.ndarray) -> np.ndarray:
    hom = np.hstack([xyz, np.ones((len(xyz), 1))])
    proj = (P @ hom.T).T
    return proj[:, :2] / proj[:, 2:3]


def _ray_angles_deg(P1: np.ndarray, P2: np.ndarray, xyz: np.ndarray) -> np.ndarray:
    a = camera_center(P1)[None, :] - xyz
    b = camera_center(P2)[None, :] - xyz
    cos = np.sum(a * b, axis=1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))
    return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))


def sample_track(t: np.ndarray, xy: np.ndarray, t_query: np.ndarray, max_gap_sec: float) -> np.ndarray:
    """追跡 (t, xy) を t_query で線形補間する。前後どちらかが欠測、または間隔が
    max_gap_sec を超える所は NaN。t は昇順。"""
    t = np.asarray(t, dtype=np.float64)
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    out = np.full((len(t_query), 2), np.nan)
    if len(t) == 0:
        return out
    valid = np.isfinite(xy).all(axis=1)
    hi = np.searchsorted(t, t_query, side="left")
    for k, (tq, h) in enumerate(zip(t_query, hi)):
        if h < len(t) and t[h] == tq:
            if valid[h]:
                out[k] = xy[h]
            continue
        lo = h - 1
        if lo < 0 or h >= len(t) or not (valid[lo] and valid[h]):
            continue
        if t[h] - t[lo] > max_gap_sec:
            continue
        w = (tq - t[lo]) / (t[h] - t[lo])
        out[k] = xy[lo] * (1.0 - w) + xy[h] * w
    return out


def triangulate_shuttle(
    P1: np.ndarray,
    P2: np.ndarray,
    t1: np.ndarray,
    xy1: np.ndarray,
    t2: np.ndarray,
    xy2: np.ndarray,
    *,
    offset_sec: float = 0.0,
    max_gap_sec: float = 0.05,
    max_residual_px: float = 3.0,
    min_angle_deg: float = 15.0,
    z_range: Tuple[float, float] = (-0.3, 12.0),
    court_margin_m: float = 4.0,
) -> Shuttle3DResult:
    """カメラ 2 の時計を t2 + offset_sec でカメラ 1 の時計に合わせ、3D 軌跡を返す。"""
    t1 = np.asarray(t1, dtype=np.float64)
    xy1 = np.asarray(xy1, dtype=np.float64).reshape(-1, 2)
    res = Shuttle3DResult(rejected={"no_partner": 0, "residual": 0, "angle": 0, "out_of_range": 0})

    ok1 = np.isfinite(xy1).all(axis=1)
    res.candidates = int(ok1.sum())
    tq = t1[ok1]
    p1 = xy1[ok1]
    p2 = sample_track(np.asarray(t2, dtype=np.float64) + offset_sec, xy2, tq, max_gap_sec)
    have = np.isfinite(p2).all(axis=1)
    res.rejected["no_partner"] = int((~have).sum())
    if not have.any():
        return res
    tq, p1, p2 = tq[have], p1[have], p2[have]

    xyz = triangulate_points(P1, P2, p1, p2)
    resid = 0.5 * (np.linalg.norm(_project(P1, xyz) - p1, axis=1)
                   + np.linalg.norm(_project(P2, xyz) - p2, axis=1))
    angle = _ray_angles_deg(P1, P2, xyz)

    in_range = (
        (xyz[:, 2] >= z_range[0]) & (xyz[:, 2] <= z_range[1])
        & (xyz[:, 0] >= -court_margin_m) & (xyz[:, 0] <= COURT_WIDTH_M + court_margin_m)
        & (xyz[:, 1] >= -court_margin_m) & (xyz[:, 1] <= COURT_LENGTH_M + court_margin_m)
    )
    keep = np.ones(len(tq), dtype=bool)
    for name, bad in (("out_of_range", ~in_range), ("residual", resid > max_residual_px),
                      ("angle", angle < min_angle_deg)):
        newly = keep & bad
        res.rejected[name] += int(newly.sum())
        keep &= ~bad

    for k in np.nonzero(keep)[0]:
        res.points.append(Shuttle3DPoint(
            t_sec=float(tq[k]), x=float(xyz[k, 0]), y=float(xyz[k, 1]), z=float(xyz[k, 2]),
            residual_px=float(resid[k]), angle_deg=float(angle[k])))
    return res

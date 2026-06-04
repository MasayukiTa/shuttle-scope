"""既知のバドミントンコート寸法を calibration ターゲットにした単カメラ校正。

コートは世界標準の固定寸法 (ダブルス 13.40m × 6.10m) なので、各カメラの画像内
4 隅 (court_calibration の roi_polygon) を 3D コート座標に対応づけて solvePnP すれば、
そのカメラの外部パラメータ (R, t) と射影行列 P が得られる。両カメラを同じコート
世界系に乗せれば相対幾何が確定し、三角測量で 3D 復元できる。
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

# バドミントン コート寸法 (m)。原点 = コート一隅、X=幅方向, Y=長さ方向, Z=上。
COURT_WIDTH_M = 6.10    # ダブルスサイドライン間
COURT_LENGTH_M = 13.40  # バックバウンダリライン間

# 画像 4 隅の順序は court_calibration.roi_polygon = TL, TR, BR, BL に合わせる。
COURT_CORNERS_3D = np.array(
    [
        [0.0, 0.0, 0.0],                      # TL
        [COURT_WIDTH_M, 0.0, 0.0],            # TR
        [COURT_WIDTH_M, COURT_LENGTH_M, 0.0],  # BR
        [0.0, COURT_LENGTH_M, 0.0],            # BL
    ],
    dtype=np.float64,
)


def estimate_intrinsics(width: int, height: int, fov_deg: float = 60.0) -> np.ndarray:
    """内部パラメータ K を画角から概算する (校正データが無い時の既定)。

    f = (W/2) / tan(fov/2)、主点 = 画像中心。
    """
    f = (width / 2.0) / np.tan(np.deg2rad(fov_deg) / 2.0)
    return np.array([[f, 0, width / 2.0], [0, f, height / 2.0], [0, 0, 1]], dtype=np.float64)


def calibrate_camera_from_court(
    image_corners_px: np.ndarray,
    width: int,
    height: int,
    K: Optional[np.ndarray] = None,
    dist: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """画像内コート 4 隅 (px, 順序 TL,TR,BR,BL) からカメラ姿勢と射影行列を求める。

    返り値: (rvec, tvec, K, P)  P = K @ [R|t] (3x4)。
    平面 (coplanar) 4 点なので solvePnP は IPPE (一般平面) で安定化する。
    コートは矩形 (非正方形) のため IPPE_SQUARE ではなく IPPE を使う。
    """
    if cv2 is None:  # pragma: no cover
        raise RuntimeError("cv2 (opencv) required for calibration")
    image_corners_px = np.asarray(image_corners_px, dtype=np.float64).reshape(4, 2)
    if K is None:
        K = estimate_intrinsics(width, height)
    if dist is None:
        dist = np.zeros((4, 1), dtype=np.float64)
    # IPPE は平面で 2 解 (ambiguity) を返す。両方を取り、入力4隅への再投影誤差が
    # 最小の解を選ぶ (悪い方の解だと巨大な reprojection になるため必須)。
    retval, rvecs, tvecs, _ = cv2.solvePnPGeneric(
        COURT_CORNERS_3D, image_corners_px, K, dist, flags=cv2.SOLVEPNP_IPPE
    )
    if not retval or not len(rvecs):
        raise RuntimeError("solvePnP failed for court corners")

    def _P_of(rv, tv):
        R, _ = cv2.Rodrigues(rv)
        return K @ np.hstack([R, tv.reshape(3, 1)])

    errs = [reprojection_error(_P_of(rv, tv), COURT_CORNERS_3D, image_corners_px)
            for rv, tv in zip(rvecs, tvecs)]
    best = int(np.argmin(errs))
    rvec, tvec = rvecs[best], tvecs[best]
    P = _P_of(rvec, tvec)
    return rvec, tvec, K, P


def reprojection_error(P: np.ndarray, pts_3d: np.ndarray, pts_2d: np.ndarray) -> float:
    """射影行列 P で 3D→2D 再投影し、与えた 2D との平均ピクセル誤差を返す (校正品質指標)。"""
    pts_3d = np.asarray(pts_3d, dtype=np.float64).reshape(-1, 3)
    pts_2d = np.asarray(pts_2d, dtype=np.float64).reshape(-1, 2)
    hom = np.hstack([pts_3d, np.ones((len(pts_3d), 1))])
    proj = (P @ hom.T).T
    proj = proj[:, :2] / proj[:, 2:3]
    return float(np.mean(np.linalg.norm(proj - pts_2d, axis=1)))

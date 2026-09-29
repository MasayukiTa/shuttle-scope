"""2 視点の射影行列 + 対応 2D 点 → 3D 復元 (三角測量)。"""
from __future__ import annotations

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


def triangulate_points(P1: np.ndarray, P2: np.ndarray,
                       pts1: np.ndarray, pts2: np.ndarray) -> np.ndarray:
    """同期した 2 視点の対応点を三角測量して 3D 点 (N,3) を返す。

    P1,P2: 3x4 射影行列 (court3d.calibrate_camera_from_court の P)。同じコート世界系。
    pts1,pts2: (N,2) 画像座標 (px)。同一インデックスが対応点。
    """
    pts1 = np.asarray(pts1, dtype=np.float64).reshape(-1, 2)
    pts2 = np.asarray(pts2, dtype=np.float64).reshape(-1, 2)
    if pts1.shape != pts2.shape:
        raise ValueError("pts1 と pts2 の形状が一致しません")
    if cv2 is not None:
        hom = cv2.triangulatePoints(P1, P2, pts1.T, pts2.T)  # 4xN
        xyz = (hom[:3] / hom[3:4]).T
        return xyz
    # cv2 が無い環境向け純 numpy DLT fallback (テスト/移植性)
    out = np.empty((len(pts1), 3), dtype=np.float64)
    for i in range(len(pts1)):
        x1, y1 = pts1[i]
        x2, y2 = pts2[i]
        A = np.vstack([
            x1 * P1[2] - P1[0],
            y1 * P1[2] - P1[1],
            x2 * P2[2] - P2[0],
            y2 * P2[2] - P2[1],
        ])
        _, _, vt = np.linalg.svd(A)
        X = vt[-1]
        out[i] = X[:3] / X[3]
    return out


def triangulation_residual(P1: np.ndarray, P2: np.ndarray,
                           pts1: np.ndarray, pts2: np.ndarray,
                           xyz: np.ndarray) -> float:
    """復元 3D を両カメラへ再投影した平均 px 誤差 (3D 推定の信頼度指標)。"""
    xyz = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    hom = np.hstack([xyz, np.ones((len(xyz), 1))])
    err = 0.0
    for P, pts in ((P1, pts1), (P2, pts2)):
        proj = (P @ hom.T).T
        proj = proj[:, :2] / proj[:, 2:3]
        err += float(np.mean(np.linalg.norm(proj - np.asarray(pts).reshape(-1, 2), axis=1)))
    return err / 2.0

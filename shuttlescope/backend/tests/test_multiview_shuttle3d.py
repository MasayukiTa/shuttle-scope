"""2 視点シャトル 3D (shuttle3d) を、既知の軌道を仮想 2 カメラで撮って検証する。

カメラ校正はコート 4 隅 → solvePnP の実経路を通す (K は真値と同じ推定値)。
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from backend.cv.multiview.court3d import (  # noqa: E402
    COURT_CORNERS_3D, calibrate_camera_from_court, estimate_intrinsics,
)
from backend.cv.multiview.shuttle3d import (  # noqa: E402
    camera_center, sample_track, triangulate_shuttle,
)

W, H = 1920, 1080
FPS = 30.0
G = 9.8


def _camera(pos, target):
    """位置 pos から target を見る真のカメラ (rvec, tvec, K, P)。"""
    K = estimate_intrinsics(W, H)
    pos = np.asarray(pos, float)
    fwd = np.asarray(target, float) - pos
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    R = np.vstack([right, down, fwd])
    t = -R @ pos
    return K @ np.hstack([R, t.reshape(3, 1)])


def _px(P, xyz):
    hom = np.hstack([xyz, np.ones((len(xyz), 1))])
    p = (P @ hom.T).T
    return p[:, :2] / p[:, 2:3]


def _calibrated(P_true):
    """真のカメラが見る 4 隅から、実際の校正経路で P を復元する。"""
    corners = _px(P_true, COURT_CORNERS_3D)
    return calibrate_camera_from_court(corners, W, H)[3]


@pytest.fixture(scope="module")
def rig():
    Pa = _camera((3.05, -7.0, 4.5), (3.05, 6.7, 1.0))    # コート後方 (長さ方向)
    Pb = _camera((-8.0, 6.7, 4.5), (3.05, 6.7, 1.0))     # コート側方 (幅方向)
    return Pa, Pb, _calibrated(Pa), _calibrated(Pb)


def _trajectory():
    t = np.arange(0.0, 1.1, 1.0 / 120.0)
    v0 = np.array([1.2, 9.0, 4.0])
    p0 = np.array([1.5, 2.0, 2.2])
    xyz = p0[None, :] + t[:, None] * v0[None, :]
    xyz[:, 2] -= 0.5 * G * t ** 2
    keep = xyz[:, 2] > 0.0
    return t[keep], xyz[keep]


def _detections(P_true, t_true, xyz, t_cam, rng, noise_px, drop, outlier_rate):
    """t_cam の各時刻にシャトルを撮影し、ノイズ・欠測・外れ値を入れる。"""
    # カメラ時刻の真の位置は、真値の軌道を時刻補間したもの
    pos = np.column_stack([np.interp(t_cam, t_true, xyz[:, k]) for k in range(3)])
    xy = _px(P_true, pos) + rng.normal(0.0, noise_px, (len(t_cam), 2))
    gone = rng.random(len(t_cam)) < drop
    bad = rng.random(len(t_cam)) < outlier_rate
    xy[bad] += rng.normal(0.0, 120.0, (bad.sum(), 2))
    xy[gone] = np.nan
    return xy, pos


def _run(rig, offset_true=0.0, offset_used=0.0, noise=0.7, drop=0.3, outlier=0.05, seed=0):
    Pa_true, Pb_true, Pa, Pb = rig
    rng = np.random.default_rng(seed)
    t_true, xyz = _trajectory()
    t1 = np.arange(0.0, t_true[-1], 1.0 / FPS)
    # カメラ 2 の時計は真の時刻より offset_true 進んでいる: t2 = t_true + offset_true
    t2_true_time = np.arange(0.0, t_true[-1], 1.0 / FPS)
    xy1, pos1 = _detections(Pa_true, t_true, xyz, t1, rng, noise, drop, outlier)
    xy2, _ = _detections(Pb_true, t_true, xyz, t2_true_time, rng, noise, drop, outlier)
    t2 = t2_true_time + offset_true
    res = triangulate_shuttle(Pa, Pb, t1, xy1, t2, xy2, offset_sec=-offset_used)
    err = []
    for p in res.points:
        truth = np.array([np.interp(p.t_sec, t_true, xyz[:, k]) for k in range(3)])
        err.append(np.linalg.norm(np.array([p.x, p.y, p.z]) - truth))
    return res, np.asarray(err)


class TestCalibrationRoundTrip:
    def test_camera_center_recovered(self, rig):
        Pa_true, _, Pa, _ = rig
        assert np.allclose(camera_center(Pa), camera_center(Pa_true), atol=0.05)


class TestSampleTrack:
    def test_no_interpolation_across_a_gap(self):
        t = np.array([0.0, 0.1, 0.2])
        xy = np.array([[0, 0], [np.nan, np.nan], [20, 0]], float)
        out = sample_track(t, xy, np.array([0.05, 0.15]), max_gap_sec=0.15)
        assert np.isnan(out).all()

    def test_interpolates_between_valid_neighbours(self):
        t = np.array([0.0, 0.1])
        xy = np.array([[0, 0], [10, 20]], float)
        out = sample_track(t, xy, np.array([0.025]), max_gap_sec=0.15)
        assert np.allclose(out[0], [2.5, 5.0])


class TestShuttle3D:
    def test_recovers_known_trajectory(self, rig):
        res, err = _run(rig)
        assert len(res.points) >= 10
        assert np.median(err) < 0.10          # 中央値 10cm 未満
        assert np.percentile(err, 95) < 0.30  # 外れ値が混ざっても大崩れしない

    def test_gross_outliers_are_rejected_not_reported(self, rig):
        res, err = _run(rig, outlier=0.25, seed=3)
        assert res.rejected["residual"] > 0
        assert np.percentile(err, 95) < 0.40

    def test_wrong_clock_offset_makes_it_worse(self, rig):
        _, good = _run(rig, offset_true=0.5 / FPS, offset_used=0.5 / FPS, drop=0.0, outlier=0.0)
        _, bad = _run(rig, offset_true=0.5 / FPS, offset_used=0.0, drop=0.0, outlier=0.0)
        assert np.median(bad) > 2.0 * np.median(good)

    def test_nearly_parallel_views_are_rejected_by_angle(self, rig):
        Pa_true, _, Pa, _ = rig
        # 同じ場所からほぼ同じ向き = 視線がほぼ平行
        Pn_true = _camera((3.5, -7.0, 4.5), (3.05, 6.7, 1.0))
        Pn = _calibrated(Pn_true)
        t_true, xyz = _trajectory()
        t = np.arange(0.0, t_true[-1], 1.0 / FPS)
        pos = np.column_stack([np.interp(t, t_true, xyz[:, k]) for k in range(3)])
        res = triangulate_shuttle(Pa, Pn, t, _px(Pa_true, pos), t, _px(Pn_true, pos))
        assert res.rejected["angle"] > 0
        assert len(res.points) < res.candidates

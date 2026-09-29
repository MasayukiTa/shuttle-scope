"""INFRA Phase D: cluster.pipeline のミニクラスタ動作テスト

ray 未インストール環境では丸ごとスキップ。
"""
from __future__ import annotations

import importlib

import pytest

ray = pytest.importorskip("ray", reason="ray 未インストール環境ではスキップ")


@pytest.fixture()
def ray_local():
    """ray.init(local_mode=True) によるミニクラスタ"""
    if ray.is_initialized():
        ray.shutdown()
    ray.init(local_mode=True, include_dashboard=False, ignore_reinit_error=True)
    yield
    ray.shutdown()


def test_run_video_analysis_pipeline_local(ray_local, monkeypatch):
    """run_video_analysis_pipeline がミニクラスタ上で完走することを確認"""
    from backend.cluster import pipeline as cluster_pipeline
    # tasks を import し直して ray.remote を再付与した状態にする
    from backend.cluster import tasks as cluster_tasks
    importlib.reload(cluster_tasks)
    importlib.reload(cluster_pipeline)

    monkeypatch.setattr(cluster_pipeline.settings, "ss_cluster_mode", "ray", raising=False)

    result = cluster_pipeline.run_video_analysis_pipeline(video_id=1, video_path="dummy.mp4")

    assert isinstance(result, dict)
    assert result["video_id"] == 1
    # 各ステージが存在すること (中身は mock/skipped でも可)
    for key in ("tracknet", "mediapipe", "clips", "statistics", "center_of_gravity", "shots"):
        assert key in result

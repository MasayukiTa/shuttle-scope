"""ベンチマーク用デバイス自動検出システムのテスト。

確認事項:
  - probe_all() が常に 1 件以上 (CPU) を返すこと
  - available=True のデバイスが 1 件以上あること
  - pynvml / openvino 未インストールでも probe_all() が例外を投げないこと
  - POST /v1/benchmark/run → job_id が返ること
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ─── probe_all() ユニットテスト ────────────────────────────────────────────────

class TestProbeAll:
    def setup_method(self):
        """テストごとにキャッシュをクリアして純粋な結果を確認する"""
        from backend.benchmark.devices import invalidate_cache
        invalidate_cache()

    def test_returns_at_least_one_device(self):
        """CPU が必ず 1 件以上含まれること"""
        from backend.benchmark.devices import probe_all
        devices = probe_all()
        assert len(devices) >= 1

    def test_cpu_device_included(self):
        """device_type='cpu' のデバイスが存在すること"""
        from backend.benchmark.devices import probe_all
        devices = probe_all()
        cpu_devices = [d for d in devices if d.device_type == "cpu"]
        assert len(cpu_devices) >= 1, "CPU デバイスが検出されていません"

    def test_at_least_one_available(self):
        """available=True のデバイスが 1 件以上あること"""
        from backend.benchmark.devices import probe_all
        devices = probe_all()
        available = [d for d in devices if d.available]
        assert len(available) >= 1, "available=True のデバイスが存在しません"

    def test_no_exception_without_pynvml(self, monkeypatch):
        """pynvml が未インストールでも例外を投げないこと"""
        import sys
        # pynvml をインポート不能にする
        monkeypatch.setitem(sys.modules, "pynvml", None)
        from backend.benchmark.devices import probe_all, invalidate_cache
        invalidate_cache()
        # 例外なく実行できることを確認
        devices = probe_all()
        assert len(devices) >= 1

    def test_no_exception_without_openvino(self, monkeypatch):
        """openvino が未インストールでも例外を投げないこと"""
        import sys
        monkeypatch.setitem(sys.modules, "openvino", None)
        monkeypatch.setitem(sys.modules, "openvino.runtime", None)
        from backend.benchmark.devices import probe_all, invalidate_cache
        invalidate_cache()
        devices = probe_all()
        assert len(devices) >= 1

    def test_device_fields_present(self):
        """各デバイスに必須フィールドが存在すること"""
        from backend.benchmark.devices import probe_all
        devices = probe_all()
        for d in devices:
            assert d.device_id, f"device_id が空: {d}"
            assert d.label, f"label が空: {d}"
            assert d.device_type in ("cpu", "igpu", "dgpu", "ray_worker"), \
                f"不正な device_type: {d.device_type}"
            assert isinstance(d.available, bool), f"available が bool でない: {d}"
            assert isinstance(d.specs, dict), f"specs が dict でない: {d}"

    def test_cache_returns_same_result(self):
        """2 回目の呼び出しがキャッシュから同じ結果を返すこと"""
        from backend.benchmark.devices import probe_all
        first = probe_all()
        second = probe_all()
        assert len(first) == len(second)
        assert [d.device_id for d in first] == [d.device_id for d in second]


# ─── API エンドポイントテスト ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client(test_engine):
    """FastAPI テストクライアント（インメモリ DB 使用）"""
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestBenchmarkAPI:
    def test_get_devices_returns_list(self, client):
        """GET /api/v1/benchmark/devices が配列を返すこと"""
        resp = client.get("/api/v1/benchmark/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_devices_cpu_present(self, client):
        """CPU デバイスが含まれること"""
        resp = client.get("/api/v1/benchmark/devices")
        assert resp.status_code == 200
        data = resp.json()
        cpu_devices = [d for d in data if d.get("device_type") == "cpu"]
        assert len(cpu_devices) >= 1

    def test_post_run_returns_job_id(self, client):
        """POST /api/v1/benchmark/run が job_id を返すこと"""
        # まずデバイス一覧を取得して device_id を特定する
        resp = client.get("/api/v1/benchmark/devices")
        assert resp.status_code == 200
        devices = resp.json()
        device_id = devices[0]["device_id"]

        # ジョブ実行リクエスト
        resp = client.post("/api/v1/benchmark/run", json={
            "device_ids": [device_id],
            "targets": ["statistics"],
            "n_frames": 5,
        })
        assert resp.status_code in (200, 202), f"Unexpected status: {resp.status_code} {resp.text}"
        data = resp.json()
        assert "job_id" in data, f"job_id がレスポンスに含まれない: {data}"
        assert data["job_id"], "job_id が空"

    def test_get_job_status(self, client):
        """GET /api/v1/benchmark/jobs/{job_id} がジョブ状態を返すこと"""
        # ジョブを作成
        resp = client.get("/api/v1/benchmark/devices")
        device_id = resp.json()[0]["device_id"]

        run_resp = client.post("/api/v1/benchmark/run", json={
            "device_ids": [device_id],
            "targets": ["statistics"],
            "n_frames": 3,
        })
        job_id = run_resp.json()["job_id"]

        # ジョブ状態を確認
        status_resp = client.get(f"/api/v1/benchmark/jobs/{job_id}")
        assert status_resp.status_code == 200
        job_data = status_resp.json()
        assert job_data["job_id"] == job_id
        assert job_data["status"] in ("pending", "running", "done", "failed")
        assert 0.0 <= job_data["progress"] <= 1.0

    def test_get_nonexistent_job_returns_404(self, client):
        """存在しない job_id は 404 を返すこと"""
        resp = client.get("/api/v1/benchmark/jobs/nonexistent-job-id-12345")
        assert resp.status_code == 404

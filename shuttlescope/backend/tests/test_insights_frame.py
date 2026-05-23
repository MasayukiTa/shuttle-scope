"""Growth Snapshot insights frame: backend tests.

- TemplateGenerator が >=1 item を返す
- ExternalApiGenerator (env 未設定) は NotImplementedError
- factory('nvidia') は env 未設定でも template にフォールバック
- HTTP endpoint が 200 + items を返す
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend.analysis.insights import (
    ExternalApiGenerator,
    TemplateGenerator,
    get_generator,
)
from backend.main import app
from backend.utils.auth import AuthCtx, get_auth


def _admin_auth_ctx():
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


def _sample_analytics():
    return {
        "shot_win_loss": [
            {"shot": "smash", "win_rate": 0.6, "delta_pp": 3.0,
             "sample_n": 100, "alt_shot": "drop"},
        ],
        "recent_form": {"win_rate": 0.55, "delta_pp": 4.0, "sample_n": 50},
        "growth_timeline_delta": {
            "metric": "serve_win_rate", "delta_pp": 2.0, "sample_n": 60,
        },
    }


def test_template_generator_emits_items():
    gen = TemplateGenerator()
    ctx = {
        "player_id": 12,
        "period_days": 30,
        "analytics": _sample_analytics(),
        "role": "player",
        "lang": "ja",
    }
    result = gen.generate(ctx)
    assert result["generator"] == "template"
    assert len(result["items"]) >= 1
    # 選手安全: 弱点 / weakness を含まない
    for it in result["items"]:
        assert "弱点" not in it["prose"]
        assert "weakness" not in it["prose"].lower()
        assert 0.0 <= it["confidence"] <= 1.0


def test_template_generator_english():
    gen = TemplateGenerator()
    ctx = {
        "player_id": 12,
        "period_days": 30,
        "analytics": _sample_analytics(),
        "role": "player",
        "lang": "en",
    }
    result = gen.generate(ctx)
    assert len(result["items"]) >= 1
    for it in result["items"]:
        assert "weakness" not in it["prose"].lower()


def test_external_stub_unconfigured_raises(monkeypatch):
    """env 未設定なら構築時点で NotImplementedError → factory が template に倒す。"""
    monkeypatch.delenv("NVIDIA_NIM_ENDPOINT", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
    with pytest.raises(NotImplementedError):
        ExternalApiGenerator(
            "nvidia",
            endpoint_env="NVIDIA_NIM_ENDPOINT",
            api_key_env="NVIDIA_NIM_API_KEY",
        )


def test_factory_nvidia_falls_back_to_template(monkeypatch):
    monkeypatch.delenv("NVIDIA_NIM_ENDPOINT", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    gen = get_generator("nvidia")
    result = gen.generate({
        "player_id": 12,
        "period_days": 30,
        "analytics": _sample_analytics(),
        "role": "player",
        "lang": "ja",
    })
    # フォールバック先 = template
    assert result["generator"] == "template"
    assert len(result["items"]) >= 1


def test_http_growth_snapshot_endpoint():
    app.dependency_overrides[get_auth] = _admin_auth_ctx
    try:
        # TrustedHostMiddleware が testserver を拒否するため localhost を使う
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(
            "/api/insights/growth_snapshot",
            params={"player_id": 12, "period_days": 30, "lang": "ja"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "items" in body
        assert isinstance(body["items"], list)
        assert body.get("generator")
        assert body["meta"]["disclaimer"] == "template-generated; LLM-pluggable"
    finally:
        app.dependency_overrides.pop(get_auth, None)

"""NvidiaNimGenerator (ExternalApiGenerator) のユニットテスト。"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import httpx
import pytest

from backend.analysis.insights import external_stub
from backend.analysis.insights.external_stub import (
    ExternalApiGenerator,
    _confidence_heuristic,
)


@pytest.fixture
def env_key(monkeypatch):
    # ダミー鍵。先頭を実鍵プレフィックス (nvapi-) にすると secret スキャナ
    # (Trivy secret / Gitleaks の nvidia-nim-api-key ルール) が誤検知するため、
    # プレフィックスを避けた固定文字列を使う。生成器は鍵の「存在」のみ確認する。
    monkeypatch.setenv("NVIDIA_API_KEY", "DUMMY_NVIDIA_KEY_FOR_TESTS")
    monkeypatch.setenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
    yield


def _ctx(sample_n: int = 10) -> dict:
    return {
        "player_id": 1,
        "period_days": 30,
        "role": "player",
        "lang": "ja",
        # 2026-05-25: ExternalApiGenerator が intent 分類するようになったので
        # user_text を入れないと「nonsense (空入力)」で短絡され NIM が呼ばれない。
        "user_text": "直近の伸びしろを教えて",
        "analytics": {
            "recent_form": {
                "win_rate": 0.58,
                "delta_pp": 4.0,
                "sample_n": sample_n,
            }
        },
    }


def _mock_response(status: int, json_body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = json_body or {}
    if status >= 400:
        req = httpx.Request("POST", "https://x/v1/chat/completions")
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"http {status}", request=req, response=httpx.Response(status, request=req)
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_no_env_key_raises_not_implemented(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(NotImplementedError):
        ExternalApiGenerator("nvidia")


def test_success_returns_insight_result(env_key):
    body = {
        "choices": [
            {"message": {"content": "直近30日の勝率は58% (N=30)。次の伸びしろはネット前です。"}}
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
    }
    gen = ExternalApiGenerator("nvidia")
    with patch.object(httpx.Client, "post", return_value=_mock_response(200, body)):
        result = gen.generate(_ctx(sample_n=50))

    assert result["generator"] == "nvidia:meta/llama-3.3-70b-instruct"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert "勝率" in item["prose"]
    assert item["id"] == "growth_main"
    assert 0.79 < item["confidence"] <= 0.85  # sample_n>=30 → 0.8
    assert result["meta"]["tokens"]["total"] == 160  # type: ignore[typeddict-item]


def test_http_401_raises_http_status_error(env_key):
    gen = ExternalApiGenerator("nvidia")
    with patch.object(httpx.Client, "post", return_value=_mock_response(401, {"error": "x"})):
        with pytest.raises(httpx.HTTPStatusError):
            gen.generate(_ctx())


def test_timeout_propagates(env_key):
    gen = ExternalApiGenerator("nvidia")
    with patch.object(
        httpx.Client, "post",
        side_effect=httpx.ReadTimeout("timeout"),
    ):
        with pytest.raises(httpx.ReadTimeout):
            gen.generate(_ctx())


def test_connect_error_retries_then_raises(env_key):
    gen = ExternalApiGenerator("nvidia")
    with patch.object(
        httpx.Client, "post",
        side_effect=httpx.ConnectError("no route"),
    ) as mock_post:
        with pytest.raises(httpx.ConnectError):
            gen.generate(_ctx())
    # 3 attempts (initial + 2 retries)
    assert mock_post.call_count == 3


def test_confidence_heuristic_bounds():
    # 小サンプル → 0.6
    assert _confidence_heuristic({"x": {"sample_n": 5}}) == pytest.approx(0.6)
    # >=30 → 0.8
    assert _confidence_heuristic({"x": {"sample_n": 50}}) == pytest.approx(0.8)
    # 巨大サンプル → 0.85 cap (現実装は 0.6+0.2=0.8 が上限挙動だが cap は 0.85 で安全側)
    assert _confidence_heuristic({"x": {"sample_n": 100000}}) <= 0.85
    # 空 analytics
    assert _confidence_heuristic({}) == pytest.approx(0.6)


def test_factory_returns_template_without_env(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("INSIGHT_GENERATOR", "nvidia")
    from backend.analysis.insights.factory import get_generator
    gen = get_generator("nvidia")
    assert type(gen).__name__ == "TemplateGenerator"


def test_factory_returns_harnessed_with_env(env_key, monkeypatch):
    monkeypatch.setenv("INSIGHT_GENERATOR", "nvidia")
    from backend.analysis.insights.factory import get_generator
    gen = get_generator("nvidia")
    assert type(gen).__name__ == "HarnessedGenerator"

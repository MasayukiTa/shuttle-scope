"""NvidiaNimGenerator (ExternalApiGenerator) のユニットテスト。"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import httpx
import pytest

from backend.analysis.insights import external_stub
from backend.analysis.insights.external_stub import (
    ExternalApiGenerator,
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
    # 言語モデルの自由文に信頼度を付けない (下の専用テストを参照)
    assert item["confidence"] is None
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


def test_the_model_output_carries_no_confidence_number():
    """言語モデルの自由文に信頼度を付けない。

    旧実装は `0.6 (+0.2 if sample_n>=30)` を `InsightItem.confidence` に入れて
    いた。0.6 も 0.8 も何かを測った値ではないのに、UI
    (`ChatMessageBubble.tsx`) は数値を見れば「信頼度 80%」と描く。
    裏取りの済んでいない文章が、いちばん信用できそうな見た目で出ていた。
    N を読者に伝えるのは prose 側 (プロンプトが N=<count> を要求する)。
    """
    assert not hasattr(external_stub, "_confidence_heuristic")


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


# ── 社外へ出るリクエストボディの中身 ──────────────────────────────────────

def _summary_shaped_ctx() -> dict:
    """player_summary_service が組み立てる実際の形に合わせた analytics。

    旧テストの `_ctx` は古い schema (recent_form 等) を使っており、
    **識別子も健康データも含まないので、この漏れを検出できなかった。**
    実際に NIM へ渡っていたのは下の形。
    """
    return {
        "player_id": 1,
        "period_days": 30,
        "role": "coach",
        "lang": "ja",
        "user_text": "直近の伸びしろを教えて",
        "analytics": {
            "player_id": 77,
            "player_name": "山田 太郎",
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "sample": {"matches": 12, "rallies": 900, "strokes": 6800},
            "outcomes": {"win_rate": 0.58, "set_win_rate": 0.55, "n": 12},
            "shot_mix": [{"shot_type": "smash", "count": 100, "share": 0.1}],
            "zones": {"hit_top": [], "land_top": []},
            "conditions": {"avg_rpe": 6.4, "avg_hooper": 11.2, "n": 20},
            "recent_trend": {"last_5_match_win_rate": 0.6, "delta_vs_prior_5": 0.05},
        },
    }


def _captured_request_body(env_key_unused=None):
    """generate() が実際に送信したボディを捕まえる。"""
    body = {
        "choices": [{"message": {"content": "直近の勝率は58% (N=12)。"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    gen = ExternalApiGenerator("nvidia")
    captured: dict = {}

    def _fake_post(self, url, **kwargs):  # noqa: ANN001
        captured["json"] = kwargs.get("json")
        return _mock_response(200, body)

    with patch.object(httpx.Client, "post", _fake_post):
        result = gen.generate(_summary_shaped_ctx())
    return captured["json"], result


def test_player_name_is_not_sent_to_the_external_model(env_key):
    """個人が特定できる名前を社外へ出さないこと。

    これが漏れていた。consents/ の同意書は Coach という**役割**への開示を
    定めているだけで、第三者への送信を許す条項は無い。
    """
    sent, _ = _captured_request_body()
    serialized = str(sent)
    assert "山田 太郎" not in serialized, "選手名が外部 API のボディに入っている"


def test_raw_wellness_scores_are_not_sent_to_the_external_model(env_key):
    """生の RPE / Hooper は Tier 2 の Sensitive Health Data。社外へ出さない。"""
    sent, _ = _captured_request_body()
    serialized = str(sent)
    assert "6.4" not in serialized, "avg_rpe が外部 API のボディに入っている"
    assert "11.2" not in serialized, "avg_hooper が外部 API のボディに入っている"
    assert "conditions" not in serialized


def test_match_statistics_are_still_sent(env_key):
    """伏せすぎていないこと。試合統計は insight の題材そのもの。"""
    sent, _ = _captured_request_body()
    serialized = str(sent)
    assert "outcomes" in serialized
    assert "shot_mix" in serialized
    assert "0.58" in serialized


def test_validator_allowed_numbers_match_what_the_model_saw(env_key):
    """返る metric が送信ペイロードと一致すること。

    metric は output_validators の「許容される数値」の集合でもある。
    モデルが見ていない数値をここに入れると、**その値に一致した幻覚を
    「裏が取れた」と判定してしまう**ので、送信内容と揃っている必要がある。
    """
    import json as _json

    sent, result = _captured_request_body()
    metric = result["items"][0]["metric"]
    assert "player_name" not in metric
    assert "conditions" not in metric
    assert "outcomes" in metric

    # 送信ボディの analytics と、返った metric が同一であること
    sent_analytics = _json.loads(sent["messages"][1]["content"])["analytics"]
    assert metric == sent_analytics


def test_unknown_keys_are_dropped_not_forwarded():
    """allow-list であること。サマリにキーが増えても黙って外へ出ないこと。"""
    from backend.utils.field_sensitivity import redact_for_external_processor

    out = redact_for_external_processor(
        {"outcomes": {"win_rate": 0.5}, "future_sensitive_field": "secret"}
    )
    assert "outcomes" in out
    assert "future_sensitive_field" not in out

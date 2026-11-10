"""LLM chat: a provider failure reaches the client as a stable code, never as raw text.

The SSE error event used to carry one fixed sentence for every failure, so a
timeout, a rejected key and an upstream outage looked the same. It now carries a
short code the client translates, and never the exception text, URL or key.
"""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.utils.jwt_utils import create_access_token

LEAK = "https://provider.invalid/v1/chat/completions key=fake-secret-value"


def _hdr(uid: int, role: str):
    return {"Authorization": f"Bearer {create_access_token(user_id=uid, role=role, minutes=10)}"}


def _status_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    return httpx.HTTPStatusError(LEAK, request=req, response=httpx.Response(status, request=req))


def _events(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            out.append(json.loads(block[5:].strip()))
    return out


def _run_failing_stream(monkeypatch, exc: BaseException, uid: int) -> list[dict]:
    import backend.routers.llm_chat as llm_chat

    class _FailingProvider:
        name = "fake"
        model = "fake-model"

        def stream_chat(self, *_args, **_kwargs):
            raise exc
            yield  # pragma: no cover - makes this a generator

    llm_chat._last_req.clear()
    monkeypatch.setattr(llm_chat, "provider_configured", lambda: True)
    monkeypatch.setattr(llm_chat, "default_chat_model", lambda: "fake-model")
    monkeypatch.setattr(llm_chat, "allowed_chat_model_ids", lambda: {"fake-model"})
    monkeypatch.setattr(llm_chat, "get_provider", lambda **_kwargs: _FailingProvider())
    monkeypatch.setattr(llm_chat, "tool_definitions", lambda: None)
    monkeypatch.setattr(
        llm_chat,
        "reserve_persistent_budget",
        lambda *_args, **_kwargs: (True, 9999, "reservation-error-code"),
    )
    monkeypatch.setattr(llm_chat, "reconcile_persistent_budget", lambda *_args, **_kwargs: None)

    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={}, headers=_hdr(uid, "llm"))
        assert c.status_code == 201, c.text
        cid = c.json()["id"]
        with client.stream(
            "POST",
            f"/api/llm/conversations/{cid}/messages",
            json={"content": "hello"},
            headers=_hdr(uid, "llm"),
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())
    assert "fake-secret-value" not in body
    assert "provider.invalid" not in body
    return _events(body)


@pytest.mark.parametrize(
    "exc, code",
    [
        (httpx.ReadTimeout(LEAK), "provider_timeout"),
        (httpx.ConnectError(LEAK), "provider_unavailable"),
        (_status_error(401), "provider_auth"),
        (_status_error(429), "provider_rate_limited"),
        (_status_error(503), "provider_unavailable"),
        (_status_error(400), "provider_rejected"),
        (RuntimeError(LEAK), "generation_failed"),
    ],
)
def test_provider_failure_is_reported_as_a_stable_code(monkeypatch, exc, code):
    events = _run_failing_stream(monkeypatch, exc, uid=9301)
    errors = [e for e in events if e.get("type") == "error"]
    assert len(errors) == 1, events
    assert errors[0]["message"] == code

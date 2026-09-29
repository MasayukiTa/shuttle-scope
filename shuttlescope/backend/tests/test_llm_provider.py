"""LLM プロバイダ抽象 (OpenAI 互換) のテスト。ネットワークは張らず、
SSE パース / payload 構築 / プロバイダ解決ロジックを検証する。"""
import os

from backend.services.llm import get_provider
from backend.services.llm.base import ChatMessage, build_messages
from backend.services.llm.openai_compatible import OpenAICompatibleProvider, parse_sse_line


def test_parse_sse_content():
    d = parse_sse_line('data: {"choices":[{"delta":{"content":"Hello"}}]}')
    assert d is not None and d.content == "Hello"


def test_parse_sse_done():
    d = parse_sse_line("data: [DONE]")
    assert d is not None and d.finish_reason == "stop" and d.content == ""


def test_parse_sse_blank_and_comment_ignored():
    assert parse_sse_line("") is None
    assert parse_sse_line(": keep-alive") is None
    assert parse_sse_line("data: not-json") is None


def test_parse_sse_tool_call():
    d = parse_sse_line('data: {"choices":[{"delta":{"tool_calls":[{"id":"t1","function":{"name":"x"}}]}}]}')
    assert d is not None and d.tool_call and d.tool_call["id"] == "t1"


def test_payload_includes_system_and_history():
    p = OpenAICompatibleProvider("http://x/v1", "k", "m")
    msgs = build_messages([ChatMessage(role="user", content="hi")], "sys")
    body = p._payload(msgs, None, 0.5, 100, True)
    assert body["model"] == "m" and body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["messages"][1]["role"] == "user" and body["messages"][1]["content"] == "hi"


def _with_env(**kv):
    """env を一時設定するコンテキスト (pytest 非依存)。"""
    class _C:
        def __enter__(self):
            self.old = {k: os.environ.get(k) for k in kv}
            for k, v in kv.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        def __exit__(self, *a):
            for k, v in self.old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _C()


def test_registry_nim_default():
    with _with_env(LLM_PROVIDER=None, LLM_BASE_URL=None, LLM_API_KEY=None,
                   NVIDIA_API_KEY="key123", NVIDIA_BASE_URL=None, NVIDIA_MODEL=None):
        pr = get_provider()
        assert "nim" in pr.name and pr.api_key == "key123" and "nvidia.com" in pr.base_url


def test_registry_local_endpoint():
    with _with_env(LLM_PROVIDER="local", LLM_BASE_URL=None):
        pr = get_provider()
        assert "127.0.0.1" in pr.base_url and pr.base_url.endswith("/v1")

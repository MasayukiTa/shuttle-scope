"""LLM tool / function-calling 抽象 + vision/tools capability のテスト。
ネットワークは張らず、ゲート (env フラグ) と payload/parse ロジックのみ検証する。"""
import os

from backend.services.llm.openai_compatible import accumulate_tool_calls
from backend.services.llm.registry import tools_available, vision_available
from backend.services.llm.tools import (
    WebSearchTool,
    enabled_tools,
    execute_tool_call,
    tool_definitions,
    tools_enabled,
)


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


# ── tools 機構のゲート (既定 OFF) ────────────────────────────────────────────

def test_tools_disabled_by_default():
    with _with_env(LLM_TOOLS=None, LLM_SEARCH_BACKEND=None, LLM_SEARCH_API_KEY=None):
        assert tools_enabled() is False
        assert enabled_tools() == []
        # 有効ツールが無ければ tools[] は None (= provider payload に tools を入れない)。
        assert tool_definitions() is None


def test_tools_flag_alone_does_not_enable_websearch():
    # LLM_TOOLS だけでは web_search は有効にならない (バックエンド/キーが必要)。
    with _with_env(LLM_TOOLS="1", LLM_SEARCH_BACKEND=None, LLM_SEARCH_API_KEY=None):
        assert tools_enabled() is True
        assert enabled_tools() == []
        assert tool_definitions() is None


def test_websearch_enabled_when_fully_configured():
    with _with_env(LLM_TOOLS="1", LLM_SEARCH_BACKEND="tavily", LLM_SEARCH_API_KEY="k"):
        tools = enabled_tools()
        assert len(tools) == 1 and tools[0].name == "web_search"
        defs = tool_definitions()
        assert defs and defs[0]["type"] == "function"
        assert defs[0]["function"]["name"] == "web_search"
        assert "query" in defs[0]["function"]["parameters"]["properties"]


def test_websearch_runs_noop_when_disabled():
    # 無効時は run() しても安全な no-op (空 content、エラーにしない、ネットワーク無し)。
    with _with_env(LLM_TOOLS=None, LLM_SEARCH_BACKEND=None, LLM_SEARCH_API_KEY=None):
        res = WebSearchTool().run({"query": "anything"})
        assert res.content == "" and res.is_error is False


def test_execute_tool_call_unknown_tool_is_noop():
    res = execute_tool_call("does_not_exist", {"x": 1})
    assert res.content == "" and res.is_error is False


def test_execute_tool_call_disabled_tool_is_noop():
    with _with_env(LLM_TOOLS=None):
        res = execute_tool_call("web_search", {"query": "x"})
        assert res.content == "" and res.is_error is False


def test_websearch_to_openai_shape():
    d = WebSearchTool().to_openai()
    assert d["type"] == "function"
    assert d["function"]["name"] == "web_search"
    assert d["function"]["parameters"]["required"] == ["query"]


# ── tool_call フラグメントの結合 ─────────────────────────────────────────────

def test_accumulate_tool_calls_joins_argument_fragments():
    deltas = [
        {"index": 0, "id": "call_1", "type": "function",
         "function": {"name": "web_search", "arguments": '{"que'}},
        {"index": 0, "function": {"arguments": 'ry":"hi"}'}},
    ]
    out = accumulate_tool_calls(deltas)
    assert len(out) == 1
    assert out[0]["id"] == "call_1"
    assert out[0]["function"]["name"] == "web_search"
    assert out[0]["function"]["arguments"] == '{"query":"hi"}'


def test_accumulate_tool_calls_multiple_indexes():
    deltas = [
        {"index": 0, "id": "a", "function": {"name": "f0", "arguments": "{}"}},
        {"index": 1, "id": "b", "function": {"name": "f1", "arguments": "{}"}},
    ]
    out = accumulate_tool_calls(deltas)
    assert [t["id"] for t in out] == ["a", "b"]
    assert [t["function"]["name"] for t in out] == ["f0", "f1"]


def test_accumulate_tool_calls_empty():
    assert accumulate_tool_calls([]) == []


# ── capability フラグ (registry) ─────────────────────────────────────────────

def test_vision_available_default_off():
    with _with_env(LLM_VISION=None):
        assert vision_available() is False


def test_vision_available_requires_provider_configured():
    # フラグが立っていてもプロバイダ未設定 (キー無し) なら False。
    with _with_env(LLM_VISION="1", LLM_PROVIDER="nim", LLM_API_KEY=None,
                   NVIDIA_API_KEY=None, OPENAI_API_KEY=None):
        assert vision_available() is False
    # キーがあれば True。
    with _with_env(LLM_VISION="1", LLM_PROVIDER="nim", LLM_API_KEY="k",
                   NVIDIA_API_KEY=None, OPENAI_API_KEY=None):
        assert vision_available() is True


def test_tools_available_default_off():
    with _with_env(LLM_TOOLS=None):
        assert tools_available() is False


def test_tools_available_requires_enabled_tool_and_provider():
    # tools 機構 ON + 検索設定 + プロバイダキーが全て揃って初めて True。
    with _with_env(LLM_TOOLS="1", LLM_SEARCH_BACKEND="tavily", LLM_SEARCH_API_KEY="k",
                   LLM_PROVIDER="nim", LLM_API_KEY="pk", NVIDIA_API_KEY=None,
                   OPENAI_API_KEY=None):
        assert tools_available() is True
    # プロバイダキーが無ければ False。
    with _with_env(LLM_TOOLS="1", LLM_SEARCH_BACKEND="tavily", LLM_SEARCH_API_KEY="k",
                   LLM_PROVIDER="nim", LLM_API_KEY=None, NVIDIA_API_KEY=None,
                   OPENAI_API_KEY=None):
        assert tools_available() is False

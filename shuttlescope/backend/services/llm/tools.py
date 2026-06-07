"""プロバイダ非依存の tool / function-calling 抽象。

将来のコーディング/検索エージェント用ツール実行ループの土台。OpenAI 互換の
`tools` (関数定義) / `tool_calls` (モデルからの呼び出し要求) を 1 つの Tool
インターフェースに集約する。

設計方針:
- ツールは env フラグ (LLM_TOOLS) が立っている時のみ「有効」。フラグが無い間は
  ツール定義は存在するが enabled=False で、呼び出されても安全な no-op を返す
  (= 既存挙動を一切変えない / NIM/deepseek が tool_calls を出さなくても無害)。
- web_search は最初の実例。実際の検索バックエンド (LLM_SEARCH_BACKEND +
  LLM_SEARCH_API_KEY 等) が未設定なら disabled のまま。設定すれば config 変更
  だけで有効化できる (コード書き換え不要)。

このモジュールはネットワークを張る実装 (web 検索) を持ち得るが、リクエスト
ハンドラのインラインで重い処理をしない既存方針に従い、検索本体は短時間で
完結する単発 HTTP に限定し、未設定時は即 no-op で返す。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """ツール実行の結果。content はモデルへ tool ロールメッセージとして返す文字列。"""
    content: str
    is_error: bool = False


class Tool:
    """全ツール共通インターフェース。

    name / description / parameters (JSON Schema) で OpenAI 互換の関数定義を作る。
    enabled() が False の間は run() は呼ばれない想定だが、安全のため run() 自体も
    無効時は no-op を返す。"""

    name: str = "tool"
    description: str = ""
    # OpenAI function calling の parameters (JSON Schema) 。
    parameters: Dict[str, Any] = {"type": "object", "properties": {}}

    def enabled(self) -> bool:
        """env 等の条件で有効か。既定は False (明示的に opt-in する)。"""
        return False

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        """ツールを実行する。無効時/未実装時は安全な no-op。"""
        return ToolResult(content="", is_error=False)

    def to_openai(self) -> Dict[str, Any]:
        """OpenAI 互換の tools[] 要素 (type=function) を返す。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class WebSearchTool(Tool):
    """外部 Web 検索ツール (最初の実例)。

    env:
    - LLM_TOOLS         : "1" 等で tool 機構自体を有効化 (大元のゲート)
    - LLM_SEARCH_BACKEND: 検索バックエンド種別 (例: "tavily")。未設定なら disabled
    - LLM_SEARCH_API_KEY: 検索 API キー

    バックエンド/キーが揃わない限り enabled()==False で no-op。揃えば config 変更
    だけで有効になる (=書き換え不要)。"""

    name = "web_search"
    description = (
        "Search the public web for up-to-date information. "
        "Use when the user asks about recent events or facts you are unsure of."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (1-10).",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
    }

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def enabled(self) -> bool:
        # tool 機構が ON かつ検索バックエンド + キーが揃っている時のみ。
        if not tools_enabled():
            return False
        backend = os.environ.get("LLM_SEARCH_BACKEND")
        key = os.environ.get("LLM_SEARCH_API_KEY")
        return bool(backend and key)

    def run(self, arguments: Dict[str, Any]) -> ToolResult:
        # 未設定なら何もしない (silent no-op、既存挙動を壊さない)。
        if not self.enabled():
            return ToolResult(content="", is_error=False)
        query = (arguments or {}).get("query") or ""
        if not query.strip():
            return ToolResult(content="empty query", is_error=True)
        max_results = int((arguments or {}).get("max_results") or 5)
        max_results = max(1, min(10, max_results))
        backend = (os.environ.get("LLM_SEARCH_BACKEND") or "").lower()
        try:
            if backend == "tavily":
                return self._tavily(query, max_results)
            # 未知のバックエンドは安全側で no-op (誤って外部送信しない)。
            logger.info("web_search: unknown backend %r, no-op", backend)
            return ToolResult(content="", is_error=False)
        except Exception as exc:  # noqa: BLE001 - 検索失敗でチャットを落とさない
            logger.warning("web_search failed: %s", exc)
            return ToolResult(content="search failed", is_error=True)

    def _tavily(self, query: str, max_results: int) -> ToolResult:
        """Tavily search API (OpenAI 互換ではない単発 HTTP)。短時間で完結。"""
        import httpx

        key = os.environ.get("LLM_SEARCH_API_KEY") or ""
        url = os.environ.get("LLM_SEARCH_BASE_URL") or "https://api.tavily.com/search"
        payload = {
            "api_key": key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
        with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0)) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results") or []
        # モデルが扱いやすいよう簡潔な JSON にまとめる。
        compact = [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": (r.get("content") or "")[:500],
            }
            for r in results[:max_results]
        ]
        return ToolResult(content=json.dumps({"results": compact}, ensure_ascii=False))


# ── レジストリ ──────────────────────────────────────────────────────────────
# 既知ツールは name -> instance で 1 か所に登録。新ツールはここに足すだけ。
_TOOLS: Dict[str, Tool] = {
    WebSearchTool.name: WebSearchTool(),
}


def tools_enabled() -> bool:
    """tool/function-calling 機構そのものが有効か (大元のゲート、env LLM_TOOLS)。"""
    return os.environ.get("LLM_TOOLS") in ("1", "true", "True", "yes", "on")


def get_tool(name: str) -> Optional[Tool]:
    return _TOOLS.get(name)


def all_tools() -> List[Tool]:
    return list(_TOOLS.values())


def enabled_tools() -> List[Tool]:
    """現在 enabled() == True のツールのみ。すべて off なら空リスト。"""
    if not tools_enabled():
        return []
    return [t for t in _TOOLS.values() if t.enabled()]


def tool_definitions() -> Optional[List[Dict[str, Any]]]:
    """プロバイダへ渡す OpenAI 互換 tools[]。有効ツールが無ければ None。

    None を返すことで provider は payload に "tools" を入れない = 既存挙動と同一。"""
    tools = enabled_tools()
    if not tools:
        return None
    return [t.to_openai() for t in tools]


def execute_tool_call(name: str, arguments: Any) -> ToolResult:
    """モデルが要求した tool_call を実行する。

    arguments は JSON 文字列 (OpenAI 互換) でも dict でも受ける。未知/無効ツールは
    安全な no-op (チャットを落とさない)。"""
    tool = get_tool(name)
    if tool is None or not tool.enabled():
        return ToolResult(content="", is_error=False)
    args: Dict[str, Any]
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except (ValueError, TypeError):
            return ToolResult(content="invalid tool arguments", is_error=True)
    elif isinstance(arguments, dict):
        args = arguments
    else:
        args = {}
    return tool.run(args)

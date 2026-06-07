"""OpenAI 互換 (/chat/completions) プロバイダ。NIM / LM Studio / llama.cpp / OpenAI 共通。"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterator, List, Optional

from backend.services.llm.base import ChatMessage, Delta, LLMProvider, build_messages

logger = logging.getLogger(__name__)


def parse_sse_line(raw: str) -> Optional[Delta]:
    """SSE の 1 行を Delta に変換。データ行でなければ None、終端なら finish_reason='stop'。"""
    line = raw.strip()
    if not line or line.startswith(":"):
        return None
    if line.startswith("data:"):
        line = line[len("data:"):].strip()
    if line == "[DONE]":
        return Delta(finish_reason="stop")
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return None
    choices = obj.get("choices") or [{}]
    ch = choices[0] if choices else {}
    delta = ch.get("delta") or {}
    tool_calls = delta.get("tool_calls") or []
    return Delta(
        content=delta.get("content") or "",
        # reasoning モデルは思考過程を reasoning_content (一部実装は reasoning) で返す。
        reasoning=delta.get("reasoning_content") or delta.get("reasoning") or "",
        # tool_call は index/id/function(name,arguments) を含む raw delta をそのまま保持。
        # 引数はストリームで分割されて届くため、accumulate_tool_calls() で index ごとに結合する。
        tool_call=tool_calls[0] if tool_calls else None,
        finish_reason=ch.get("finish_reason"),
    )


def accumulate_tool_calls(deltas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ストリームで分割された tool_call フラグメントを index ごとに 1 つへ結合する。

    OpenAI 互換ストリームでは tool_call の function.arguments が複数 delta に
    分かれて届く。各 delta は同じ index を共有するので、index をキーに id/name を
    確定し arguments 文字列を連結する。tool 実行ループ (将来) の土台。"""
    by_index: Dict[int, Dict[str, Any]] = {}
    order: List[int] = []
    for tc in deltas:
        if not tc:
            continue
        idx = tc.get("index", 0) or 0
        if idx not in by_index:
            by_index[idx] = {"id": None, "type": "function",
                             "function": {"name": "", "arguments": ""}}
            order.append(idx)
        slot = by_index[idx]
        if tc.get("id"):
            slot["id"] = tc["id"]
        if tc.get("type"):
            slot["type"] = tc["type"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]
    return [by_index[i] for i in order]


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: Optional[str], model: str,
                 name: Optional[str] = None, timeout: float = 120.0) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = name or f"openai:{model}"
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _payload(self, messages: List[ChatMessage], tools, temperature, max_tokens, stream) -> Dict[str, Any]:
        p: Dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if tools:
            p["tools"] = tools
        return p

    def stream_chat(self, messages, *, tools=None, system=None, temperature=0.7,
                    max_tokens=1024, **kwargs) -> Iterator[Delta]:
        import httpx
        msgs = build_messages(list(messages), system)
        payload = self._payload(msgs, tools, temperature, max_tokens, True)
        url = f"{self.base_url}/chat/completions"
        with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0)) as client:
            with client.stream("POST", url, headers=self._headers(), json=payload) as resp:
                resp.raise_for_status()
                for raw in resp.iter_lines():
                    d = parse_sse_line(raw)
                    if d is None:
                        continue
                    if d.finish_reason == "stop" and not d.content and not d.tool_call and not d.reasoning:
                        break
                    yield d

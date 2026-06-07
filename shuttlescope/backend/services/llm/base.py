"""LLM プロバイダ抽象の型とインターフェース。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Union

# OpenAI 互換の content は文字列、またはマルチモーダル content part の配列を取れる
# (例: [{"type":"text","text":...}, {"type":"image_url","image_url":{"url": dataurl}}]).
ContentType = Union[str, List[Dict[str, Any]]]


@dataclass
class ChatMessage:
    """1 つの会話メッセージ。role = system|user|assistant|tool。

    content は通常は文字列だが、vision (マルチモーダル) 入力時は OpenAI 互換の
    content part 配列 (text / image_url) も保持できる。"""
    role: str
    content: ContentType = ""
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    def to_openai(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d


@dataclass
class Delta:
    """ストリーミングの増分トークン/イベント。"""
    content: str = ""
    # reasoning モデル (DeepSeek-R1 / deepseek-reasoner 等) の思考過程 (chain-of-thought)。
    # OpenAI 互換 delta の `reasoning_content` フィールド。回答 (content) とは別系統で届く。
    reasoning: str = ""
    tool_call: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None


class LLMProvider:
    """全プロバイダ共通インターフェース。"""
    name: str = "base"
    model: str = ""

    def stream_chat(
        self,
        messages: List[ChatMessage],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Iterator[Delta]:
        """トークンをストリーミングで yield する。"""
        raise NotImplementedError

    def chat(
        self,
        messages: List[ChatMessage],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> ChatMessage:
        """非ストリーミング。既定実装は stream_chat を集約する。"""
        parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        for d in self.stream_chat(messages, tools=tools, system=system,
                                  temperature=temperature, max_tokens=max_tokens, **kwargs):
            if d.content:
                parts.append(d.content)
            if d.tool_call:
                tool_calls.append(d.tool_call)
        return ChatMessage(role="assistant", content="".join(parts),
                           tool_calls=tool_calls or None)


def build_messages(history: List[ChatMessage], system: Optional[str]) -> List[ChatMessage]:
    """system プロンプトを先頭に差し込んだメッセージ列を返す。"""
    msgs: List[ChatMessage] = []
    if system:
        msgs.append(ChatMessage(role="system", content=system))
    msgs.extend(history)
    return msgs

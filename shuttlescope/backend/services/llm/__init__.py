"""汎用 LLM サービス基盤 (/#/llm のバックエンド)。

OpenAI 互換エンドポイント (NVIDIA NIM / LM Studio / llama.cpp / OpenAI) を 1 つの
プロバイダ抽象で扱う。ストリーミング + tool(function) calling 対応で、将来の
コーディングエージェント用ツール実行ループの土台にする。
バドミントン特化の insights chat (backend/analysis/insights) とは別系統。"""
from backend.services.llm.base import ChatMessage, Delta, LLMProvider
from backend.services.llm.openai_compatible import OpenAICompatibleProvider
from backend.services.llm.registry import get_provider

__all__ = ["ChatMessage", "Delta", "LLMProvider", "OpenAICompatibleProvider", "get_provider"]

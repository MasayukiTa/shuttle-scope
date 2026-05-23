"""InsightGenerator 選択ファクトリ。

INSIGHT_GENERATOR 環境変数で切り替え:
- 'template' (default) → TemplateGenerator
- 'nvidia' → NVIDIA NIM 用スタブ (未設定なら template フォールバック)
- 'openai' → OpenAI 用スタブ
- 'anthropic' → Anthropic 用スタブ
- 'local'  → ローカル Ollama 等のスタブ

スタブが NotImplementedError を投げたら router 側で fallback できるよう
このファクトリは「呼び出し時フォールバック」もラップして提供する。
"""
from __future__ import annotations

import os

from backend.analysis.insights.base import InsightGenerator
from backend.analysis.insights.external_stub import ExternalApiGenerator
from backend.analysis.insights.template import TemplateGenerator
from backend.analysis.insights.types import InsightContext, InsightResult


class _FallbackWrapper:
    """外部 LLM が NotImplementedError を投げたら template に倒す。"""

    def __init__(self, primary: InsightGenerator, fallback: InsightGenerator) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = getattr(primary, "name", "external") + "+template-fallback"

    def generate(self, ctx: InsightContext) -> InsightResult:
        try:
            return self.primary.generate(ctx)
        except NotImplementedError:
            return self.fallback.generate(ctx)


def get_generator(name: str | None = None) -> InsightGenerator:
    """ジェネレータを返す。未指定なら INSIGHT_GENERATOR 環境変数を見る。"""
    if name is None:
        name = os.environ.get("INSIGHT_GENERATOR", "template").strip().lower()
    else:
        name = name.strip().lower()

    template = TemplateGenerator()

    if name in ("", "template"):
        return template
    if name == "nvidia":
        primary = ExternalApiGenerator(
            "nvidia",
            endpoint_env="NVIDIA_NIM_ENDPOINT",
            api_key_env="NVIDIA_NIM_API_KEY",
        )
        return _FallbackWrapper(primary, template)
    if name == "openai":
        primary = ExternalApiGenerator(
            "openai",
            endpoint_env="OPENAI_API_BASE",
            api_key_env="OPENAI_API_KEY",
        )
        return _FallbackWrapper(primary, template)
    if name == "anthropic":
        primary = ExternalApiGenerator(
            "anthropic",
            endpoint_env="ANTHROPIC_API_BASE",
            api_key_env="ANTHROPIC_API_KEY",
        )
        return _FallbackWrapper(primary, template)
    if name in ("local", "ollama", "local_ollama"):
        primary = ExternalApiGenerator(
            "local_ollama",
            endpoint_env="OLLAMA_ENDPOINT",
            api_key_env=None,
        )
        return _FallbackWrapper(primary, template)
    # 未知の値は安全側 (template) に倒す
    return template

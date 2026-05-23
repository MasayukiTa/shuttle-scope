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


def _wrap_external(provider: str, endpoint_env: str, api_key_env: str | None,
                   template: InsightGenerator) -> InsightGenerator:
    """外部 LLM を構築し HarnessedGenerator でラップ。env 未設定/構築失敗 → template。"""
    import os as _os
    # 構築前 env チェック (省略すれば即フォールバック)
    if not _os.environ.get(endpoint_env):
        return template
    if api_key_env and not _os.environ.get(api_key_env):
        return template
    try:
        from backend.analysis.insights.safety.harness import HarnessedGenerator
        primary = ExternalApiGenerator(provider, endpoint_env=endpoint_env,
                                       api_key_env=api_key_env)
        return HarnessedGenerator(inner=primary, fallback=template)
    except Exception:
        return template


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
        return _wrap_external("nvidia", "NVIDIA_NIM_ENDPOINT",
                              "NVIDIA_NIM_API_KEY", template)
    if name == "openai":
        return _wrap_external("openai", "OPENAI_API_BASE",
                              "OPENAI_API_KEY", template)
    if name == "anthropic":
        return _wrap_external("anthropic", "ANTHROPIC_API_BASE",
                              "ANTHROPIC_API_KEY", template)
    if name in ("local", "ollama", "local_ollama"):
        return _wrap_external("local_ollama", "OLLAMA_ENDPOINT",
                              None, template)
    # 未知の値は安全側 (template) に倒す
    return template

"""InsightGenerator 選択ファクトリ。

INSIGHT_GENERATOR 環境変数で切り替え:
- 'template' (default) → TemplateGenerator
- 'nvidia' → NVIDIA NIM (OpenAI 互換) → HarnessedGenerator でラップ
- 'openai' / 'anthropic' / 'local' → 旧スタブ経路 (NotImplementedError 即 fallback)

外部 LLM 構築失敗 (NotImplementedError 含む) は即 template に倒す。
"""
from __future__ import annotations

import os

from backend.analysis.insights.base import InsightGenerator
from backend.analysis.insights.external_stub import ExternalApiGenerator
from backend.analysis.insights.template import TemplateGenerator


def _wrap_external(
    provider: str,
    template: InsightGenerator,
    endpoint_env: str | None = None,
    api_key_env: str | None = None,
) -> InsightGenerator:
    """外部 LLM を構築し HarnessedGenerator でラップ。構築失敗 → template。"""
    try:
        primary = ExternalApiGenerator(
            provider, endpoint_env=endpoint_env, api_key_env=api_key_env
        )
    except NotImplementedError:
        return template
    except Exception:
        return template
    try:
        from backend.analysis.insights.safety.harness import HarnessedGenerator
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
        # NVIDIA_API_KEY / NVIDIA_BASE_URL / NVIDIA_MODEL を ExternalApiGenerator 内で読む
        return _wrap_external("nvidia", template)
    if name == "openai":
        return _wrap_external(
            "openai", template,
            endpoint_env="OPENAI_API_BASE",
            api_key_env="OPENAI_API_KEY",
        )
    if name == "anthropic":
        return _wrap_external(
            "anthropic", template,
            endpoint_env="ANTHROPIC_API_BASE",
            api_key_env="ANTHROPIC_API_KEY",
        )
    if name in ("local", "ollama", "local_ollama"):
        return _wrap_external(
            "local_ollama", template,
            endpoint_env="OLLAMA_ENDPOINT",
            api_key_env=None,
        )
    # 未知の値は安全側 (template) に倒す
    return template

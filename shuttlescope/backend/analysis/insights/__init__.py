"""Growth Snapshot insights package.

LLM-pluggable frame: now uses TemplateGenerator, future can swap to
NVIDIA NIM / OpenAI / Anthropic / local Ollama via INSIGHT_GENERATOR env var.
"""
from backend.analysis.insights.base import InsightGenerator
from backend.analysis.insights.factory import get_generator
from backend.analysis.insights.template import TemplateGenerator
from backend.analysis.insights.external_stub import ExternalApiGenerator
from backend.analysis.insights.types import (
    InsightContext,
    InsightItem,
    InsightResult,
)

__all__ = [
    "InsightGenerator",
    "TemplateGenerator",
    "ExternalApiGenerator",
    "get_generator",
    "InsightContext",
    "InsightItem",
    "InsightResult",
]

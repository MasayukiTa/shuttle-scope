"""InsightGenerator プロトコル定義。"""
from __future__ import annotations

from typing import Protocol

from backend.analysis.insights.types import InsightContext, InsightResult


class InsightGenerator(Protocol):
    """全ジェネレータが満たすべきインタフェース。

    Template / NVIDIA NIM / OpenAI / Local LLM 等が差し替え可能。
    """

    def generate(self, ctx: InsightContext) -> InsightResult:
        ...

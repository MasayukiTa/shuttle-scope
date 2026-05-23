"""外部 LLM (NVIDIA NIM / OpenAI / Anthropic / Local Ollama) 用スタブ。

現時点では実 API call はせず、未設定なら NotImplementedError を投げる。
factory がそれを拾って Template にフォールバックする。

将来の実装時の契約:
- 入力: `ctx.analytics` を要約した dict をプロンプトに同梱
- system prompt (必須・選手安全ガード):
    "You are a badminton coach speaking to a player.
     Use growth-oriented framing, never use the word 弱点 / weakness.
     Output 2-3 short sentences in {lang}."
- 出力 JSON shape は InsightResult / InsightItem に揃える
- network 失敗 / レート制限時も NotImplementedError 系の例外で
  template フォールバックさせる
"""
from __future__ import annotations

import os

from backend.analysis.insights.types import InsightContext, InsightResult


class ExternalApiGenerator:
    """LLM プロバイダ抽象。

    Args:
        provider: 'nvidia' / 'openai' / 'anthropic' / 'local_ollama'
        endpoint_env: エンドポイント URL を保持する環境変数名
        api_key_env: API key を保持する環境変数名 (local の場合は None 可)
    """

    def __init__(
        self,
        provider: str,
        endpoint_env: str,
        api_key_env: str | None = None,
    ) -> None:
        self.provider = provider
        self.endpoint_env = endpoint_env
        self.api_key_env = api_key_env
        self.name = f"{provider}-stub"

    def generate(self, ctx: InsightContext) -> InsightResult:
        endpoint = os.environ.get(self.endpoint_env)
        api_key = os.environ.get(self.api_key_env) if self.api_key_env else "local"
        if not endpoint or not api_key:
            raise NotImplementedError(
                "External insight generator not configured "
                f"(provider={self.provider}, missing env: "
                f"{self.endpoint_env}/{self.api_key_env})"
            )
        # NOTE: 実装者が後から埋める。プロンプト整形 → HTTP 呼び出し → JSON parse →
        # InsightResult に整形。今は呼び出されたら明示エラー。
        raise NotImplementedError(
            "External insight generator wiring is intentionally stubbed; "
            "see file docstring for prompt-shaping contract."
        )

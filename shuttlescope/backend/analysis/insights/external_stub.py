"""外部 LLM (NVIDIA NIM / OpenAI 互換) 用ジェネレータ。

NVIDIA NIM の OpenAI 互換 `/v1/chat/completions` を実呼び出しする。
未設定や HTTP/接続エラーは例外を投げ、HarnessedGenerator 側で
template fallback されることを想定する (NEVER hard-fail)。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.analysis.insights.safety.audit import log_llm_call
from backend.analysis.insights.safety.system_prompts import (
    SYSTEM_PROMPT_V1_EN,
    SYSTEM_PROMPT_V1_JA,
    SYSTEM_PROMPT_META_JA,
    SYSTEM_PROMPT_META_EN,
    SYSTEM_PROMPT_FORECAST_JA,
    SYSTEM_PROMPT_FORECAST_EN,
    classify_intent,
)
from backend.analysis.insights.types import (
    InsightContext,
    InsightItem,
    InsightResult,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_sample_size(analytics: dict | None) -> int:
    """analytics から最大 sample_n を拾う (heuristic 用)。"""
    if not analytics:
        return 0
    max_n = 0
    for v in analytics.values():
        if isinstance(v, dict):
            n = int(v.get("sample_n", 0) or 0)
            if n > max_n:
                max_n = n
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    n = int(it.get("sample_n", 0) or 0)
                    if n > max_n:
                        max_n = n
    return max_n


def _confidence_heuristic(analytics: dict | None) -> float:
    """baseline 0.6, sample_n>=30 で +0.2, 上限 0.85。"""
    n = _extract_sample_size(analytics)
    c = 0.6
    if n >= 30:
        c += 0.2
    if c > 0.85:
        c = 0.85
    return c


class ExternalApiGenerator:
    """NVIDIA NIM (OpenAI 互換) ジェネレータ。

    Args:
        provider: 'nvidia' (現状サポートはこれのみ)
        endpoint_env: 互換性のため受けるが NVIDIA_BASE_URL を優先参照
        api_key_env: 互換性のため受けるが NVIDIA_API_KEY を優先参照
    """

    def __init__(
        self,
        provider: str = "nvidia",
        endpoint_env: str | None = None,
        api_key_env: str | None = None,
    ) -> None:
        self.provider = provider
        # 後方互換: factory から渡される env 名も尊重する
        base_url = (
            os.environ.get(endpoint_env or "")
            if endpoint_env
            else None
        ) or os.environ.get("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
        api_key = (
            os.environ.get(api_key_env or "")
            if api_key_env
            else None
        ) or os.environ.get("NVIDIA_API_KEY")

        if not api_key:
            raise NotImplementedError(
                f"External insight generator not configured "
                f"(provider={provider}, missing NVIDIA_API_KEY)"
            )

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = os.environ.get(
            "NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"
        )
        self.name = f"{provider}:{self.model}"

    def _post_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        """接続エラーのみ最大 2 回リトライ。4xx/5xx は即返す。"""
        last_exc: Exception | None = None
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            for attempt in range(3):
                try:
                    return client.post(url, headers=headers, json=payload)
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    last_exc = exc
                    if attempt >= 2:
                        raise
                    time.sleep(0.5 * (attempt + 1))
        assert last_exc is not None  # pragma: no cover
        raise last_exc

    def generate(self, ctx: InsightContext) -> InsightResult:
        lang = ctx.get("lang", "ja")
        analytics = ctx.get("analytics") or {}
        role = ctx.get("role", "player")
        role_label = {
            "player": "選手",
            "coach": "コーチ",
            "analyst": "アナリスト",
            "admin": "管理者",
        }.get(role, role) if lang == "ja" else role

        # 2026-05-25 intent routing: ユーザの入力テキストを intent 分類して
        #   meta / forecast / data の 3 系統で system prompt を切替える。
        #   ctx に user_text が無い場合は data intent (旧挙動) と同等。
        user_text = ctx.get("user_text") if isinstance(ctx, dict) else None  # type: ignore[union-attr]
        intent = classify_intent(user_text or "")
        if intent == "meta":
            base_prompt = SYSTEM_PROMPT_META_JA if lang == "ja" else SYSTEM_PROMPT_META_EN
        elif intent == "forecast":
            base_prompt = SYSTEM_PROMPT_FORECAST_JA if lang == "ja" else SYSTEM_PROMPT_FORECAST_EN
        else:
            base_prompt = SYSTEM_PROMPT_V1_JA if lang == "ja" else SYSTEM_PROMPT_V1_EN
        # NOTE: prompt 本文に {count} {pct} 等の中括弧があるため .format は使えず replace で。
        system_prompt = base_prompt.replace("{role_label}", str(role_label))

        if intent == "meta":
            # meta は固定回答に近いので analytics を渡しても無視されてよい
            if lang == "ja":
                question_hint = "ユーザがアシスタント自身について質問しています。簡潔に自己紹介してください。"
            else:
                question_hint = "User asked about the assistant. Reply with a concise self-introduction."
        elif intent == "forecast":
            if lang == "ja":
                question_hint = (
                    f"ユーザの質問: 「{(user_text or '')[:80]}」 — これは予測質問です。"
                    "AI として確実な予測は提供できないことを明示し、過去データの傾向のみ示してください。"
                )
            else:
                question_hint = (
                    f"User question: \"{(user_text or '')[:80]}\" — this is a prediction question. "
                    "State that an AI can't make hard predictions and describe trends from past data only."
                )
        else:
            if lang == "ja":
                question_hint = (
                    f"ユーザの質問: 「{(user_text or '直近の伸びしろは？')[:80]}」 — 成長アドバイスを 1 件、3 文以内・200 文字以内。"
                    "N=<count> または信頼度 <pct>% を必ず含めてください。"
                )
            else:
                question_hint = (
                    f"User question: \"{(user_text or 'What is my next growth area?')[:80]}\". "
                    "Generate 1 short growth insight (<=3 sentences, <=100 words). "
                    "Include N=<count> or confidence percentage."
                )

        user_body = json.dumps(
            {"analytics": analytics, "question_hint": question_hint},
            ensure_ascii=False,
        )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_body},
            ],
            "temperature": 0.3,
            "max_tokens": 350,
            "top_p": 0.9,
        }

        t0 = time.monotonic()
        try:
            resp = self._post_with_retry(url, headers, payload)
        except Exception as exc:
            try:
                log_llm_call(
                    user_id=ctx.get("user_id") if isinstance(ctx, dict) else None,
                    provider=self.name,
                    validation_result={"ok": False, "reason": f"network:{type(exc).__name__}"},
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )
            except Exception:
                pass
            raise

        latency_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code >= 400:
            try:
                log_llm_call(
                    user_id=ctx.get("user_id") if isinstance(ctx, dict) else None,
                    provider=self.name,
                    validation_result={
                        "ok": False,
                        "reason": f"http_{resp.status_code}",
                    },
                    latency_ms=latency_ms,
                )
            except Exception:
                pass
            resp.raise_for_status()

        data = resp.json()
        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        ) or ""
        usage = data.get("usage", {}) or {}
        tokens_in = int(usage.get("prompt_tokens", 0) or 0)
        tokens_out = int(usage.get("completion_tokens", 0) or 0)
        tokens_total = int(usage.get("total_tokens", tokens_in + tokens_out) or 0)

        try:
            log_llm_call(
                user_id=ctx.get("user_id") if isinstance(ctx, dict) else None,
                provider=self.name,
                validation_result={"ok": True, "reason": None},
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
            )
        except Exception:
            pass

        confidence = _confidence_heuristic(analytics)
        item = InsightItem(
            id="growth_main",
            prose=content.strip(),
            evidence_path="",  # NIM 出力はテキストのみ
            confidence=confidence,
            metric=analytics,
        )
        return InsightResult(
            items=[item],
            generator=self.name,
            generated_at=_now_iso(),
            meta={  # type: ignore[typeddict-unknown-key]
                "tokens": {
                    "in": tokens_in,
                    "out": tokens_out,
                    "total": tokens_total,
                },
                "latency_ms": latency_ms,
            },
        )

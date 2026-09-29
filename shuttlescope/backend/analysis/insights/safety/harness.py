"""LLM 出力を検証し、失敗時に template fallback に倒す HarnessedGenerator。"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.analysis.insights.base import InsightGenerator
from backend.analysis.insights.safety.audit import log_llm_call
from backend.analysis.insights.safety.output_validators import validate_response
from backend.analysis.insights.types import InsightContext, InsightResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HarnessedGenerator:
    """inner ジェネレータの出力を検証し、ダメなら fallback に倒す。"""

    name = "harnessed"

    def __init__(
        self,
        inner: InsightGenerator,
        fallback: InsightGenerator,
        audit: bool = True,
    ) -> None:
        self.inner = inner
        self.fallback = fallback
        self.audit = audit
        self._provider = getattr(inner, "name", "unknown")

    def _fallback_with_meta(
        self,
        ctx: InsightContext,
        reason: str,
        source_meta: dict | None = None,
    ) -> InsightResult:
        result = self.fallback.generate(ctx)
        meta = dict(result.get("meta") or {})  # type: ignore[arg-type]
        # Preserve provider usage even when output validation rejects the prose.
        # The external call was still billable, so dropping token metadata here
        # would make the persistent budget undercount failed/filtered calls.
        if source_meta:
            for key in ("tokens", "latency_ms"):
                if key in source_meta:
                    meta[key] = source_meta[key]
        meta["fallback_reason"] = reason
        meta["fallback_at"] = _now_iso()
        result["meta"] = meta  # type: ignore[typeddict-item]
        return result

    def generate(self, ctx: InsightContext) -> InsightResult:
        user_id = ctx.get("user_id") if isinstance(ctx, dict) else None  # type: ignore[union-attr]
        lang = ctx.get("lang", "ja")

        # 1) inner 実行 — 例外時 fallback
        try:
            result = self.inner.generate(ctx)
        except Exception as exc:  # noqa: BLE001
            reason = f"inner_exception:{type(exc).__name__}"
            if self.audit:
                try:
                    log_llm_call(
                        user_id=user_id,
                        provider=self._provider,
                        validation_result={"ok": False, "reason": reason},
                    )
                except Exception:  # noqa: BLE001
                    pass
            return self._fallback_with_meta(ctx, reason)

        # 2) item ごとに検証
        for item in result.get("items", []):
            prose = item.get("prose", "")
            metric = item.get("metric") or {}
            numeric_policy = item.get("numeric_policy", "grounded")
            v = validate_response(
                prose,
                lang,
                metric,
                numeric_policy=numeric_policy,
            )
            if not v["ok"]:
                if self.audit:
                    try:
                        log_llm_call(
                            user_id=user_id,
                            provider=self._provider,
                            validation_result=v,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                source_meta = dict(result.get("meta") or {})  # type: ignore[arg-type]
                return self._fallback_with_meta(
                    ctx, v["reason"] or "unknown", source_meta=source_meta
                )

        # 3) すべて OK
        if self.audit:
            try:
                log_llm_call(
                    user_id=user_id,
                    provider=self._provider,
                    validation_result={"ok": True, "reason": None},
                )
            except Exception:  # noqa: BLE001
                pass
        return result

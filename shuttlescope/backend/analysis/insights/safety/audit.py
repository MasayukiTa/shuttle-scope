"""LLM 呼び出し監査ログ。security_events への薄いラッパー。"""
from __future__ import annotations

from backend.utils.security_log import emit_security_event


def log_llm_call(
    *,
    user_id: int | None,
    provider: str,
    validation_result: dict,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    prompt_hash: str = "",
    response_hash: str = "",
) -> None:
    """1 件分の LLM 呼び出しを security_events に記録。失敗は emit 側で飲み込まれる。"""
    details = {
        "provider": provider,
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "latency_ms": int(latency_ms),
        "prompt_hash": prompt_hash,
        "response_hash": response_hash,
        "ok": bool(validation_result.get("ok", False)),
        "reason": validation_result.get("reason"),
    }
    emit_security_event(
        "llm_call",
        severity="info",
        user_id=user_id,
        details=details,
    )

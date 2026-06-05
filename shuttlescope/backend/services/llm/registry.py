"""設定からプロバイダを解決する。

env:
- LLM_PROVIDER : nim(=nvidia, 既定) | local(LM Studio/llama) | openai
- LLM_BASE_URL / LLM_API_KEY / LLM_MODEL : 明示指定 (各プロバイダ既定にフォールバック)
NIM は既存 NVIDIA_BASE_URL/NVIDIA_API_KEY/NVIDIA_MODEL もフォールバックに使う。
"""
from __future__ import annotations

import os
from typing import Optional

from backend.services.llm.openai_compatible import OpenAICompatibleProvider

_NIM_DEFAULT_BASE = "https://integrate.api.nvidia.com/v1"
_NIM_DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"
_LOCAL_DEFAULT_BASE = "http://127.0.0.1:1234/v1"   # LM Studio 既定
_OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"


def _env(*keys: str, default: Optional[str] = None) -> Optional[str]:
    for k in keys:
        v = os.environ.get(k)
        if v:
            return v
    return default


def get_provider(provider: Optional[str] = None, model: Optional[str] = None) -> OpenAICompatibleProvider:
    provider = (provider or os.environ.get("LLM_PROVIDER") or "nim").lower()
    if provider in ("nim", "nvidia"):
        base = _env("LLM_BASE_URL", "NVIDIA_BASE_URL", default=_NIM_DEFAULT_BASE)
        key = _env("LLM_API_KEY", "NVIDIA_API_KEY")
        mdl = model or _env("LLM_MODEL", "NVIDIA_MODEL", default=_NIM_DEFAULT_MODEL)
    elif provider == "local":
        base = _env("LLM_BASE_URL", default=_LOCAL_DEFAULT_BASE)
        key = _env("LLM_API_KEY")  # ローカルは鍵不要が多い
        mdl = model or _env("LLM_MODEL", default="local-model")
    else:  # openai / その他 OpenAI 互換
        base = _env("LLM_BASE_URL", default=_OPENAI_DEFAULT_BASE)
        key = _env("LLM_API_KEY", "OPENAI_API_KEY")
        mdl = model or _env("LLM_MODEL", default="gpt-4o-mini")
    return OpenAICompatibleProvider(base, key, mdl, name=f"{provider}:{mdl}")


def provider_configured(provider: Optional[str] = None) -> bool:
    """鍵やローカルエンドポイントが用意されているか (ローカルは常に True 扱い)。"""
    provider = (provider or os.environ.get("LLM_PROVIDER") or "nim").lower()
    if provider == "local":
        return True
    return bool(_env("LLM_API_KEY", "NVIDIA_API_KEY", "OPENAI_API_KEY"))

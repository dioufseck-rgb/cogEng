"""LLM and Map-step configuration helpers for orchestrator runtimes."""

from __future__ import annotations

from typing import Literal

from rulekit.build.llm import LLMCaller
from rulekit.orchestrator.map_step import PreboundFactsMapStep, TypedNarrativeMapStep

MapMode = Literal["prebound", "narrative"]


def create_llm_caller(
    *,
    provider: str = "anthropic",
    model: str | None = None,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    max_retries: int = 2,
    retry_base_delay_s: float = 1.0,
) -> LLMCaller:
    """Create the standard RuleKit LLM adapter used by Build and Map."""
    selected_model = model or _default_model(provider)
    return LLMCaller(
        provider=provider,
        model=selected_model,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        retry_base_delay_s=retry_base_delay_s,
    )


def create_map_step(
    *,
    map_mode: str = "prebound",
    llm_provider: str = "anthropic",
    llm_model: str | None = None,
    llm_max_tokens: int = 4096,
    llm_timeout: float = 120.0,
    llm_max_retries: int = 2,
    llm_retry_base_delay_s: float = 1.0,
    batch_size: int | None = None,
):
    """Create the Map step for a run.

    ``prebound`` is deterministic and reads ``structured_fields.facts``.
    ``narrative`` uses an LLM to extract atom bindings from natural text.
    """
    if map_mode == "prebound":
        return PreboundFactsMapStep()
    if map_mode == "narrative":
        llm = create_llm_caller(
            provider=llm_provider,
            model=llm_model,
            max_tokens=llm_max_tokens,
            timeout=llm_timeout,
            max_retries=llm_max_retries,
            retry_base_delay_s=llm_retry_base_delay_s,
        )
        return TypedNarrativeMapStep(llm, batch_size=batch_size)
    raise ValueError("map_mode must be 'prebound' or 'narrative'")


def _default_model(provider: str) -> str:
    if provider == "anthropic":
        return "claude-opus-4-7"
    if provider == "openai":
        return "gpt-5"
    if provider == "gemini":
        return "gemini-2.5-pro"
    raise ValueError("llm_provider must be 'anthropic', 'openai', or 'gemini'")


__all__ = ["MapMode", "create_llm_caller", "create_map_step"]

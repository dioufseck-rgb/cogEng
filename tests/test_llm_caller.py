from __future__ import annotations

from rulekit.build.llm import LLMCaller
from rulekit.orchestrator.llm_config import create_map_step
from rulekit.orchestrator.map_step import PreboundFactsMapStep, TypedNarrativeMapStep


class FlakyLLM(LLMCaller):
    def __init__(self):
        super().__init__(model="claude-opus-4-7", max_retries=2, retry_base_delay_s=0)
        self.calls = 0

    def _call_once(self, prompt, max_tokens=None, stream=True):
        del prompt, max_tokens, stream
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary provider error")
        return '{"ok": true}'


def test_llm_caller_retries_transient_failures():
    llm = FlakyLLM()

    assert llm.call("stage", "prompt") == '{"ok": true}'
    assert llm.calls == 2


def test_llm_caller_infers_openai_provider_from_model():
    llm = LLMCaller(model="gpt-5", offline_responses={"stage": "{}"})

    assert llm.provider == "openai"
    assert llm.call("stage", "prompt") == "{}"


def test_llm_caller_infers_gemini_provider_from_model():
    llm = LLMCaller(model="gemini-2.5-pro", offline_responses={"stage": "{}"})

    assert llm.provider == "gemini"
    assert llm.call("stage", "prompt") == "{}"


def test_create_map_step_selects_prebound_or_narrative():
    assert isinstance(create_map_step(map_mode="prebound"), PreboundFactsMapStep)
    step = create_map_step(
        map_mode="narrative",
        llm_provider="anthropic",
        llm_model="claude-opus-4-7",
    )
    assert isinstance(step, TypedNarrativeMapStep)

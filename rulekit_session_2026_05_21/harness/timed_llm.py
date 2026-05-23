"""
TimedLLMCaller — instrumentation wrapper around LLMCaller.

Records per-call wall-clock elapsed time and token usage. Provides
aggregate summaries needed by the protocol's Section 5.3 record schema.

This is a wrapper: it delegates calls to a real LLMCaller and intercepts
the response to extract timing and token usage.
"""

from __future__ import annotations
import time
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

from rulekit.decomposer import LLMCaller


class TimedLLMCaller:
    """
    Drop-in instrumented replacement for LLMCaller. Same call signature;
    records timing and token usage per call in self.calls (list of dicts).
    """

    def __init__(self, inner: LLMCaller):
        self.inner = inner
        self.calls: list[dict] = []

    def call(self, label: str, prompt: str) -> str:
        """Issue the call, record timing and token usage."""
        start = time.monotonic()
        response = self.inner.call(label, prompt)
        elapsed = time.monotonic() - start

        # Token accounting. The underlying LLMCaller exposes usage via
        # its last_usage attribute when available; if not, we approximate
        # from prompt/response lengths divided by an average chars-per-token
        # factor (~4 for English). The harness records both the recorded
        # value and the method used so analysis can flag approximations.
        usage = self._extract_usage(prompt, response)

        self.calls.append({
            "label": label,
            "elapsed_s": elapsed,
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "token_source": usage["source"],
        })
        return response

    def _extract_usage(self, prompt: str, response: str) -> dict:
        """Extract token usage. Prefers API-reported counts when available."""
        # Try to get exact usage from the underlying caller's last response
        last_usage = getattr(self.inner, "last_usage", None)
        if last_usage:
            return {
                "input_tokens": getattr(last_usage, "input_tokens", 0),
                "output_tokens": getattr(last_usage, "output_tokens", 0),
                "source": "api",
            }

        # Approximate from character lengths (4 chars per token typical)
        return {
            "input_tokens": max(1, len(prompt) // 4),
            "output_tokens": max(1, len(response) // 4),
            "source": "approximated",
        }

    @property
    def n_calls(self) -> int:
        return len(self.calls)

    @property
    def total_elapsed_s(self) -> float:
        return sum(c["elapsed_s"] for c in self.calls)

    @property
    def total_input_tokens(self) -> int:
        return sum(c["input_tokens"] for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c["output_tokens"] for c in self.calls)

    def reset(self):
        """Clear recorded calls (useful when reusing the wrapper)."""
        self.calls = []


# Pricing: Anthropic's published rates for Opus-class models. The numbers
# in $ per million tokens are documented; we record them here for the
# analysis script. Update at study execution time if rates change.
OPUS_PRICING_USD_PER_M_TOKENS = {
    "input": 15.00,   # $15 per million input tokens
    "output": 75.00,  # $75 per million output tokens
}


def compute_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Compute call cost in USD at protocol-recorded pricing."""
    return (
        input_tokens * OPUS_PRICING_USD_PER_M_TOKENS["input"] / 1_000_000
        + output_tokens * OPUS_PRICING_USD_PER_M_TOKENS["output"] / 1_000_000
    )

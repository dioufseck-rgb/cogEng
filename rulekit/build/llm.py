"""
LLM-driven build utilities.

This module hosts general-purpose utilities used by the LLM-driven
build pipeline (decomposer, refinement, deduplication) and by the
runtime Map substrates. Extracted from decomposer.py in Phase 1 of
the contract migration so these utilities have a stable home that
isn't entangled with the dataclass spec layer being retired.

Contents:

    LLMCaller
        Anthropic-API caller wrapper with offline-response support
        for tests. Streams by default; supports per-call max_tokens
        override and stream/non-stream selection.

    parse_json_response(text)
        Parse JSON from an LLM response. Strips markdown fences if
        present, and if the response contains reasoning before the
        JSON, finds the largest balanced JSON object or array.
        Tolerant to a degree that matters for production-grade LLM
        outputs but no further — bad JSON still raises
        JSONDecodeError.

    to_decimal_constant(value, label_for_error="")
        Coerce a JSON-derived numeric value (int, float, Decimal,
        string-with-currency-formatting) to a Decimal. Goes through
        str() for floats to avoid binary-representation error
        (Decimal(0.0912) is not what you want; Decimal(str(0.0912))
        is). Strips $ and commas from string inputs.

Stability
=========

The names in this module are stable. They are imported by Map
substrates (boolean.py, typed.py, structured.py), by bin/ scripts,
and by tests. The migration deliberately does not rename them.

Backward compatibility
======================

For the duration of the migration, decomposer.py re-exports
LLMCaller, _parse_json_response, and _to_decimal_constant so existing
imports keep working. The underscore-prefixed names are the legacy
spellings; the public-name spellings (parse_json_response,
to_decimal_constant) are the canonical forms going forward. Both
work.

When all consumers have been updated to import from build.llm
directly, the re-exports in decomposer.py can go away. That's a
separate commit.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Optional


# ---------------------------------------------------------------------------
# LLM caller
# ---------------------------------------------------------------------------

class LLMCaller:
    """Anthropic-API caller wrapper with offline-response support for tests.

    Parameters:
        model: model string (e.g. "claude-opus-4-7")
        offline_responses: dict of stage_name → canned response for tests.
            When `call(stage_name=...)` is invoked with a stage_name that
            appears as a key in this dict, the corresponding value is
            returned verbatim and no network call is made. Used by unit
            tests to exercise build/runtime code without LLM costs.
        max_tokens: default max output tokens per call (default 4096).
            Can be overridden per call.
        timeout: HTTP timeout in seconds (default 120).
    """

    def __init__(self, model: str = "claude-opus-4-7",
                 offline_responses: Optional[dict] = None,
                 max_tokens: int = 4096,
                 timeout: float = 120.0):
        self.model = model
        self.offline_responses = offline_responses or {}
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None

    def call(self, stage_name: str, prompt: str,
             max_tokens: Optional[int] = None,
             stream: bool = True) -> str:
        """Make an LLM call and return the text response.

        If `stage_name` is registered in `offline_responses`, the canned
        response is returned and no network call is made.

        Streaming is the default because long calls otherwise risk
        client-side hangs and offer no progress observability. Pass
        `stream=False` for short calls where streaming overhead isn't
        justified.
        """
        if stage_name in self.offline_responses:
            return self.offline_responses[stage_name]
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(timeout=self.timeout)
        mt = max_tokens if max_tokens is not None else self.max_tokens
        if stream:
            # Streaming — accumulate text deltas. Gives both progress
            # observability and avoids client-side hang on long calls.
            collected = []
            with self._client.messages.stream(
                model=self.model,
                max_tokens=mt,
                messages=[{"role": "user", "content": prompt}],
            ) as s:
                for text in s.text_stream:
                    collected.append(text)
            return "".join(collected)
        else:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=mt,
                messages=[{"role": "user", "content": prompt}],
            )
            # response.content is a list of content blocks. With adaptive
            # thinking enabled (default on Opus 4.7), the first block may
            # be a thinking block — extract from the first block of type
            # "text" instead.
            for block in response.content:
                block_type = getattr(block, "type", None)
                if block_type == "text" or (
                    block_type is None and hasattr(block, "text")
                ):
                    return block.text
            # No text block found — return empty so downstream parsers
            # surface the issue clearly.
            return ""


# ---------------------------------------------------------------------------
# JSON parsing tolerant of LLM preambles and markdown fences
# ---------------------------------------------------------------------------

def parse_json_response(text: str):
    """Parse JSON from an LLM response.

    Tolerances applied, in order:
        1. Whitespace stripped from both ends.
        2. Markdown fences (```json ... ```) stripped if present.
        3. Whole-text parse attempted (fast path for compliant
           responses).
        4. If the whole text doesn't parse, scan for balanced
           {...} and [...] blocks. Try each candidate, longest first,
           returning the first that parses. This handles responses
           where the model emitted reasoning before the JSON.

    Raises JSONDecodeError if no candidate parses. The error message
    includes the response length and the first 200 characters, which
    is enough context for debugging in practice without dumping
    arbitrary-length text into logs.
    """
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Try to parse the whole text first (fast path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: extract the last JSON object or array in the text.
    # This handles responses where the model emits reasoning before
    # the JSON, e.g. "Let me analyze... {...}". We grab the largest
    # well-formed JSON block by scanning from each opening
    # brace/bracket.
    candidates = []
    for i, ch in enumerate(text):
        if ch in "{[":
            # Try to find a balanced closing brace/bracket from here
            depth = 0
            in_str = False
            esc = False
            opener = ch
            closer = "}" if ch == "{" else "]"
            for j in range(i, len(text)):
                c = text[j]
                if esc:
                    esc = False
                    continue
                if c == "\\":
                    esc = True
                    continue
                if c == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[i:j + 1])
                        break
    # Try candidates from longest to shortest (longest is most likely
    # the full intended JSON, not a fragment inside reasoning)
    for cand in sorted(candidates, key=len, reverse=True):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    # All candidates failed — raise the original error type so callers
    # can handle it as before
    raise json.JSONDecodeError(
        f"No valid JSON found in response of length {len(text)}",
        text[:200], 0
    )


# Backward-compatible alias. Public callers should use
# parse_json_response; the underscore form remains for callers that
# import from this module during transition.
_parse_json_response = parse_json_response


# ---------------------------------------------------------------------------
# Decimal coercion from JSON-derived numeric values
# ---------------------------------------------------------------------------

def to_decimal_constant(value, label_for_error: str = "") -> Decimal:
    """Coerce a JSON-derived numeric value to a Decimal.

    Accepts: Decimal (returned unchanged), int, float, str.

    Floats go through `str()` to avoid binary-representation error:
        Decimal(0.0912) → Decimal('0.0912000000000000058...') — BAD
        Decimal(str(0.0912)) → Decimal('0.0912')               — GOOD

    Strings have `$` and `,` stripped before conversion, so values
    like `"$5,150,000"` parse as expected.

    `label_for_error` is included in the error message when
    conversion fails, for debugging which atom or constant caused
    the failure.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        return Decimal(cleaned)
    raise ValueError(
        f"Cannot convert {value!r} (type {type(value).__name__}) to Decimal"
        + (f" for {label_for_error!r}" if label_for_error else "")
    )


# Backward-compatible alias.
_to_decimal_constant = to_decimal_constant


__all__ = [
    "LLMCaller",
    "parse_json_response",
    "_parse_json_response",
    "to_decimal_constant",
    "_to_decimal_constant",
]

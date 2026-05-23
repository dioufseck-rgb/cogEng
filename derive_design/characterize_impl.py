"""
Substrate-calling characterize implementation.

Takes a characterize request (the structured dictionary the orchestrator
constructs), invokes Claude via the Anthropic API, parses the response,
and returns a NodeResult. This is the runtime substrate-dependent
operation; substrate variation in determinations traces here.
"""

import json
import os
from anthropic import Anthropic
from derive_orchestrator import NodeResult, EscalationSignals


# Default model. Swappable for cross-substrate investigation.
DEFAULT_MODEL = "claude-sonnet-4-5"


PROMPT_TEMPLATE = """You are evaluating a single condition from an insurance policy against \
the facts of a specific claim. Your job is to determine whether the facts \
satisfy the condition.

POLICY PROVISION: {policy_reference}

CONDITION:
{condition_text}

EXPECTED OUTPUT TYPE: {expected_output_type}

{definitions_section}

AVAILABLE FACTS:
{facts_section}

YOUR TASK:

Evaluate whether the available facts satisfy the condition.

Respond in this exact JSON structure (and nothing else — no preamble, no \
explanation outside the JSON):

{{
  "value": <typed value matching the expected output type, or null if you cannot commit>,
  "confidence": <number between 0 and 1 representing your certainty in your value>,
  "cited_facts": [<list of source identifiers from the available facts that materially support your evaluation>],
  "reasoning": "<1-3 sentences explaining your move from the cited facts to the value. Reference the condition and any relevant definitions. Do not introduce facts not in the input.>",
  "escalation_signals": {{
    "insufficient_facts": <true if required facts are missing from the input>,
    "contradictory_facts": <true if the facts conflict in ways you cannot principlely resolve from the facts alone>,
    "low_confidence_in_value": <true if you committed to a value but with confidence below 0.7>,
    "contested_reading": <true ONLY when the specific facts in THIS case sit at a genuine interpretive boundary where two competent reviewers applying the rule could reasonably reach different evaluations and the difference would matter for the outcome. Do NOT set true merely because rule text is in principle interpretable; almost every rule is. Set true when this specific case's facts create a real interpretive question.>,
    "requires_institutional_judgment": <true ONLY when reaching a defensible value depends on weighing considerations the rule does not specify (e.g., balancing patient autonomy against guideline conformance). Do NOT set true merely because clinical reasoning was involved; clinical reasoning by itself is not institutional judgment.>
  }},
  "escalation_reason": "<if any escalation signal is true, briefly explain why; otherwise empty string>"
}}

Rules for your response:

- Cite only facts that materially support your evaluation. Use the source \
identifiers from the AVAILABLE FACTS list (e.g., "claim intake free-text", \
"track incident report").
- Do not invent facts not in the input.
- Apply any definitions as given. If a definition is silent on an aspect, \
note the silence in your reasoning rather than substitute your own \
understanding.
- If the facts conflict and you cannot principlely resolve the conflict, \
set value to null, set contradictory_facts to true, and explain in the \
reasoning.
- If the condition cannot be evaluated cleanly from the facts and \
definitions alone — because the case sits at a genuine interpretive \
boundary that competent reviewers would resolve differently, or because \
reaching a value requires weighing considerations outside what the rule \
specifies — commit to your best reading at appropriate confidence and \
set contested_reading or requires_institutional_judgment accordingly. \
Be selective: these signals are about THIS case's specific facts \
creating a real interpretive issue, not about the rule being abstractly \
interpretable. If the rule and facts produce a clear answer for this \
specific case, do not set these signals just because someone could \
theoretically disagree.
- Keep reasoning to 1-3 sentences. Do not aggregate across conditions or \
opine on outcomes outside this specific condition.
- Output JSON only. No markdown, no preamble, no closing remarks.
"""


def format_facts_section(facts: list[dict]) -> str:
    """Render the facts list for inclusion in the prompt."""
    if not facts:
        return "(no facts surfaced for this condition; the source content " \
               "did not address it)"

    lines = []
    for f in facts:
        source = f.get("source_identifier", "unknown source")
        statement = f.get("statement", "")
        confidence = f.get("confidence", 0.0)
        source_class = f.get("source_class", "extract")
        field_name = f.get("field_name", "")

        # For retrieve facts, prefix the statement with the field name so
        # the substrate sees which schema field this value corresponds to.
        # Extract facts are already narrative-shaped and don't need this.
        if source_class == "retrieve" and field_name:
            statement_rendered = f"{field_name} = {statement}"
        else:
            statement_rendered = statement

        lines.append(
            f"- [{source_class}] {source} (confidence {confidence:.2f}):\n"
            f"  {statement_rendered}"
        )
    return "\n".join(lines)


def format_definitions_section(definitions: list) -> str:
    """Render the definitions for inclusion in the prompt."""
    if not definitions:
        return ""

    lines = ["DEFINITIONS (apply these in your evaluation):"]
    for d in definitions:
        if isinstance(d, str):
            lines.append(f"  - {d}")
        elif isinstance(d, dict):
            name = d.get("name", "unnamed definition")
            text = d.get("text", "")
            lines.append(f"  - {name}: {text}")
    lines.append("")  # blank line after section
    return "\n".join(lines)


def build_prompt(request: dict) -> str:
    """Build the characterize prompt from a request dict."""
    return PROMPT_TEMPLATE.format(
        policy_reference=request["policy_reference"],
        condition_text=request["condition"]["text"],
        expected_output_type=request["condition"]["expected_output_type"],
        definitions_section=format_definitions_section(
            request.get("definitions", [])
        ),
        facts_section=format_facts_section(request.get("facts", [])),
    )


def parse_response(text: str, request: dict) -> NodeResult:
    """Parse the substrate's JSON response into a NodeResult."""
    # Strip any markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        # Remove closing fence
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return NodeResult(
            node_id=request["node_id"],
            value=None,
            confidence=0.0,
            error=f"failed to parse substrate response as JSON: {e}",
            reasoning=f"raw response (first 200 chars): {text[:200]}",
            escalation_signals=EscalationSignals(
                requires_institutional_judgment=True,
            ),
            escalation_reason="substrate response could not be parsed",
        )

    # Extract escalation signals
    sig_dict = parsed.get("escalation_signals", {})
    signals = EscalationSignals(
        insufficient_facts=bool(sig_dict.get("insufficient_facts", False)),
        contradictory_facts=bool(sig_dict.get("contradictory_facts", False)),
        low_confidence_in_value=bool(sig_dict.get("low_confidence_in_value", False)),
        contested_reading=bool(sig_dict.get("contested_reading", False)),
        requires_institutional_judgment=bool(
            sig_dict.get("requires_institutional_judgment", False)
        ),
    )

    # Confidence — clamp to [0, 1]
    confidence = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    # Cited facts
    cited = parsed.get("cited_facts", [])
    if not isinstance(cited, list):
        cited = []

    return NodeResult(
        node_id=request["node_id"],
        value=parsed.get("value"),
        confidence=confidence,
        cited_facts=[str(c) for c in cited],
        reasoning=str(parsed.get("reasoning", "")),
        escalation_signals=signals,
        escalation_reason=str(parsed.get("escalation_reason", "")),
    )


class CharacterizeImpl:
    """
    Substrate-calling characterize implementation.

    Constructed with a model identifier. Invocation calls the Anthropic API,
    parses the response, returns a NodeResult.

    Tracks call metadata for analysis: how many calls were made, what each
    leaf returned, latency per call. Useful for empirical investigation.
    """

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str = None):
        self.model = model
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.call_log = []  # list of (request, response, latency_ms)

    def __call__(self, request: dict) -> NodeResult:
        prompt = build_prompt(request)

        import time
        start = time.time()
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            latency_ms = int((time.time() - start) * 1000)
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            result = NodeResult(
                node_id=request["node_id"],
                value=None,
                confidence=0.0,
                error=f"API call failed: {type(e).__name__}: {e}",
                escalation_signals=EscalationSignals(
                    requires_institutional_judgment=True,
                ),
                escalation_reason="substrate call failed",
            )
            self.call_log.append({
                "node_id": request["node_id"],
                "request": request,
                "response_text": None,
                "result": result,
                "latency_ms": latency_ms,
                "error": str(e),
            })
            return result

        result = parse_response(text, request)
        self.call_log.append({
            "node_id": request["node_id"],
            "request": request,
            "response_text": text,
            "result": result,
            "latency_ms": latency_ms,
            "error": None,
        })
        return result

    def summary(self) -> dict:
        """Summary statistics for the calls made so far."""
        total_calls = len(self.call_log)
        if total_calls == 0:
            return {"total_calls": 0}

        total_latency = sum(c["latency_ms"] for c in self.call_log)
        errors = sum(1 for c in self.call_log if c["error"] is not None)
        escalations = sum(
            1 for c in self.call_log
            if c["result"].escalation_flag
        )

        return {
            "total_calls": total_calls,
            "total_latency_ms": total_latency,
            "avg_latency_ms": total_latency / total_calls,
            "errors": errors,
            "escalations": escalations,
            "model": self.model,
        }

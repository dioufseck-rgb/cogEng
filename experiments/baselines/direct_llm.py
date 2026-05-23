"""
Direct-LLM baseline (System B in the protocol).

Single LLM call per case: input is the full policy text plus the case
description; output is structured JSON with determination and explanation.

Three candidate prompts (P1 minimal, P2 structured, P3 chain-of-thought)
are evaluated on the held-out validation set; the best is frozen as
`direct_llm_prompt.txt` and used for the main experiment.
"""

from __future__ import annotations
import json
import sys
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(os.path.dirname(_HERE))  # nested → project root
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

from rulekit.build.decomposer import _parse_json_response


# -----------------------------------------------------------------------
# Three candidate prompts (Section 4 of the protocol)
# -----------------------------------------------------------------------

PROMPT_P1_MINIMAL = """Read the policy and case below. Determine whether
the case satisfies the policy. Output ONLY a JSON object with two fields:

{{
  "determination": "approved" | "denied" | "insufficient_evidence",
  "explanation": "<one paragraph>"
}}

POLICY:
{policy_text}

CASE:
{case_description}

DETERMINATIONS TO PRODUCE (one truth value per id):
{determination_descriptions}

OUTPUT FORMAT:
{{
  "determinations": {{
    "<det_id>": "true" | "false" | "undetermined"
  }},
  "explanation": "<one paragraph>"
}}

Output only the JSON object. No preamble.
"""


PROMPT_P2_STRUCTURED = """You are an experienced {voice}. Read the policy
below and the case description below.

Step 1: Identify the policy's requirements relevant to the determination(s)
listed.

Step 2: For each requirement, evaluate whether the case description
supports it (true), contradicts it (false), or fails to address it
(undetermined). Do not assume facts not stated.

Step 3: Combine your evaluations under the policy's logical structure
(AND/OR/exception pathways) to produce each determination.

POLICY:
{policy_text}

CASE:
{case_description}

DETERMINATIONS TO PRODUCE:
{determination_descriptions}

OUTPUT FORMAT:
{{
  "determinations": {{
    "<det_id>": "true" | "false" | "undetermined"
  }},
  "explanation": "<paragraph naming the requirements you evaluated and how they combined>"
}}

Output only the JSON object. No preamble.
"""


PROMPT_P3_CHAIN_OF_THOUGHT = """You are an experienced {voice}. Read the
policy and case carefully. Work through the determination step by step.

THINK STEP BY STEP, showing your reasoning in the explanation field:

1. List the policy's requirements.
2. For each requirement, state explicitly whether the case satisfies it,
   fails to satisfy it, or has insufficient evidence. Quote the relevant
   policy text and the relevant case fact for each.
3. Apply the policy's logical structure (which requirements are
   conjunctive, which are alternatives, which are exception pathways).
4. Conclude with the determination.

Be conservative: if the case does not explicitly support a requirement,
mark it undetermined rather than guessing. If any required element is
undetermined, the overall determination should generally be undetermined.

POLICY:
{policy_text}

CASE:
{case_description}

DETERMINATIONS TO PRODUCE:
{determination_descriptions}

OUTPUT FORMAT:
{{
  "determinations": {{
    "<det_id>": "true" | "false" | "undetermined"
  }},
  "explanation": "<your full step-by-step reasoning>"
}}

Output only the JSON object. No preamble, no commentary outside the JSON.
"""


CANDIDATE_PROMPTS = {
    "P1": PROMPT_P1_MINIMAL,
    "P2": PROMPT_P2_STRUCTURED,
    "P3": PROMPT_P3_CHAIN_OF_THOUGHT,
}


# -----------------------------------------------------------------------
# Frozen prompt accessor
# -----------------------------------------------------------------------

def load_frozen_prompt(path: str = None, allow_default: bool = False) -> str:
    """
    Load the frozen prompt from disk (set by `select_prompt.py` after
    validation). The protocol requires this to be set before main
    experiment runs.

    If allow_default=True (pilot mode), falls back to the P2 (structured)
    candidate if no frozen prompt exists. This lets the pilot verify the
    end-to-end pipeline before validation cases are authored. The main
    experiment must use a properly-selected prompt (allow_default=False).
    """
    if path is None:
        path = os.path.join(_HERE, "direct_llm_prompt.txt")
    if not os.path.exists(path):
        if allow_default:
            import sys
            print(
                f"[pilot fallback] No frozen prompt at {path}; "
                f"using P2 (structured) as default. This is only acceptable "
                f"for pilot runs. Main experiment requires "
                f"`python harness/select_prompt.py` to have run.",
                file=sys.stderr,
            )
            return CANDIDATE_PROMPTS["P2"]
        raise FileNotFoundError(
            f"Frozen prompt not found at {path}. "
            f"Run `python harness/select_prompt.py` first to choose and "
            f"freeze a baseline prompt per protocol Section 4."
        )
    with open(path) as f:
        return f.read()


# -----------------------------------------------------------------------
# Run baseline on a single case
# -----------------------------------------------------------------------

def run_direct_llm(case: dict, policy_text: str,
                   determination_specs: list[dict],
                   voice_role: str,
                   timed_llm, prompt_template: str = None) -> dict:
    """
    Single-call adjudication via direct-LLM.

    Args:
        case: case dict with 'description', 'case_id', 'expected_outcomes'
        policy_text: the full policy text
        determination_specs: list of {id, description, polarity}
        voice_role: institutional role description
        timed_llm: TimedLLMCaller instance
        prompt_template: which template to use (None = load frozen)

    Returns:
        {
          'determinations': {det_id: "true"|"false"|"undetermined"},
          'raw_output': str,
          'explanation': str,
          'parsed_ok': bool,
          'parse_error': str | None
        }
    """
    if prompt_template is None:
        prompt_template = load_frozen_prompt()

    # Format the determination descriptions section
    det_desc = "\n".join(
        f"  - {d['id']}: {d['description']}"
        for d in determination_specs
    )

    prompt = prompt_template.format(
        voice=voice_role,
        policy_text=policy_text,
        case_description=case["description"],
        determination_descriptions=det_desc,
    )

    raw = timed_llm.call("direct_llm_judge", prompt)

    # Parse robustly. If parsing fails, record the raw and mark as parse error.
    try:
        parsed = _parse_json_response(raw)
        # Normalize: protocol requires each declared det_id to have a value
        determinations = {}
        for d in determination_specs:
            v = parsed.get("determinations", {}).get(d["id"], "undetermined")
            determinations[d["id"]] = _normalize_kleene_str(v)
        explanation = parsed.get("explanation", "")
        return {
            "determinations": determinations,
            "raw_output": raw,
            "explanation": explanation,
            "parsed_ok": True,
            "parse_error": None,
        }
    except Exception as e:
        # Defensive parse: try regex extraction of det values
        determinations = {d["id"]: "undetermined" for d in determination_specs}
        return {
            "determinations": determinations,
            "raw_output": raw,
            "explanation": "",
            "parsed_ok": False,
            "parse_error": str(e),
        }


def _normalize_kleene_str(v) -> str:
    """Normalize an LLM-emitted truth value to one of true/false/undetermined."""
    if v is None:
        return "undetermined"
    s = str(v).strip().lower()
    # Map common variants
    if s in ("true", "t", "yes", "approved", "approve", "approval"):
        return "true"
    if s in ("false", "f", "no", "denied", "deny", "denial", "rejected"):
        return "false"
    if s in ("undetermined", "unknown", "insufficient_evidence",
             "insufficient", "indeterminate", "u"):
        return "undetermined"
    return "undetermined"

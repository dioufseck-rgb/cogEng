"""
RuleKit builder — Substage A1: atom extraction.

Input: policy source text plus a reasonable-reader voice declaration.
Output: a list of Atom objects with stable IDs, atomic statements, and
        source attribution.

Discipline: every atom is atomic. No logical connectives. No compound
claims. Atomize to the maximum granularity the source supports.

This module is part of the tree-builder pipeline:
    A1 (atoms) + A2 (determinations) -> B (cross-validation) -> C (association)
A1 is implemented here. A2 and downstream substages are stubs for now.
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Optional

from rulekit.schema import Atom


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ReaderVoice:
    """The reasonable-reader voice for a specific drafting culture."""
    role: str             # e.g., "plan medical director", "appeals adjudicator"
    domain: str           # e.g., "medical-necessity authorization for cervical surgery"
    background: str       # context the reader brings to the policy

    @classmethod
    def pa_reviewer(cls) -> "ReaderVoice":
        return cls(
            role="experienced plan medical director and prior authorization reviewer",
            domain="medical-necessity authorization for cervical spinal surgery",
            background=(
                "You understand clinical documentation conventions, the distinction "
                "between radiculopathy and myelopathy, what physical therapy "
                "documentation typically contains, and how exception provisions "
                "modify base requirements."
            ),
        )

    @classmethod
    def fcba_reviewer(cls) -> "ReaderVoice":
        return cls(
            role="experienced credit card dispute adjudicator at a financial institution",
            domain="billing error resolution under FCBA",
            background=(
                "You understand how billing errors are categorized under "
                "Regulation Z, how dispute documentation flows, and how "
                "different reason codes map to the enumerated billing-error "
                "categories."
            ),
        )


# ---------------------------------------------------------------------------
# Atomicity discipline — mechanical check
# ---------------------------------------------------------------------------

# Logical connective patterns. The check is conservative: flag anything that
# might be a connective. The LLM revision pass resolves false positives.
CONNECTIVE_PATTERNS = [
    # Standard logical connectives as whole words
    (r"\band\b", "and"),
    (r"\bor\b", "or"),
    (r"\beither\b", "either"),
    (r"\bneither\b", "neither"),
    (r"\bnor\b", "nor"),
    (r"\bunless\b", "unless"),
    (r"\bexcept\b", "except"),
    (r"\bif\b", "if"),
    # Comma-separated lists often hide disjunction or conjunction
    (r",\s*\w+\s*,\s*\w+", "comma-separated list"),
    # Slash often hides disjunction
    (r"\w+/\w+", "slash-separated"),
]


def check_atomicity(statement: str) -> list[str]:
    """
    Return a list of detected connective patterns in the statement.
    Empty list means atomicity check passed.
    Some patterns require LLM judgment to confirm (e.g., "and" in "name and account")
    so this is a first-pass mechanical scan, not a final verdict.
    """
    statement_lower = statement.lower()
    detected = []
    for pattern, label in CONNECTIVE_PATTERNS:
        if re.search(pattern, statement_lower):
            detected.append(label)
    return detected


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

A1_PROMPT_TEMPLATE = """You are a {role} reading a {domain} policy.

{background}

Your task is atom extraction. You will read a section of policy and produce a list of atomic propositions that the policy makes about cases.

An atom is a single claim that can be true or false about a case. Atoms MUST be atomic:
- No logical connectives (and, or, not, either, neither, unless, except).
- No compound claims joining multiple facts.
- If a policy sentence contains "X and Y" as joint requirements, split into two atoms (X) and (Y).
- If a policy sentence contains "X or Y" as alternatives, split into two atoms (X) and (Y).
- If a sentence has "X with Y" where X and Y are independently evaluable, split.
- A modifier inside a single claim (e.g., "supervised physical therapy") may itself need splitting if the modifier is separately evaluable ("PT happened" and "PT was supervised" are two atoms).

For each atom, produce:
- id: a short stable identifier you choose, prefixed with the policy abbreviation. Use lowercase with dots, e.g., "pa.diagnosis_radiculopathy" or "pa.pt_six_weeks". Keep IDs descriptive but compact.
- statement: the atomic claim as a single declarative sentence about the case, in natural language.
- source_span: a citation to the section, subsection, or paragraph in the policy where this atom is drawn from. Use the policy's own numbering.

Do NOT produce atoms for:
- Section headings or titles.
- Scope statements (who the policy applies to).
- References to other policies or authorities.
- Process or procedural requirements that don't bear on the determination outcome.
- Examples or commentary.

DO produce atoms for:
- Each requirement that the policy specifies must hold for a case.
- Each criterion that the policy enumerates as a possible basis for a determination.
- Each condition that the policy attaches to a requirement or exception.

Output format: a JSON array of objects, each with keys "id", "statement", "source_span". Output ONLY the JSON, no other text.

POLICY TEXT:
{policy_text}
"""


def build_a1_prompt(policy_text: str, voice: ReaderVoice) -> str:
    """Construct the prompt for substage A1."""
    return A1_PROMPT_TEMPLATE.format(
        role=voice.role,
        domain=voice.domain,
        background=voice.background,
        policy_text=policy_text,
    )


# ---------------------------------------------------------------------------
# LLM call (Anthropic API)
# ---------------------------------------------------------------------------

def call_llm_a1(prompt: str, model: str = "claude-opus-4-7") -> str:
    """
    Call the Anthropic API with the A1 prompt. Returns raw response text.
    """
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def call_llm_a1_offline(prompt: str, response_text: str) -> str:
    """
    Offline variant: accept a pre-generated response text. Useful when
    running without API access, or for replaying a saved response in tests.
    The 'prompt' argument is accepted for interface symmetry but not used.
    """
    return response_text


# ---------------------------------------------------------------------------
# Parsing the LLM response
# ---------------------------------------------------------------------------

def parse_a1_response(response_text: str) -> list[dict]:
    """
    Parse the LLM's JSON response. Handles common formatting issues
    (markdown code fences, leading/trailing whitespace).
    """
    text = response_text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


# ---------------------------------------------------------------------------
# The substage A1 entry point
# ---------------------------------------------------------------------------

@dataclass
class A1Result:
    """Result of running substage A1."""
    atoms: dict[str, Atom]              # atom_id -> Atom
    atomicity_flags: dict[str, list[str]]   # atom_id -> list of detected connectives
    raw_response: str                   # the LLM's raw output for audit
    prompt: str                         # the prompt that was sent


def run_a1(policy_text: str, voice: ReaderVoice,
           model: str = "claude-opus-4-7",
           offline_response: Optional[str] = None) -> A1Result:
    """
    Run substage A1 (atom extraction) over a policy text.
    Returns an A1Result with atoms, atomicity flags, and audit fields.

    If offline_response is provided, skip the LLM API call and use that
    response text directly. Useful for testing without API access.
    """
    prompt = build_a1_prompt(policy_text, voice)
    if offline_response is not None:
        raw_response = offline_response
    else:
        raw_response = call_llm_a1(prompt, model=model)
    parsed = parse_a1_response(raw_response)

    atoms = {}
    atomicity_flags = {}
    for entry in parsed:
        atom = Atom(
            id=entry["id"],
            statement=entry["statement"],
            source_span=entry["source_span"],
        )
        atoms[atom.id] = atom
        flags = check_atomicity(atom.statement)
        if flags:
            atomicity_flags[atom.id] = flags

    return A1Result(
        atoms=atoms,
        atomicity_flags=atomicity_flags,
        raw_response=raw_response,
        prompt=prompt,
    )

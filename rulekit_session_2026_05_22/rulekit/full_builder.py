"""
RuleKit builder — end-to-end pipeline.

Takes a policy document as input and produces:
- An atom list (extraction with atomicity discipline)
- A determination list (with linkage metadata)
- An association graph (atoms-to-determinations)
- A composed tree per determination
- A schema with typed field declarations

The output is a BuildResult with everything needed to evaluate cases.

Pipeline stages:
  Stage 1: extract_atoms (with revision pass for flagged atoms)
  Stage 2: extract_determinations
  Stage 3: associate (atoms-to-determinations with operator hints)
  Stage 4: compose (per determination, produce the tree)
  Stage 5: build_schema (typed fields for every atom)

Discipline:
- Every LLM call has bounded input, bounded output, single responsibility.
- Mechanical validation runs after each LLM call.
- Failures route to a focused revision call with the diagnostic.
- The full pipeline is run end-to-end with the LLM acting as the substrate.
"""

from __future__ import annotations
import json
import re
import os
from dataclasses import dataclass, field
from typing import Optional, Any, Union

from rulekit.schema import Atom, Schema, SchemaField, EvalMode
from rulekit.engine import (
    Leaf, AndNode, OrNode, AtLeastNode, NotNode, CardinalityNode,
    Determination, Provenance,
)
from rulekit.builder import (
    ReaderVoice, check_atomicity, parse_a1_response,
)


# ---------------------------------------------------------------------------
# LLM call abstraction (with offline support)
# ---------------------------------------------------------------------------

class LLMCaller:
    """
    Wraps the LLM call interface. Supports online (Anthropic API) and
    offline (pre-recorded responses) modes.
    """

    def __init__(self, model: str = "claude-opus-4-7",
                 offline_responses: Optional[dict] = None):
        self.model = model
        self.offline_responses = offline_responses or {}
        self._client = None

    def call(self, stage_name: str, prompt: str) -> str:
        """
        Call the LLM. If offline_responses has a key matching stage_name,
        return that. Otherwise hit the API.
        """
        if stage_name in self.offline_responses:
            return self.offline_responses[stage_name]
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text


def _parse_json_response(text: str) -> Any:
    """Parse a JSON response, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Stage 1: Extract atoms
# ---------------------------------------------------------------------------

EXTRACT_ATOMS_PROMPT = """You are a {role} reading a {domain} policy.

{background}

Your task is atom extraction. Read the policy and produce atomic propositions
that the policy makes about cases.

An atom is a single claim about a case that can be true, false, or
undetermined given evidence. The right granularity for atoms is governed by
two indicators working together:

1. THE POLICY'S DRAFTING. Lettered sub-items, numbered sub-sections, explicit
   "and"/"or" conjunctions, and bulleted lists are structural cues that the
   policy itself draws boundaries. Honor those boundaries.

2. THE EVIDENCE'S STRUCTURE. Atoms should be separately evaluable from the
   kinds of records the substrate has access to. If two claims always
   co-evaluate from the same evidence, they probably belong in one atom.
   If they could evaluate differently (one TRUE, one FALSE; or one
   UNDETERMINED while the other is settled), they belong in separate atoms.

When the two indicators agree, follow them. When they conflict, use judgment.
The examples below show the calibration.

EXAMPLES OF CORRECT ATOMIZATION
================================

Example 1 — joint requirement with separable evidence
------------------------------------------------------
Policy text: "The applicant must submit a completed form within 30 days of
the qualifying event."

Good atoms:
  - "The applicant submitted a completed form."
  - "The submission occurred within 30 days of the qualifying event."

Rationale: Two operationally distinct claims. A case where the form was
submitted but the timing is unclear should evaluate UNDETERMINED on the
timing atom and TRUE on the submission atom, not UNDETERMINED on a single
bundled claim. Splitting preserves information at the leaves.

Example 2 — enumerated sub-clauses
-----------------------------------
Policy text: "(a) The form is signed by the applicant, (b) the form is
notarized, and (c) the form is submitted in original."

Good atoms:
  - "The form is signed by the applicant."
  - "The form is notarized."
  - "The form is submitted in original."

Rationale: The policy explicitly enumerates three sub-clauses with letters.
Each is a distinct requirement establishable from distinct evidence (the
signature, the notary stamp, the document type). Honor the structure the
policy draws.

Example 3 — disjunctive eligibility criteria
---------------------------------------------
Policy text: "Eligibility requires either (a) a state-issued license, or
(b) certification by an approved professional body."

Good atoms:
  - "The applicant holds a state-issued license."
  - "The applicant holds certification by an approved professional body."

Rationale: Two alternatives. Each is separately evaluable. The disjunction
between them belongs at the composition stage (joined by OR), not inside a
single atom.

Example 4 — negation of a disjunction (De Morgan)
--------------------------------------------------
Policy text: "The transaction was not authorized by the cardholder or
anyone with delegated authority."

Good atoms:
  - "The transaction was unauthorized by the cardholder."
  - "The transaction was unauthorized by anyone with delegated authority."

Rationale: The disjunction is inside a negation. By De Morgan, "not (A or
B)" equals "(not A) and (not B)". Each negation is a separately evaluable
claim (different evidence sources: cardholder testimony vs delegated-
authority records). The conjunction is then handled at composition time
(AND of the two atoms), NOT by listing the original "or" as a disjunction.

DO NOT produce: ["unauthorized_use", "no actual authority", "no implied
authority", "no apparent authority", ...] — that over-decomposes the
single "authority" concept the policy treats as one and risks producing a
disjunction (OR) where the logic requires a conjunction (AND).

Example 5 — separable modifier
-------------------------------
Policy text: "The treatment was supervised and directed at the underlying
condition."

Good atoms:
  - "The treatment was supervised."
  - "The treatment was directed at the underlying condition."

Rationale: "Supervised" and "directed at the underlying condition" are
distinct claims evaluable from distinct documentation (who supervised vs.
what the treatment targeted). They could evaluate differently in a real
case.

EXAMPLES OF OVER-ATOMIZATION (avoid this)
==========================================

Example A — atomic noun phrase that splits poorly
--------------------------------------------------
Policy text: "The applicant must hold a valid license issued by the state
board."

Over-atomized (WRONG):
  - "The applicant has a license."
  - "The license is valid."
  - "The license was issued by a state board."

Why this is wrong: These claims aren't separately evaluable from typical
evidence. A license record either shows a valid, state-board-issued license
or it doesn't. The three "atoms" always co-evaluate from the same source.

Correct atomization:
  - "The applicant holds a valid license issued by the state board."

Caveat: If the substrate genuinely has separate evidence streams for
license validity vs issuing authority (e.g., one registry verifies
validity, a different registry verifies the issuing authority), then
splitting is warranted. Granularity follows the evidence structure.

Example B — splitting a single concept into kinds
--------------------------------------------------
Policy text: "The applicant has good standing with the committee."

Over-atomized (WRONG):
  - "The applicant has financial good standing."
  - "The applicant has ethical good standing."
  - "The applicant has procedural good standing."

Why this is wrong: "Good standing" is a single concept the policy treats
as one. Inventing sub-kinds the policy doesn't draw imposes structural
detail the policy doesn't make. Atoms should not introduce content the
policy doesn't make explicit.

Correct atomization:
  - "The applicant has good standing with the committee."

EXAMPLES OF UNDER-ATOMIZATION (avoid this)
===========================================

Example C — collapsing enumerated sub-clauses into one
--------------------------------------------------------
Policy text: "(a) The form is signed, (b) the form is notarized, and
(c) the form is submitted in original."

Under-atomized (WRONG):
  - "The form is signed, notarized, and submitted in original."

Why this is wrong: The policy explicitly enumerates three sub-clauses. Each
should be its own atom. Bundling loses the structure the policy itself draws
and produces an atom containing a logical connective ("and").

Example D — bundling a time-window with an underlying requirement
------------------------------------------------------------------
Policy text: "Member must have current imaging within 6 months that
demonstrates structural pathology."

Under-atomized (WRONG):
  - "Member has imaging within 6 months demonstrating structural
    pathology."

Why this is wrong: This atom hides three separable claims: (1) imaging
exists, (2) within 6 months, (3) demonstrates structural pathology. Each
is independently evaluable. A case might have imaging that is current but
shows no pathology — this should evaluate FALSE on the pathology atom and
TRUE on the recency atom, not UNDETERMINED on the bundled claim.

Correct atomization:
  - "Imaging is available for the member."
  - "The imaging was performed within 6 months of the request."
  - "The imaging demonstrates structural pathology."

ATOMS YOU SHOULD NOT PRODUCE
=============================
- Section headings or titles
- Scope statements describing who/what the policy applies to
- References to other policies, authorities, or statutes (these are
  context, not claims about cases)
- Procedural requirements that don't affect the determination outcome
- Examples or commentary the policy includes for illustration
- Determinations themselves (what the policy decides) — those are handled
  separately

ATOMS YOU SHOULD PRODUCE
=========================
- Each requirement that must hold for the determination
- Each enumerated criterion the policy lists as a possible basis
- Each condition attached to a requirement or exception
- Each temporal or quantitative threshold ("within 6 months",
  "at least 4 weeks")
- Each documentation requirement ("physician must provide attestation")

OUTPUT FORMAT
==============
Produce a JSON array of objects. Each object has:
- "id": a short stable identifier prefixed with "{abbreviation}.", using
  lowercase with dots (e.g., "{abbreviation}.diagnosis_confirmed",
  "{abbreviation}.imaging_recent").
- "statement": the atomic claim as a single declarative sentence about
  the case.
- "source_span": a citation to the section, subsection, or paragraph in
  the policy where this atom is drawn from. Use the policy's own numbering
  (e.g., "2.1(a)", "1026.13(a)(3)"). Never put a sentence in source_span;
  use only the policy's structural reference.

Output ONLY the JSON array. No preamble, no commentary, no markdown
code fences.

POLICY TEXT:
{policy_text}
"""


REVISE_ATOMS_PROMPT = """You previously extracted atoms from a policy. Some atoms still contain logical connectives that need to be split.

Here are the atoms that need revision:

{flagged_atoms}

For each flagged atom, produce one or more split atoms that are properly atomic. Keep the source_span the same. For IDs, append a letter suffix (e.g., the atom "pa.diagnosis_radic" becomes "pa.diagnosis_radic_a" and "pa.diagnosis_radic_b" if split into two).

Output format: a JSON object mapping each original atom ID to a list of split atom objects with keys "id", "statement", "source_span".

Example:
{{
  "original_id_1": [
    {{"id": "original_id_1_a", "statement": "First split claim.", "source_span": "..."}},
    {{"id": "original_id_1_b", "statement": "Second split claim.", "source_span": "..."}}
  ]
}}

Output ONLY the JSON, no other text.
"""


def extract_atoms(policy_text: str, voice: ReaderVoice, abbreviation: str,
                  llm: LLMCaller) -> tuple[dict[str, Atom], dict[str, list[str]], str]:
    """
    Stage 1: extract atoms from policy text.
    Returns (atoms, atomicity_flags, raw_response).
    """
    prompt = EXTRACT_ATOMS_PROMPT.format(
        role=voice.role, domain=voice.domain, background=voice.background,
        abbreviation=abbreviation, policy_text=policy_text,
    )
    raw = llm.call("extract_atoms", prompt)
    parsed = _parse_json_response(raw)

    atoms = {}
    flags = {}
    for entry in parsed:
        atom = Atom(id=entry["id"], statement=entry["statement"],
                    source_span=entry["source_span"])
        atoms[atom.id] = atom
        f = check_atomicity(atom.statement)
        if f:
            flags[atom.id] = f
    return atoms, flags, raw


def revise_flagged_atoms(atoms: dict[str, Atom], flags: dict[str, list[str]],
                         llm: LLMCaller) -> dict[str, Atom]:
    """
    Revision pass: for each flagged atom, ask the LLM for proper splits.
    Returns the updated atom dict with flagged atoms replaced by their splits.
    """
    if not flags:
        return atoms

    flagged_text = "\n".join(
        f"- {atom_id} (flags: {fl}) → {atoms[atom_id].statement}"
        for atom_id, fl in flags.items()
    )
    prompt = REVISE_ATOMS_PROMPT.format(flagged_atoms=flagged_text)
    raw = llm.call("revise_atoms", prompt)
    parsed = _parse_json_response(raw)

    revised = dict(atoms)
    for original_id, splits in parsed.items():
        if original_id in revised:
            del revised[original_id]
        for split_entry in splits:
            split_atom = Atom(
                id=split_entry["id"],
                statement=split_entry["statement"],
                source_span=split_entry["source_span"],
            )
            revised[split_atom.id] = split_atom
    return revised


# ---------------------------------------------------------------------------
# Stage 2: Extract determinations
# ---------------------------------------------------------------------------

EXTRACT_DETERMINATIONS_PROMPT = """You are a {role} reading a {domain} policy.

{background}

Your task is determination extraction. A determination is an outcome the policy can produce when applied to a case. Examples:
- "Authorization approved" / "Authorization denied"
- "Qualifies as a billing error" / "Does not qualify as a billing error"
- "Motion in order" / "Motion out of order"

For each determination the policy establishes, produce:
- id: a short stable identifier (e.g., "{abbreviation}.D1", "{abbreviation}.D2").
- description: a one-sentence description of the outcome.
- polarity: "positive" or "negative" if linked to another determination on the same axis (e.g., approval is positive, denial is negative). Use null if the determination stands alone.
- linked_to: the id of the linked determination if any. Use null if standalone.
- source_span: where in the policy the determination is established.
- transcribed: true if the policy explicitly states this determination; false if it is inferred (e.g., denial is often inferred as the structural complement of approval).

Most policies have at least two linked determinations (an approval/denial pair, an in-order/out-of-order pair, etc.). The negative one is often inferred from the structure of the positive one.

Policy abbreviation: {abbreviation}

Output format: a JSON array of objects. Output ONLY the JSON, no other text.

POLICY TEXT:
{policy_text}
"""


@dataclass
class DeterminationSpec:
    """Lightweight determination specification before composition."""
    id: str
    description: str
    polarity: Optional[str]
    linked_to: Optional[str]
    source_span: str
    transcribed: bool


def extract_determinations(policy_text: str, voice: ReaderVoice,
                           abbreviation: str,
                           llm: LLMCaller) -> tuple[dict[str, DeterminationSpec], str]:
    """Stage 2: extract determinations from policy text."""
    prompt = EXTRACT_DETERMINATIONS_PROMPT.format(
        role=voice.role, domain=voice.domain, background=voice.background,
        abbreviation=abbreviation, policy_text=policy_text,
    )
    raw = llm.call("extract_determinations", prompt)
    parsed = _parse_json_response(raw)

    determinations = {}
    for entry in parsed:
        det = DeterminationSpec(
            id=entry["id"],
            description=entry["description"],
            polarity=entry.get("polarity"),
            linked_to=entry.get("linked_to"),
            source_span=entry["source_span"],
            transcribed=entry.get("transcribed", True),
        )
        determinations[det.id] = det
    return determinations, raw


# ---------------------------------------------------------------------------
# Stage 3: Compose tree per determination (combines association + composition)
# ---------------------------------------------------------------------------

COMPOSE_TREE_PROMPT = """You are a {role} reading a {domain} policy.

{background}

You have already extracted atoms and identified that the policy establishes determination {det_id}: "{det_description}".

Your task is to compose a tree that expresses the policy's logical structure for this determination, using only the atoms provided. The tree should be true exactly when the determination holds.

OPERATORS — use exactly one per node:

- "and": all children must hold. Use when the policy says "all of the following," 
  "and," or lists requirements as joint conditions.

- "or": at least one child must hold. Use when the policy says "any of the 
  following," "or," or lists alternatives.

- "not": exactly one child, polarity inverted. Use when the policy negates a 
  condition ("not X," "without X").

- "at_least": at least N of K children must hold. Use ONLY when the policy 
  uses explicit cardinality language ("at least N of the following") AND the 
  number of possible combinations is large enough that explicit expansion 
  would be unwieldy.

HANDLING "AT LEAST N" CARDINALITY:

The policy may use language like "at least 2 of the following four pharma classes." 
For such cardinality, follow this rule:

- If the number of qualifying combinations (N-choose-k) is 6 or fewer, EXPAND 
  the cardinality explicitly into an OR over conjunctions. For example, "at 
  least 2 of {{A, B, C, D}}" becomes:
  
    or(
      and(A, B), and(A, C), and(A, D),
      and(B, C), and(B, D), and(C, D)
    )
  
  List ALL combinations.

- If the expansion would exceed 6 combinations, emit a single "at_least" node 
  with the threshold N declared. Do not expand.

DE MORGAN TRANSFORMATIONS:

When the policy expresses a condition as the negation of a disjunction ("not 
made to A or B"), the equivalent positive form is the conjunction of negations:

    and(not(A), not(B))

When the policy expresses the negation of a conjunction ("did not provide both 
X and Y"), the equivalent is:

    or(not(X), not(Y))

Apply these transformations explicitly when composing the tree. Do NOT produce 
or(A, B, C, D) when the policy semantics is and(not(...)) — that is a logical 
error.

PROVENANCE — for each operator you commit to, mark its source:

- "transcribed": the policy explicitly draws this operator ("all of the 
  following," "any of the following," "at least N")
- "structural": the operator is implied by policy organization (numbered 
  subsections, parenthetical lists)
- "inferred": the operator is the reasonable reader's interpretation when the 
  policy is silent

For inferred operators, include "latent_type" (one of: "scope", "binding", 
"edge-case", "meta-interpretation") and "confidence" (0.0 to 1.0).

LINKED DETERMINATIONS:

If this is a negative determination linked to a positive one (e.g., DENIED 
linked to APPROVED), and there are no independent grounds for denial in the 
source text, you may produce a tree that is just NOT(other_determination). 
Set type to "not_other_determination" and include "other_id".

OUTPUT FORMAT — a JSON object representing the tree. Each node has:

- "type": one of "and", "or", "not", "at_least", "leaf", or "not_other_determination"

- For "and": "children" (list of subtrees), "surface_label" (string, e.g., "ALL 
  (Section 2 criteria)"), "provenance" (string), "source_span" (string), and 
  optionally "latent_type" and "confidence" for inferred operators.

- For "or": same as "and", with surface_label like "ANY (diagnosis)".

- For "at_least": "n" (integer), "children", "surface_label" (e.g., "AT LEAST 
  N of the following"), "provenance", "source_span".

- For "not": "child" (subtree, not list), "provenance", "source_span", optionally 
  "latent_type" and "confidence".

- For "leaf": "atom_id" (string).

- For "not_other_determination": "other_id" (string).

ATOMS AVAILABLE (use only these atom IDs in leaves):
{atom_listing}

POLICY TEXT:
{policy_text}

LINKED DETERMINATIONS (for context — you are composing for {det_id} specifically):
{linked_listing}

Output ONLY the JSON, no other text.
"""


def _format_atom_listing(atoms: dict[str, Atom]) -> str:
    lines = []
    for atom_id, atom in atoms.items():
        lines.append(f"- {atom_id} [{atom.source_span}]: {atom.statement}")
    return "\n".join(lines)


def _format_linked_listing(dets: dict[str, DeterminationSpec], current_id: str) -> str:
    lines = []
    for did, det in dets.items():
        if did == current_id:
            continue
        polarity = det.polarity or "neutral"
        lines.append(f"- {did} ({polarity}, transcribed={det.transcribed}): {det.description}")
    return "\n".join(lines) if lines else "(none)"


def _build_node_from_dict(node_dict: dict, atoms: dict[str, Atom],
                          other_trees: dict[str, Any]):
    """
    Recursively build a node from the LLM's JSON tree representation.
    Supports operators: and, or, not, at_least, leaf, not_other_determination.
    """
    from rulekit.engine import AndNode, OrNode, AtLeastNode, NotNode, Leaf

    node_type = node_dict["type"]

    if node_type == "leaf":
        atom_id = node_dict["atom_id"]
        if atom_id not in atoms:
            raise ValueError(f"Leaf references unknown atom: {atom_id}")
        return Leaf(atom_id=atom_id)

    if node_type == "not_other_determination":
        other_id = node_dict["other_id"]
        if other_id not in other_trees:
            raise ValueError(f"Reference to unbuilt determination: {other_id}")
        return NotNode(
            child=other_trees[other_id],
            provenance=Provenance.INFERRED,
            source_span="Structural complement of linked determination",
            confidence=0.9,
            latent_type="meta-interpretation",
        )

    if node_type == "not":
        child = _build_node_from_dict(node_dict["child"], atoms, other_trees)
        return NotNode(
            child=child,
            provenance=Provenance(node_dict.get("provenance", "structural")),
            source_span=node_dict.get("source_span", ""),
            confidence=node_dict.get("confidence"),
            latent_type=node_dict.get("latent_type"),
        )

    if node_type == "and":
        children = [_build_node_from_dict(c, atoms, other_trees) for c in node_dict["children"]]
        if len(children) < 1:
            raise ValueError(f"and node has no children. Surface label: {node_dict.get('surface_label', '?')}")
        return AndNode(
            children=children,
            surface_label=node_dict.get("surface_label", ""),
            provenance=Provenance(node_dict.get("provenance", "structural")),
            source_span=node_dict.get("source_span", ""),
            confidence=node_dict.get("confidence"),
            latent_type=node_dict.get("latent_type"),
        )

    if node_type == "or":
        children = [_build_node_from_dict(c, atoms, other_trees) for c in node_dict["children"]]
        if len(children) < 1:
            raise ValueError(f"or node has no children. Surface label: {node_dict.get('surface_label', '?')}")
        return OrNode(
            children=children,
            surface_label=node_dict.get("surface_label", ""),
            provenance=Provenance(node_dict.get("provenance", "structural")),
            source_span=node_dict.get("source_span", ""),
            confidence=node_dict.get("confidence"),
            latent_type=node_dict.get("latent_type"),
        )

    if node_type == "at_least":
        children = [_build_node_from_dict(c, atoms, other_trees) for c in node_dict["children"]]
        n = node_dict["n"]
        k = len(children)
        if n < 1:
            raise ValueError(
                f"at_least node has n={n} (must be ≥ 1). "
                f"Surface label: {node_dict.get('surface_label', '?')}"
            )
        if n > k:
            raise ValueError(
                f"at_least node has n={n} > k={k} (unsatisfiable threshold). "
                f"Surface label: {node_dict.get('surface_label', '?')}."
            )
        return AtLeastNode(
            n=n,
            children=children,
            surface_label=node_dict.get("surface_label", ""),
            provenance=Provenance(node_dict.get("provenance", "structural")),
            source_span=node_dict.get("source_span", ""),
            confidence=node_dict.get("confidence"),
            latent_type=node_dict.get("latent_type"),
        )

    raise ValueError(f"Unknown node type: {node_type}")


def compose_tree(det: DeterminationSpec, atoms: dict[str, Atom],
                 all_determinations: dict[str, DeterminationSpec],
                 policy_text: str, voice: ReaderVoice,
                 other_trees: dict[str, Any], llm: LLMCaller) -> tuple[Any, str]:
    """Stage 3: compose the tree for a specific determination."""
    prompt = COMPOSE_TREE_PROMPT.format(
        role=voice.role, domain=voice.domain, background=voice.background,
        det_id=det.id, det_description=det.description,
        atom_listing=_format_atom_listing(atoms),
        policy_text=policy_text,
        linked_listing=_format_linked_listing(all_determinations, det.id),
    )
    raw = llm.call(f"compose_{det.id}", prompt)
    parsed = _parse_json_response(raw)
    tree = _build_node_from_dict(parsed, atoms, other_trees)
    return tree, raw


# ---------------------------------------------------------------------------
# Stage 4: Build schema
# ---------------------------------------------------------------------------

BUILD_SCHEMA_PROMPT = """You are a {role} working on the operationalization of a {domain} policy.

For each atom, decide:
- evaluation_mode: one of "computed", "characterized", or "looked_up".
  - "computed" if the atom's truth value should be derived by deterministic arithmetic (e.g., "PT duration ≥ 6 weeks" — compute the duration from records, compare to threshold).
  - "characterized" if the atom requires judgment from the substrate against textual records (e.g., "diagnosis is confirmed").
  - "looked_up" if the value comes from a table or external service (e.g., "member's plan type is PPO").
- specification: a short note describing how the field is to be evaluated (computation rule for computed, prompt-style spec for characterized, lookup source for looked_up).
- undetermined_rule: when this field produces UNDETERMINED rather than TRUE/FALSE.

ATOMS:
{atom_listing}

Output format: a JSON object mapping atom_id to an object with keys "evaluation_mode", "specification", "undetermined_rule". Output ONLY the JSON, no other text.
"""


def build_schema(atoms: dict[str, Atom], voice: ReaderVoice, schema_name: str,
                 llm: LLMCaller) -> tuple[Schema, str]:
    """Stage 4: build the schema with typed field declarations."""
    prompt = BUILD_SCHEMA_PROMPT.format(
        role=voice.role, domain=voice.domain,
        atom_listing=_format_atom_listing(atoms),
    )
    raw = llm.call("build_schema", prompt)
    parsed = _parse_json_response(raw)

    fields = {}
    for atom_id, spec in parsed.items():
        if atom_id not in atoms:
            continue
        fields[atom_id] = SchemaField(
            atom_id=atom_id,
            evaluation_mode=EvalMode(spec["evaluation_mode"]),
            specification=spec["specification"],
            undetermined_rule=spec["undetermined_rule"],
        )

    schema = Schema(name=schema_name, atoms=atoms, fields=fields)
    return schema, raw


# ---------------------------------------------------------------------------
# End-to-end builder
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    """Result of the end-to-end builder."""
    atoms: dict[str, Atom]
    schema: Schema
    determinations: dict[str, Determination]
    atomicity_flags: dict[str, list[str]]
    audit: dict[str, str]    # stage_name -> raw response


def build_from_policy(policy_text: str, voice: ReaderVoice,
                      abbreviation: str, schema_name: str,
                      llm: LLMCaller) -> BuildResult:
    """
    End-to-end builder. Takes a policy document and produces a complete
    set of Determination objects with schema and atoms, ready for evaluation.

    Pipeline:
      1. Extract atoms (with revision for flagged ones)
      2. Extract determinations
      3. Compose tree per determination
      4. Build schema
    """
    audit = {}

    # Stage 1: extract atoms
    atoms, flags, raw1 = extract_atoms(policy_text, voice, abbreviation, llm)
    audit["extract_atoms"] = raw1

    # Stage 1b: revise flagged atoms
    if flags:
        atoms = revise_flagged_atoms(atoms, flags, llm)
        # Re-run atomicity check on the revised atoms
        flags = {aid: check_atomicity(a.statement)
                 for aid, a in atoms.items()
                 if check_atomicity(a.statement)}

    # Stage 2: extract determinations
    determinations_spec, raw2 = extract_determinations(
        policy_text, voice, abbreviation, llm,
    )
    audit["extract_determinations"] = raw2

    # Stage 3: compose tree per determination
    # Compose transcribed determinations first so inferred ones can reference them.
    determination_objects = {}
    other_trees: dict[str, Any] = {}

    order = sorted(determinations_spec.keys(),
                   key=lambda did: 0 if determinations_spec[did].transcribed else 1)
    for det_id in order:
        det_spec = determinations_spec[det_id]
        tree, raw_compose = compose_tree(
            det_spec, atoms, determinations_spec, policy_text,
            voice, other_trees, llm,
        )
        audit[f"compose_{det_id}"] = raw_compose
        other_trees[det_id] = tree

        determination_objects[det_id] = Determination(
            id=det_id,
            description=det_spec.description,
            tree=tree,
            provenance=Provenance.TRANSCRIBED if det_spec.transcribed else Provenance.INFERRED,
            polarity=det_spec.polarity,
            linked_to=det_spec.linked_to,
            source_span=det_spec.source_span,
        )

    # Stage 4: build schema
    schema, raw3 = build_schema(atoms, voice, schema_name, llm)
    audit["build_schema"] = raw3

    return BuildResult(
        atoms=atoms,
        schema=schema,
        determinations=determination_objects,
        atomicity_flags=flags,
        audit=audit,
    )

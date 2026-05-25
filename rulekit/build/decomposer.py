"""
Top-down decomposer.

Builds the DAG by recursively decomposing each declared determination
against the policy text. Each LLM call is small and bounded: given a
claim, return either "atomic" or "an operator with these N children."

The recursion terminates when every path reaches an atomic claim.

After decomposition, a single deduplication pass identifies semantically
equivalent atoms and merges them — making the structure a DAG rather
than a tree.

This module is independent of full_builder.py. Both can coexist while
we evaluate which approach is more reliable.
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Union

from rulekit.engine import (
    Kleene, Leaf, AndNode, OrNode, AtLeastNode, NotNode,
    Determination, Provenance, FactBundle,
)
from rulekit.engine.typed import (
    NumericLeaf, Constant,
    TimesConstNode, PlusConstNode, MinusConstNode, ConstMinusNode,
    DivByConstNode, ConstDivByNode,
    EqNode, LtNode, LeqNode, GtNode, GeqNode,
)
from rulekit.schema import Atom
from rulekit.build.extract import ReaderVoice


# ---------------------------------------------------------------------------
# Determination spec — the institution's input
# ---------------------------------------------------------------------------

@dataclass
class DeterminationDeclaration:
    """Institution-declared determination — what the build must produce."""
    id: str
    description: str
    polarity: str = "neutral"  # positive / negative / neutral
    linked_to: Optional[str] = None
    source_span: str = ""
    composition: str = "derived"  # "derived" (LLM composes) or "complement" (NOT of linked)
    scope_hint: Optional[str] = None  # natural-language hint to focus the LLM


@dataclass
class BuildSpec:
    """Full institutional spec for a build.

    The spec is the institution's declarative input. It carries everything
    a domain-agnostic library needs to produce a runnable adjudicator from
    policy text:

      - policy metadata (name, source path, short abbreviation)
      - the reader voice (role/domain/background) — either inline as a
        ``voice`` field, or as a ``voice_key`` referencing a registered
        named voice (legacy/example use)
      - named numeric constants used by the policy (e.g. salary cap,
        threshold values), as a dict from snake_case label to Decimal
      - the list of declared determinations the build must produce

    The library is policy-domain-agnostic — NBA, FINRA, FCBA, PA, tax,
    insurance, healthcare adjudication all express the same shape here.
    """
    policy_name: str
    policy_source: str
    abbreviation: str
    determinations: list[DeterminationDeclaration]
    # Voice: either inline (preferred for library use) or registry key (legacy).
    # Exactly one of `voice` and `voice_key` must be set.
    voice: Optional["ReaderVoice"] = None
    voice_key: Optional[str] = None
    # Named numeric constants (e.g., {"salary_cap": Decimal("140588000")}).
    # Threaded into Stage-4 engine conversion so ConstantSpec(label=...) and
    # UnaryArithmeticSpec(constant_label=...) resolve to real values.
    constants: dict[str, Decimal] = field(default_factory=dict)

    def __post_init__(self):
        if self.voice is None and self.voice_key is None:
            raise ValueError(
                f"BuildSpec requires either a `voice` (inline ReaderVoice) "
                f"or a `voice_key` (registered name). Got neither for "
                f"policy {self.policy_name!r}."
            )
        if self.voice is not None and self.voice_key is not None:
            raise ValueError(
                f"BuildSpec requires exactly one of `voice` or `voice_key`, "
                f"not both. Got both for policy {self.policy_name!r}."
            )


def load_spec_from_yaml(path: str, voices_registry: Optional[dict] = None) -> BuildSpec:
    """Load a YAML build spec from a path.

    The YAML may declare the voice in either of two ways:

      1. INLINE (preferred, domain-agnostic):
         voice:
           role: "experienced adjudicator at ..."
           domain: "..."
           background: |
             Multi-line background...

      2. REGISTRY LOOKUP (legacy / built-in examples):
         policy:
           voice: "pa"        # key into voices_registry

    Constants may be declared inline:
         constants:
           some_named_value: 140588000

    Values are coerced to Decimal at load time so the engine's arithmetic
    is precision-preserving.

    Backward-compat: existing PA/FCBA YAMLs that use ``policy.voice``
    as a registry key continue to work as long as ``voices_registry``
    is passed (typically ``domains.voices.VOICES``). If both inline
    ``voice`` block and ``policy.voice`` key are present, the inline
    block takes precedence.

    Uses PyYAML; install via `pip install pyyaml`.
    """
    import yaml
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Voice resolution: inline block beats legacy registry key
    voice: Optional[ReaderVoice] = None
    voice_key: Optional[str] = None
    if "voice" in data:
        # Inline voice block — preferred path
        v = data["voice"]
        voice = ReaderVoice(
            role=v["role"],
            domain=v["domain"],
            background=v["background"],
        )
    elif "voice" in data.get("policy", {}):
        # Legacy: policy.voice is a registry key
        voice_key = data["policy"]["voice"]
        if voices_registry is not None and voice_key in voices_registry:
            voice = voices_registry[voice_key]()
            voice_key = None  # consumed
        # If no registry passed in, BuildSpec stores voice_key and the
        # caller is responsible for resolution.

    # Constants block: optional, coerced to Decimal via str() to avoid
    # float-binary representation errors (Decimal(0.0912) is bad;
    # Decimal('0.0912') is good).
    constants: dict[str, Decimal] = {}
    for label, value in (data.get("constants") or {}).items():
        if isinstance(value, str):
            # Strip $ and commas if user wrote "$140,588,000"
            cleaned = value.replace("$", "").replace(",", "").strip()
            constants[label] = Decimal(cleaned)
        elif isinstance(value, int):
            constants[label] = Decimal(value)
        elif isinstance(value, float):
            constants[label] = Decimal(str(value))
        else:
            raise ValueError(
                f"Constants value for {label!r} must be int/float/str, "
                f"got {type(value).__name__}: {value!r}"
            )

    return BuildSpec(
        policy_name=data["policy"]["name"],
        policy_source=data["policy"]["source"],
        abbreviation=data["policy"]["abbreviation"],
        voice=voice,
        voice_key=voice_key,
        constants=constants,
        determinations=[
            DeterminationDeclaration(**d) for d in data["determinations"]
        ],
    )


# ---------------------------------------------------------------------------
# Node specs — intermediate representation between LLM and engine
# ---------------------------------------------------------------------------

@dataclass
class LeafSpec:
    """An atomic claim — terminates the recursion."""
    claim: str  # the natural-language statement
    source_span: str = ""
    # Assigned during deduplication
    atom_id: Optional[str] = None


@dataclass
class OperatorSpec:
    """An internal node — operator over a list of child claims."""
    operator: str  # "and", "or", "not", "at_least"
    children: list[Union["LeafSpec", "OperatorSpec", "ComparisonSpec"]]
    n: Optional[int] = None  # for at_least only
    surface_label: str = ""
    source_span: str = ""
    provenance: str = "structural"  # transcribed / structural / inferred
    confidence: Optional[float] = None
    latent_type: Optional[str] = None


@dataclass
class NumericLeafSpec:
    """An atomic numeric attribute — extracted by Map from case data.

    Produced by the typed numeric sub-decomposer (Piece 2). Becomes an
    engine NumericLeaf node at Stage-4 conversion.
    """
    atom_id_hint: str       # snake_case identifier, e.g. "team_salary"
    statement: str          # natural-language description of what Map extracts
    source_span: str = ""
    # Assigned during typed-atom deduplication (Piece 6, not yet implemented)
    atom_id: Optional[str] = None


@dataclass
class ConstantSpec:
    """A literal or named-policy numeric constant.

    Produced by the typed numeric sub-decomposer (Piece 2). Becomes an
    engine Constant node at Stage-4 conversion. Either ``value`` (bare
    literal) or ``label`` (named CBA constant) is set; never both.
    """
    value: Optional[float] = None      # bare numeric literal
    label: Optional[str] = None        # snake_case named constant
    source_span: str = ""

    def __post_init__(self):
        if (self.value is None) == (self.label is None):
            raise ValueError(
                f"ConstantSpec must have exactly one of value or label set "
                f"(got value={self.value!r}, label={self.label!r})"
            )


@dataclass
class UnaryArithmeticSpec:
    """An engine-expressible unary arithmetic node: child OP constant.

    The six operators correspond to the typed engine's arithmetic nodes:
        times_const, plus_const, minus_const, const_minus,
        div_by_const, const_div_by.

    The child is itself a NumericSpec — possibly another UnaryArithmeticSpec
    (allowing nested expressions like "9.12% of (cap minus prior salary)").
    Produced by the typed numeric sub-decomposer (Piece 2). Becomes the
    corresponding engine arithmetic node at Stage-4 conversion.
    """
    operator: str           # "times_const" | "plus_const" | "minus_const" |
                            # "const_minus" | "div_by_const" | "const_div_by"
    constant: Optional[float] = None       # numeric literal constant
    constant_label: Optional[str] = None   # OR a named constant label
    child: Optional["NumericSpec"] = None   # nested numeric spec
    surface_label: str = ""
    source_span: str = ""

    def __post_init__(self):
        if (self.constant is None) == (self.constant_label is None):
            raise ValueError(
                f"UnaryArithmeticSpec must have exactly one of constant or "
                f"constant_label set (got constant={self.constant!r}, "
                f"constant_label={self.constant_label!r})"
            )
        if self.child is None:
            raise ValueError(
                f"UnaryArithmeticSpec requires a child (operator={self.operator!r})"
            )


@dataclass
class DerivedAtomSpec:
    """A numeric quantity whose computation is delegated to Map.

    Used for arithmetic the engine deliberately cannot express:
      - aggregate_sum: sum over multiple instances
      - max_of / min_of: max or min over multiple terms
      - conditional: arithmetic whose form depends on a condition
      - named_quantity: a derived quantity defined elsewhere in the policy

    See typed_build_decisions.md, Decisions 4 and 5. Becomes an engine
    NumericLeaf node at Stage-4 conversion; Map computes the value per
    case using a per-atom extraction prompt informed by the statement.
    """
    atom_id_hint: str
    statement: str
    computation_kind: str   # "aggregate_sum" | "max_of" | "min_of" |
                            # "conditional" | "named_quantity"
    source_span: str = ""
    # Assigned during typed-atom deduplication (Piece 6, not yet implemented)
    atom_id: Optional[str] = None


# Union over the four numeric spec types produced by Piece 2
NumericSpec = Union[NumericLeafSpec, ConstantSpec, UnaryArithmeticSpec, DerivedAtomSpec]


@dataclass
class ComparisonSpec:
    """A numeric comparison node — produced by the typed Stage-1 classifier.

    The classifier emits the operator and free-text LHS/RHS descriptions;
    the numeric sub-decomposer (Piece 2) then expands each description into
    a structured NumericSpec tree. Both stages happen during the decomposer's
    recursion: when a comparison is identified, the sub-decomposer is invoked
    immediately to populate lhs_spec and rhs_spec.

    The free-text descriptions and kind hints are retained for audit and
    debugging; the structured specs are what Stage-4 engine conversion
    consumes.

    Stage-4 conversion (Piece 5) is not yet implemented — ComparisonSpec
    still raises NotImplementedError at spec_to_engine_node. Boolean-only
    policies (PA, FCBA) build cleanly; typed policies halt at conversion.
    """
    operator: str  # "leq", "lt", "geq", "gt", "eq"
    lhs_description: str
    rhs_description: str
    lhs_kind: str  # "numeric_leaf" | "constant" | "arithmetic"
    rhs_kind: str  # "numeric_leaf" | "constant" | "arithmetic"
    # Structured LHS/RHS specs — populated by the sub-decomposer after
    # the classifier returns a comparison. None until expanded.
    lhs_spec: Optional[NumericSpec] = None
    rhs_spec: Optional[NumericSpec] = None
    surface_label: str = ""
    source_span: str = ""
    provenance: str = "structural"
    confidence: Optional[float] = None
    latent_type: Optional[str] = None


NodeSpec = Union[LeafSpec, OperatorSpec, ComparisonSpec]


# ---------------------------------------------------------------------------
# Decomposition prompt
# ---------------------------------------------------------------------------

DECOMPOSE_PROMPT = """You are a {role} reading a {domain} policy.

{background}

You are building a logical decomposition tree for a determination. At each
step you are given a single claim. You must decide whether the claim is
ATOMIC (cannot be decomposed further) or COMPOSED (decomposed by an
operator over sub-claims).

Determination being decomposed: {determination_id}
Determination description: {determination_description}
{scope_section}

Current claim to decompose: "{claim}"

Path from determination root to this claim (breadcrumb):
{path}

POLICY TEXT (excerpt):
{policy_text}

DECIDING WHETHER A CLAIM IS ATOMIC
====================================

A claim is ATOMIC when:
- It is a single proposition evaluable from typical evidence as true,
  false, or undetermined.
- It contains no logical connectives (and, or, not, either, neither,
  unless, except) that would require decomposition.
- Further splitting would produce sub-claims that always co-evaluate
  from the same evidence source.

A claim is COMPOSED when:
- It contains explicit conjunction ("all of the following", "and"),
  disjunction ("any of the following", "or"), negation ("not", "without"),
  or cardinality ("at least N of").
- The policy's drafting explicitly enumerates sub-clauses for this claim.
- The claim can be separated into independently evaluable sub-claims.

EXAMPLES OF ATOMIC CLAIMS
==========================
- "The applicant submitted a completed form."
- "The submission occurred within 30 days of the qualifying event."
- "The applicant holds a valid license issued by the state board."
- "The treatment was supervised."

EXAMPLES OF COMPOSED CLAIMS
============================
- "The applicant submitted a completed form within 30 days." → AND of
  two atomic claims (submission + timing).
- "Eligibility requires a state-issued license or certification by an
  approved body." → OR of two atomic claims.
- "The transaction was not authorized by the cardholder or anyone with
  delegated authority." → AND of two negated atomic claims (De Morgan):
  "transaction unauthorized by cardholder" AND "transaction unauthorized
  by delegated authority."

OPERATORS YOU MAY USE FOR COMPOSED CLAIMS
==========================================
- "and": all children must hold.
- "or": at least one child must hold.
- "not": exactly one child, polarity inverted.
- "at_least": at least N of K children must hold. Use ONLY when the
  policy uses explicit cardinality language AND the number of qualifying
  combinations would be unwieldy to expand. For small cardinality (≤6
  combinations of choosing N from K), prefer to expand to OR of ANDs.

DE MORGAN TRANSFORMATIONS
==========================
When the policy expresses a condition as the negation of a disjunction
("not A or B"), the equivalent positive form is the conjunction of
negations: AND(NOT A, NOT B). Apply this transformation explicitly.

PROVENANCE
============
For each operator you commit to, mark its source:
- "transcribed": the policy explicitly draws this operator.
- "structural": the operator is implied by policy organization.
- "inferred": the operator is the reasonable reader's interpretation
  when the policy is silent.

For inferred operators, include "latent_type" (scope / binding /
edge-case / meta-interpretation) and "confidence" (0.0–1.0).

OUTPUT FORMAT
==============

If the claim is ATOMIC, output:
{{
  "type": "leaf",
  "claim": "{claim}",
  "source_span": "<policy section/subsection reference>"
}}

If the claim is COMPOSED, output:
{{
  "type": "and" | "or" | "not" | "at_least",
  "n": <integer, only for at_least>,
  "children": [
    {{"claim": "<sub-claim 1>", "source_span": "<reference>"}},
    {{"claim": "<sub-claim 2>", "source_span": "<reference>"}},
    ...
  ],
  "surface_label": "<short descriptive label>",
  "provenance": "transcribed" | "structural" | "inferred",
  "source_span": "<policy section/subsection reference>"
}}

For inferred operators, also include "latent_type" and "confidence".

The children's claims are sub-claims that will be recursively decomposed.
Do not decompose them yourself — produce only the immediate decomposition
of THIS claim, with each child as a claim string the decomposer will
expand in its own step.

Use the policy's own numbering for source_span (e.g., "2.1(a)",
"1026.13(a)(3)"). Never put a sentence in source_span; use only the
policy's structural reference.

Output ONLY the JSON object. No preamble, no commentary, no markdown
code fences.
"""


# ---------------------------------------------------------------------------
# LLM caller (reused interface from full_builder)
# ---------------------------------------------------------------------------

class LLMCaller:
    def __init__(self, model: str = "claude-opus-4-7",
                 offline_responses: Optional[dict] = None):
        self.model = model
        self.offline_responses = offline_responses or {}
        self._client = None

    def call(self, stage_name: str, prompt: str) -> str:
        if stage_name in self.offline_responses:
            return self.offline_responses[stage_name]
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        # response.content is a list of content blocks. With adaptive thinking
        # enabled (default on Opus 4.7), the first block may be a thinking
        # block — extract from the first block of type "text" instead.
        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text" or (block_type is None and hasattr(block, "text")):
                return block.text
        # No text block found — return empty so downstream parsers surface
        # the issue clearly.
        return ""


def _parse_json_response(text: str):
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
    # well-formed JSON block by scanning from each opening brace/bracket.
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
                        candidates.append(text[i:j+1])
                        break
    # Try candidates from longest to shortest (longest is most likely the
    # full intended JSON, not a fragment inside reasoning)
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


# ---------------------------------------------------------------------------
# The recursive decomposer
# ---------------------------------------------------------------------------

@dataclass
class DecomposeState:
    """State tracked across decomposition calls."""
    llm: LLMCaller
    policy_text: str
    voice: ReaderVoice
    determination: DeterminationDeclaration
    max_depth: int = 10
    call_count: int = 0
    audit: list[dict] = field(default_factory=list)


def decompose_claim(claim: str, path: list[str], depth: int,
                    state: DecomposeState) -> NodeSpec:
    """Recursively decompose a claim into a NodeSpec."""
    if depth > state.max_depth:
        # Safety net — if recursion goes too deep, treat as atomic.
        return LeafSpec(claim=claim, source_span="(forced atomic: max depth)")

    state.call_count += 1
    stage_name = f"decompose_{state.determination.id}_{state.call_count:03d}"

    scope_section = ""
    if state.determination.scope_hint:
        scope_section = f"Scope focus: {state.determination.scope_hint}"

    # Use the typed Stage-1 classifier prompt. This prompt extends the
    # Boolean classification (leaf/and/or/not/at_least) with a COMPARISON
    # outcome for numeric inequalities and equalities. Boolean-only policies
    # (PA, FCBA) continue to produce only Boolean classifications; typed
    # policies (NBA) gain access to ComparisonSpec outputs.
    from rulekit.build.typed_classify_prompt import render_prompt
    prompt = render_prompt(
        role=state.voice.role,
        domain=state.voice.domain,
        background=state.voice.background,
        determination_id=state.determination.id,
        determination_description=state.determination.description,
        scope_section=scope_section,
        claim=claim,
        path="\n".join(f"  - {p}" for p in path) if path else "  (root)",
        policy_text=state.policy_text,
    )

    raw = state.llm.call(stage_name, prompt)
    state.audit.append({
        "stage": stage_name,
        "claim": claim,
        "depth": depth,
        "raw_response": raw,
    })
    parsed = _parse_json_response(raw)

    return _build_spec_from_parsed(parsed, path, depth, state)


def _build_spec_from_parsed(parsed: dict, path: list[str], depth: int,
                            state: DecomposeState) -> NodeSpec:
    """Convert parsed JSON into a NodeSpec, recursing on children."""
    raw_type = parsed.get("type", "")
    # Normalize: lowercase, replace hyphens with underscores
    node_type = raw_type.strip().lower().replace("-", "_")

    if node_type == "leaf":
        return LeafSpec(
            claim=parsed["claim"],
            source_span=parsed.get("source_span", ""),
        )

    if node_type == "comparison":
        # Numeric comparison — the Stage-1 classifier identifies the operator
        # and provides free-text descriptions of LHS and RHS. We immediately
        # invoke the Piece-2 numeric sub-decomposer to expand each description
        # into a structured NumericSpec tree (NumericLeafSpec / ConstantSpec /
        # UnaryArithmeticSpec / DerivedAtomSpec). Both stages happen during
        # this single decompose_claim call so callers see a fully-expanded
        # ComparisonSpec.
        #
        # Stage-4 engine conversion (Piece 5) is not yet implemented; the
        # populated ComparisonSpec will still raise NotImplementedError at
        # spec_to_engine_node until that piece lands. Boolean-only policies
        # build cleanly.
        lhs_spec = decompose_numeric_expression(
            description=parsed["lhs_description"],
            kind=parsed["lhs_kind"],
            state=state,
        )
        rhs_spec = decompose_numeric_expression(
            description=parsed["rhs_description"],
            kind=parsed["rhs_kind"],
            state=state,
        )
        return ComparisonSpec(
            operator=parsed["operator"],
            lhs_description=parsed["lhs_description"],
            rhs_description=parsed["rhs_description"],
            lhs_kind=parsed["lhs_kind"],
            rhs_kind=parsed["rhs_kind"],
            lhs_spec=lhs_spec,
            rhs_spec=rhs_spec,
            surface_label=parsed.get("surface_label", ""),
            source_span=parsed.get("source_span", ""),
            provenance=parsed.get("provenance", "structural"),
            confidence=parsed.get("confidence"),
            latent_type=parsed.get("latent_type"),
        )

    # Map common operator variants to canonical names
    op_aliases = {
        "and": "and",
        "all": "and",
        "all_of": "and",
        "conjunction": "and",
        "or": "or",
        "any": "or",
        "any_of": "or",
        "disjunction": "or",
        "not": "not",
        "negation": "not",
        "at_least": "at_least",
        "atleast": "at_least",
        "at_least_n": "at_least",
        "cardinality": "at_least",
        "n_of": "at_least",
    }
    if node_type not in op_aliases:
        raise ValueError(
            f"Unknown operator type {raw_type!r} (normalized to {node_type!r}). "
            f"Surface label: {parsed.get('surface_label', '?')!r}. "
            f"Expected one of: leaf, and, or, not, at_least, comparison."
        )
    canonical = op_aliases[node_type]

    # Composed — recurse on each child claim
    child_specs = []
    children_data = parsed.get("children", [])
    for child_dict in children_data:
        child_claim = child_dict["claim"]
        new_path = path + [parsed.get("surface_label", canonical)]
        child_spec = decompose_claim(child_claim, new_path, depth + 1, state)
        child_specs.append(child_spec)

    if canonical == "not":
        # NOT has exactly one child
        if len(child_specs) != 1:
            raise ValueError(
                f"NOT operator must have exactly one child, got {len(child_specs)}"
            )
        return OperatorSpec(
            operator="not",
            children=child_specs,
            surface_label=parsed.get("surface_label", ""),
            source_span=parsed.get("source_span", ""),
            provenance=parsed.get("provenance", "structural"),
            confidence=parsed.get("confidence"),
            latent_type=parsed.get("latent_type"),
        )

    return OperatorSpec(
        operator=canonical,
        children=child_specs,
        n=parsed.get("n"),
        surface_label=parsed.get("surface_label", ""),
        source_span=parsed.get("source_span", ""),
        provenance=parsed.get("provenance", "structural"),
        confidence=parsed.get("confidence"),
        latent_type=parsed.get("latent_type"),
    )


# ---------------------------------------------------------------------------
# Piece 2: numeric sub-decomposer
# ---------------------------------------------------------------------------
#
# When the Stage-1 classifier returns a comparison, we expand each side's
# free-text description into a structured NumericSpec tree by calling the
# numeric sub-decomposer prompt. The prompt is defined in
# typed_numeric_decompose_prompt.py and has been validated against 17 eval
# cases live (see tests/eval_typed_decomposer/eval_cases_sub_decomposer.json).


def decompose_numeric_expression(description: str, kind: str,
                                 state: "DecomposeState") -> NumericSpec:
    """Invoke the typed numeric sub-decomposer for one (description, kind) pair.

    Returns one of:
      - NumericLeafSpec: case-data numeric attribute
      - ConstantSpec: literal or named policy constant
      - UnaryArithmeticSpec: engine-expressible unary arithmetic (recursive)
      - DerivedAtomSpec: arithmetic delegated to Map (aggregate / max / etc.)

    The sub-decomposer prompt internalizes the engine's intentionally-bounded
    arithmetic vocabulary; see typed_build_decisions.md (Decisions 4, 5).
    """
    from rulekit.build.typed_numeric_decompose_prompt import (
        render_numeric_decompose_prompt,
    )
    state.call_count += 1
    stage_name = (
        f"numeric_decompose_{state.determination.id}_{state.call_count:03d}"
    )
    prompt = render_numeric_decompose_prompt(description=description, kind=kind)
    raw = state.llm.call(stage_name, prompt)
    state.audit.append({
        "stage": stage_name,
        "description": description,
        "kind": kind,
        "raw_response": raw,
    })
    parsed = _parse_json_response(raw)
    return _build_numeric_spec_from_parsed(parsed, state)


def _build_numeric_spec_from_parsed(parsed: dict,
                                    state: "DecomposeState") -> NumericSpec:
    """Convert sub-decomposer JSON output into a NumericSpec tree.

    Recurses on the child of unary_arithmetic so nested expressions like
    'TIMES_CONST(0.0912, CONST_MINUS(cap, prior_salary))' are built fully
    by a single top-level call.
    """
    spec_type = parsed.get("spec_type", "").strip().lower()

    if spec_type == "numeric_leaf":
        return NumericLeafSpec(
            atom_id_hint=parsed["atom_id_hint"],
            statement=parsed.get("statement", ""),
            source_span=parsed.get("source_span", ""),
        )

    if spec_type == "constant":
        # Exactly one of value or label must be present
        value = parsed.get("value")
        label = parsed.get("label")
        return ConstantSpec(
            value=value,
            label=label,
            source_span=parsed.get("source_span", ""),
        )

    if spec_type == "unary_arithmetic":
        operator = parsed["operator"].strip().lower()
        valid_ops = {
            "times_const", "plus_const", "minus_const",
            "const_minus", "div_by_const", "const_div_by",
        }
        if operator not in valid_ops:
            raise ValueError(
                f"Unknown unary_arithmetic operator {operator!r}. "
                f"Expected one of: {sorted(valid_ops)}"
            )
        # The child is itself a NumericSpec — recurse
        child_parsed = parsed.get("child")
        if child_parsed is None:
            raise ValueError(
                f"unary_arithmetic spec missing 'child' field. "
                f"Operator: {operator!r}"
            )
        child_spec = _build_numeric_spec_from_parsed(child_parsed, state)
        return UnaryArithmeticSpec(
            operator=operator,
            constant=parsed.get("constant"),
            constant_label=parsed.get("constant_label"),
            child=child_spec,
            surface_label=parsed.get("surface_label", ""),
            source_span=parsed.get("source_span", ""),
        )

    if spec_type == "derived_atom":
        return DerivedAtomSpec(
            atom_id_hint=parsed["atom_id_hint"],
            statement=parsed.get("statement", ""),
            computation_kind=parsed["computation_kind"],
            source_span=parsed.get("source_span", ""),
        )

    raise ValueError(
        f"Unknown numeric spec_type {spec_type!r}. "
        f"Expected one of: numeric_leaf, constant, unary_arithmetic, derived_atom."
    )


# ---------------------------------------------------------------------------
# Deduplication — find semantically equivalent leaves and merge
# ---------------------------------------------------------------------------

DEDUP_PROMPT = """You are reviewing leaf claims extracted by recursive
decomposition of a policy. Some claims may be semantically equivalent —
they reference the same underlying fact even if worded differently.

Your task is to identify equivalence groups. For each group, choose one
representative claim. The other claims in the group will be unified with
the representative.

CRITERIA FOR EQUIVALENCE
=========================
Two claims are equivalent if:
- They evaluate from the same evidence source.
- They would always co-evaluate (TRUE together, FALSE together,
  UNDETERMINED together) given the same case.
- Differences in wording do not imply different propositions.

Two claims are NOT equivalent if:
- They reference different evidence (even if topically related).
- They could evaluate differently for some case (e.g., "PT for 6 weeks"
  vs "PT for 4 weeks" — different thresholds, not equivalent).
- One contains an additional qualifier the other lacks.

LEAF CLAIMS
============
{leaf_listing}

OUTPUT FORMAT
==============
A JSON object mapping each leaf index (as a string) to its equivalence
group representative index. If a leaf is its own representative (not
equivalent to any other), it maps to itself.

Example:
{{
  "0": "0",      // leaf 0 is its own representative
  "1": "0",      // leaf 1 is equivalent to leaf 0
  "2": "2",      // leaf 2 stands alone
  "3": "0",      // leaf 3 is also equivalent to leaf 0
  "4": "4"       // leaf 4 stands alone
}}

Output ONLY the JSON object.
"""


def collect_leaves(spec: NodeSpec, leaves: Optional[list] = None) -> list:
    """Collect all LeafSpec nodes in a NodeSpec tree.

    ComparisonSpec nodes are NOT traversed — they're terminal at this stage
    (their numeric sub-structure will be expanded by Piece 2). The atoms
    they reference are typed-numeric, not Boolean, and won't be deduplicated
    against Boolean leaves anyway.
    """
    if leaves is None:
        leaves = []
    if isinstance(spec, LeafSpec):
        leaves.append(spec)
    elif isinstance(spec, OperatorSpec):
        for child in spec.children:
            collect_leaves(child, leaves)
    # ComparisonSpec: terminal — do not recurse
    return leaves


def deduplicate_leaves(specs: dict[str, NodeSpec], llm: LLMCaller,
                       abbreviation: str) -> dict[str, str]:
    """
    Identify equivalence groups across all leaves in all determination specs.
    Returns a mapping from leaf-index → representative-leaf-index.
    Assigns atom_id to each LeafSpec based on its representative.
    """
    # Collect every leaf from every determination
    all_leaves = []
    for det_id, spec in specs.items():
        for leaf in collect_leaves(spec):
            all_leaves.append((det_id, leaf))

    if not all_leaves:
        return {}

    leaf_listing = "\n".join(
        f"  {i}: ({det_id}) {leaf.claim}"
        for i, (det_id, leaf) in enumerate(all_leaves)
    )

    prompt = DEDUP_PROMPT.format(leaf_listing=leaf_listing)
    raw = llm.call("dedup", prompt)
    mapping = _parse_json_response(raw)
    # Keys may be strings from JSON; canonicalize
    mapping = {int(k): int(v) for k, v in mapping.items()}

    # Assign atom IDs: each equivalence group gets one ID based on its representative
    rep_to_atom_id = {}
    counter = 0
    for i in range(len(all_leaves)):
        rep = mapping.get(i, i)
        if rep not in rep_to_atom_id:
            counter += 1
            rep_to_atom_id[rep] = f"{abbreviation}.a{counter:03d}"

    # Annotate each leaf with its assigned atom_id
    for i, (det_id, leaf) in enumerate(all_leaves):
        rep = mapping.get(i, i)
        leaf.atom_id = rep_to_atom_id[rep]

    return mapping


# ---------------------------------------------------------------------------
# Piece 6 — typed atom deduplication
# ---------------------------------------------------------------------------
#
# When Build runs across multiple determinations, numeric atoms appearing in
# multiple comparisons need to be unified — otherwise the engine sees N copies
# of "team_salary" instead of one, and Map has to extract the same fact N
# times per case. The Boolean dedup pass (deduplicate_leaves) handles this
# for LeafSpec atoms; this section is the typed analog.
#
# Two architectural guardrails:
#   1. Type discipline. A Boolean atom (Kleene-valued) is never the same atom
#      as a numeric atom (Decimal-valued). The two dedup passes are scoped
#      separately by atom_type.
#   2. Computation-kind discipline within numeric. A NumericLeafSpec (Map's
#      standard extraction) is never the same atom as a DerivedAtomSpec
#      (Map computes via aggregate / max / etc.). Within derived atoms,
#      different computation_kinds are also kept separate.
#
# The dedup key is the spec's `statement` field — the natural-language
# description of what Map extracts/computes. This is more stable across LLM
# runs than `atom_id_hint`, which Opus may name differently on different
# invocations.


NUMERIC_DEDUP_PROMPT = """You are reviewing numeric atoms extracted by the
typed Build pipeline. Each atom represents a numeric quantity (a dollar
amount, a count, a measurement) that Map will extract from case data.

Some atoms may refer to the same underlying quantity even if worded slightly
differently. Your task is to identify equivalence groups. For each group,
choose one representative atom. The other atoms in the group will be unified
with the representative.

CRITERIA FOR EQUIVALENCE
=========================
Two numeric atoms are equivalent if and only if:
- They refer to the same quantity (same evidence, same definition).
- They would always produce the same numeric value for the same case.
- Differences in wording are surface paraphrases of the same concept.

Two atoms are NOT equivalent if:
- They reference different quantities (even if topically related).
  E.g., "team salary" vs "player salary" — different aggregations.
  E.g., "contract first-year salary" vs "contract total value" — different
  computations.
- They differ in a qualifier that matters for value.
  E.g., "team salary before the trade" vs "team salary after the trade".
- One is more specific than the other.
  E.g., "Player Salary" vs "Player Salary as of January 10" — different
  snapshot timing.

NUMERIC ATOMS
==============
{atom_listing}

OUTPUT FORMAT
==============
A JSON object mapping each atom index (as a string) to its equivalence group
representative index. If an atom is its own representative (not equivalent to
any other), it maps to itself.

Example:
{{
  "0": "0",
  "1": "0",
  "2": "2",
  "3": "0",
  "4": "4"
}}

Output ONLY the JSON object.
"""


def collect_numeric_specs(spec, numeric_specs=None):
    """Walk a NodeSpec tree, collecting every NumericLeafSpec and DerivedAtomSpec.

    Recurses into:
      - OperatorSpec children (and / or / not / at_least)
      - ComparisonSpec lhs_spec and rhs_spec
      - UnaryArithmeticSpec child (the nested numeric subtree)

    Does NOT collect ConstantSpec (constants are not extracted atoms — their
    values are declared in the build spec's constants registry).
    """
    if numeric_specs is None:
        numeric_specs = []

    if isinstance(spec, (NumericLeafSpec, DerivedAtomSpec)):
        numeric_specs.append(spec)
        return numeric_specs

    if isinstance(spec, OperatorSpec):
        for child in spec.children:
            collect_numeric_specs(child, numeric_specs)
        return numeric_specs

    if isinstance(spec, ComparisonSpec):
        if spec.lhs_spec is not None:
            collect_numeric_specs(spec.lhs_spec, numeric_specs)
        if spec.rhs_spec is not None:
            collect_numeric_specs(spec.rhs_spec, numeric_specs)
        return numeric_specs

    if isinstance(spec, UnaryArithmeticSpec):
        if spec.child is not None:
            collect_numeric_specs(spec.child, numeric_specs)
        return numeric_specs

    # LeafSpec, ConstantSpec: terminal, not collected
    return numeric_specs


def _atom_class_key(spec) -> str:
    """Group key for type-and-computation-kind-scoped dedup.

    NumericLeafSpec atoms compete only with other NumericLeafSpec atoms.
    DerivedAtomSpec atoms compete only with other DerivedAtomSpec atoms of
    the same computation_kind (e.g., aggregate_sum-vs-aggregate_sum, but
    never aggregate_sum-vs-max_of).
    """
    if isinstance(spec, NumericLeafSpec):
        return "numeric_leaf"
    if isinstance(spec, DerivedAtomSpec):
        return f"derived:{spec.computation_kind}"
    raise ValueError(f"Unexpected numeric spec class: {type(spec).__name__}")


def _make_canonical_id(abbreviation: str, hint: str, taken: set[str]) -> str:
    """Produce a canonical atom_id from a hint, ensuring uniqueness.

    Convention: '{abbreviation}.{hint}' — readable in traces. If the
    natural name is already taken (e.g., two distinct concepts collided
    on the same hint), append a numeric suffix.
    """
    base = f"{abbreviation}.{hint}"
    if base not in taken:
        taken.add(base)
        return base
    # Collision — disambiguate
    n = 2
    while True:
        candidate = f"{base}_{n}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        n += 1


def deduplicate_numeric_atoms(
    specs: dict[str, NodeSpec],
    llm: LLMCaller,
    abbreviation: str,
) -> dict[str, str]:
    """Identify equivalence groups across all numeric atoms in all spec trees.

    Returns a mapping from (atom_class_key, index) → representative index
    within that class. Each numeric atom (NumericLeafSpec or DerivedAtomSpec)
    has its `atom_id` field populated with a canonical, deduplicated ID.

    Scoping rules:
      - NumericLeafSpec atoms are deduped against each other only.
      - DerivedAtomSpec atoms are deduped only against derived atoms of the
        same computation_kind.
      - Boolean atoms (LeafSpec) are unaffected by this pass — deduplicate_leaves
        handles them separately.
    """
    # Group all numeric specs by their class key
    by_class: dict[str, list[tuple[str, object]]] = {}
    for det_id, spec in specs.items():
        for numeric_spec in collect_numeric_specs(spec):
            key = _atom_class_key(numeric_spec)
            by_class.setdefault(key, []).append((det_id, numeric_spec))

    if not by_class:
        return {}

    # Within each class, run a separate dedup LLM call
    taken_ids: set[str] = set()
    full_mapping: dict[str, str] = {}

    for class_key, atoms_in_class in by_class.items():
        n = len(atoms_in_class)
        if n == 0:
            continue
        if n == 1:
            # Singleton class — assign canonical id directly, no LLM call
            _, sole = atoms_in_class[0]
            sole.atom_id = _make_canonical_id(
                abbreviation, sole.atom_id_hint, taken_ids
            )
            full_mapping[f"{class_key}:0"] = f"{class_key}:0"
            continue

        # Multiple atoms in class — ask the LLM to identify equivalence groups
        atom_listing = "\n".join(
            f"  {i}: ({det_id}) hint={spec.atom_id_hint!r} | statement: {spec.statement}"
            for i, (det_id, spec) in enumerate(atoms_in_class)
        )

        prompt = NUMERIC_DEDUP_PROMPT.format(atom_listing=atom_listing)
        raw = llm.call(f"numeric_dedup_{class_key}", prompt)
        try:
            class_mapping = _parse_json_response(raw)
            class_mapping = {int(k): int(v) for k, v in class_mapping.items()}
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # If dedup fails, fall back to no-merging (each atom is its own rep)
            class_mapping = {i: i for i in range(n)}

        # Validate mapping — each value must be a valid representative
        for i in range(n):
            if i not in class_mapping:
                class_mapping[i] = i
            rep = class_mapping[i]
            if rep < 0 or rep >= n:
                class_mapping[i] = i  # invalid rep → make atom its own rep

        # Assign canonical IDs: one per representative
        rep_to_atom_id: dict[int, str] = {}
        for i in range(n):
            rep = class_mapping[i]
            if rep not in rep_to_atom_id:
                _, rep_spec = atoms_in_class[rep]
                rep_to_atom_id[rep] = _make_canonical_id(
                    abbreviation, rep_spec.atom_id_hint, taken_ids
                )

        for i, (det_id, spec) in enumerate(atoms_in_class):
            rep = class_mapping[i]
            spec.atom_id = rep_to_atom_id[rep]
            full_mapping[f"{class_key}:{i}"] = f"{class_key}:{rep}"

    return full_mapping


# ---------------------------------------------------------------------------
# Finalize: run both deduplication passes in canonical order
# ---------------------------------------------------------------------------

def finalize_spec(
    specs: dict[str, NodeSpec],
    llm: LLMCaller,
    abbreviation: str,
) -> dict[str, dict[str, str]]:
    """
    Finalize a set of decomposed spec trees by running both atom-deduplication
    passes in canonical order.

    Two passes are required because Boolean leaves and numeric atoms emerge
    from decomposition without assigned atom_ids, and Stage-4 engine-node
    conversion (spec_to_engine_node) requires every atom-bearing node to have
    a canonical atom_id.

    The two passes are:
      1. deduplicate_leaves — unifies semantically equivalent LeafSpec
         (Boolean) atoms across all spec trees in the input dict.
      2. deduplicate_numeric_atoms — unifies semantically equivalent
         NumericLeafSpec and DerivedAtomSpec atoms, with class-scoping by
         computation_kind.

    Both passes mutate the spec trees in place to assign atom_id values.

    Returns a dict containing the per-pass mappings (for logging/audit):
        {
          "boolean_dedup": {leaf_index: representative_index, ...},
          "numeric_dedup": {(class_key, idx): representative_idx, ...},
        }

    USAGE:
        # After decomposing every determination:
        finalize_spec(decomposition_specs, llm, abbreviation="nba")
        # Now the specs are ready for spec_to_engine_node.

    Notes:
        - Empty input (no specs, or specs with no atoms) is handled
          gracefully: the corresponding pass simply returns an empty
          mapping and makes no LLM calls.
        - Singleton classes (one atom in a class) skip the LLM call;
          the atom is still assigned a canonical ID derived from its
          atom_id_hint.
        - This function is the canonical entry point for finalizing
          decomposition before Stage-4. Direct calls to one dedup pass
          without the other will leave the spec tree in a state that
          fails Stage-4 conversion.
    """
    audit: dict[str, dict] = {}

    # Pass 1: Boolean leaves
    boolean_mapping = deduplicate_leaves(specs, llm, abbreviation)
    audit["boolean_dedup"] = boolean_mapping

    # Pass 2: numeric atoms (NumericLeafSpec and DerivedAtomSpec)
    numeric_mapping = deduplicate_numeric_atoms(specs, llm, abbreviation)
    # Convert the (class_key, idx) tuple keys to strings for JSON-friendliness
    # in the audit log; the underlying mapping is preserved.
    audit["numeric_dedup"] = {
        f"{k[0]}:{k[1]}": v for k, v in numeric_mapping.items()
    } if isinstance(next(iter(numeric_mapping), None), tuple) else numeric_mapping

    return audit


# ---------------------------------------------------------------------------
# Build engine nodes from NodeSpec
# ---------------------------------------------------------------------------

def _to_decimal_constant(value, label_for_error: str = "") -> Decimal:
    """Convert a numeric value from JSON (which may be float or int) to Decimal.

    Uses str() to avoid float-binary representation errors:
        Decimal(0.0912) → Decimal('0.0912000000000000058...') — BAD
        Decimal(str(0.0912)) → Decimal('0.0912') — GOOD

    Integers are passed through directly.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        # Strip $, commas
        cleaned = value.replace("$", "").replace(",", "").strip()
        return Decimal(cleaned)
    raise ValueError(
        f"Cannot convert {value!r} (type {type(value).__name__}) to Decimal"
        + (f" for {label_for_error!r}" if label_for_error else "")
    )


def _numeric_spec_to_engine_node(
    spec,
    atoms: dict[str, Atom],
    constants: dict[str, Decimal],
):
    """Convert a NumericSpec tree into engine numeric nodes.

    Recursive — UnaryArithmeticSpec children are themselves NumericSpecs.

    NumericLeafSpec and DerivedAtomSpec both become engine NumericLeaf nodes;
    the atom is registered with atom_type='numeric'. The difference is in how
    Map evaluates the atom:
      - NumericLeafSpec: Map's standard numeric extraction from case text
      - DerivedAtomSpec: Map applies the computation_kind (aggregate, max_of,
        etc.) when binding the atom

    ConstantSpec(value=...) becomes Constant(value=Decimal(value)).
    ConstantSpec(label=...) requires the label to be present in `constants`;
    becomes Constant(value=constants[label], label=label).
    """
    # NumericLeafSpec — case-data attribute
    if isinstance(spec, NumericLeafSpec):
        atom_id = spec.atom_id or spec.atom_id_hint
        if atom_id not in atoms:
            atoms[atom_id] = Atom(
                id=atom_id,
                statement=spec.statement,
                source_span=spec.source_span,
                atom_type="numeric",
            )
        return NumericLeaf(atom_id=atom_id)

    # DerivedAtomSpec — Map-computed numeric atom (aggregate / max_of / etc.)
    if isinstance(spec, DerivedAtomSpec):
        atom_id = spec.atom_id or spec.atom_id_hint
        if atom_id not in atoms:
            # Carry the computation_kind in the atom's notes for Map to read.
            atoms[atom_id] = Atom(
                id=atom_id,
                statement=spec.statement,
                source_span=spec.source_span,
                atom_type="numeric",
                notes=f"computation_kind={spec.computation_kind}",
            )
        return NumericLeaf(atom_id=atom_id)

    # ConstantSpec — literal or named policy constant
    if isinstance(spec, ConstantSpec):
        if spec.value is not None:
            return Constant(
                value=_to_decimal_constant(spec.value),
                label="",
            )
        if spec.label is not None:
            if spec.label not in constants:
                raise ValueError(
                    f"ConstantSpec references named constant {spec.label!r}, "
                    f"but no value was provided in the constants registry. "
                    f"Add an entry to the build's constants dict. "
                    f"Known constants: {sorted(constants.keys())}"
                )
            return Constant(
                value=constants[spec.label],
                label=spec.label,
            )
        raise ValueError("ConstantSpec has neither value nor label set")

    # UnaryArithmeticSpec — recursive arithmetic
    if isinstance(spec, UnaryArithmeticSpec):
        # Resolve the constant (literal or named)
        if spec.constant is not None:
            const_value = _to_decimal_constant(spec.constant)
        elif spec.constant_label is not None:
            if spec.constant_label not in constants:
                raise ValueError(
                    f"UnaryArithmeticSpec({spec.operator}) references constant "
                    f"label {spec.constant_label!r}, but no value provided. "
                    f"Known constants: {sorted(constants.keys())}"
                )
            const_value = constants[spec.constant_label]
        else:
            raise ValueError(
                f"UnaryArithmeticSpec({spec.operator}) has neither constant "
                f"nor constant_label set"
            )

        child_node = _numeric_spec_to_engine_node(spec.child, atoms, constants)
        op = spec.operator

        if op == "times_const":
            return TimesConstNode(
                child=child_node, constant=const_value,
                surface_label=spec.surface_label, source_span=spec.source_span,
            )
        if op == "plus_const":
            return PlusConstNode(
                child=child_node, constant=const_value,
                surface_label=spec.surface_label, source_span=spec.source_span,
            )
        if op == "minus_const":
            return MinusConstNode(
                child=child_node, constant=const_value,
                surface_label=spec.surface_label, source_span=spec.source_span,
            )
        if op == "const_minus":
            return ConstMinusNode(
                constant=const_value, child=child_node,
                surface_label=spec.surface_label, source_span=spec.source_span,
            )
        if op == "div_by_const":
            return DivByConstNode(
                child=child_node, constant=const_value,
                surface_label=spec.surface_label, source_span=spec.source_span,
            )
        if op == "const_div_by":
            return ConstDivByNode(
                constant=const_value, child=child_node,
                surface_label=spec.surface_label, source_span=spec.source_span,
            )
        raise ValueError(f"Unknown unary_arithmetic operator: {op!r}")

    raise ValueError(
        f"Unknown numeric spec class: {type(spec).__name__}"
    )


def spec_to_engine_node(
    spec: NodeSpec,
    atoms: dict[str, Atom],
    constants: Optional[dict[str, Decimal]] = None,
):
    """Convert a NodeSpec tree into engine nodes (AndNode, OrNode, comparison
    nodes, arithmetic nodes, etc.).

    Assumes deduplicate_leaves has been called so every LeafSpec has an
    atom_id. NumericLeafSpec / DerivedAtomSpec atoms are auto-registered
    from their atom_id_hint (proper typed-atom dedup is Piece 6 work).

    The `constants` registry maps named-constant labels (e.g. 'salary_cap')
    to Decimal values. Required when the spec tree contains ConstantSpec or
    UnaryArithmeticSpec references to named constants. For Boolean-only
    policies (PA, FCBA), no constants are referenced and the registry can be
    None or empty.
    """
    if constants is None:
        constants = {}

    if isinstance(spec, LeafSpec):
        if spec.atom_id is None:
            raise ValueError(f"Leaf has no atom_id (run deduplicate_leaves first): {spec.claim}")
        # Ensure the atom is registered
        if spec.atom_id not in atoms:
            atoms[spec.atom_id] = Atom(
                id=spec.atom_id,
                statement=spec.claim,
                source_span=spec.source_span,
            )
        return Leaf(atom_id=spec.atom_id)

    if isinstance(spec, ComparisonSpec):
        # Stage-4 typed-engine conversion (Piece 5).
        # Build LHS and RHS numeric subtrees, then wrap in the appropriate
        # comparison node. The result is a Kleene-Boolean node that composes
        # with AndNode/OrNode/NotNode in the surrounding Boolean tree.
        if spec.lhs_spec is None or spec.rhs_spec is None:
            raise ValueError(
                f"ComparisonSpec is not fully expanded (lhs_spec or rhs_spec "
                f"is None). Sub-decomposer (Piece 2) must run before "
                f"spec_to_engine_node. Operator: {spec.operator!r}, "
                f"surface: {spec.surface_label!r}"
            )
        left = _numeric_spec_to_engine_node(spec.lhs_spec, atoms, constants)
        right = _numeric_spec_to_engine_node(spec.rhs_spec, atoms, constants)
        op = spec.operator.lower()
        common_kwargs = dict(
            left=left, right=right,
            surface_label=spec.surface_label,
            source_span=spec.source_span,
        )
        if op == "leq":
            return LeqNode(**common_kwargs)
        if op == "lt":
            return LtNode(**common_kwargs)
        if op == "geq":
            return GeqNode(**common_kwargs)
        if op == "gt":
            return GtNode(**common_kwargs)
        if op == "eq":
            return EqNode(**common_kwargs)
        raise ValueError(
            f"Unknown comparison operator: {spec.operator!r}. "
            f"Expected one of: leq, lt, geq, gt, eq."
        )

    if isinstance(spec, OperatorSpec):
        children = [spec_to_engine_node(c, atoms, constants) for c in spec.children]
        prov = Provenance(spec.provenance)
        # Normalize operator name: lowercase, replace hyphens with underscores
        op_normalized = (spec.operator or "").strip().lower().replace("-", "_")
        if op_normalized == "and":
            return AndNode(
                children=children, surface_label=spec.surface_label,
                provenance=prov, source_span=spec.source_span,
                confidence=spec.confidence, latent_type=spec.latent_type,
            )
        if op_normalized == "or":
            return OrNode(
                children=children, surface_label=spec.surface_label,
                provenance=prov, source_span=spec.source_span,
                confidence=spec.confidence, latent_type=spec.latent_type,
            )
        if op_normalized == "not":
            return NotNode(
                child=children[0], provenance=prov, source_span=spec.source_span,
                confidence=spec.confidence, latent_type=spec.latent_type,
            )
        if op_normalized in ("at_least", "atleast", "at_least_n", "cardinality"):
            if spec.n is None:
                raise ValueError(
                    f"at_least operator missing 'n' parameter. "
                    f"Surface label: {spec.surface_label!r}, "
                    f"children count: {len(children)}"
                )
            return AtLeastNode(
                n=spec.n, children=children, surface_label=spec.surface_label,
                provenance=prov, source_span=spec.source_span,
                confidence=spec.confidence, latent_type=spec.latent_type,
            )
        raise ValueError(
            f"Unknown operator name {spec.operator!r} (normalized to {op_normalized!r}). "
            f"Surface label: {spec.surface_label!r}, children: {len(spec.children)}. "
            f"Expected one of: and, or, not, at_least."
        )
    raise ValueError(f"Unknown spec node class: {type(spec).__name__}")


# ---------------------------------------------------------------------------
# End-to-end builder
# ---------------------------------------------------------------------------

@dataclass
class DAGBuildResult:
    spec: BuildSpec
    atoms: dict[str, Atom]
    determinations: dict[str, Determination]
    audit: dict[str, list]
    decomposition_specs: dict[str, NodeSpec]
    refinement_results: dict = field(default_factory=dict)  # det_id -> RefinementResult


def build_from_spec(spec: BuildSpec,
                    voice: Optional[ReaderVoice] = None,
                    llm: Optional[LLMCaller] = None,
                    refine: bool = True,
                    constants: Optional[dict[str, Decimal]] = None,
                    state_dir: Optional[str] = None) -> DAGBuildResult:
    """End-to-end DAG build from institutional spec + policy text.

    `voice` and `constants` may be supplied either:
      (a) inline in `spec` (the library-native path — institution declares
          everything in one YAML)
      (b) passed as arguments (legacy path — call site supplies them)

    Explicit arguments take precedence over the spec when both are present.
    This lets test code override spec values without rewriting the spec.

    `llm` defaults to a fresh LLMCaller() if not provided.

    If `state_dir` is provided, decompose results are streamed to disk
    after each determination completes. On re-entry with the same
    state_dir, previously-decomposed determinations are loaded from
    disk and skipped, allowing resume after a crash. Only the decompose
    stage is persisted (the expensive part). Finalize and Stage-4 run
    fresh on each invocation; they are fast enough to not need
    persistence.
    """
    # Lazy import to avoid circular dep
    if refine:
        from rulekit.build.refinement import refine_tree

    # Resolve voice: explicit arg > spec.voice
    resolved_voice = voice or spec.voice
    if resolved_voice is None:
        raise ValueError(
            f"build_from_spec needs a ReaderVoice — either passed as `voice` "
            f"or set on spec.voice. Policy: {spec.policy_name!r}, "
            f"voice_key on spec: {spec.voice_key!r}. If voice_key is set, "
            f"resolve it to a ReaderVoice via the voices registry before "
            f"calling build_from_spec."
        )

    # Resolve constants: explicit arg > spec.constants
    resolved_constants = constants if constants is not None else spec.constants

    # Default LLM caller
    if llm is None:
        llm = LLMCaller()

    with open(spec.policy_source, encoding="utf-8") as f:
        policy_text = f.read()

    # Decompose each determination
    # If state_dir is provided, persist each result as soon as it's
    # produced and skip determinations already saved on disk.
    decomposition_specs = {}
    audit = {}
    if state_dir is not None:
        import os
        import pickle
        os.makedirs(state_dir, exist_ok=True)

    for det_decl in spec.determinations:
        if det_decl.composition == "complement":
            # Defer — handled after the source determination is built
            continue

        # Resume path: if a saved spec for this determination exists,
        # load and skip the decompose call entirely.
        if state_dir is not None:
            state_path = os.path.join(state_dir, f"decompose_{det_decl.id}.pkl")
            if os.path.exists(state_path):
                with open(state_path, "rb") as f:
                    saved = pickle.load(f)
                decomposition_specs[det_decl.id] = saved["spec"]
                audit[det_decl.id] = saved["audit"]
                continue

        state = DecomposeState(
            llm=llm,
            policy_text=policy_text,
            voice=resolved_voice,
            determination=det_decl,
        )
        root_spec = decompose_claim(
            claim=det_decl.description,
            path=[],
            depth=0,
            state=state,
        )
        decomposition_specs[det_decl.id] = root_spec
        audit[det_decl.id] = state.audit

        # Stream this determination's result to disk before continuing
        # to the next. A crash during the next determination's decompose
        # leaves this one recoverable.
        if state_dir is not None:
            state_path = os.path.join(state_dir, f"decompose_{det_decl.id}.pkl")
            with open(state_path, "wb") as f:
                pickle.dump({"spec": root_spec, "audit": state.audit}, f)

    # Finalize: run both Boolean and numeric atom deduplication.
    # Both passes are required before Stage-4 conversion can succeed
    # for spec trees containing Boolean leaves and/or numeric atoms.
    finalize_audit = finalize_spec(decomposition_specs, llm, spec.abbreviation)
    audit["finalize"] = finalize_audit

    # Refine each determination's tree to remove redundancies
    refinement_results = {}
    if refine:
        for det_id, tree in list(decomposition_specs.items()):
            ref_result = refine_tree(tree, det_id, llm)
            decomposition_specs[det_id] = ref_result.tree
            refinement_results[det_id] = ref_result
            audit[f"refine_{det_id}"] = [{
                "ops_applied": len(ref_result.operations_applied),
                "flags": len(ref_result.flags),
            }]

    # Build engine nodes — pass the resolved constants registry so
    # ConstantSpec(label=...) and UnaryArithmeticSpec(constant_label=...)
    # resolve to real values.
    atoms: dict[str, Atom] = {}
    determination_objects = {}
    for det_decl in spec.determinations:
        if det_decl.composition == "complement":
            continue
        tree = spec_to_engine_node(
            decomposition_specs[det_decl.id], atoms, resolved_constants
        )
        determination_objects[det_decl.id] = Determination(
            id=det_decl.id,
            description=det_decl.description,
            tree=tree,
            provenance=Provenance.TRANSCRIBED,
            polarity=det_decl.polarity,
            linked_to=det_decl.linked_to,
            source_span=det_decl.source_span,
        )

    # Build complement determinations
    for det_decl in spec.determinations:
        if det_decl.composition != "complement":
            continue
        if det_decl.linked_to not in determination_objects:
            raise ValueError(
                f"Complement {det_decl.id} references unbuilt {det_decl.linked_to}"
            )
        complement_tree = NotNode(
            child=determination_objects[det_decl.linked_to].tree,
            provenance=Provenance.INFERRED,
            source_span="Structural complement of linked determination",
            confidence=0.95,
            latent_type="meta-interpretation",
        )
        determination_objects[det_decl.id] = Determination(
            id=det_decl.id,
            description=det_decl.description,
            tree=complement_tree,
            provenance=Provenance.INFERRED,
            polarity=det_decl.polarity,
            linked_to=det_decl.linked_to,
            source_span=det_decl.source_span,
        )

    return DAGBuildResult(
        spec=spec,
        atoms=atoms,
        determinations=determination_objects,
        audit=audit,
        decomposition_specs=decomposition_specs,
        refinement_results=refinement_results,
    )
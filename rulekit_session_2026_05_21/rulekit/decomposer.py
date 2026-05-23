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
from typing import Optional, Union

from rulekit.engine import (
    Kleene, Leaf, AndNode, OrNode, AtLeastNode, NotNode,
    Determination, Provenance, FactBundle,
)
from rulekit.schema import Atom
from rulekit.builder import ReaderVoice


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
    """Full institutional spec for a build."""
    policy_name: str
    policy_source: str
    abbreviation: str
    voice_key: str  # "pa", "fcba", etc.
    determinations: list[DeterminationDeclaration]


def load_spec_from_yaml(path: str) -> BuildSpec:
    """Load a YAML build spec. Uses PyYAML; install via `pip install pyyaml`."""
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f)
    return BuildSpec(
        policy_name=data["policy"]["name"],
        policy_source=data["policy"]["source"],
        abbreviation=data["policy"]["abbreviation"],
        voice_key=data["policy"]["voice"],
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
    children: list[Union["LeafSpec", "OperatorSpec"]]
    n: Optional[int] = None  # for at_least only
    surface_label: str = ""
    source_span: str = ""
    provenance: str = "structural"  # transcribed / structural / inferred
    confidence: Optional[float] = None
    latent_type: Optional[str] = None


NodeSpec = Union[LeafSpec, OperatorSpec]


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
        return response.content[0].text


def _parse_json_response(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


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

    prompt = DECOMPOSE_PROMPT.format(
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
            f"Expected one of: leaf, and, or, not, at_least."
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
    """Collect all LeafSpec nodes in a NodeSpec tree."""
    if leaves is None:
        leaves = []
    if isinstance(spec, LeafSpec):
        leaves.append(spec)
    elif isinstance(spec, OperatorSpec):
        for child in spec.children:
            collect_leaves(child, leaves)
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
# Build engine nodes from NodeSpec
# ---------------------------------------------------------------------------

def spec_to_engine_node(spec: NodeSpec, atoms: dict[str, Atom]):
    """Convert a NodeSpec tree into engine nodes (AndNode, OrNode, etc.).

    Assumes deduplicate_leaves has been called so every LeafSpec has an atom_id.
    """
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

    if isinstance(spec, OperatorSpec):
        children = [spec_to_engine_node(c, atoms) for c in spec.children]
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


def build_from_spec(spec: BuildSpec, voice: ReaderVoice,
                    llm: LLMCaller, refine: bool = True) -> DAGBuildResult:
    """End-to-end DAG build from institutional spec + policy text."""
    # Lazy import to avoid circular dep
    if refine:
        from rulekit.refinement import refine_tree

    with open(spec.policy_source) as f:
        policy_text = f.read()

    # Decompose each determination
    decomposition_specs = {}
    audit = {}
    for det_decl in spec.determinations:
        if det_decl.composition == "complement":
            # Defer — handled after the source determination is built
            continue
        state = DecomposeState(
            llm=llm,
            policy_text=policy_text,
            voice=voice,
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

    # Dedup leaves across all determinations
    mapping = deduplicate_leaves(decomposition_specs, llm, spec.abbreviation)
    audit["dedup"] = [{"mapping": mapping}]

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

    # Build engine nodes
    atoms: dict[str, Atom] = {}
    determination_objects = {}
    for det_decl in spec.determinations:
        if det_decl.composition == "complement":
            continue
        tree = spec_to_engine_node(decomposition_specs[det_decl.id], atoms)
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

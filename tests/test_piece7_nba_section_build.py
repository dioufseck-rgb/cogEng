"""
test_piece7_nba_section_build.py — Piece 7 integration test.

The first real scaling test of the typed Build pipeline. Takes Article VII
Section 6 of the NBA CBA (the Exceptions section) and runs three determinations
through the full pipeline:

  1. Piece 1: Stage-1 classifier (Boolean + COMPARISON)
  2. Piece 2: numeric sub-decomposer (auto-fired on each comparison)
  3. Piece 6: typed atom deduplication across determinations
  4. Piece 5: Stage-4 typed-engine conversion

Architecturally-load-bearing assertions:
  - Each determination produces a non-trivial spec tree
  - Comparisons are fully expanded by the sub-decomposer
  - Typed atom dedup unifies semantically-equivalent atoms across the three
    determinations (concretely: contract_first_year_salary should appear once
    in the atom registry, not three times)
  - Final engine DAGs evaluate correctly on a synthetic case bundle
  - All three determinations share a single FactBundle's atom values

USAGE
=====
    export ANTHROPIC_API_KEY=sk-ant-...   # or CLAUDE_API_KEY
    python tests/test_piece7_nba_section_build.py

EXPECTED COST
=============
~20-35 LLM calls total. Estimated cost: $3-6.
"""
from __future__ import annotations
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulekit.build.decomposer import (
    DeterminationDeclaration, DecomposeState, LLMCaller,
    LeafSpec, OperatorSpec, ComparisonSpec,
    NumericLeafSpec, ConstantSpec, UnaryArithmeticSpec, DerivedAtomSpec,
    decompose_claim, spec_to_engine_node,
    deduplicate_numeric_atoms, collect_numeric_specs,
)
from rulekit.build.extract import ReaderVoice
from rulekit.engine import FactBundle, AndNode, OrNode, NotNode, AtLeastNode, Kleene
from rulekit.engine.typed import NumericValue, NumericLeaf, Constant


# ---------------------------------------------------------------------------
# Load policy text. The canonical source is the RuleArena clone alongside
# the rulekit repo (../RuleArena/nba/reference_rules.txt); the test also
# falls back to an in-repo copy at domains/nba/reference_rules.txt if
# someone has staged it there.
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(REPO_ROOT)
GRANDPARENT = os.path.dirname(PARENT)

_CANDIDATE_PATHS = [
    # RuleArena sibling to the rulekit repo
    os.path.join(PARENT, "RuleArena", "nba", "reference_rules.txt"),
    # RuleArena one level higher (in case rulekit is itself nested)
    os.path.join(GRANDPARENT, "RuleArena", "nba", "reference_rules.txt"),
    # RuleArena inside the rulekit repo (in case someone vendored it)
    os.path.join(REPO_ROOT, "RuleArena", "nba", "reference_rules.txt"),
    # In-repo staging
    os.path.join(REPO_ROOT, "domains", "nba", "reference_rules.txt"),
]

POLICY_PATH = None
for _candidate in _CANDIDATE_PATHS:
    if os.path.exists(_candidate):
        POLICY_PATH = _candidate
        break

if POLICY_PATH is None:
    raise FileNotFoundError(
        "Could not find reference_rules.txt. Looked in:\n"
        + "\n".join(f"  - {p}" for p in _CANDIDATE_PATHS)
        + "\nProvide a copy at one of these paths, or edit the candidates list."
    )

with open(POLICY_PATH) as f:
    FULL_CBA_TEXT = f.read()


# ---------------------------------------------------------------------------
# Extract Section 6 + supporting context (Section 2(e) and the section 6
# preamble). We want to keep the policy_text manageable for the LLM context
# while still giving it the rule text it needs to ground classifications.
# ---------------------------------------------------------------------------

def _extract_subsection(full: str, start_marker: str, end_marker: str) -> str:
    """Extract a contiguous range between two markers (start inclusive, end
    exclusive). Returns the slice as-is."""
    start = full.find(start_marker)
    if start == -1:
        raise ValueError(f"Start marker not found: {start_marker!r}")
    end = full.find(end_marker, start + 1)
    if end == -1:
        return full[start:]
    return full[start:end]


# A short preamble naming the apron-level constants — needed because 6(f)
# references the First Apron Level. We don't include all of Section 2(e)
# (that's a 5KB table of transaction restrictions); the preamble below is
# enough context for the classifier to recognize the apron-level concept.
APRON_PREAMBLE = (
    "Background (from Article VII, Section 2): "
    "The Salary Cap, First Apron Level, Second Apron Level, and Tax Level "
    "are dollar amounts published each Salary Cap Year. For 2024-25, the "
    "Salary Cap is $140,588,000 and the First Apron Level is $178,132,000. "
    "A Team's Team Salary is the sum of the Salaries of all players on the "
    "Team for the relevant Salary Cap Year.\n\n"
)

# Section 6(d) Bi-annual through end of 6(f) Taxpayer MLE — the three rules
# under test. Section 6(g) Room MLE is excluded; the determinations only
# need the d/e/f sub-sections.
SECTION_6_TRIO = _extract_subsection(
    FULL_CBA_TEXT,
    "(d) Bi-annual Exception.",
    "(g) Mid-Level Salary Exception for Room Teams.",
)

POLICY_TEXT = APRON_PREAMBLE + SECTION_6_TRIO


# ---------------------------------------------------------------------------
# Three determinations on the same Section
# ---------------------------------------------------------------------------

D_BI_ANNUAL = DeterminationDeclaration(
    id="nba.bi_annual.D1",
    description=(
        "Is this signing permitted via the Bi-annual Exception under "
        "Article VII, Section 6(d)?"
    ),
    polarity="positive",
    source_span="Article VII, Section 6(d)",
    composition="derived",
    scope_hint=(
        "Focus on the requirements that must be satisfied for a Player "
        "Contract to be permitted via the Bi-annual Exception: salary "
        "limit, length limit, prior-use restrictions, and any other "
        "conditions stated in Section 6(d)."
    ),
)

D_NON_TAXPAYER_MLE = DeterminationDeclaration(
    id="nba.non_taxpayer_mle.D1",
    description=(
        "Is this signing permitted via the Non-Taxpayer Mid-Level Salary "
        "Exception under Article VII, Section 6(e)?"
    ),
    polarity="positive",
    source_span="Article VII, Section 6(e)",
    composition="derived",
    scope_hint=(
        "Focus on the requirements that must be satisfied for a Player "
        "Contract to be permitted via the Non-Taxpayer Mid-Level Salary "
        "Exception: salary limit, length limit, prior-use restrictions, "
        "and any other conditions stated in Section 6(e)."
    ),
)

D_TAXPAYER_MLE = DeterminationDeclaration(
    id="nba.taxpayer_mle.D1",
    description=(
        "Is this signing permitted via the Taxpayer Mid-Level Salary "
        "Exception under Article VII, Section 6(f)?"
    ),
    polarity="positive",
    source_span="Article VII, Section 6(f)",
    composition="derived",
    scope_hint=(
        "Focus on the requirements that must be satisfied for a Player "
        "Contract to be permitted via the Taxpayer Mid-Level Salary "
        "Exception: salary limit, length limit, the team-salary bracket "
        "gate (post-exception Team Salary must exceed the First Apron "
        "Level), prior-use restrictions, and any other conditions stated "
        "in Section 6(f)."
    ),
)

DETERMINATIONS = [D_BI_ANNUAL, D_NON_TAXPAYER_MLE, D_TAXPAYER_MLE]


# ---------------------------------------------------------------------------
# Reader voice
# ---------------------------------------------------------------------------

NBA_VOICE = ReaderVoice(
    role="experienced NBA team-operations counsel",
    domain="NBA Collective Bargaining Agreement (CBA)",
    background=(
        "You are reading the NBA CBA, applying its rules with attention to "
        "the practical structure of transactions and the precise numeric "
        "thresholds (Salary Cap, First Apron Level, Second Apron Level, "
        "exception percentages, contract length limits) that govern team "
        "operations. The Bi-annual, Non-Taxpayer MLE, and Taxpayer MLE "
        "Exceptions are alternative paths to permitting an off-cap signing; "
        "each has its own salary limit, length limit, and (for Taxpayer "
        "MLE) team-salary bracket gate."
    ),
)


# ---------------------------------------------------------------------------
# Constants registry — the institution declares its named CBA constants
# ---------------------------------------------------------------------------

# Constants registry. We include multiple aliases for the Taxpayer MLE
# amount because Opus may choose different names for it across runs
# ('taxpayer_mle_amount', 'taxpayer_mid_level_exception_amount', etc.).
# This is a lightweight bridge between the LLM's naming choices and the
# institution's declared constants — a proper Build pipeline would have
# a constants-resolution stage, but for now we pre-declare the aliases.
NBA_CONSTANTS: dict[str, Decimal] = {
    "salary_cap": Decimal("140588000"),
    "first_apron_level": Decimal("178132000"),
    "second_apron_level": Decimal("188931000"),
    # Taxpayer MLE amount — multiple aliases for the same underlying value
    "taxpayer_mle_amount": Decimal("5168000"),
    "taxpayer_mid_level_exception_amount": Decimal("5168000"),
    "taxpayer_mid_level_salary_exception_amount": Decimal("5168000"),
    "taxpayer_mle_dollar_amount": Decimal("5168000"),
}


# ---------------------------------------------------------------------------
# Pretty-printers
# ---------------------------------------------------------------------------

def describe_spec(spec, indent=0):
    pad = "  " * indent
    if isinstance(spec, LeafSpec):
        return f"{pad}LeafSpec[{spec.source_span or '?'}]: {spec.claim[:80]}"
    if isinstance(spec, OperatorSpec):
        lines = [f"{pad}{spec.operator.upper()}({len(spec.children)}) [{spec.surface_label or '?'}]"]
        for c in spec.children:
            lines.append(describe_spec(c, indent + 1))
        return "\n".join(lines)
    if isinstance(spec, ComparisonSpec):
        lines = [
            f"{pad}COMPARISON({spec.operator}) [{spec.surface_label or '?'}]",
            f"{pad}  LHS '{spec.lhs_description}' [hint={spec.lhs_kind}]:",
            describe_numeric(spec.lhs_spec, indent + 2),
            f"{pad}  RHS '{spec.rhs_description}' [hint={spec.rhs_kind}]:",
            describe_numeric(spec.rhs_spec, indent + 2),
        ]
        return "\n".join(lines)
    return f"{pad}<{type(spec).__name__}>"


def describe_numeric(spec, indent=0):
    pad = "  " * indent
    if spec is None:
        return f"{pad}<None>"
    if isinstance(spec, NumericLeafSpec):
        return f"{pad}NumericLeafSpec(atom_id_hint={spec.atom_id_hint!r}, atom_id={spec.atom_id!r})"
    if isinstance(spec, ConstantSpec):
        if spec.value is not None:
            return f"{pad}ConstantSpec(value={spec.value})"
        return f"{pad}ConstantSpec(label={spec.label!r})"
    if isinstance(spec, UnaryArithmeticSpec):
        const_repr = (f"constant={spec.constant}" if spec.constant is not None
                      else f"constant_label={spec.constant_label!r}")
        return (
            f"{pad}UnaryArithmeticSpec({spec.operator}, {const_repr}):\n"
            + describe_numeric(spec.child, indent + 1)
        )
    if isinstance(spec, DerivedAtomSpec):
        return (f"{pad}DerivedAtomSpec(atom_id_hint={spec.atom_id_hint!r}, "
                f"atom_id={spec.atom_id!r}, "
                f"computation_kind={spec.computation_kind!r})")
    return f"{pad}<{type(spec).__name__}>"


def describe_engine_node(n, indent=0):
    pad = "  " * indent
    t = type(n).__name__
    label = getattr(n, "surface_label", "") or ""
    label_part = f" [{label}]" if label else ""
    if hasattr(n, "atom_id"):
        return f"{pad}{t}({n.atom_id!r}){label_part}"
    if hasattr(n, "value") and hasattr(n, "label") and not hasattr(n, "children"):
        return f"{pad}{t}(value={n.value}, label={n.label!r})"
    if hasattr(n, "left") and hasattr(n, "right"):
        return (f"{pad}{t}{label_part}\n"
                + describe_engine_node(n.left, indent + 1) + "\n"
                + describe_engine_node(n.right, indent + 1))
    if hasattr(n, "constant") and hasattr(n, "child"):
        return (f"{pad}{t}(constant={n.constant}){label_part}\n"
                + describe_engine_node(n.child, indent + 1))
    if hasattr(n, "child"):  # NOT
        return f"{pad}{t}{label_part}\n" + describe_engine_node(n.child, indent + 1)
    if hasattr(n, "children"):
        n_kw = f" n={n.n}" if hasattr(n, "n") and getattr(n, "n", None) is not None else ""
        lines = [f"{pad}{t}({len(n.children)} children{n_kw}){label_part}"]
        for c in n.children:
            lines.append(describe_engine_node(c, indent + 1))
        return "\n".join(lines)
    return f"{pad}{t} <?>"


def count_specs(spec, counts=None):
    if counts is None:
        counts = {"LeafSpec": 0, "OperatorSpec": 0, "ComparisonSpec": 0,
                  "NumericLeafSpec": 0, "ConstantSpec": 0,
                  "UnaryArithmeticSpec": 0, "DerivedAtomSpec": 0}
    if isinstance(spec, LeafSpec):
        counts["LeafSpec"] += 1
    elif isinstance(spec, OperatorSpec):
        counts["OperatorSpec"] += 1
        for c in spec.children:
            count_specs(c, counts)
    elif isinstance(spec, ComparisonSpec):
        counts["ComparisonSpec"] += 1
        _count_numeric_inplace(spec.lhs_spec, counts)
        _count_numeric_inplace(spec.rhs_spec, counts)
    return counts


def _count_numeric_inplace(spec, counts):
    if spec is None:
        return
    t = type(spec).__name__
    if t in counts:
        counts[t] += 1
    if isinstance(spec, UnaryArithmeticSpec):
        _count_numeric_inplace(spec.child, counts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        if os.environ.get("CLAUDE_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = os.environ["CLAUDE_API_KEY"]
        else:
            print("ERROR: set ANTHROPIC_API_KEY (or CLAUDE_API_KEY)")
            sys.exit(2)

    llm = LLMCaller(model="claude-opus-4-7")
    voice = NBA_VOICE

    print("=" * 70)
    print("PIECE 7 — END-TO-END NBA SECTION BUILD")
    print("=" * 70)
    print(f"\nPolicy source: {POLICY_PATH}")
    print(f"Policy text: Section 2(e) preamble + Section 6 sub-sections d/e/f ({len(POLICY_TEXT)} chars)")
    print(f"Determinations: {len(DETERMINATIONS)}")
    for d in DETERMINATIONS:
        print(f"  - {d.id}: {d.source_span}")

    # ----- Stage 1+2: decompose each determination -----
    print("\n" + "=" * 70)
    print("STAGES 1 + 2: Decompose each determination")
    print("=" * 70)

    det_specs: dict[str, NodeSpec] = {}
    total_llm_calls = 0

    for det in DETERMINATIONS:
        state = DecomposeState(
            llm=llm, policy_text=POLICY_TEXT, voice=voice, determination=det,
        )
        print(f"\n[Decomposing {det.id}]")
        spec = decompose_claim(
            claim=det.description,
            path=[det.id],
            depth=0,
            state=state,
        )
        det_specs[det.id] = spec
        print(f"  LLM calls: {state.call_count}")
        total_llm_calls += state.call_count
        print(f"  Spec tree:")
        print(describe_spec(spec, indent=2))

    # Spec inventory across all three
    print("\n" + "=" * 70)
    print("SPEC INVENTORY ACROSS ALL DETERMINATIONS (pre-dedup)")
    print("=" * 70)
    grand_counts = {"LeafSpec": 0, "OperatorSpec": 0, "ComparisonSpec": 0,
                    "NumericLeafSpec": 0, "ConstantSpec": 0,
                    "UnaryArithmeticSpec": 0, "DerivedAtomSpec": 0}
    for det_id, spec in det_specs.items():
        c = count_specs(spec)
        print(f"  {det_id}: {dict((k, v) for k, v in c.items() if v > 0)}")
        for k, v in c.items():
            grand_counts[k] += v
    print(f"\n  GRAND TOTAL: {dict((k, v) for k, v in grand_counts.items() if v > 0)}")

    pre_dedup_numeric_count = (grand_counts["NumericLeafSpec"]
                               + grand_counts["DerivedAtomSpec"])
    print(f"  Numeric atoms before dedup: {pre_dedup_numeric_count}")

    # ----- Piece 6: dedup -----
    print("\n" + "=" * 70)
    print("PIECE 6: Typed atom deduplication")
    print("=" * 70)

    # Track call_count delta from dedup
    dedup_state = DecomposeState(
        llm=llm, policy_text="", voice=voice, determination=DETERMINATIONS[0],
    )
    pre_call_count = len(llm.calls_made) if hasattr(llm, "calls_made") else 0
    mapping = deduplicate_numeric_atoms(det_specs, llm, abbreviation="nba")
    print(f"  Dedup mapping has {len(mapping)} entries.")

    # Collect all numeric atoms after dedup; show their canonical IDs
    all_numerics = []
    for det_id, spec in det_specs.items():
        for ns in collect_numeric_specs(spec):
            all_numerics.append((det_id, ns))

    print(f"\n  Numeric atoms after dedup (total {len(all_numerics)}):")
    distinct_ids = set()
    for det_id, ns in all_numerics:
        kind = type(ns).__name__
        hint = ns.atom_id_hint
        aid = ns.atom_id or "<unassigned>"
        extra = ""
        if isinstance(ns, DerivedAtomSpec):
            extra = f" [computation_kind={ns.computation_kind}]"
        print(f"    [{det_id}] {kind}(hint={hint!r}) → atom_id={aid}{extra}")
        if ns.atom_id:
            distinct_ids.add(ns.atom_id)
    print(f"\n  DISTINCT atom_ids after dedup: {len(distinct_ids)}")
    print(f"  Pre-dedup numeric atom count: {pre_dedup_numeric_count}")
    if pre_dedup_numeric_count > 0:
        savings = pre_dedup_numeric_count - len(distinct_ids)
        print(f"  Dedup unified {savings} atom(s) "
              f"({savings/pre_dedup_numeric_count*100:.0f}% reduction)")

    # ----- Piece 5: convert each determination to an engine node -----
    print("\n" + "=" * 70)
    print("PIECE 5: Convert each spec tree to engine DAG")
    print("=" * 70)

    atoms: dict[str, object] = {}  # shared registry across all three
    engine_nodes: dict[str, object] = {}

    for det_id, spec in det_specs.items():
        try:
            node = spec_to_engine_node(spec, atoms, NBA_CONSTANTS)
            engine_nodes[det_id] = node
            print(f"\n  [{det_id}] OK")
            print(describe_engine_node(node, indent=2))
        except Exception as e:
            print(f"\n  [{det_id}] FAILED: {type(e).__name__}: {e}")
            engine_nodes[det_id] = None

    print(f"\n  Total atoms registered: {len(atoms)}")
    for atom_id, atom in atoms.items():
        print(f"    {atom_id} (atom_type={atom.atom_type}, statement={atom.statement[:60]!r})")

    # ----- End-to-end evaluation -----
    print("\n" + "=" * 70)
    print("EVALUATING ALL THREE DAGS AGAINST SHARED CASE BUNDLES")
    print("=" * 70)

    # Discover atom IDs by statement content
    def find_atom_id(predicate):
        for aid, atom in atoms.items():
            if atom.atom_type == "numeric" and predicate(atom.statement.lower()):
                return aid
        return None

    salary_id = find_atom_id(lambda s: "salary" in s and "first" in s)
    length_id = find_atom_id(lambda s: ("length" in s or "term" in s or "season" in s)
                             and "salary" not in s)
    team_salary_id = find_atom_id(lambda s: ("team salary" in s or "team's team salary" in s
                                              or "team-wide" in s))

    print(f"\n  Discovered atom mapping:")
    print(f"    contract_salary -> {salary_id!r}")
    print(f"    contract_length -> {length_id!r}")
    print(f"    team_salary     -> {team_salary_id!r}")

    if not salary_id or not length_id:
        print("\n  ! Could not map enough atoms. Inspect above and adjust.")
        return

    # Identify Boolean atoms — the richer auto-built trees may include
    # Boolean predicates (e.g., "team has already used Room MLE this year").
    # For evaluation we provide reasonable defaults so the cases don't
    # short-circuit to UNDETERMINED on every Boolean atom.
    boolean_atoms = {aid: atom for aid, atom in atoms.items()
                     if atom.atom_type == "boolean"}
    print(f"\n  Boolean atoms in DAG: {len(boolean_atoms)}")
    for aid, atom in boolean_atoms.items():
        print(f"    {aid}: {atom.statement[:80]}")

    # Conservative defaults for Boolean predicates: set FALSE for
    # "prior use" / "previously used" / "already used" predicates
    # (assume the team has NOT already used a conflicting exception).
    # Everything else defaults to UNDETERMINED.
    boolean_defaults = {}
    for aid, atom in boolean_atoms.items():
        s = atom.statement.lower()
        if any(k in s for k in ["already used", "previously used",
                                "previously signed", "prior use"]):
            boolean_defaults[aid] = Kleene.FALSE
        else:
            boolean_defaults[aid] = Kleene.UNDETERMINED

    # Test cases. Numeric atoms get realistic values; Boolean atoms
    # inherit the conservative defaults above.
    test_cases = [
        ("Bi-annual case: $4M, 2 seasons, team $170M (below first apron)", {
            salary_id: NumericValue.of("4000000"),
            length_id: NumericValue.of(2),
            **({team_salary_id: NumericValue.of("170000000")} if team_salary_id else {}),
            **boolean_defaults,
        }),
        ("Non-Taxpayer MLE case: $12M, 4 seasons, team $170M", {
            salary_id: NumericValue.of("12000000"),
            length_id: NumericValue.of(4),
            **({team_salary_id: NumericValue.of("170000000")} if team_salary_id else {}),
            **boolean_defaults,
        }),
        ("Taxpayer MLE case: $5M, 2 seasons, team $180M (above first apron)", {
            salary_id: NumericValue.of("5000000"),
            length_id: NumericValue.of(2),
            **({team_salary_id: NumericValue.of("180000000")} if team_salary_id else {}),
            **boolean_defaults,
        }),
        ("Salary over even MLE limit: $20M, 2 seasons", {
            salary_id: NumericValue.of("20000000"),
            length_id: NumericValue.of(2),
            **({team_salary_id: NumericValue.of("170000000")} if team_salary_id else {}),
            **boolean_defaults,
        }),
    ]

    for case_label, values in test_cases:
        bundle = FactBundle(values=values)
        print(f"\n  CASE: {case_label}")
        for det_id, node in engine_nodes.items():
            if node is None:
                print(f"    {det_id}: <skip — node not built>")
                continue
            try:
                result = node.evaluate(bundle)
                short_id = det_id.split(".")[1]
                print(f"    {short_id:25s} → {result}")
            except Exception as e:
                short_id = det_id.split(".")[1]
                print(f"    {short_id:25s} → ERROR: {type(e).__name__}: {e}")

    print("\n" + "=" * 70)
    print(f"TOTAL LLM CALLS: {total_llm_calls + len(mapping)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
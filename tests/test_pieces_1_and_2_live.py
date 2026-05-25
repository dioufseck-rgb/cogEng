"""
test_pieces_1_and_2_live.py -- end-to-end integration test for the typed
Build pipeline through Piece 5: Stage-1 classifier (Piece 1) + LHS/RHS
sub-decomposer (Piece 2) + Stage-4 typed-engine conversion (Piece 5).

WHAT THIS TESTS
================
Given a short CBA snippet and a declared determination, run the full Build
recursion from policy text to runnable engine DAG. Verify that:
  - The decomposer produces a tree mixing Boolean operators and ComparisonSpec
  - Each ComparisonSpec has lhs_spec and rhs_spec populated by the
    sub-decomposer (not just free-text descriptions)
  - Stage-4 converts the fully-expanded spec tree to engine nodes
    (AndNode, LeqNode, TimesConstNode, NumericLeaf, Constant)
  - The resulting engine DAG evaluates correctly against synthetic case data

USAGE
=====
    export ANTHROPIC_API_KEY=sk-ant-...   # or set CLAUDE_API_KEY
    python tests/test_pieces_1_and_2_live.py

EXPECTED COST
=============
Roughly 5-15 LLM calls depending on tree shape. Estimated cost: $1-2.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulekit.build.decomposer import (
    BuildSpec, DeterminationDeclaration, DecomposeState, LLMCaller,
    LeafSpec, OperatorSpec, ComparisonSpec,
    NumericLeafSpec, ConstantSpec, UnaryArithmeticSpec, DerivedAtomSpec,
    decompose_claim, spec_to_engine_node,
)
from rulekit.build.extract import ReaderVoice


# ---------------------------------------------------------------------------
# Test policy text -- a small CBA snippet that we know contains numeric
# comparisons. From Article VII, Section 6(e) -- Non-Taxpayer MLE.
# ---------------------------------------------------------------------------

CBA_SNIPPET = """Article VII, Section 6(e) -- Non-Taxpayer Mid-Level Salary Exception

(1) A Team may use the Non-Taxpayer Mid-Level Salary Exception to sign one
or more Player Contracts during each Salary Cap Year that, in the aggregate,
provide for Salaries and Unlikely Bonuses in the first Salary Cap Year
totaling up to 9.12% of the Salary Cap for such Salary Cap Year.

(2) The term of a Player Contract signed pursuant to the Non-Taxpayer
Mid-Level Salary Exception may not exceed four (4) Seasons in length.
"""

# A high-level determination that should require comparisons to evaluate
DETERMINATION = DeterminationDeclaration(
    id="nba.mle.D1",
    description=(
        "A Player Contract signed via the Non-Taxpayer Mid-Level Salary "
        "Exception is permitted when (a) the contract first-year salary is "
        "at or below 9.12% of the Salary Cap, AND (b) the contract length "
        "does not exceed four Seasons."
    ),
    polarity="positive",
    source_span="Article VII, Section 6(e)",
    composition="derived",
)


NBA_VOICE = ReaderVoice(
    role="experienced NBA team-operations counsel",
    domain="NBA Collective Bargaining Agreement",
    background=(
        "You are reading the NBA CBA, applying its rules with attention to "
        "the practical structure of transactions and the precise numeric "
        "thresholds (salary cap, apron levels, exception percentages, "
        "contract length limits) that govern team operations."
    ),
)


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------

def describe_spec(spec, indent=0):
    """Recursive pretty-printer for a NodeSpec / NumericSpec tree."""
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
    return f"{pad}<unknown spec type: {type(spec).__name__}>"


def describe_numeric(spec, indent=0):
    pad = "  " * indent
    if spec is None:
        return f"{pad}<None -- not expanded>"
    if isinstance(spec, NumericLeafSpec):
        return f"{pad}NumericLeafSpec(atom_id_hint={spec.atom_id_hint!r})"
    if isinstance(spec, ConstantSpec):
        if spec.value is not None:
            return f"{pad}ConstantSpec(value={spec.value})"
        return f"{pad}ConstantSpec(label={spec.label!r})"
    if isinstance(spec, UnaryArithmeticSpec):
        const_repr = f"constant={spec.constant}" if spec.constant is not None else f"constant_label={spec.constant_label!r}"
        return (
            f"{pad}UnaryArithmeticSpec({spec.operator}, {const_repr}):\n"
            + describe_numeric(spec.child, indent + 1)
        )
    if isinstance(spec, DerivedAtomSpec):
        return f"{pad}DerivedAtomSpec(atom_id_hint={spec.atom_id_hint!r}, computation_kind={spec.computation_kind!r})"
    return f"{pad}<unknown numeric spec type: {type(spec).__name__}>"


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
        _count_numeric(spec.lhs_spec, counts)
        _count_numeric(spec.rhs_spec, counts)
    return counts


def _count_numeric(spec, counts):
    if spec is None:
        return
    t = type(spec).__name__
    if t in counts:
        counts[t] += 1
    if isinstance(spec, UnaryArithmeticSpec):
        _count_numeric(spec.child, counts)


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

    state = DecomposeState(
        llm=llm,
        policy_text=CBA_SNIPPET,
        voice=voice,
        determination=DETERMINATION,
    )

    print("=" * 70)
    print("STAGE-1 + PIECE-2 INTEGRATION TEST")
    print("=" * 70)
    print(f"\nDetermination: {DETERMINATION.id}")
    print(f"Description: {DETERMINATION.description[:120]}...")
    print(f"\nPolicy text (snippet, {len(CBA_SNIPPET)} chars):")
    print(CBA_SNIPPET)

    print("\n" + "=" * 70)
    print("Decomposing top-level determination...")
    print("=" * 70)

    spec = decompose_claim(
        claim=DETERMINATION.description,
        path=[DETERMINATION.id],
        depth=0,
        state=state,
    )

    print(f"\nTotal LLM calls made: {state.call_count}")
    print(f"\nResulting spec tree:")
    print(describe_spec(spec, indent=1))

    counts = count_specs(spec)
    print(f"\nSpec inventory:")
    for k, v in sorted(counts.items()):
        if v > 0:
            print(f"  {k}: {v}")

    # Key assertions
    print("\n" + "=" * 70)
    print("ASSERTIONS")
    print("=" * 70)
    if counts["ComparisonSpec"] == 0:
        print("  ✗ No ComparisonSpec produced. Either the determination was Boolean-only")
        print("    or the Stage-1 classifier missed the comparisons. Inspect the tree above.")
    else:
        print(f"  ✓ {counts['ComparisonSpec']} ComparisonSpec(s) produced -- the typed extension fired.")

    # Find all comparisons and verify their lhs_spec/rhs_spec are populated
    comparisons_found = []
    def _find_comparisons(s):
        if isinstance(s, ComparisonSpec):
            comparisons_found.append(s)
        elif isinstance(s, OperatorSpec):
            for c in s.children:
                _find_comparisons(c)
    _find_comparisons(spec)

    for i, c in enumerate(comparisons_found):
        if c.lhs_spec is None or c.rhs_spec is None:
            print(f"  ✗ Comparison {i} has missing lhs_spec or rhs_spec -- sub-decomposer DID NOT fire.")
        else:
            lhs_t = type(c.lhs_spec).__name__
            rhs_t = type(c.rhs_spec).__name__
            print(f"  ✓ Comparison {i}: operator={c.operator}, LHS={lhs_t}, RHS={rhs_t}")

    # Stage-4 should now succeed (Piece 5 has been implemented)
    print("\n" + "=" * 70)
    print("STAGE-4 CONVERSION (Piece 5 -- now implemented)")
    print("=" * 70)

    # Constants registry for the NBA CBA -- institution-declared values
    from decimal import Decimal
    NBA_CONSTANTS = {
        "salary_cap": Decimal("140588000"),          # 2024-25 cap
        "first_apron_level": Decimal("178132000"),
        "second_apron_level": Decimal("188931000"),
    }

    try:
        atoms = {}
        engine_node = spec_to_engine_node(spec, atoms, NBA_CONSTANTS)
        print(f"  ✓ Stage-4 conversion succeeded.")
        print(f"    Engine node type: {type(engine_node).__name__}")
        print(f"    Atoms registered: {len(atoms)}")
        for atom_id, atom in atoms.items():
            print(f"      {atom_id} (atom_type={atom.atom_type}, statement={atom.statement[:60]!r})")

        # Show the engine node structure
        print("\n    Engine DAG shape:")

        def describe_engine_node(n, indent=4):
            pad = " " * indent
            t = type(n).__name__
            label = getattr(n, "surface_label", "") or ""
            label_part = f" [{label}]" if label else ""
            if hasattr(n, "atom_id"):
                return f"{pad}{t}(atom_id={n.atom_id!r}){label_part}"
            if hasattr(n, "value") and hasattr(n, "label") and not hasattr(n, "children"):
                # Constant
                return f"{pad}{t}(value={n.value}, label={n.label!r})"
            if hasattr(n, "left") and hasattr(n, "right"):
                # Comparison
                lines = [f"{pad}{t}{label_part}"]
                lines.append(describe_engine_node(n.left, indent + 2))
                lines.append(describe_engine_node(n.right, indent + 2))
                return "\n".join(lines)
            if hasattr(n, "constant") and hasattr(n, "child"):
                # Unary arithmetic
                lines = [f"{pad}{t}(constant={n.constant}){label_part}"]
                lines.append(describe_engine_node(n.child, indent + 2))
                return "\n".join(lines)
            if hasattr(n, "children"):
                lines = [f"{pad}{t}({len(n.children)} children){label_part}"]
                for c in n.children:
                    lines.append(describe_engine_node(c, indent + 2))
                return "\n".join(lines)
            return f"{pad}{t} <?>"

        print(describe_engine_node(engine_node))

        # Now actually run it against a synthetic case bundle to prove
        # the auto-built DAG produces correct adjudication output.
        print("\n" + "=" * 70)
        print("EVALUATING THE AUTO-BUILT DAG AGAINST SYNTHETIC CASES")
        print("=" * 70)

        from rulekit.engine import FactBundle
        from rulekit.engine.typed import NumericValue

        # Identify which atom IDs the auto-build chose
        # (may differ from hand-authored conventions)
        numeric_atom_ids = [aid for aid, a in atoms.items() if a.atom_type == "numeric"]
        print(f"  Numeric atoms in DAG: {numeric_atom_ids}")

        # Find atom IDs for salary and length.
        # Order matters: salary first (most specific match), then length
        # from the REMAINING atoms (to avoid "first_year_salary" matching
        # the "year" keyword for length).
        salary_id = next(
            (a for a in numeric_atom_ids
             if "salary" in a.lower() and "length" not in a.lower()),
            None,
        )
        remaining = [a for a in numeric_atom_ids if a != salary_id]
        length_id = next(
            (a for a in remaining
             if ("length" in a.lower() or "season" in a.lower()
                 or "duration" in a.lower() or "term" in a.lower())),
            None,
        )
        print(f"  Mapped: salary_id={salary_id!r}, length_id={length_id!r}")

        if salary_id and length_id:
            # Case 1: legal MLE signing -- $5.15M salary, 3 seasons
            bundle1 = FactBundle(values={
                salary_id: NumericValue.of("5150000"),
                length_id: NumericValue.of(3),
            })
            r1 = engine_node.evaluate(bundle1)
            print(f"\n  Case 1: $5.15M salary, 3 seasons -> {r1}  "
                  f"({'LEGAL' if str(r1) == 'true' else 'NOT LEGAL'})")

            # Case 2: illegal -- salary too high
            bundle2 = FactBundle(values={
                salary_id: NumericValue.of("20000000"),
                length_id: NumericValue.of(3),
            })
            r2 = engine_node.evaluate(bundle2)
            print(f"  Case 2: $20M salary, 3 seasons   -> {r2}  "
                  f"({'LEGAL' if str(r2) == 'true' else 'NOT LEGAL'})")

            # Case 3: illegal -- length too long
            bundle3 = FactBundle(values={
                salary_id: NumericValue.of("5150000"),
                length_id: NumericValue.of(5),
            })
            r3 = engine_node.evaluate(bundle3)
            print(f"  Case 3: $5.15M salary, 5 seasons -> {r3}  "
                  f"({'LEGAL' if str(r3) == 'true' else 'NOT LEGAL'})")

            # Case 4: undetermined -- missing salary
            bundle4 = FactBundle(values={
                salary_id: NumericValue.undetermined(),
                length_id: NumericValue.of(3),
            })
            r4 = engine_node.evaluate(bundle4)
            print(f"  Case 4: ??? salary, 3 seasons    -> {r4}  "
                  f"(undetermined inputs yield undetermined disposition)")
        else:
            print(f"  ! Could not map atom IDs to test bundle inputs.")
            print(f"    salary_id={salary_id}, length_id={length_id}")

    except NotImplementedError as e:
        print(f"  ✗ Halted unexpectedly: {e}")
    except Exception as e:
        print(f"  ✗ Conversion failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"Total LLM calls for this build: {state.call_count}")
    print(f"Audit log has {len(state.audit)} entries.")
    print("=" * 70)


if __name__ == "__main__":
    main()
"""
test_finalize_spec.py — unit tests for the finalize_spec orchestration.

finalize_spec is the canonical entry point that runs both Boolean leaf
deduplication and numeric atom deduplication in sequence before Stage-4
engine-node conversion. Without it, spec trees containing Boolean leaves
fail conversion because Stage-4 requires every atom-bearing node to have
an atom_id.

Tests cover:
  - Both passes execute when both types of atoms are present
  - Boolean-only spec trees still work (numeric pass is a no-op)
  - Numeric-only spec trees still work (Boolean pass is a no-op)
  - Empty input (no specs) doesn't crash
  - After finalize_spec, spec_to_engine_node succeeds end-to-end
  - The audit dict captures both pass results

No real LLM calls. Run: python tests/test_finalize_spec.py
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulekit.build.decomposer import (
    LeafSpec, OperatorSpec, ComparisonSpec,
    NumericLeafSpec, ConstantSpec, UnaryArithmeticSpec, DerivedAtomSpec,
    finalize_spec, spec_to_engine_node,
)


# ---------------------------------------------------------------------------
# Test scaffolding (matches the pattern used in test_typed_atom_dedup.py)
# ---------------------------------------------------------------------------

_results = {"pass": 0, "fail": 0}


def section(name):
    print()
    print("=" * 70)
    print(name)
    print("=" * 70)


def check(cond, label):
    if cond:
        _results["pass"] += 1
        print(f"  PASS  {label}")
    else:
        _results["fail"] += 1
        print(f"  FAIL  {label}")


class ScriptedLLM:
    """Returns canned responses keyed on stage name substrings.
    Default: identity mapping (every atom is its own representative)."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def call(self, stage_name, prompt):
        self.calls.append(stage_name)
        for key, resp in self.responses.items():
            if key in stage_name:
                return resp
        import re
        ids = re.findall(r"^\s*(\d+):", prompt, re.MULTILINE)
        if ids:
            n = len(set(ids))
            return json.dumps({str(i): str(i) for i in range(n)})
        return json.dumps({})


# ---------------------------------------------------------------------------
# Mixed spec (Boolean + numeric)
# ---------------------------------------------------------------------------

def test_mixed_runs_both_passes():
    section("finalize_spec runs both passes on mixed spec")

    # A spec with one Boolean leaf and one numeric comparison.
    spec = OperatorSpec(
        operator="and",
        children=[
            LeafSpec(claim="The team has a valid roster"),
            ComparisonSpec(
                operator="leq",
                lhs_description="contract salary",
                rhs_description="9.12% of salary cap",
                lhs_kind="numeric_leaf", rhs_kind="arithmetic",
                lhs_spec=NumericLeafSpec(
                    atom_id_hint="contract_first_year_salary",
                    statement="contract first-year salary",
                ),
                rhs_spec=UnaryArithmeticSpec(
                    operator="times_const", constant=0.0912,
                    child=ConstantSpec(label="salary_cap"),
                ),
            ),
        ],
    )

    llm = ScriptedLLM()
    specs = {"det.test": spec}
    audit = finalize_spec(specs, llm, abbreviation="nba")

    check("boolean_dedup" in audit, "audit includes boolean_dedup")
    check("numeric_dedup" in audit, "audit includes numeric_dedup")

    # Boolean leaf got an atom_id
    boolean_leaf = spec.children[0]
    check(boolean_leaf.atom_id is not None, f"Boolean leaf has atom_id (got {boolean_leaf.atom_id!r})")
    check(boolean_leaf.atom_id.startswith("nba."), f"Boolean atom_id uses abbreviation (got {boolean_leaf.atom_id!r})")

    # Numeric leaf got an atom_id
    comparison = spec.children[1]
    numeric_leaf = comparison.lhs_spec
    check(numeric_leaf.atom_id is not None, f"Numeric leaf has atom_id (got {numeric_leaf.atom_id!r})")
    check(numeric_leaf.atom_id.startswith("nba."), f"Numeric atom_id uses abbreviation (got {numeric_leaf.atom_id!r})")


def test_mixed_stage4_succeeds_after_finalize():
    section("Stage-4 conversion succeeds after finalize_spec")

    spec = OperatorSpec(
        operator="and",
        children=[
            LeafSpec(claim="The team has a valid roster"),
            ComparisonSpec(
                operator="leq",
                lhs_description="contract salary",
                rhs_description="9.12% of salary cap",
                lhs_kind="numeric_leaf", rhs_kind="arithmetic",
                lhs_spec=NumericLeafSpec(
                    atom_id_hint="contract_first_year_salary",
                    statement="contract first-year salary",
                ),
                rhs_spec=UnaryArithmeticSpec(
                    operator="times_const", constant=0.0912,
                    child=ConstantSpec(label="salary_cap"),
                ),
            ),
        ],
    )

    llm = ScriptedLLM()
    specs = {"det.test": spec}
    finalize_spec(specs, llm, abbreviation="nba")

    # Stage-4 should now succeed
    from decimal import Decimal
    atoms = {}
    constants = {"salary_cap": Decimal("140588000")}
    try:
        node = spec_to_engine_node(specs["det.test"], atoms, constants)
        check(node is not None, "spec_to_engine_node returned a node")
        check(len(atoms) == 2, f"two atoms registered (got {len(atoms)}: {list(atoms.keys())})")
    except Exception as e:
        check(False, f"Stage-4 raised {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Boolean-only spec
# ---------------------------------------------------------------------------

def test_boolean_only_no_numeric_calls():
    section("Boolean-only spec — numeric pass is a no-op")

    spec = OperatorSpec(
        operator="and",
        children=[
            LeafSpec(claim="The team has a valid roster"),
            LeafSpec(claim="The player is eligible to sign"),
        ],
    )

    llm = ScriptedLLM()
    specs = {"det.test": spec}
    audit = finalize_spec(specs, llm, abbreviation="nba")

    # Both Boolean leaves should have atom_ids
    for leaf in spec.children:
        check(leaf.atom_id is not None, f"Boolean leaf has atom_id (got {leaf.atom_id!r})")

    # No numeric calls were necessary
    numeric_dedup_calls = [c for c in llm.calls if c.startswith("numeric_dedup")]
    check(len(numeric_dedup_calls) == 0, f"no numeric dedup LLM calls (got {len(numeric_dedup_calls)})")


def test_boolean_only_stage4_succeeds():
    section("Boolean-only spec — Stage-4 succeeds after finalize")

    spec = OperatorSpec(
        operator="and",
        children=[
            LeafSpec(claim="Player is eligible"),
            LeafSpec(claim="Team is in good standing"),
        ],
    )

    llm = ScriptedLLM()
    specs = {"det.test": spec}
    finalize_spec(specs, llm, abbreviation="nba")

    atoms = {}
    try:
        node = spec_to_engine_node(specs["det.test"], atoms)
        check(node is not None, "Stage-4 returned a node")
        check(len(atoms) == 2, f"two Boolean atoms registered (got {len(atoms)})")
    except Exception as e:
        check(False, f"Stage-4 raised {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Numeric-only spec
# ---------------------------------------------------------------------------

def test_numeric_only_no_boolean_calls():
    section("Numeric-only spec — Boolean pass is a no-op")

    spec = ComparisonSpec(
        operator="leq",
        lhs_description="contract salary",
        rhs_description="9.12% of cap",
        lhs_kind="numeric_leaf", rhs_kind="arithmetic",
        lhs_spec=NumericLeafSpec(
            atom_id_hint="contract_first_year_salary",
            statement="contract salary",
        ),
        rhs_spec=UnaryArithmeticSpec(
            operator="times_const", constant=0.0912,
            child=ConstantSpec(label="salary_cap"),
        ),
    )

    llm = ScriptedLLM()
    specs = {"det.test": spec}
    finalize_spec(specs, llm, abbreviation="nba")

    # The Boolean leaf dedup uses stage name 'dedup'; with no Boolean
    # leaves to process, the function returns early without LLM call.
    boolean_dedup_calls = [c for c in llm.calls if c == "dedup"]
    check(len(boolean_dedup_calls) == 0, f"no Boolean dedup LLM calls (got {len(boolean_dedup_calls)})")

    check(spec.lhs_spec.atom_id is not None, "numeric leaf has atom_id")


# ---------------------------------------------------------------------------
# Cross-determination dedup (the load-bearing scenario)
# ---------------------------------------------------------------------------

def test_two_determinations_share_atoms():
    section("Two determinations sharing atoms — unified after finalize")

    # Two determinations, each AND of (a Boolean predicate) and (a comparison
    # on the same atom 'contract_first_year_salary'). After finalize_spec,
    # both numeric atoms should share a single atom_id, and the Boolean
    # leaves should be deduped only if the LLM says they're equivalent
    # (the default ScriptedLLM is identity, so they stay separate).

    def make_spec(boolean_claim, hint):
        return OperatorSpec(
            operator="and",
            children=[
                LeafSpec(claim=boolean_claim),
                ComparisonSpec(
                    operator="leq",
                    lhs_description="salary",
                    rhs_description="cap",
                    lhs_kind="numeric_leaf", rhs_kind="constant",
                    lhs_spec=NumericLeafSpec(
                        atom_id_hint=hint, statement="salary"),
                    rhs_spec=ConstantSpec(value=100000000),
                ),
            ],
        )

    spec_a = make_spec("Team A is eligible",
                       "contract_first_year_salary")
    spec_b = make_spec("Team B is eligible",
                       "contract_first_year_salary")

    # Scripted LLM: numeric atoms with the same hint should dedup together.
    # The numeric dedup stage names are 'numeric_dedup_{class_key}'.
    llm = ScriptedLLM(responses={
        # Force the two numeric atoms (index 0, 1) into the same group
        "numeric_dedup": json.dumps({"0": "0", "1": "0"}),
    })
    specs = {"det.a": spec_a, "det.b": spec_b}
    finalize_spec(specs, llm, abbreviation="nba")

    a_numeric_id = spec_a.children[1].lhs_spec.atom_id
    b_numeric_id = spec_b.children[1].lhs_spec.atom_id
    check(a_numeric_id == b_numeric_id,
          f"two numeric atoms unified (a={a_numeric_id}, b={b_numeric_id})")

    # Boolean leaves: identity mapping (default), so they stay separate
    a_bool_id = spec_a.children[0].atom_id
    b_bool_id = spec_b.children[0].atom_id
    check(a_bool_id != b_bool_id,
          f"two distinct Boolean atoms kept separate "
          f"(a={a_bool_id}, b={b_bool_id})")


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

def test_empty_input_no_crash():
    section("Empty input — no crash, no LLM calls")

    llm = ScriptedLLM()
    audit = finalize_spec({}, llm, abbreviation="nba")
    check(audit is not None, "returned an audit dict")
    check(len(llm.calls) == 0, f"no LLM calls (got {len(llm.calls)})")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_mixed_runs_both_passes()
    test_mixed_stage4_succeeds_after_finalize()
    test_boolean_only_no_numeric_calls()
    test_boolean_only_stage4_succeeds()
    test_numeric_only_no_boolean_calls()
    test_two_determinations_share_atoms()
    test_empty_input_no_crash()

    print()
    print("=" * 70)
    print(f"RESULTS: {_results['pass']} passed, {_results['fail']} failed")
    print("=" * 70)
    sys.exit(0 if _results["fail"] == 0 else 1)

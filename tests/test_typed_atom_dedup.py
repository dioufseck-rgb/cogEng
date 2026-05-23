"""
test_typed_atom_dedup.py — unit tests for Piece 6 (typed atom deduplication).

Tests:
  - collect_numeric_specs walks all numeric spec types correctly
  - deduplicate_numeric_atoms handles single-class and multi-class scenarios
  - Type discipline: Boolean atoms unaffected; numeric_leaf vs derived kept separate
  - Computation_kind discipline: derived atoms grouped by computation_kind
  - Equivalence groups: equivalent atoms get the same atom_id
  - Singleton classes don't trigger LLM calls
  - Boolean LeafSpec atoms are NOT collected by the numeric pass

No LLM calls — uses a scripted LLM that returns canned equivalence mappings.

Run: python tests/test_typed_atom_dedup.py
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulekit.build.decomposer import (
    LeafSpec, OperatorSpec, ComparisonSpec,
    NumericLeafSpec, ConstantSpec, UnaryArithmeticSpec, DerivedAtomSpec,
    collect_numeric_specs, deduplicate_numeric_atoms,
    _atom_class_key, _make_canonical_id,
)


PASS_COUNT = 0
FAIL_COUNT = 0


def check(condition, message):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS  {message}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL  {message}")


def section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ---------------------------------------------------------------------------
# Scripted LLM
# ---------------------------------------------------------------------------

class ScriptedLLM:
    """Returns canned responses keyed on stage name substrings."""
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def call(self, stage_name, prompt):
        self.calls.append(stage_name)
        for key, resp in self.responses.items():
            if key in stage_name:
                return resp
        # Default: every atom is its own representative (identity mapping)
        # Count atoms in the prompt to build the mapping
        # Parse listing lines like "  0: (det) hint='...'..."
        import re
        ids = re.findall(r"^\s*(\d+):", prompt, re.MULTILINE)
        if ids:
            n = len(set(ids))
            return json.dumps({str(i): str(i) for i in range(n)})
        return json.dumps({})


# ---------------------------------------------------------------------------
# collect_numeric_specs
# ---------------------------------------------------------------------------

def test_collect_walks_comparison_lhs_rhs():
    section("collect_numeric_specs walks ComparisonSpec lhs/rhs")

    spec = ComparisonSpec(
        operator="leq",
        lhs_description="x", rhs_description="9.12% of cap",
        lhs_kind="numeric_leaf", rhs_kind="arithmetic",
        lhs_spec=NumericLeafSpec(atom_id_hint="contract_salary", statement="salary x"),
        rhs_spec=UnaryArithmeticSpec(
            operator="times_const", constant=0.0912,
            child=ConstantSpec(label="salary_cap"),
        ),
    )

    collected = collect_numeric_specs(spec)
    check(len(collected) == 1, f"collected 1 numeric atom (got {len(collected)})")
    check(collected[0].atom_id_hint == "contract_salary", "LHS atom collected")


def test_collect_walks_nested_arithmetic():
    section("collect_numeric_specs walks UnaryArithmeticSpec.child recursively")

    # Build: TIMES_CONST(0.0912, CONST_MINUS(salary_cap, prior_salary))
    deep_spec = UnaryArithmeticSpec(
        operator="times_const", constant=0.0912,
        child=UnaryArithmeticSpec(
            operator="const_minus", constant_label="salary_cap",
            child=NumericLeafSpec(atom_id_hint="prior_salary", statement="prior salary"),
        ),
    )

    collected = collect_numeric_specs(deep_spec)
    check(len(collected) == 1, "nested NumericLeafSpec collected through arithmetic")
    check(collected[0].atom_id_hint == "prior_salary", "atom_id_hint preserved")


def test_collect_walks_operator_children():
    section("collect_numeric_specs walks OperatorSpec children")

    # AND(comparison_with_numeric, leaf_boolean) — only numeric atom collected
    spec = OperatorSpec(
        operator="and",
        children=[
            ComparisonSpec(
                operator="leq", lhs_description="x", rhs_description="4",
                lhs_kind="numeric_leaf", rhs_kind="constant",
                lhs_spec=NumericLeafSpec(atom_id_hint="x_val", statement="x value"),
                rhs_spec=ConstantSpec(value=4),
            ),
            LeafSpec(claim="y is true", source_span="..."),
        ],
    )

    collected = collect_numeric_specs(spec)
    check(len(collected) == 1, "1 numeric atom collected (LeafSpec NOT counted)")
    check(collected[0].atom_id_hint == "x_val", "numeric atom inside comparison")


def test_collect_handles_derived_atom():
    section("collect_numeric_specs picks up DerivedAtomSpec")

    spec = ComparisonSpec(
        operator="leq", lhs_description="agg salary", rhs_description="3.32% cap",
        lhs_kind="arithmetic", rhs_kind="arithmetic",
        lhs_spec=DerivedAtomSpec(
            atom_id_hint="aggregated_bi_annual_salary",
            statement="Sum of bi-annual exception salaries",
            computation_kind="aggregate_sum",
        ),
        rhs_spec=UnaryArithmeticSpec(
            operator="times_const", constant=0.0332,
            child=ConstantSpec(label="salary_cap"),
        ),
    )

    collected = collect_numeric_specs(spec)
    check(len(collected) == 1, "1 derived atom collected")
    check(isinstance(collected[0], DerivedAtomSpec), "DerivedAtomSpec type preserved")
    check(collected[0].computation_kind == "aggregate_sum", "computation_kind preserved")


def test_collect_skips_constants_and_boolean_leaves():
    section("collect_numeric_specs skips ConstantSpec and LeafSpec")

    # Constants and Boolean leaves should not be collected as numeric atoms
    spec = OperatorSpec(
        operator="and",
        children=[
            LeafSpec(claim="something is true", source_span=""),
            ComparisonSpec(
                operator="leq", lhs_description="x", rhs_description="5",
                lhs_kind="numeric_leaf", rhs_kind="constant",
                lhs_spec=NumericLeafSpec(atom_id_hint="x", statement="x"),
                rhs_spec=ConstantSpec(value=5),  # not collected
            ),
        ],
    )

    collected = collect_numeric_specs(spec)
    check(len(collected) == 1, "constants and Boolean leaves correctly skipped")


# ---------------------------------------------------------------------------
# _atom_class_key
# ---------------------------------------------------------------------------

def test_atom_class_key_scoping():
    section("_atom_class_key — type and computation_kind scoping")

    leaf = NumericLeafSpec(atom_id_hint="x", statement="x")
    derived_agg = DerivedAtomSpec(
        atom_id_hint="y", statement="y",
        computation_kind="aggregate_sum",
    )
    derived_max = DerivedAtomSpec(
        atom_id_hint="z", statement="z",
        computation_kind="max_of",
    )

    check(_atom_class_key(leaf) == "numeric_leaf", "numeric_leaf class")
    check(_atom_class_key(derived_agg) == "derived:aggregate_sum",
          "derived:aggregate_sum class")
    check(_atom_class_key(derived_max) == "derived:max_of",
          "derived:max_of class")
    check(_atom_class_key(derived_agg) != _atom_class_key(derived_max),
          "different computation_kinds get different class keys")


# ---------------------------------------------------------------------------
# _make_canonical_id
# ---------------------------------------------------------------------------

def test_canonical_id_naming():
    section("_make_canonical_id naming and collision handling")

    taken: set[str] = set()
    a = _make_canonical_id("nba", "team_salary", taken)
    b = _make_canonical_id("nba", "contract_salary", taken)
    c = _make_canonical_id("nba", "team_salary", taken)  # collision

    check(a == "nba.team_salary", "first id is base form")
    check(b == "nba.contract_salary", "different hint gets different id")
    check(c == "nba.team_salary_2", "collision disambiguates with suffix")


# ---------------------------------------------------------------------------
# deduplicate_numeric_atoms
# ---------------------------------------------------------------------------

def test_dedup_singleton_no_llm_call():
    section("Singleton classes do NOT trigger LLM calls")

    spec = ComparisonSpec(
        operator="leq", lhs_description="x", rhs_description="4",
        lhs_kind="numeric_leaf", rhs_kind="constant",
        lhs_spec=NumericLeafSpec(atom_id_hint="contract_salary", statement="x"),
        rhs_spec=ConstantSpec(value=4),
    )

    llm = ScriptedLLM()
    deduplicate_numeric_atoms({"D1": spec}, llm, "nba")

    check(len(llm.calls) == 0, f"no LLM calls for singleton (got {llm.calls})")
    check(spec.lhs_spec.atom_id == "nba.contract_salary",
          f"atom_id assigned ({spec.lhs_spec.atom_id})")


def test_dedup_equivalent_atoms_merge():
    section("Equivalent numeric atoms across determinations merge")

    spec1 = ComparisonSpec(
        operator="leq", lhs_description="team salary", rhs_description="cap",
        lhs_kind="numeric_leaf", rhs_kind="constant",
        lhs_spec=NumericLeafSpec(atom_id_hint="team_salary",
                                 statement="The team's current team salary in USD."),
        rhs_spec=ConstantSpec(label="salary_cap"),
    )
    spec2 = ComparisonSpec(
        operator="gt", lhs_description="team salary", rhs_description="apron",
        lhs_kind="numeric_leaf", rhs_kind="constant",
        lhs_spec=NumericLeafSpec(atom_id_hint="current_team_salary",
                                 statement="The team's current team salary in USD."),
        rhs_spec=ConstantSpec(label="first_apron_level"),
    )

    # Scripted response: both atoms (indices 0 and 1) map to representative 0
    llm = ScriptedLLM(responses={
        "numeric_dedup_numeric_leaf": json.dumps({"0": "0", "1": "0"}),
    })
    deduplicate_numeric_atoms({"D1": spec1, "D2": spec2}, llm, "nba")

    check(spec1.lhs_spec.atom_id == spec2.lhs_spec.atom_id,
          f"both atoms unified: {spec1.lhs_spec.atom_id!r} == {spec2.lhs_spec.atom_id!r}")
    check(spec1.lhs_spec.atom_id == "nba.team_salary",
          f"unified id uses representative's hint ({spec1.lhs_spec.atom_id})")


def test_dedup_non_equivalent_atoms_separate():
    section("Non-equivalent numeric atoms get separate atom_ids")

    spec1 = ComparisonSpec(
        operator="leq", lhs_description="team salary", rhs_description="cap",
        lhs_kind="numeric_leaf", rhs_kind="constant",
        lhs_spec=NumericLeafSpec(atom_id_hint="team_salary", statement="team salary"),
        rhs_spec=ConstantSpec(label="salary_cap"),
    )
    spec2 = ComparisonSpec(
        operator="leq", lhs_description="contract length", rhs_description="4",
        lhs_kind="numeric_leaf", rhs_kind="constant",
        lhs_spec=NumericLeafSpec(atom_id_hint="contract_length_seasons",
                                 statement="contract length in seasons"),
        rhs_spec=ConstantSpec(value=4),
    )

    # Scripted: each atom is its own representative
    llm = ScriptedLLM(responses={
        "numeric_dedup_numeric_leaf": json.dumps({"0": "0", "1": "1"}),
    })
    deduplicate_numeric_atoms({"D1": spec1, "D2": spec2}, llm, "nba")

    check(spec1.lhs_spec.atom_id != spec2.lhs_spec.atom_id,
          "different concepts get different atom_ids")
    check(spec1.lhs_spec.atom_id == "nba.team_salary", "first atom id correct")
    check(spec2.lhs_spec.atom_id == "nba.contract_length_seasons",
          "second atom id correct")


def test_dedup_computation_kind_scoping():
    section("DerivedAtomSpec deduplication is scoped by computation_kind")

    # Two atoms with similar statements but different computation_kinds —
    # they must NEVER be merged because their semantics differ.
    spec1 = ComparisonSpec(
        operator="leq", lhs_description="agg salary", rhs_description="3.32% cap",
        lhs_kind="arithmetic", rhs_kind="arithmetic",
        lhs_spec=DerivedAtomSpec(
            atom_id_hint="bi_annual_total",
            statement="Sum of bi-annual exception first-year salaries.",
            computation_kind="aggregate_sum",
        ),
        rhs_spec=ConstantSpec(value=0),
    )
    spec2 = ComparisonSpec(
        operator="leq", lhs_description="max sal", rhs_description="cap",
        lhs_kind="arithmetic", rhs_kind="constant",
        lhs_spec=DerivedAtomSpec(
            atom_id_hint="bi_annual_max",
            statement="Maximum of bi-annual exception salaries.",
            computation_kind="max_of",
        ),
        rhs_spec=ConstantSpec(label="salary_cap"),
    )

    # Each atom is alone in its class — no LLM call expected
    llm = ScriptedLLM()
    deduplicate_numeric_atoms({"D1": spec1, "D2": spec2}, llm, "nba")

    check(len(llm.calls) == 0,
          "no LLM call when each computation_kind class is singleton")
    check(spec1.lhs_spec.atom_id != spec2.lhs_spec.atom_id,
          "different computation_kinds never merged even with similar statements")


def test_dedup_keeps_numeric_and_derived_separate():
    section("NumericLeafSpec and DerivedAtomSpec are scoped separately")

    spec1 = ComparisonSpec(
        operator="leq", lhs_description="x", rhs_description="y",
        lhs_kind="numeric_leaf", rhs_kind="numeric_leaf",
        lhs_spec=NumericLeafSpec(atom_id_hint="team_salary", statement="team salary"),
        rhs_spec=NumericLeafSpec(atom_id_hint="contract_salary", statement="contract salary"),
    )
    spec2 = ComparisonSpec(
        operator="leq", lhs_description="x", rhs_description="y",
        lhs_kind="arithmetic", rhs_kind="constant",
        lhs_spec=DerivedAtomSpec(
            atom_id_hint="agg_team",
            statement="aggregated team-wide salary",
            computation_kind="aggregate_sum",
        ),
        rhs_spec=ConstantSpec(value=0),
    )

    # numeric_leaf class has 2 atoms (need 1 LLM call)
    # derived:aggregate_sum class has 1 atom (no LLM call)
    llm = ScriptedLLM(responses={
        "numeric_dedup_numeric_leaf": json.dumps({"0": "0", "1": "1"}),  # no merge
    })
    deduplicate_numeric_atoms({"D1": spec1, "D2": spec2}, llm, "nba")

    check(len(llm.calls) == 1, f"one LLM call for the multi-atom class (got {len(llm.calls)})")
    check("numeric_leaf" in llm.calls[0], "call scoped to numeric_leaf class")
    # All three atoms should have distinct atom_ids
    ids = {
        spec1.lhs_spec.atom_id, spec1.rhs_spec.atom_id, spec2.lhs_spec.atom_id,
    }
    check(len(ids) == 3, f"all three atoms got distinct ids: {ids}")


def test_dedup_engine_conversion_after_dedup():
    section("Engine conversion uses dedup-assigned atom_ids")

    # Build same spec from two determinations referencing equivalent atoms.
    # After dedup, both should produce engine NumericLeaf nodes with the
    # SAME atom_id, and the Atom registry should have only one entry.
    spec1 = ComparisonSpec(
        operator="leq", lhs_description="ts", rhs_description="cap",
        lhs_kind="numeric_leaf", rhs_kind="constant",
        lhs_spec=NumericLeafSpec(atom_id_hint="team_salary",
                                 statement="The team's current team salary."),
        rhs_spec=ConstantSpec(label="salary_cap"),
    )
    spec2 = ComparisonSpec(
        operator="gt", lhs_description="ts", rhs_description="apron",
        lhs_kind="numeric_leaf", rhs_kind="constant",
        lhs_spec=NumericLeafSpec(atom_id_hint="team_total_salary",
                                 statement="The team's current team salary."),
        rhs_spec=ConstantSpec(label="first_apron_level"),
    )

    llm = ScriptedLLM(responses={
        "numeric_dedup_numeric_leaf": json.dumps({"0": "0", "1": "0"}),  # merge
    })
    deduplicate_numeric_atoms({"D1": spec1, "D2": spec2}, llm, "nba")

    # Now convert
    from decimal import Decimal
    from rulekit.build.decomposer import spec_to_engine_node
    constants = {"salary_cap": Decimal("140588000"), "first_apron_level": Decimal("178132000")}

    atoms = {}
    node1 = spec_to_engine_node(spec1, atoms, constants)
    node2 = spec_to_engine_node(spec2, atoms, constants)

    check(node1.left.atom_id == node2.left.atom_id,
          f"both engine nodes use same atom_id: {node1.left.atom_id}")
    check(len(atoms) == 1,
          f"only one atom registered after dedup (got {len(atoms)}: {list(atoms.keys())})")


def test_dedup_empty_input():
    section("Empty input — no specs, no work")

    llm = ScriptedLLM()
    result = deduplicate_numeric_atoms({}, llm, "nba")
    check(len(llm.calls) == 0, "no LLM calls for empty input")
    check(result == {}, "empty mapping returned")

    # Boolean-only spec — no numeric atoms to dedup
    bool_spec = OperatorSpec(
        operator="and",
        children=[
            LeafSpec(claim="x", source_span=""),
            LeafSpec(claim="y", source_span=""),
        ],
    )
    result2 = deduplicate_numeric_atoms({"D1": bool_spec}, llm, "nba")
    check(len(llm.calls) == 0, "no LLM calls when no numeric atoms present")
    check(result2 == {}, "empty mapping when no numeric atoms")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # collect_numeric_specs
    test_collect_walks_comparison_lhs_rhs()
    test_collect_walks_nested_arithmetic()
    test_collect_walks_operator_children()
    test_collect_handles_derived_atom()
    test_collect_skips_constants_and_boolean_leaves()

    # Helper functions
    test_atom_class_key_scoping()
    test_canonical_id_naming()

    # deduplicate_numeric_atoms
    test_dedup_singleton_no_llm_call()
    test_dedup_equivalent_atoms_merge()
    test_dedup_non_equivalent_atoms_separate()
    test_dedup_computation_kind_scoping()
    test_dedup_keeps_numeric_and_derived_separate()
    test_dedup_engine_conversion_after_dedup()
    test_dedup_empty_input()

    print()
    print("=" * 70)
    print(f"RESULTS: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print("=" * 70)

    if FAIL_COUNT > 0:
        sys.exit(1)

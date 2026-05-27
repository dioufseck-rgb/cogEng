"""
FCBA refined round-trip test — the contract's load-bearing validation.

What this proves
================
The 71-node hand-built engine DAG from bin/test_fcba_composite_refined.py
can be:

  1. dumped to a DeterminationProgram via engine_to_program (the contract
     can express its full structure),
  2. validated by validate_program (the contract considers the dump
     well-formed),
  3. serialized to JSON and re-loaded (the contract's serialization is
     lossless),
  4. converted back to engine objects via program_to_engine, and
  5. evaluated against the same pre-bound atom bundles as the original
     DAG, producing the same Kleene results on every scenario.

This is Scope 2 of the round-trip (engine-evaluation equivalence). It
does not exercise Map (no LLM calls, no narrative-to-atom binding). The
Scope-3 end-to-end test that reproduces the empirical 12/13 — full
narrative cases through Map — is a separate larger test that requires
LLM access and belongs in a session of its own.

Why Scope 2 is sufficient as a contract validation
==================================================
The converter is responsible for: structural fidelity (every engine node
type maps to a contract node type and back), value-type fidelity
(booleans stay boolean, numerics stay numeric, comparisons bridge
correctly), and sharing preservation (a node referenced twice is one
Python object, not two copies). All three are visible at the
pre-bound-bundle level. The contract being able to express FCBA refined
exactly is the question this test answers; whether Map's binding
behavior reproduces the empirical 12/13 is a separate question about
the Map substrate, not the contract.

Imports from the existing test file
===================================
We import build_fcba_composite_refined_dag, _baseline_atoms, and
build_fact_bundle from bin/test_fcba_composite_refined.py rather than
copying them. This means: when the producer updates the hand-built
fragment, this round-trip test still tests today's structure, not
yesterday's snapshot of it.

The sanity-check scenarios are also pulled from the existing file
(extracted to a local list since run_dag_sanity_checks() prints and
runs them; we want the data, not the printer).
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

# Set up the import paths the same way the bin/ test does.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "bin"))

# Import the existing hand-built DAG and its case data.
from test_fcba_composite_refined import (  # noqa: E402
    _baseline_atoms,
    build_fact_bundle,
    build_fcba_composite_refined_dag,
)

from rulekit.engine import Kleene  # noqa: E402
from rulekit.engine.boolean import Determination  # noqa: E402

from rulekit.contract import (  # noqa: E402
    DeterminationProgram,
    validate_program,
)
from rulekit.contract.convert import (  # noqa: E402
    engine_to_program,
    program_to_engine,
)


# ---------------------------------------------------------------------------
# Sanity-check scenarios pulled from the hand-built test file
# ---------------------------------------------------------------------------
# Each scenario is (label, atoms_dict, expected_kleene, description).
# The atoms_dict is in the form _baseline_atoms() returns (plain Python
# bool/int/None values). build_fact_bundle converts that to engine
# FactBundle shape.
#
# These are the exact nine scenarios from run_dag_sanity_checks() in
# bin/test_fcba_composite_refined.py. Kept here as data so the test can
# iterate over them programmatically.

def _scenarios():
    base = _baseline_atoms
    return [
        ("baseline_no_error_compliant", base(), Kleene.TRUE,
         "All sub-determinations pass for no-error case"),

        ("error_as_asserted_full_compliance",
         {**base(),
          "concluded_no_error": False, "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": True,
          "credited_related_other_charges": True,
          "sent_correction_notice": True},
         Kleene.TRUE,
         "Error-as-asserted with all three credit components: should pass"),

        ("error_as_asserted_missing_finance_charges",
         {**base(),
          "concluded_no_error": False, "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": False,
          "credited_related_other_charges": True,
          "sent_correction_notice": True},
         Kleene.FALSE,
         "Error-as-asserted but missing finance-charge credit: should fail"),

        ("different_error_full_compliance",
         {**base(),
          "concluded_no_error": False, "concluded_different_error": True,
          "sent_written_explanation": True,
          "corrected_the_different_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": True,
          "credited_related_other_charges": True},
         Kleene.TRUE,
         "Different-error with correction and full credit: should pass"),

        ("different_error_missing_finance_charges",
         {**base(),
          "concluded_no_error": False, "concluded_different_error": True,
          "sent_written_explanation": True,
          "corrected_the_different_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": False,
          "credited_related_other_charges": True},
         Kleene.FALSE,
         "Different-error but missing finance-charge credit: should fail"),

        ("acknowledgment_waiver_valid",
         {**base(),
          "days_from_notice_to_acknowledgment": None,
          "days_from_notice_to_resolution": 25,
          "resolution_date_days_since_notice": 25,
          "second_complete_billing_cycle_days_since_notice": 32,
          "concluded_no_error": False, "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": True,
          "credited_related_other_charges": True,
          "sent_correction_notice": True},
         Kleene.TRUE,
         "No separate ack but full error-as-asserted procedure complete "
         "by day 25 (within 30): waiver applies, should pass"),

        ("acknowledgment_waiver_invalid_procedure_incomplete",
         {**base(),
          "days_from_notice_to_acknowledgment": None,
          "days_from_notice_to_resolution": 25,
          "resolution_date_days_since_notice": 25,
          "second_complete_billing_cycle_days_since_notice": 32,
          "concluded_no_error": False, "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": False,
          "credited_related_other_charges": True,
          "sent_correction_notice": True},
         Kleene.FALSE,
         "No ack, resolution by day 25, but procedure incomplete (no "
         "finance charges): waiver does NOT apply"),

        ("two_billing_cycle_deadline_binding",
         {**base(),
          "days_from_notice_to_resolution": 60,
          "resolution_date_days_since_notice": 60,
          "second_complete_billing_cycle_days_since_notice": 51},
         Kleene.FALSE,
         "Resolution at day 60 but second billing cycle closes at day "
         "51: two-cycle deadline is binding, fails even though within 90"),

        ("collection_of_finance_charges_only",
         {**base(),
          "did_attempt_to_collect_principal": False,
          "did_attempt_to_collect_related_finance_charges": True,
          "did_attempt_to_collect_related_other_charges": False},
         Kleene.FALSE,
         "Collection of finance charges on disputed amount: "
         "§1026.13(d)(1) violation"),
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_engine_nodes(root) -> int:
    """Walk an engine DAG and count distinct Python objects (memoized
    by id)."""
    seen = set()

    def _walk(n):
        if id(n) in seen:
            return
        seen.add(id(n))
        # Collect children based on attributes present
        for attr in ("children",):
            if hasattr(n, attr):
                for c in getattr(n, attr):
                    _walk(c)
        for attr in ("child", "left", "right", "condition", "if_true", "if_false"):
            if hasattr(n, attr):
                v = getattr(n, attr)
                if v is not None:
                    _walk(v)

    _walk(root)
    return len(seen)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_dump_to_program_validates():
    """Step 1+2: the 71-node engine DAG dumps to a DeterminationProgram
    that passes validate_program."""
    dag = build_fcba_composite_refined_dag()
    det = Determination(
        id="fcba.D1",
        description="FCBA §1026.13 composite resolution adjudication "
                    "(refined depth).",
        tree=dag,
        source_span="§1026.13",
    )
    program = engine_to_program([det], program_name="FCBA refined RT")
    report = validate_program(program)
    assert report.ok, report.summary()
    print("test_dump_to_program_validates: OK")


def test_node_count_and_sharing_preservation():
    """The contract program has the same number of distinct nodes as the
    engine DAG (because the converter preserves sharing). FCBA refined's
    conclusion-procedure subtree is constructed once and shared between
    the conclusion-procedure check and the acknowledgment-waiver check.
    """
    dag = build_fcba_composite_refined_dag()
    engine_node_count = _count_engine_nodes(dag)

    det = Determination(id="fcba.D1", description="d", tree=dag,
                         source_span="§1026.13")
    program = engine_to_program([det], program_name="FCBA refined RT")

    # Every distinct engine node should get exactly one NodeId.
    contract_node_count = len(program.nodes)
    assert contract_node_count == engine_node_count, (
        f"contract has {contract_node_count} nodes; engine has "
        f"{engine_node_count} distinct objects"
    )

    print(f"test_node_count_and_sharing_preservation: OK "
          f"({contract_node_count} nodes, sharing preserved)")


def test_json_round_trip():
    """The dumped program serializes to JSON, deserializes back, and
    re-validates."""
    dag = build_fcba_composite_refined_dag()
    det = Determination(id="fcba.D1", description="d", tree=dag,
                         source_span="§1026.13")
    program = engine_to_program([det], program_name="FCBA refined RT")
    js = program.model_dump_json()
    program2 = DeterminationProgram.model_validate_json(js)
    assert program2 == program
    report = validate_program(program2)
    assert report.ok, report.summary()
    print(f"test_json_round_trip: OK ({len(js)} bytes)")


def test_engine_evaluation_equivalence():
    """For every sanity-check scenario, the original engine DAG and the
    round-tripped DAG produce the same Kleene result on the same
    FactBundle.

    This is the load-bearing test. If it passes, the contract can
    express FCBA refined and the converter preserves its semantics.
    """
    original = build_fcba_composite_refined_dag()
    det = Determination(id="fcba.D1", description="d", tree=original,
                         source_span="§1026.13")
    program = engine_to_program([det], program_name="FCBA refined RT")
    rt = program_to_engine(program)
    converted = rt.determinations["fcba.D1"].tree

    scenarios = _scenarios()
    mismatches = []
    for label, atoms, expected, description in scenarios:
        bundle = build_fact_bundle(atoms)
        orig_result = original.evaluate(bundle, [])
        conv_result = converted.evaluate(bundle, [])
        # Sanity: the original should match its own expected result.
        # If this fails it's not a contract problem — it's a pre-existing
        # issue in the hand-built DAG. Report and continue.
        if orig_result != expected:
            mismatches.append(
                f"  ORIGINAL mismatch on {label!r}: "
                f"got {orig_result}, expected {expected}"
            )
            continue
        if conv_result != orig_result:
            mismatches.append(
                f"  CONVERTED diverges on {label!r}: "
                f"original={orig_result}, converted={conv_result}"
            )

    if mismatches:
        for m in mismatches:
            print(m)
        raise AssertionError(
            f"{len(mismatches)}/{len(scenarios)} scenario(s) failed"
        )

    print(f"test_engine_evaluation_equivalence: OK "
          f"({len(scenarios)}/{len(scenarios)} scenarios match)")


def test_json_round_trip_evaluation_equivalence():
    """End-to-end: dump engine -> JSON -> reload -> convert -> evaluate.
    Same results as the original DAG on every scenario.

    This proves the JSON form is operationally equivalent to the
    in-memory hand-built form. If someone ships the JSON, the runtime
    that loads it produces the same answers."""
    original = build_fcba_composite_refined_dag()
    det = Determination(id="fcba.D1", description="d", tree=original,
                         source_span="§1026.13")
    program = engine_to_program([det], program_name="FCBA refined RT")
    js = program.model_dump_json()
    program2 = DeterminationProgram.model_validate_json(js)
    rt = program_to_engine(program2)
    converted = rt.determinations["fcba.D1"].tree

    scenarios = _scenarios()
    mismatches = []
    for label, atoms, expected, description in scenarios:
        bundle = build_fact_bundle(atoms)
        orig_result = original.evaluate(bundle, [])
        conv_result = converted.evaluate(bundle, [])
        if orig_result != expected:
            mismatches.append(f"original mismatch on {label!r}")
            continue
        if conv_result != orig_result:
            mismatches.append(
                f"json round-trip diverges on {label!r}: "
                f"orig={orig_result}, after-json={conv_result}"
            )

    if mismatches:
        for m in mismatches:
            print(f"  {m}")
        raise AssertionError(
            f"{len(mismatches)}/{len(scenarios)} scenario(s) failed"
        )

    print(f"test_json_round_trip_evaluation_equivalence: OK "
          f"({len(scenarios)}/{len(scenarios)} scenarios match)")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_dump_to_program_validates,
        test_node_count_and_sharing_preservation,
        test_json_round_trip,
        test_engine_evaluation_equivalence,
        test_json_round_trip_evaluation_equivalence,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"{t.__name__}: FAIL — {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"{t.__name__}: ERROR — {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n{failed}/{len(tests)} tests failed")
        sys.exit(1)
    print(f"\nall {len(tests)} tests passed — "
          f"FCBA refined round-trip is structurally and semantically equivalent")

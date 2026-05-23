"""
Tests for the typed-engine extension.

Coverage:
1. NumericValue construction and equality
2. Each arithmetic node, with determinate and UNDETERMINED inputs
3. Each comparison node, with determinate and UNDETERMINED inputs
4. End-to-end composition with the existing Boolean engine
5. Trace formatting
6. Type-discipline errors (Kleene-stored-as-numeric raises TypeError)
"""

from __future__ import annotations

import sys
import os
from decimal import Decimal

# Allow running from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulekit.engine import (
    Kleene, FactBundle, AndNode, OrNode, NotNode, Leaf, Provenance,
)
from rulekit.engine.typed import (
    NumericValue, AtomType,
    NumericLeaf, Constant,
    TimesConstNode, PlusConstNode, MinusConstNode, ConstMinusNode,
    DivByConstNode, ConstDivByNode,
    EqNode, LtNode, LeqNode, GtNode, GeqNode,
    format_typed_trace, get_numeric,
)


# Track test results
_results = {"pass": 0, "fail": 0, "errors": []}


def check(name, condition, detail=""):
    if condition:
        _results["pass"] += 1
        print(f"  PASS  {name}")
    else:
        _results["fail"] += 1
        _results["errors"].append((name, detail))
        print(f"  FAIL  {name}  {detail}")


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ---------------------------------------------------------------------------
# 1. NumericValue
# ---------------------------------------------------------------------------

def test_numeric_value():
    section("NumericValue construction and behavior")

    v = NumericValue.of(5)
    check("NumericValue.of(int)", v.value == Decimal("5") and not v.is_undetermined)

    v = NumericValue.of(5.5)
    check("NumericValue.of(float)", v.value == Decimal("5.5"))

    v = NumericValue.of("12345.67")
    check("NumericValue.of(str)", v.value == Decimal("12345.67"))

    v = NumericValue.of(Decimal("100"))
    check("NumericValue.of(Decimal)", v.value == Decimal("100"))

    u = NumericValue.undetermined()
    check("NumericValue.undetermined()", u.is_undetermined and u.value is None)

    u2 = NumericValue.of(None)
    check("NumericValue.of(None) is undetermined", u2.is_undetermined)

    # Immutability
    try:
        v.value = Decimal("999")
        check("NumericValue is frozen", False, "Mutation should have raised")
    except Exception:
        check("NumericValue is frozen", True)

    # Equality
    a = NumericValue.of(5)
    b = NumericValue.of(5)
    check("Determinate equality", a == b)
    check("Undetermined equality",
          NumericValue.undetermined() == NumericValue.undetermined())
    check("Determinate != Undetermined",
          NumericValue.of(5) != NumericValue.undetermined())


# ---------------------------------------------------------------------------
# 2. Arithmetic nodes
# ---------------------------------------------------------------------------

def test_arithmetic_nodes():
    section("Arithmetic nodes — determinate inputs")

    # Set up a bundle with one numeric atom bound to 100
    bundle = FactBundle(values={"x": NumericValue.of(100)})
    leaf = NumericLeaf(atom_id="x")

    # TimesConstNode: 100 * 0.5 = 50
    node = TimesConstNode(child=leaf, constant=Decimal("0.5"))
    result = node.evaluate(bundle)
    check("TimesConst 100 * 0.5 = 50", result.value == Decimal("50.0"))

    # PlusConstNode: 100 + 25 = 125
    node = PlusConstNode(child=leaf, constant=Decimal("25"))
    result = node.evaluate(bundle)
    check("PlusConst 100 + 25 = 125", result.value == Decimal("125"))

    # MinusConstNode: 100 - 30 = 70
    node = MinusConstNode(child=leaf, constant=Decimal("30"))
    result = node.evaluate(bundle)
    check("MinusConst 100 - 30 = 70", result.value == Decimal("70"))

    # ConstMinusNode: 500 - 100 = 400
    node = ConstMinusNode(constant=Decimal("500"), child=leaf)
    result = node.evaluate(bundle)
    check("ConstMinus 500 - 100 = 400", result.value == Decimal("400"))

    # DivByConstNode: 100 / 4 = 25
    node = DivByConstNode(child=leaf, constant=Decimal("4"))
    result = node.evaluate(bundle)
    check("DivByConst 100 / 4 = 25", result.value == Decimal("25"))

    # ConstDivByNode: 500 / 100 = 5
    node = ConstDivByNode(constant=Decimal("500"), child=leaf)
    result = node.evaluate(bundle)
    check("ConstDivBy 500 / 100 = 5", result.value == Decimal("5"))

    # DivByConst: zero constant raises at construction
    try:
        DivByConstNode(child=leaf, constant=Decimal("0"))
        check("DivByConst with zero constant raises", False)
    except ValueError:
        check("DivByConst with zero constant raises", True)

    # ConstDivBy: zero child gives UNDETERMINED (not exception)
    bundle_zero = FactBundle(values={"x": NumericValue.of(0)})
    node = ConstDivByNode(constant=Decimal("500"), child=NumericLeaf(atom_id="x"))
    result = node.evaluate(bundle_zero)
    check("ConstDivBy with zero child -> UNDETERMINED", result.is_undetermined)


def test_arithmetic_undetermined_propagation():
    section("Arithmetic nodes — UNDETERMINED propagation")

    bundle = FactBundle(values={"x": NumericValue.undetermined()})
    leaf = NumericLeaf(atom_id="x")

    for cls_name, node in [
        ("TimesConst", TimesConstNode(child=leaf, constant=Decimal("0.5"))),
        ("PlusConst", PlusConstNode(child=leaf, constant=Decimal("25"))),
        ("MinusConst", MinusConstNode(child=leaf, constant=Decimal("30"))),
        ("ConstMinus", ConstMinusNode(constant=Decimal("500"), child=leaf)),
        ("DivByConst", DivByConstNode(child=leaf, constant=Decimal("4"))),
        ("ConstDivBy", ConstDivByNode(constant=Decimal("500"), child=leaf)),
    ]:
        result = node.evaluate(bundle)
        check(f"{cls_name}(UNDETERMINED) -> UNDETERMINED", result.is_undetermined)


def test_constant_node():
    section("Constant node")

    bundle = FactBundle(values={})
    c = Constant(value=Decimal("140588000"), label="2024-25 Salary Cap")
    result = c.evaluate(bundle)
    check("Constant value", result.value == Decimal("140588000"))
    check("Constant is never UNDETERMINED", not result.is_undetermined)


def test_arithmetic_chains():
    section("Arithmetic chains — composition")

    # Compute 9.12% × cap + 0 (just chaining for the test)
    # Then verify chain UNDETERMINED propagation
    bundle = FactBundle(values={"cap": NumericValue.of(140588000)})
    leaf = NumericLeaf(atom_id="cap")

    # 9.12% of cap = 12,821,625.6
    pct = TimesConstNode(child=leaf, constant=Decimal("0.0912"))
    result = pct.evaluate(bundle)
    expected = Decimal("140588000") * Decimal("0.0912")
    check("9.12% × cap", result.value == expected)

    # Now chain: ((cap × 0.0912) + 1000) − 500
    chain = MinusConstNode(
        child=PlusConstNode(child=pct, constant=Decimal("1000")),
        constant=Decimal("500"),
    )
    result = chain.evaluate(bundle)
    check("Chained arithmetic", result.value == expected + Decimal("500"))

    # Undetermined propagation through a chain
    bundle_u = FactBundle(values={"cap": NumericValue.undetermined()})
    result_u = chain.evaluate(bundle_u)
    check("Chained UNDETERMINED propagation", result_u.is_undetermined)


# ---------------------------------------------------------------------------
# 3. Comparison nodes
# ---------------------------------------------------------------------------

def test_comparison_nodes():
    section("Comparison nodes — determinate")

    bundle = FactBundle(values={
        "a": NumericValue.of(100),
        "b": NumericValue.of(200),
        "c": NumericValue.of(100),
    })
    a = NumericLeaf(atom_id="a")
    b = NumericLeaf(atom_id="b")
    c = NumericLeaf(atom_id="c")

    check("Eq 100 == 100", EqNode(left=a, right=c).evaluate(bundle) == Kleene.TRUE)
    check("Eq 100 == 200", EqNode(left=a, right=b).evaluate(bundle) == Kleene.FALSE)

    check("Lt 100 < 200", LtNode(left=a, right=b).evaluate(bundle) == Kleene.TRUE)
    check("Lt 100 < 100 (strict)", LtNode(left=a, right=c).evaluate(bundle) == Kleene.FALSE)
    check("Lt 200 < 100", LtNode(left=b, right=a).evaluate(bundle) == Kleene.FALSE)

    check("Leq 100 ≤ 100", LeqNode(left=a, right=c).evaluate(bundle) == Kleene.TRUE)
    check("Leq 100 ≤ 200", LeqNode(left=a, right=b).evaluate(bundle) == Kleene.TRUE)
    check("Leq 200 ≤ 100", LeqNode(left=b, right=a).evaluate(bundle) == Kleene.FALSE)

    check("Gt 200 > 100", GtNode(left=b, right=a).evaluate(bundle) == Kleene.TRUE)
    check("Gt 100 > 100 (strict)", GtNode(left=a, right=c).evaluate(bundle) == Kleene.FALSE)

    check("Geq 100 ≥ 100", GeqNode(left=a, right=c).evaluate(bundle) == Kleene.TRUE)
    check("Geq 200 ≥ 100", GeqNode(left=b, right=a).evaluate(bundle) == Kleene.TRUE)
    check("Geq 100 ≥ 200", GeqNode(left=a, right=b).evaluate(bundle) == Kleene.FALSE)


def test_comparison_undetermined():
    section("Comparison nodes — UNDETERMINED propagation")

    bundle = FactBundle(values={
        "known": NumericValue.of(100),
        "unknown": NumericValue.undetermined(),
    })
    known = NumericLeaf(atom_id="known")
    unknown = NumericLeaf(atom_id="unknown")

    for op_name, cls in [("eq", EqNode), ("lt", LtNode), ("leq", LeqNode),
                          ("gt", GtNode), ("geq", GeqNode)]:
        # Left undetermined
        node = cls(left=unknown, right=known)
        check(f"{op_name}(UND, known) = UND",
              node.evaluate(bundle) == Kleene.UNDETERMINED)
        # Right undetermined
        node = cls(left=known, right=unknown)
        check(f"{op_name}(known, UND) = UND",
              node.evaluate(bundle) == Kleene.UNDETERMINED)
        # Both undetermined
        node = cls(left=unknown, right=unknown)
        check(f"{op_name}(UND, UND) = UND",
              node.evaluate(bundle) == Kleene.UNDETERMINED)


# ---------------------------------------------------------------------------
# 4. End-to-end composition with Boolean engine
# ---------------------------------------------------------------------------

def test_end_to_end_composition():
    section("End-to-end: typed arithmetic feeding Boolean composition")

    # Simulate a tiny NBA-style rule:
    #
    #   op_permitted_via_non_taxpayer_mle :=
    #     AND(
    #       team_above_cap_below_first_apron,         -- boolean atom
    #       contract_salary_within_9.12_pct_cap        -- typed comparison
    #     )
    #
    #   contract_salary_within_9.12_pct_cap :=
    #     LEQ(
    #       contract_first_year_salary,                -- numeric atom
    #       TIMES_CONST(salary_cap, 0.0912)            -- numeric arith
    #     )

    SALARY_CAP = Decimal("140588000")

    # Bundle: contract salary = $5,150,000, team is above cap below first apron
    bundle_ok = FactBundle(values={
        "contract_first_year_salary": NumericValue.of(5150000),
        "salary_cap": NumericValue.of(SALARY_CAP),
        "team_above_cap_below_first_apron": Kleene.TRUE,
    })

    salary_node = NumericLeaf(atom_id="contract_first_year_salary")
    cap_node = NumericLeaf(atom_id="salary_cap")
    mle_limit = TimesConstNode(child=cap_node, constant=Decimal("0.0912"),
                                surface_label="9.12% × cap")
    salary_within_limit = LeqNode(left=salary_node, right=mle_limit,
                                   surface_label="salary ≤ MLE limit")

    op_permitted = AndNode(children=[
        Leaf(atom_id="team_above_cap_below_first_apron"),
        salary_within_limit,
    ], surface_label="op_permitted_via_non_taxpayer_mle")

    # Determinate case: should be TRUE (5.15M ≤ 12.82M, and team in bracket)
    trace = []
    result = op_permitted.evaluate(bundle_ok, trace)
    check("Mixed DAG: salary in limit AND team in bracket -> TRUE",
          result == Kleene.TRUE)

    # Case where salary exceeds limit
    bundle_over = FactBundle(values={
        "contract_first_year_salary": NumericValue.of(15000000),
        "salary_cap": NumericValue.of(SALARY_CAP),
        "team_above_cap_below_first_apron": Kleene.TRUE,
    })
    result = op_permitted.evaluate(bundle_over)
    check("Mixed DAG: salary > MLE limit -> FALSE", result == Kleene.FALSE)

    # Case where team is NOT in the right bracket
    bundle_wrong_bracket = FactBundle(values={
        "contract_first_year_salary": NumericValue.of(5150000),
        "salary_cap": NumericValue.of(SALARY_CAP),
        "team_above_cap_below_first_apron": Kleene.FALSE,
    })
    result = op_permitted.evaluate(bundle_wrong_bracket)
    check("Mixed DAG: wrong bracket -> FALSE", result == Kleene.FALSE)

    # Case where salary is unknown - should propagate UNDETERMINED
    bundle_unknown = FactBundle(values={
        "contract_first_year_salary": NumericValue.undetermined(),
        "salary_cap": NumericValue.of(SALARY_CAP),
        "team_above_cap_below_first_apron": Kleene.TRUE,
    })
    result = op_permitted.evaluate(bundle_unknown)
    check("Mixed DAG: UNDETERMINED salary -> UNDETERMINED (Kleene)",
          result == Kleene.UNDETERMINED)

    # Case where salary is unknown AND team bracket is FALSE
    # Kleene AND with one FALSE child dominates -> FALSE
    bundle_unknown_and_wrong = FactBundle(values={
        "contract_first_year_salary": NumericValue.undetermined(),
        "salary_cap": NumericValue.of(SALARY_CAP),
        "team_above_cap_below_first_apron": Kleene.FALSE,
    })
    result = op_permitted.evaluate(bundle_unknown_and_wrong)
    check("Mixed DAG: UND salary + FALSE bracket -> FALSE (Kleene dominance)",
          result == Kleene.FALSE)


# ---------------------------------------------------------------------------
# 5. Trace formatting
# ---------------------------------------------------------------------------

def test_trace_format():
    section("Trace formatting")

    SALARY_CAP = Decimal("140588000")
    bundle = FactBundle(values={
        "contract_first_year_salary": NumericValue.of(5150000),
        "salary_cap": NumericValue.of(SALARY_CAP),
        "team_in_bracket": Kleene.TRUE,
    })

    salary_node = NumericLeaf(atom_id="contract_first_year_salary")
    cap_node = NumericLeaf(atom_id="salary_cap")
    mle_limit = TimesConstNode(child=cap_node, constant=Decimal("0.0912"),
                                surface_label="9.12% × cap")
    salary_within_limit = LeqNode(left=salary_node, right=mle_limit,
                                   surface_label="salary ≤ MLE limit")
    op_permitted = AndNode(children=[
        Leaf(atom_id="team_in_bracket"),
        salary_within_limit,
    ], surface_label="permitted_via_non_taxpayer_mle")

    trace = []
    result = op_permitted.evaluate(bundle, trace)
    formatted = format_typed_trace(trace)
    print("\n--- Sample trace output ---")
    print(formatted)
    print("---")

    check("Trace contains the AND label",
          "permitted_via_non_taxpayer_mle" in formatted)
    check("Trace contains the LEQ label", "salary ≤ MLE limit" in formatted)
    check("Trace contains TIMES_CONST label", "9.12% × cap" in formatted)
    check("Trace contains numeric values",
          "5150000" in formatted and "140588000" in formatted)
    check("Trace ends with result", result == Kleene.TRUE)


# ---------------------------------------------------------------------------
# 6. Type discipline
# ---------------------------------------------------------------------------

def test_type_discipline():
    section("Type discipline — Kleene-as-numeric raises")

    bundle = FactBundle(values={
        "boolean_atom": Kleene.TRUE,  # Wrong type for a numeric leaf!
    })

    # Attempting to read a Kleene-bound atom as numeric should raise.
    try:
        get_numeric(bundle, "boolean_atom")
        check("get_numeric on Kleene-bound atom raises", False,
              "Should have raised TypeError")
    except TypeError:
        check("get_numeric on Kleene-bound atom raises", True)

    # NumericLeaf.evaluate on a Kleene-bound atom should also raise
    leaf = NumericLeaf(atom_id="boolean_atom")
    try:
        leaf.evaluate(bundle)
        check("NumericLeaf.evaluate on Kleene-bound atom raises", False)
    except TypeError:
        check("NumericLeaf.evaluate on Kleene-bound atom raises", True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    test_numeric_value()
    test_constant_node()
    test_arithmetic_nodes()
    test_arithmetic_undetermined_propagation()
    test_arithmetic_chains()
    test_comparison_nodes()
    test_comparison_undetermined()
    test_end_to_end_composition()
    test_trace_format()
    test_type_discipline()

    print("\n" + "=" * 70)
    print(f"RESULTS: {_results['pass']} passed, {_results['fail']} failed")
    print("=" * 70)
    if _results["fail"] > 0:
        print("\nFailures:")
        for name, detail in _results["errors"]:
            print(f"  - {name}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()

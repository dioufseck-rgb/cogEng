"""
test_typed_engine_conversion.py — unit tests for Piece 5 (Stage-4 conversion).

Tests _numeric_spec_to_engine_node and spec_to_engine_node for ComparisonSpec
across every conversion path. No LLM calls; uses hand-constructed spec trees.

Run: python tests/test_typed_engine_conversion.py
"""
from __future__ import annotations
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulekit.build.decomposer import (
    LeafSpec, OperatorSpec, ComparisonSpec,
    NumericLeafSpec, ConstantSpec, UnaryArithmeticSpec, DerivedAtomSpec,
    spec_to_engine_node, _numeric_spec_to_engine_node, _to_decimal_constant,
)
from rulekit.engine.typed import (
    NumericLeaf, Constant,
    TimesConstNode, PlusConstNode, MinusConstNode, ConstMinusNode,
    DivByConstNode, ConstDivByNode,
    EqNode, LtNode, LeqNode, GtNode, GeqNode,
    NumericValue,
    Kleene as TypedKleene,
)
from rulekit.engine import Kleene
from rulekit.schema import Atom

# CBA constants for tests
NBA_CONSTANTS = {
    "salary_cap": Decimal("140588000"),
    "first_apron_level": Decimal("178132000"),
    "second_apron_level": Decimal("188931000"),
}


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

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
# _to_decimal_constant
# ---------------------------------------------------------------------------

def test_to_decimal_constant():
    section("_to_decimal_constant")

    check(_to_decimal_constant(4) == Decimal(4), "int 4 -> Decimal(4)")
    check(_to_decimal_constant(0.0912) == Decimal("0.0912"),
          "float 0.0912 -> Decimal('0.0912') (no binary error)")
    check(_to_decimal_constant("250000") == Decimal(250000), "str '250000' -> Decimal(250000)")
    check(_to_decimal_constant("$250,000") == Decimal(250000), "str '$250,000' -> Decimal(250000)")
    check(_to_decimal_constant(Decimal("99.99")) == Decimal("99.99"),
          "Decimal passthrough")

    # The float-binary error case: 0.1 + 0.2 in float = 0.30000000000000004
    # but our parser uses str(), which gives Decimal('0.30000000000000004') — that's still the
    # float's string representation, not 0.3. So this is a known caveat for callers.
    # What matters is that LITERALS from JSON (which Python parses directly) round-trip cleanly.
    check(_to_decimal_constant(1.05) == Decimal("1.05"),
          "float 1.05 -> Decimal('1.05')")

    try:
        _to_decimal_constant([1, 2, 3])
        check(False, "list raises ValueError")
    except ValueError:
        check(True, "list raises ValueError")


# ---------------------------------------------------------------------------
# _numeric_spec_to_engine_node — every NumericSpec type
# ---------------------------------------------------------------------------

def test_numeric_leaf_spec():
    section("NumericLeafSpec -> NumericLeaf")

    atoms = {}
    spec = NumericLeafSpec(
        atom_id_hint="team_salary",
        statement="The team's current team salary in USD.",
        source_span="Section 6(e)",
    )
    node = _numeric_spec_to_engine_node(spec, atoms, NBA_CONSTANTS)
    check(isinstance(node, NumericLeaf), "produces NumericLeaf")
    check(node.atom_id == "team_salary", "atom_id matches hint")
    check("team_salary" in atoms, "atom registered")
    check(atoms["team_salary"].atom_type == "numeric", "atom_type is numeric")
    check(atoms["team_salary"].statement == "The team's current team salary in USD.",
          "statement preserved")

    # Idempotence — calling again shouldn't re-register
    n_atoms_before = len(atoms)
    _numeric_spec_to_engine_node(spec, atoms, NBA_CONSTANTS)
    check(len(atoms) == n_atoms_before, "second call doesn't duplicate")


def test_constant_spec_value():
    section("ConstantSpec with value -> Constant")

    spec = ConstantSpec(value=4)
    node = _numeric_spec_to_engine_node(spec, {}, NBA_CONSTANTS)
    check(isinstance(node, Constant), "produces Constant")
    check(node.value == Decimal(4), "value matches")
    check(node.label == "", "label empty for value-only constant")

    # Float constant
    spec_float = ConstantSpec(value=0.0912)
    node_float = _numeric_spec_to_engine_node(spec_float, {}, NBA_CONSTANTS)
    check(node_float.value == Decimal("0.0912"), "float 0.0912 preserved as Decimal")


def test_constant_spec_label():
    section("ConstantSpec with label -> Constant (looked up)")

    spec = ConstantSpec(label="salary_cap")
    node = _numeric_spec_to_engine_node(spec, {}, NBA_CONSTANTS)
    check(isinstance(node, Constant), "produces Constant")
    check(node.value == Decimal("140588000"), "value resolved from registry")
    check(node.label == "salary_cap", "label preserved")

    # Missing label should raise
    bad_spec = ConstantSpec(label="unknown_constant")
    try:
        _numeric_spec_to_engine_node(bad_spec, {}, NBA_CONSTANTS)
        check(False, "missing label raises")
    except ValueError as e:
        check("unknown_constant" in str(e), "error mentions missing label")


def test_unary_arithmetic_all_operators():
    section("UnaryArithmeticSpec — all six operators")

    leaf = NumericLeafSpec(atom_id_hint="x", statement="x value")

    # times_const: child × constant
    spec = UnaryArithmeticSpec(operator="times_const", constant=2.0, child=leaf)
    node = _numeric_spec_to_engine_node(spec, {}, {})
    check(isinstance(node, TimesConstNode), "times_const -> TimesConstNode")
    check(node.constant == Decimal("2.0"), "times_const constant correct")

    # plus_const: child + constant
    spec = UnaryArithmeticSpec(operator="plus_const", constant=250000, child=leaf)
    node = _numeric_spec_to_engine_node(spec, {}, {})
    check(isinstance(node, PlusConstNode), "plus_const -> PlusConstNode")
    check(node.constant == Decimal(250000), "plus_const constant correct")

    # minus_const: child - constant
    spec = UnaryArithmeticSpec(operator="minus_const", constant=100000, child=leaf)
    node = _numeric_spec_to_engine_node(spec, {}, {})
    check(isinstance(node, MinusConstNode), "minus_const -> MinusConstNode")

    # const_minus: constant - child
    spec = UnaryArithmeticSpec(operator="const_minus", constant_label="salary_cap", child=leaf)
    node = _numeric_spec_to_engine_node(spec, {}, NBA_CONSTANTS)
    check(isinstance(node, ConstMinusNode), "const_minus -> ConstMinusNode")
    check(node.constant == Decimal("140588000"), "const_minus uses named constant")

    # div_by_const: child / constant
    spec = UnaryArithmeticSpec(operator="div_by_const", constant=2, child=leaf)
    node = _numeric_spec_to_engine_node(spec, {}, {})
    check(isinstance(node, DivByConstNode), "div_by_const -> DivByConstNode")

    # const_div_by: constant / child
    spec = UnaryArithmeticSpec(operator="const_div_by", constant=100, child=leaf)
    node = _numeric_spec_to_engine_node(spec, {}, {})
    check(isinstance(node, ConstDivByNode), "const_div_by -> ConstDivByNode")


def test_nested_arithmetic():
    section("Nested UnaryArithmeticSpec — recursion")

    # Build: 9.12% × (salary_cap − prior_salary)
    inner = UnaryArithmeticSpec(
        operator="const_minus",
        constant_label="salary_cap",
        child=NumericLeafSpec(atom_id_hint="prior_salary", statement="prior"),
    )
    outer = UnaryArithmeticSpec(
        operator="times_const",
        constant=0.0912,
        child=inner,
    )

    atoms = {}
    node = _numeric_spec_to_engine_node(outer, atoms, NBA_CONSTANTS)

    check(isinstance(node, TimesConstNode), "outer is TimesConstNode")
    check(node.constant == Decimal("0.0912"), "outer constant 0.0912")
    check(isinstance(node.child, ConstMinusNode), "child is ConstMinusNode")
    check(node.child.constant == Decimal("140588000"), "inner uses cap")
    check(isinstance(node.child.child, NumericLeaf), "innermost is NumericLeaf")
    check(node.child.child.atom_id == "prior_salary", "innermost atom id correct")
    check("prior_salary" in atoms, "leaf atom registered")


def test_derived_atom_spec():
    section("DerivedAtomSpec -> NumericLeaf with computation_kind in notes")

    spec = DerivedAtomSpec(
        atom_id_hint="max_salary_ceiling",
        statement="The greater of 25% cap or 105% prior salary",
        computation_kind="max_of",
    )
    atoms = {}
    node = _numeric_spec_to_engine_node(spec, atoms, {})

    check(isinstance(node, NumericLeaf), "produces NumericLeaf")
    check(node.atom_id == "max_salary_ceiling", "atom_id matches hint")
    check(atoms["max_salary_ceiling"].atom_type == "numeric", "atom_type is numeric")
    check("computation_kind=max_of" in atoms["max_salary_ceiling"].notes,
          "computation_kind recorded in notes")


# ---------------------------------------------------------------------------
# spec_to_engine_node — ComparisonSpec
# ---------------------------------------------------------------------------

def test_comparison_all_operators():
    section("ComparisonSpec — all five operators")

    operators = [
        ("leq", LeqNode),
        ("lt", LtNode),
        ("geq", GeqNode),
        ("gt", GtNode),
        ("eq", EqNode),
    ]
    for op_str, expected_class in operators:
        spec = ComparisonSpec(
            operator=op_str,
            lhs_description="x", rhs_description="4",
            lhs_kind="numeric_leaf", rhs_kind="constant",
            lhs_spec=NumericLeafSpec(atom_id_hint="x", statement="x value"),
            rhs_spec=ConstantSpec(value=4),
        )
        node = spec_to_engine_node(spec, {}, {})
        check(isinstance(node, expected_class), f"operator={op_str} -> {expected_class.__name__}")


def test_comparison_unexpanded_raises():
    section("ComparisonSpec without lhs/rhs_spec raises ValueError")

    spec = ComparisonSpec(
        operator="leq",
        lhs_description="x", rhs_description="y",
        lhs_kind="numeric_leaf", rhs_kind="numeric_leaf",
        lhs_spec=None, rhs_spec=None,
    )
    try:
        spec_to_engine_node(spec, {}, {})
        check(False, "unexpanded ComparisonSpec raises")
    except ValueError as e:
        check("not fully expanded" in str(e), "error message clear")


def test_comparison_inside_and_boolean():
    section("ComparisonSpec composed inside AndNode — end-to-end")

    # AND of two comparisons (the exact structure from the integration test):
    # AND(
    #   LEQ(contract_first_year_salary, TIMES_CONST(0.0912, salary_cap)),
    #   LEQ(contract_length_seasons, 4)
    # )
    spec_salary = ComparisonSpec(
        operator="leq",
        lhs_description="contract first-year salary",
        rhs_description="9.12% of the Salary Cap",
        lhs_kind="numeric_leaf", rhs_kind="arithmetic",
        lhs_spec=NumericLeafSpec(atom_id_hint="contract_first_year_salary",
                                 statement="contract first-year salary"),
        rhs_spec=UnaryArithmeticSpec(
            operator="times_const",
            constant=0.0912,
            child=ConstantSpec(label="salary_cap"),
        ),
        surface_label="salary within MLE limit",
    )
    spec_length = ComparisonSpec(
        operator="leq",
        lhs_description="contract length in Seasons",
        rhs_description="the integer 4",
        lhs_kind="numeric_leaf", rhs_kind="constant",
        lhs_spec=NumericLeafSpec(atom_id_hint="contract_length_seasons",
                                 statement="contract length in seasons"),
        rhs_spec=ConstantSpec(value=4),
        surface_label="length ≤ 4",
    )
    spec_and = OperatorSpec(
        operator="and",
        children=[spec_salary, spec_length],
        surface_label="Non-Taxpayer MLE permitted",
    )

    atoms = {}
    node = spec_to_engine_node(spec_and, atoms, NBA_CONSTANTS)

    # Inspect structure
    from rulekit.engine import AndNode
    check(isinstance(node, AndNode), "top-level AndNode")
    check(len(node.children) == 2, "two children")
    check(isinstance(node.children[0], LeqNode), "first child is LeqNode (salary)")
    check(isinstance(node.children[1], LeqNode), "second child is LeqNode (length)")

    # Inspect the salary comparison
    salary_node = node.children[0]
    check(isinstance(salary_node.left, NumericLeaf), "salary LHS is NumericLeaf")
    check(isinstance(salary_node.right, TimesConstNode), "salary RHS is TimesConstNode")
    check(salary_node.right.constant == Decimal("0.0912"), "salary RHS constant 0.0912")
    check(isinstance(salary_node.right.child, Constant), "salary RHS child is Constant")
    check(salary_node.right.child.value == Decimal("140588000"), "salary RHS uses cap")

    # Inspect the length comparison
    length_node = node.children[1]
    check(length_node.left.atom_id == "contract_length_seasons",
          "length LHS atom id correct")
    check(length_node.right.value == Decimal(4), "length RHS constant 4")

    # Atom registry
    check("contract_first_year_salary" in atoms, "salary atom registered")
    check("contract_length_seasons" in atoms, "length atom registered")
    check(atoms["contract_first_year_salary"].atom_type == "numeric",
          "salary atom typed numeric")
    check(atoms["contract_length_seasons"].atom_type == "numeric",
          "length atom typed numeric")


# ---------------------------------------------------------------------------
# End-to-end evaluation — produce engine nodes, feed FactBundle, get result
# ---------------------------------------------------------------------------

def test_end_to_end_evaluation():
    section("End-to-end: built DAG evaluates against synthetic case data")

    # Same AND-of-two-LEQs structure, but now we'll evaluate it with
    # a synthetic FactBundle to confirm the engine runs end-to-end.

    spec_salary = ComparisonSpec(
        operator="leq",
        lhs_description="contract first-year salary",
        rhs_description="9.12% of Salary Cap",
        lhs_kind="numeric_leaf", rhs_kind="arithmetic",
        lhs_spec=NumericLeafSpec(atom_id_hint="contract_first_year_salary",
                                 statement="contract first-year salary"),
        rhs_spec=UnaryArithmeticSpec(
            operator="times_const", constant=0.0912,
            child=ConstantSpec(label="salary_cap"),
        ),
    )
    spec_length = ComparisonSpec(
        operator="leq",
        lhs_description="contract length", rhs_description="4",
        lhs_kind="numeric_leaf", rhs_kind="constant",
        lhs_spec=NumericLeafSpec(atom_id_hint="contract_length_seasons",
                                 statement="contract length in seasons"),
        rhs_spec=ConstantSpec(value=4),
    )
    spec_and = OperatorSpec(
        operator="and", children=[spec_salary, spec_length],
        surface_label="Non-Taxpayer MLE permitted",
    )

    atoms = {}
    node = spec_to_engine_node(spec_and, atoms, NBA_CONSTANTS)

    # FactBundle: contract salary $5.15M (within 9.12% × 140.588M = ~12.82M),
    #             contract length 3 seasons (within 4)
    from rulekit.engine import FactBundle
    bundle = FactBundle(values={
        "contract_first_year_salary": NumericValue.of("5150000"),
        "contract_length_seasons": NumericValue.of(3),
    })

    result = node.evaluate(bundle)
    check(result == Kleene.TRUE,
          f"contract within MLE limits -> TRUE (got {result})")

    # Now make the salary too high
    bundle_high = FactBundle(values={
        "contract_first_year_salary": NumericValue.of("20000000"),  # 20M > 12.82M
        "contract_length_seasons": NumericValue.of(3),
    })
    result_high = node.evaluate(bundle_high)
    check(result_high == Kleene.FALSE,
          f"contract salary too high -> FALSE (got {result_high})")

    # Undetermined salary -> AND short-circuits to length check, both
    # need to evaluate; LEQ on undetermined LHS yields UND; AND with UND
    # and TRUE yields UND.
    bundle_und = FactBundle(values={
        "contract_first_year_salary": NumericValue.undetermined(),
        "contract_length_seasons": NumericValue.of(3),
    })
    result_und = node.evaluate(bundle_und)
    check(result_und == Kleene.UNDETERMINED,
          f"undetermined salary -> UND (got {result_und})")


# ---------------------------------------------------------------------------
# Boolean policies still work (no constants needed)
# ---------------------------------------------------------------------------

def test_boolean_only_path_still_works():
    section("Boolean-only spec (no comparisons) still builds with empty constants")

    # Build: AND(LeafSpec("x"), LeafSpec("y")) where leaves have atom_ids set
    leaf_x = LeafSpec(claim="x is true", source_span="1.1")
    leaf_x.atom_id = "pa.a01"
    leaf_y = LeafSpec(claim="y is true", source_span="1.2")
    leaf_y.atom_id = "pa.a02"
    spec_and = OperatorSpec(
        operator="and",
        children=[leaf_x, leaf_y],
        surface_label="x and y",
    )

    atoms = {}
    node = spec_to_engine_node(spec_and, atoms)  # No constants arg

    from rulekit.engine import AndNode
    check(isinstance(node, AndNode), "Boolean AndNode built")
    check(len(node.children) == 2, "two leaf children")
    check("pa.a01" in atoms, "leaf atom registered")
    check(atoms["pa.a01"].atom_type == "boolean", "Boolean atom type default")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_to_decimal_constant()
    test_numeric_leaf_spec()
    test_constant_spec_value()
    test_constant_spec_label()
    test_unary_arithmetic_all_operators()
    test_nested_arithmetic()
    test_derived_atom_spec()
    test_comparison_all_operators()
    test_comparison_unexpanded_raises()
    test_comparison_inside_and_boolean()
    test_end_to_end_evaluation()
    test_boolean_only_path_still_works()

    print()
    print("=" * 70)
    print(f"RESULTS: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print("=" * 70)

    if FAIL_COUNT > 0:
        sys.exit(1)

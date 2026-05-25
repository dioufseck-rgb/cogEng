"""
test_binary_variadic_spec.py -- tests for the new spec types added to
support pushing multi-fact arithmetic into the engine (Phase 2 finding:
Map cannot reliably compute multi-fact arithmetic; engine must do it).

Covers:
  - Spec dataclass construction and validation
  - Spec deserialization from LLM-JSON output (via
    _build_numeric_spec_from_parsed)
  - Spec-to-engine-node conversion (via _numeric_spec_to_engine_node)
  - End-to-end: parse JSON -> spec -> engine node -> evaluate
"""
from __future__ import annotations
import os
import sys
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.build.decomposer import (
    NumericLeafSpec, ConstantSpec, UnaryArithmeticSpec,
    PlusSpec, MinusSpec, MulSpec,
    SumSpec, MaxSpec, MinSpec,
    _build_numeric_spec_from_parsed,
    _numeric_spec_to_engine_node,
)
from rulekit.engine import FactBundle, Kleene
from rulekit.engine.typed import (
    NumericValue, NumericLeaf, Constant,
    PlusNode, MinusNode, MulNode,
    SumNode, MaxNode, MinNode,
    TimesConstNode, LeqNode,
)


passed = 0
failed = 0


def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")


# ---------------------------------------------------------------------------
# Test 1: Spec dataclass construction
# ---------------------------------------------------------------------------
print("=" * 70)
print("Test 1: Spec dataclasses construct correctly")
print("=" * 70)

a = NumericLeafSpec(atom_id_hint="a", statement="value a")
b = NumericLeafSpec(atom_id_hint="b", statement="value b")

plus = PlusSpec(left=a, right=b)
check(plus.left.atom_id_hint == "a", "PlusSpec.left preserved")
check(plus.right.atom_id_hint == "b", "PlusSpec.right preserved")

minus = MinusSpec(left=a, right=b)
check(minus.left.atom_id_hint == "a", "MinusSpec.left preserved")

mul = MulSpec(left=a, right=b)
check(mul.right.atom_id_hint == "b", "MulSpec.right preserved")

c = NumericLeafSpec(atom_id_hint="c", statement="value c")
sum_spec = SumSpec(children=[a, b, c])
check(len(sum_spec.children) == 3, "SumSpec preserves 3 children")

max_spec = MaxSpec(children=[a, b])
check(len(max_spec.children) == 2, "MaxSpec preserves 2 children")


# ---------------------------------------------------------------------------
# Test 2: Validation
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 2: Variadic specs require >= 2 children")
print("=" * 70)

try:
    SumSpec(children=[a])
    check(False, "SumSpec with 1 child should raise")
except ValueError:
    check(True, "SumSpec with 1 child raises ValueError")

try:
    MaxSpec(children=[a])
    check(False, "MaxSpec with 1 child should raise")
except ValueError:
    check(True, "MaxSpec with 1 child raises ValueError")

try:
    MinSpec(children=[])
    check(False, "MinSpec with empty children should raise")
except ValueError:
    check(True, "MinSpec with empty children raises ValueError")


# ---------------------------------------------------------------------------
# Test 3: Deserialization from JSON-shaped dict
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 3: _build_numeric_spec_from_parsed handles new spec types")
print("=" * 70)

# Simulate LLM JSON output for plus
parsed_plus = {
    "spec_type": "plus",
    "left": {
        "spec_type": "numeric_leaf",
        "atom_id_hint": "pre_signing_team_salary",
        "statement": "The team's salary before the signing.",
    },
    "right": {
        "spec_type": "numeric_leaf",
        "atom_id_hint": "first_year_salary",
        "statement": "The first-year salary of the new contract.",
    },
    "surface_label": "team_salary_post_signing",
}

spec = _build_numeric_spec_from_parsed(parsed_plus, state=None)
check(isinstance(spec, PlusSpec), "Deserialized 'plus' -> PlusSpec")
check(spec.left.atom_id_hint == "pre_signing_team_salary",
      "PlusSpec left atom_id correctly parsed")
check(spec.right.atom_id_hint == "first_year_salary",
      "PlusSpec right atom_id correctly parsed")

# Variadic: max
parsed_max = {
    "spec_type": "max",
    "children": [
        {
            "spec_type": "unary_arithmetic",
            "operator": "times_const",
            "constant": 0.35,
            "child": {
                "spec_type": "constant",
                "label": "salary_cap",
            },
        },
        {
            "spec_type": "unary_arithmetic",
            "operator": "times_const",
            "constant": 1.05,
            "child": {
                "spec_type": "numeric_leaf",
                "atom_id_hint": "prior_year_salary",
                "statement": "Player prior year salary",
            },
        },
    ],
    "surface_label": "max_salary_ceiling",
}

spec = _build_numeric_spec_from_parsed(parsed_max, state=None)
check(isinstance(spec, MaxSpec), "Deserialized 'max' -> MaxSpec")
check(len(spec.children) == 2, "MaxSpec has 2 children")
check(isinstance(spec.children[0], UnaryArithmeticSpec),
      "MaxSpec child 0 is UnaryArithmeticSpec")

# Sum
parsed_sum = {
    "spec_type": "sum",
    "children": [
        {"spec_type": "numeric_leaf", "atom_id_hint": "a", "statement": "a"},
        {"spec_type": "numeric_leaf", "atom_id_hint": "b", "statement": "b"},
        {"spec_type": "numeric_leaf", "atom_id_hint": "c", "statement": "c"},
    ],
}
spec = _build_numeric_spec_from_parsed(parsed_sum, state=None)
check(isinstance(spec, SumSpec), "Deserialized 'sum' -> SumSpec")
check(len(spec.children) == 3, "SumSpec has 3 children")


# ---------------------------------------------------------------------------
# Test 4: Conversion to engine nodes
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 4: _numeric_spec_to_engine_node converts to correct engine nodes")
print("=" * 70)

atoms = {}
constants = {"salary_cap": Decimal("140588000")}

# PlusSpec
plus_spec = PlusSpec(left=a, right=b)
node = _numeric_spec_to_engine_node(plus_spec, atoms, constants)
check(isinstance(node, PlusNode), "PlusSpec -> PlusNode")
check(isinstance(node.left, NumericLeaf), "PlusNode.left is NumericLeaf")
check(node.left.atom_id == "a", "PlusNode.left.atom_id correct")

# MaxSpec with arithmetic children
parsed_max_spec = _build_numeric_spec_from_parsed(parsed_max, state=None)
atoms.clear()
node = _numeric_spec_to_engine_node(parsed_max_spec, atoms, constants)
check(isinstance(node, MaxNode), "MaxSpec -> MaxNode")
check(len(node.children) == 2, "MaxNode has 2 children")
check(isinstance(node.children[0], TimesConstNode),
      "MaxNode child 0 is TimesConstNode (preserves recursion)")

# SumSpec
sum_spec = SumSpec(children=[a, b])
atoms.clear()
node = _numeric_spec_to_engine_node(sum_spec, atoms, constants)
check(isinstance(node, SumNode), "SumSpec -> SumNode")
check(len(node.children) == 2, "SumNode has 2 children")


# ---------------------------------------------------------------------------
# Test 5: End-to-end — parse JSON, build spec, convert, evaluate
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 5: End-to-end -- LLM JSON to evaluated NumericValue")
print("=" * 70)

# This is the team_salary_post_signing scenario, full pipeline:
# 1. LLM-shaped JSON for plus(pre_signing, first_year_salary)
# 2. Deserialize to PlusSpec
# 3. Convert to PlusNode
# 4. Evaluate with bound atoms
# 5. Check the result matches what a human would compute

json_dict = {
    "spec_type": "plus",
    "left": {
        "spec_type": "numeric_leaf",
        "atom_id_hint": "pre_signing_team_salary",
        "statement": "Pre-signing team salary",
    },
    "right": {
        "spec_type": "numeric_leaf",
        "atom_id_hint": "first_year_salary",
        "statement": "First-year salary of new contract",
    },
}

spec = _build_numeric_spec_from_parsed(json_dict, state=None)
atoms = {}
node = _numeric_spec_to_engine_node(spec, atoms, constants)

bundle = FactBundle(values={
    "pre_signing_team_salary": NumericValue(value=Decimal("160000000")),
    "first_year_salary": NumericValue(value=Decimal("35000000")),
})

result = node.evaluate(bundle)
check(result.value == Decimal("195000000"),
      "End-to-end: 160M + 35M = 195M evaluates correctly")

# Now wrap in a comparison: post_signing <= salary_cap should be FALSE
cap_compare = LeqNode(
    left=node,
    right=Constant(value=Decimal("140588000"), label="salary_cap"),
)
result = cap_compare.evaluate(bundle)
check(result == Kleene.FALSE,
      "End-to-end: 195M > 140.588M cap -> FALSE (catches cap violation)")


# ---------------------------------------------------------------------------
# Test 6: Validation in deserialization
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 6: Deserialization validation")
print("=" * 70)

# Missing 'left' in binary
try:
    _build_numeric_spec_from_parsed({"spec_type": "plus", "right": {}}, state=None)
    check(False, "Missing 'left' should raise")
except ValueError:
    check(True, "Missing 'left' raises ValueError")

# Variadic with <2 children
try:
    _build_numeric_spec_from_parsed({
        "spec_type": "max",
        "children": [{"spec_type": "numeric_leaf",
                      "atom_id_hint": "a", "statement": ""}],
    }, state=None)
    check(False, "Variadic with 1 child should raise")
except ValueError:
    check(True, "Variadic with 1 child raises ValueError")

# Unknown spec_type
try:
    _build_numeric_spec_from_parsed({"spec_type": "foo"}, state=None)
    check(False, "Unknown spec_type should raise")
except ValueError as e:
    msg = str(e)
    check("plus" in msg and "max" in msg,
          "Unknown spec_type error mentions new types in expected list")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)
sys.exit(0 if failed == 0 else 1)

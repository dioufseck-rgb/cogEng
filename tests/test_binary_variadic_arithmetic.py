"""
test_binary_variadic_arithmetic.py -- tests for the new arithmetic node
types added to handle Map's "won't compute across atom boundaries"
limitation: PlusNode, MinusNode, MulNode (binary) and SumNode, MaxNode,
MinNode (variadic).

Tests cover:
  - Basic evaluation with bound NumericValues
  - UNDETERMINED propagation (any UND input -> UND output)
  - Trace emission
  - Validation (variadic nodes require >= 2 children)
  - Mixed-Decimal and integer values
  - Composition (operators feeding other operators)
"""
from __future__ import annotations
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from decimal import Decimal
from rulekit.engine import FactBundle, Kleene
from rulekit.engine.typed import (
    NumericLeaf, NumericValue, Constant,
    PlusNode, MinusNode, MulNode,
    SumNode, MaxNode, MinNode,
    TimesConstNode, PlusConstNode,
    GeqNode, LeqNode,
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


def mkbundle(**vals):
    """Helper to build a FactBundle from kwargs."""
    out = {}
    for k, v in vals.items():
        if v is None:
            out[k] = NumericValue.undetermined()
        else:
            out[k] = NumericValue(value=Decimal(str(v)))
    return FactBundle(values=out)


# ---------------------------------------------------------------------------
# Test 1: PlusNode basic
# ---------------------------------------------------------------------------
print("=" * 70)
print("Test 1: PlusNode")
print("=" * 70)
a = NumericLeaf(atom_id="a")
b = NumericLeaf(atom_id="b")
plus = PlusNode(left=a, right=b)

bundle = mkbundle(a=100, b=25)
r = plus.evaluate(bundle)
check(r.value == Decimal("125"), "PlusNode(100, 25) = 125")

bundle = mkbundle(a=Decimal("160000000"), b=Decimal("35000000"))
r = plus.evaluate(bundle)
check(r.value == Decimal("195000000"),
      "PlusNode(160M, 35M) = 195M (the case-specific scenario)")


# ---------------------------------------------------------------------------
# Test 2: PlusNode UNDETERMINED propagation
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 2: UNDETERMINED propagation in binary nodes")
print("=" * 70)

bundle = mkbundle(a=100, b=None)
r = plus.evaluate(bundle)
check(r.is_undetermined, "PlusNode(100, UND) -> UND")

bundle = mkbundle(a=None, b=25)
r = plus.evaluate(bundle)
check(r.is_undetermined, "PlusNode(UND, 25) -> UND")

bundle = mkbundle(a=None, b=None)
r = plus.evaluate(bundle)
check(r.is_undetermined, "PlusNode(UND, UND) -> UND")


# ---------------------------------------------------------------------------
# Test 3: MinusNode
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 3: MinusNode")
print("=" * 70)
minus = MinusNode(left=a, right=b)
bundle = mkbundle(a=100, b=25)
r = minus.evaluate(bundle)
check(r.value == Decimal("75"), "MinusNode(100, 25) = 75")

bundle = mkbundle(a=25, b=100)
r = minus.evaluate(bundle)
check(r.value == Decimal("-75"), "MinusNode(25, 100) = -75")


# ---------------------------------------------------------------------------
# Test 4: MulNode
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 4: MulNode")
print("=" * 70)
mul = MulNode(left=a, right=b)
bundle = mkbundle(a=100, b=25)
r = mul.evaluate(bundle)
check(r.value == Decimal("2500"), "MulNode(100, 25) = 2500")

bundle = mkbundle(a=Decimal("0.05"), b=Decimal("140000000"))
r = mul.evaluate(bundle)
check(r.value == Decimal("7000000.00"),
      "MulNode(0.05, 140M) = 7M (e.g., 5% of cap)")


# ---------------------------------------------------------------------------
# Test 5: SumNode
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 5: SumNode")
print("=" * 70)
c = NumericLeaf(atom_id="c")
d = NumericLeaf(atom_id="d")

sum2 = SumNode(children=[a, b])
bundle = mkbundle(a=10, b=20)
r = sum2.evaluate(bundle)
check(r.value == Decimal("30"), "SumNode([10, 20]) = 30")

sum4 = SumNode(children=[a, b, c, d])
bundle = mkbundle(a=10, b=20, c=30, d=40)
r = sum4.evaluate(bundle)
check(r.value == Decimal("100"), "SumNode([10, 20, 30, 40]) = 100")

bundle = mkbundle(a=10, b=20, c=None, d=40)
r = sum4.evaluate(bundle)
check(r.is_undetermined,
      "SumNode([10, 20, UND, 40]) -> UND (any UND propagates)")

# Validation
try:
    SumNode(children=[a])
    failed_validation = False
except ValueError:
    failed_validation = True
check(failed_validation, "SumNode([a]) with only 1 child raises ValueError")


# ---------------------------------------------------------------------------
# Test 6: MaxNode
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 6: MaxNode (conservative -- any UND -> UND)")
print("=" * 70)
max2 = MaxNode(children=[a, b])

bundle = mkbundle(a=100, b=25)
r = max2.evaluate(bundle)
check(r.value == Decimal("100"), "MaxNode([100, 25]) = 100")

bundle = mkbundle(a=25, b=100)
r = max2.evaluate(bundle)
check(r.value == Decimal("100"), "MaxNode([25, 100]) = 100 (order independent)")

# Critically: UND propagates even if a stated value would clearly dominate
bundle = mkbundle(a=Decimal("1000000000"), b=None)
r = max2.evaluate(bundle)
check(r.is_undetermined,
      "MaxNode([1B, UND]) -> UND (can't conclude max if any input unknown)")

# Variadic, NBA-style "greater of 35% of cap or 105% of prior salary"
# Computed upstream as TimesConstNode results
cap_pct = TimesConstNode(child=NumericLeaf(atom_id="cap"),
                          constant=Decimal("0.35"))
prior_pct = TimesConstNode(child=NumericLeaf(atom_id="prior"),
                            constant=Decimal("1.05"))
max_ceiling = MaxNode(children=[cap_pct, prior_pct])

bundle = mkbundle(cap=140000000, prior=30000000)
r = max_ceiling.evaluate(bundle)
# 35% of 140M = 49M; 105% of 30M = 31.5M; max = 49M
check(r.value == Decimal("49000000.00"),
      "MaxNode([35% x 140M cap, 105% x 30M prior]) = 49M")


# ---------------------------------------------------------------------------
# Test 7: MinNode
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 7: MinNode")
print("=" * 70)
min2 = MinNode(children=[a, b])

bundle = mkbundle(a=100, b=25)
r = min2.evaluate(bundle)
check(r.value == Decimal("25"), "MinNode([100, 25]) = 25")

bundle = mkbundle(a=25, b=100)
r = min2.evaluate(bundle)
check(r.value == Decimal("25"), "MinNode([25, 100]) = 25 (order independent)")


# ---------------------------------------------------------------------------
# Test 8: Composition -- operators feeding operators
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 8: Composition (the NBA team_salary_post_signing scenario)")
print("=" * 70)
# team_salary_post_signing = pre_signing_team_salary +
#                            (first_year_salary + first_year_unlikely_bonuses)
pre_signing = NumericLeaf(atom_id="pre")
first_salary = NumericLeaf(atom_id="salary")
first_bonus = NumericLeaf(atom_id="bonus")

new_signing = PlusNode(left=first_salary, right=first_bonus)
post_signing = PlusNode(left=pre_signing, right=new_signing)

bundle = mkbundle(pre=160000000, salary=35000000, bonus=0)
r = post_signing.evaluate(bundle)
check(r.value == Decimal("195000000"),
      "Composed: post-signing = 160M + (35M + 0) = 195M")

# Now with a cap comparison
salary_cap = NumericLeaf(atom_id="cap")
cap_check = LeqNode(left=post_signing, right=salary_cap)

bundle = mkbundle(pre=160000000, salary=35000000, bonus=0, cap=140588000)
r = cap_check.evaluate(bundle)
check(r == Kleene.FALSE,
      "Composed: 195M <= 140.588M cap -> FALSE (correctly flags violation)")

bundle = mkbundle(pre=80000000, salary=35000000, bonus=0, cap=140588000)
r = cap_check.evaluate(bundle)
check(r == Kleene.TRUE,
      "Composed: 80M + 35M = 115M <= 140.588M cap -> TRUE (no violation)")

# UND in inputs propagates through composition
bundle = mkbundle(pre=160000000, salary=None, bonus=0, cap=140588000)
r = cap_check.evaluate(bundle)
check(r == Kleene.UNDETERMINED,
      "Composed UND propagation: any UND input -> cap_check is UND")


# ---------------------------------------------------------------------------
# Test 9: Trace emission
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("Test 9: Trace emission")
print("=" * 70)
bundle = mkbundle(a=100, b=25)
trace = []
plus.evaluate(bundle, trace)
entry = trace[0]
check(entry["type"] == "plus", "PlusNode trace type = 'plus'")
check(entry["left_value"] == "100", "left_value captured")
check(entry["right_value"] == "25", "right_value captured")
check(entry["result"] == "125", "result captured")

trace = []
max_ceiling.evaluate(
    mkbundle(cap=140000000, prior=30000000), trace)
entry = trace[0]
check(entry["type"] == "max", "MaxNode trace type = 'max'")
check(len(entry["child_values"]) == 2, "child_values has 2 entries")
check(entry["result"] == "49000000.00", "MaxNode result captured")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)
sys.exit(0 if failed == 0 else 1)

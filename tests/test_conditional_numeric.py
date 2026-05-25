"""
test_conditional_numeric.py -- tests for ConditionalNumericNode.

ConditionalNumericNode is the engine's representation of bracketed
selection in policy adjudication: IF condition THEN if_true_value
ELSE if_false_value.

Discovered necessary by the Phase 3 composition probe on Higher Max
Criteria (YOS bracket selection): three independent LLM samples
consistently produced the conditional-numeric pattern.

Tests cover:
  - Basic selection when condition is TRUE
  - Basic selection when condition is FALSE
  - UND condition -> UND result (UND-conservative semantics)
  - Composition (condition itself is a comparison; branches are arithmetic)
  - Trace emission with branch annotation
  - Nested conditionals (modeling 3+ brackets)
  - Branch evaluation only happens for selected branch (audit honesty)
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
    ConditionalNumericNode,
    LtNode, GeqNode, LeqNode,
    PlusNode, TimesConstNode, MaxNode,
)
from rulekit.engine.boolean import Leaf


passed = 0
failed = 0


def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


def mkbundle(**values):
    """Build a FactBundle from atom_id -> value mappings.
    Numeric values become NumericValue; Booleans/Kleene become Kleene."""
    out = {}
    for k, v in values.items():
        if isinstance(v, NumericValue):
            out[k] = v
        elif isinstance(v, Kleene):
            out[k] = v
        elif isinstance(v, bool):
            out[k] = Kleene.TRUE if v else Kleene.FALSE
        elif isinstance(v, (int, float, Decimal)):
            out[k] = NumericValue(value=Decimal(str(v)))
        elif v is None:
            out[k] = NumericValue.undetermined()
        else:
            out[k] = v
    return FactBundle(values=out)


# ---------------------------------------------------------------------------
# Basic selection: condition TRUE -> select if_true branch
# ---------------------------------------------------------------------------
print("--- Basic TRUE selection ---")

node = ConditionalNumericNode(
    condition=Leaf(atom_id="cond"),
    if_true=NumericLeaf(atom_id="a"),
    if_false=NumericLeaf(atom_id="b"),
)
r = node.evaluate(mkbundle(cond=Kleene.TRUE, a=100, b=200))
check(r.value == Decimal("100"), "cond=T -> if_true value (100)")

r = node.evaluate(mkbundle(cond=Kleene.FALSE, a=100, b=200))
check(r.value == Decimal("200"), "cond=F -> if_false value (200)")


# ---------------------------------------------------------------------------
# UND condition -> UND result
# ---------------------------------------------------------------------------
print("--- UND condition propagation ---")

r = node.evaluate(mkbundle(cond=Kleene.UNDETERMINED, a=100, b=200))
check(r.is_undetermined, "cond=UND -> UND (both branches known)")

r = node.evaluate(mkbundle(cond=Kleene.UNDETERMINED, a=100, b=None))
check(r.is_undetermined, "cond=UND with UND branch -> UND")


# ---------------------------------------------------------------------------
# UND branch behavior: only the selected branch's UND matters
# ---------------------------------------------------------------------------
print("--- Selective branch UND ---")

# cond=TRUE selects if_true; if_false=UND should not contaminate
r = node.evaluate(mkbundle(cond=Kleene.TRUE, a=100, b=None))
check(r.value == Decimal("100"),
      "cond=T with if_false=UND -> if_true value (selective)")

# cond=FALSE selects if_false; if_true=UND should not contaminate
r = node.evaluate(mkbundle(cond=Kleene.FALSE, a=None, b=200))
check(r.value == Decimal("200"),
      "cond=F with if_true=UND -> if_false value (selective)")

# But the selected branch being UND -> UND
r = node.evaluate(mkbundle(cond=Kleene.TRUE, a=None, b=200))
check(r.is_undetermined,
      "cond=T but if_true=UND -> UND (selected branch unbound)")

r = node.evaluate(mkbundle(cond=Kleene.FALSE, a=100, b=None))
check(r.is_undetermined,
      "cond=F but if_false=UND -> UND (selected branch unbound)")


# ---------------------------------------------------------------------------
# Comparison-based condition: condition is itself a numeric comparison
# ---------------------------------------------------------------------------
print("--- Comparison-based condition ---")

# Model: IF yos < 7 THEN 25%*cap ELSE 30%*cap (simplified YOS bracket)
yos_lt_7 = LtNode(
    left=NumericLeaf(atom_id="yos"),
    right=Constant(label="seven", value=Decimal("7")),
)
twenty_five_pct_cap = TimesConstNode(
    child=Constant(label="salary_cap", value=Decimal("140000000")),
    constant=Decimal("0.25"),
)
thirty_pct_cap = TimesConstNode(
    child=Constant(label="salary_cap", value=Decimal("140000000")),
    constant=Decimal("0.30"),
)
bracket = ConditionalNumericNode(
    condition=yos_lt_7,
    if_true=twenty_five_pct_cap,
    if_false=thirty_pct_cap,
)

r = bracket.evaluate(mkbundle(yos=5))
check(r.value == Decimal("35000000.00"), "yos=5 (<7) -> 25%*cap = 35M")

r = bracket.evaluate(mkbundle(yos=8))
check(r.value == Decimal("42000000.00"), "yos=8 (>=7) -> 30%*cap = 42M")

r = bracket.evaluate(mkbundle(yos=None))
check(r.is_undetermined, "yos=UND -> comparison=UND -> bracket=UND")


# ---------------------------------------------------------------------------
# Nested conditionals: model 3 YOS brackets
# ---------------------------------------------------------------------------
print("--- Nested conditionals (3 YOS brackets) ---")

# IF yos < 7 THEN 25%*cap
# ELSE IF yos < 10 THEN 30%*cap
# ELSE 35%*cap
yos_lt_10 = LtNode(
    left=NumericLeaf(atom_id="yos"),
    right=Constant(label="ten", value=Decimal("10")),
)
thirty_five_pct_cap = TimesConstNode(
    child=Constant(label="salary_cap", value=Decimal("140000000")),
    constant=Decimal("0.35"),
)

mid_or_top = ConditionalNumericNode(
    condition=yos_lt_10,
    if_true=thirty_pct_cap,
    if_false=thirty_five_pct_cap,
)
all_brackets = ConditionalNumericNode(
    condition=yos_lt_7,
    if_true=twenty_five_pct_cap,
    if_false=mid_or_top,
)

r = all_brackets.evaluate(mkbundle(yos=3))
check(r.value == Decimal("35000000.00"), "yos=3 -> bottom bracket (25%)")

r = all_brackets.evaluate(mkbundle(yos=8))
check(r.value == Decimal("42000000.00"), "yos=8 -> mid bracket (30%)")

r = all_brackets.evaluate(mkbundle(yos=12))
check(r.value == Decimal("49000000.00"), "yos=12 -> top bracket (35%)")


# ---------------------------------------------------------------------------
# Composition with MaxNode: greater-of pattern from Higher Max Criteria
# ---------------------------------------------------------------------------
print("--- Composition with MaxNode (greater-of pattern) ---")

# max(bracket_pct * cap, 105% * prior_salary) -- the classic NBA max-salary
# formula structure that combines conditional numeric with greater-of.
prior_salary_boost = TimesConstNode(
    child=NumericLeaf(atom_id="prior_salary"),
    constant=Decimal("1.05"),
)
max_salary = MaxNode(
    children=[all_brackets, prior_salary_boost],
)

# Player with 5 YOS, prior salary of $40M:
#   bottom bracket = 25% * 140M = 35M
#   105% * 40M = 42M
#   max = 42M (prior salary wins)
r = max_salary.evaluate(mkbundle(yos=5, prior_salary=40000000))
check(r.value == Decimal("42000000.00"),
      "yos=5, prior=40M -> max(35M, 42M) = 42M")

# Player with 5 YOS, prior salary of $20M:
#   bottom bracket = 35M
#   105% * 20M = 21M
#   max = 35M (cap-bracket wins)
r = max_salary.evaluate(mkbundle(yos=5, prior_salary=20000000))
check(r.value == Decimal("35000000.00"),
      "yos=5, prior=20M -> max(35M, 21M) = 35M")


# ---------------------------------------------------------------------------
# Trace emission
# ---------------------------------------------------------------------------
print("--- Trace emission ---")

trace = []
r = bracket.evaluate(mkbundle(yos=5), trace)
check(len(trace) == 1, "trace has 1 root entry")
entry = trace[0]
check(entry["type"] == "conditional_numeric", "trace type = 'conditional_numeric'")
check(entry["condition_value"] == "true", "condition_value recorded as 'true'")
check(entry["evaluated_branch"] == "if_true", "evaluated_branch = 'if_true'")
check("if_false_trace" not in entry,
      "if_false not in trace (only evaluated branch is recorded)")
check("condition_trace" in entry, "condition_trace included")
check(entry["result"] == "35000000.00", "result captured in trace")


trace = []
r = bracket.evaluate(mkbundle(yos=8), trace)
entry = trace[0]
check(entry["evaluated_branch"] == "if_false", "yos=8 -> evaluated if_false branch")
check("if_true_trace" not in entry, "if_true_trace not included when not evaluated")
check("if_false_trace" in entry, "if_false_trace included when evaluated")


trace = []
r = bracket.evaluate(mkbundle(yos=None), trace)
entry = trace[0]
check(entry["evaluated_branch"] == "none (condition undetermined)",
      "UND condition -> no branch evaluated in trace")
check(entry["result"] == "undetermined", "UND result in trace")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)
sys.exit(0 if failed == 0 else 1)

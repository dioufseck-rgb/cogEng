"""
RuleKit typed-engine extension — numeric atoms, constant arithmetic, and
comparison operators that bridge numerics to Kleene-Boolean values.

This module ADDS to the existing engine without modifying it. Nodes defined
here can be composed into DAGs alongside the existing Boolean nodes
(AndNode, OrNode, NotNode, AtLeastNode). The composition story is:

- Numeric atoms (NumericLeaf) and constants (Constant) supply numeric values.
- Arithmetic nodes (TimesConst, PlusConst, MinusConst, ConstMinus,
  DivByConst, ConstDivBy) transform numerics into numerics. Each takes one
  Map-bound numeric input and one Build-time constant.
- Comparison nodes (Eq, Lt, Leq, Gt, Geq) take two numerics and produce a
  Kleene-Boolean value — the bridge from numeric quantities to the
  existing Boolean composition layer above.

Design commitments:

1. UNDETERMINED propagates faithfully. Any UNDETERMINED input to an
   arithmetic node yields an UNDETERMINED numeric output. Any UNDETERMINED
   input to a comparison node yields a Kleene.UNDETERMINED Boolean output.
   No clever vacuous-truth shortcuts.

2. All numeric values use Decimal, not float. Financial reasoning in
   floats is a known footgun; we use decimal precision throughout.
   Constants declared at Build time are coerced to Decimal at construction.

3. Constants come from policy text and are validated at Build. They are
   not bound by Map and never carry UNDETERMINED.

4. The engine handles only fixed-shape arithmetic where one operand is a
   Build-time constant. General arithmetic over two Map-bound numerics
   (sum-of-three-salaries, percentage-of-one-atom-relative-to-another) is
   Map's responsibility — Map binds the result as a single derived
   numeric atom. The line is principled: the engine does the
   inequality-bridge work and the policy-declared transformations; Map
   does the per-case computations.

The existing engine.py is unchanged. FactBundle is extended via duck
typing: it can now hold either Kleene values (for Boolean atoms) or
NumericValue values (for numeric atoms). Existing Boolean code reads
Kleene values exactly as before; typed-engine code reads NumericValue
values from the same bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional, Union

from rulekit.engine.boolean import (
    Kleene,
    Provenance,
    FactBundle,
)


# ---------------------------------------------------------------------------
# Numeric value type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumericValue:
    """
    A numeric value that may be UNDETERMINED.

    Determinate values carry a Decimal in `value`. UNDETERMINED values
    have `value=None` and are constructed via `NumericValue.undetermined()`.

    The class is immutable (frozen) so the engine can pass values through
    arithmetic without worrying about aliasing.
    """

    value: Optional[Decimal]

    @classmethod
    def of(cls, v) -> "NumericValue":
        """Construct a determinate NumericValue from a number-like input."""
        if isinstance(v, NumericValue):
            return v
        if v is None:
            return cls.undetermined()
        if isinstance(v, Decimal):
            return cls(value=v)
        try:
            return cls(value=Decimal(str(v)))
        except (InvalidOperation, TypeError, ValueError) as e:
            raise ValueError(f"Cannot construct NumericValue from {v!r}: {e}")

    @classmethod
    def undetermined(cls) -> "NumericValue":
        return cls(value=None)

    @property
    def is_undetermined(self) -> bool:
        return self.value is None

    def __str__(self) -> str:
        if self.is_undetermined:
            return "undetermined"
        return str(self.value)


# ---------------------------------------------------------------------------
# Atom type extension (lives here so we don't modify schema.py yet)
# ---------------------------------------------------------------------------


class AtomType(Enum):
    BOOLEAN = "boolean"
    NUMERIC = "numeric"


# ---------------------------------------------------------------------------
# Helpers for FactBundle access with type discipline
# ---------------------------------------------------------------------------


def get_numeric(bundle: FactBundle, atom_id: str) -> NumericValue:
    """
    Read a numeric value from the bundle.

    If the atom is missing, returns UNDETERMINED. If a Kleene value was
    stored under this atom_id (i.e., Map produced the wrong type),
    raises TypeError — that's a wiring bug we want to surface, not
    silently coerce.
    """
    raw = bundle.values.get(atom_id)
    if raw is None:
        return NumericValue.undetermined()
    if isinstance(raw, NumericValue):
        return raw
    if isinstance(raw, Kleene):
        raise TypeError(
            f"Atom {atom_id!r} is bound to Kleene value {raw} but a "
            f"NumericValue was expected. Check the atom's declared type."
        )
    # Tolerate raw Decimal/int/str — coerce to NumericValue.
    return NumericValue.of(raw)


# ---------------------------------------------------------------------------
# Leaf nodes: NumericLeaf and Constant
# ---------------------------------------------------------------------------


@dataclass
class NumericLeaf:
    """A leaf that reads a Map-bound numeric value from the bundle."""
    atom_id: str

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        value = get_numeric(bundle, self.atom_id)
        if trace is not None:
            trace.append({
                "type": "numeric_leaf",
                "atom_id": self.atom_id,
                "value": str(value),
                "evidence": bundle.evidence_for(self.atom_id),
            })
        return value


@dataclass
class Constant:
    """A Build-time constant. Never UNDETERMINED."""
    value: Decimal
    label: str = ""  # optional human-readable label, e.g., "9.12% of cap"

    def __post_init__(self):
        # Coerce to Decimal once at construction; downstream code can
        # rely on self.value being a Decimal.
        if not isinstance(self.value, Decimal):
            self.value = Decimal(str(self.value))

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        result = NumericValue(value=self.value)
        if trace is not None:
            trace.append({
                "type": "constant",
                "value": str(self.value),
                "label": self.label,
            })
        return result


# ---------------------------------------------------------------------------
# Arithmetic nodes
#
# Each takes one Map-bound numeric child and one Build-time constant.
# UNDETERMINED in -> UNDETERMINED out. No exceptions for vacuous cases.
# Division by zero is a Build-time error: the constant operand of
# DivByConst must be nonzero, and the runtime operand of ConstDivBy
# yields UNDETERMINED if it is zero (the policy author can't predict
# whether the case will produce a zero denominator).
# ---------------------------------------------------------------------------


@dataclass
class TimesConstNode:
    """child × constant"""
    child: Union[NumericLeaf, Constant, "TimesConstNode", "PlusConstNode",
                 "MinusConstNode", "ConstMinusNode", "DivByConstNode",
                 "ConstDivByNode"]
    constant: Decimal
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def __post_init__(self):
        if not isinstance(self.constant, Decimal):
            self.constant = Decimal(str(self.constant))

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        local_trace = [] if trace is not None else None
        child_value = self.child.evaluate(bundle, local_trace)
        if child_value.is_undetermined:
            result = NumericValue.undetermined()
        else:
            result = NumericValue(value=child_value.value * self.constant)
        if trace is not None:
            trace.append(_arith_trace_entry(
                "times_const", self, child_value, result, local_trace,
                extra={"constant": str(self.constant)}
            ))
        return result


@dataclass
class PlusConstNode:
    """child + constant"""
    child: Union[NumericLeaf, Constant, TimesConstNode, "PlusConstNode",
                 "MinusConstNode", "ConstMinusNode", "DivByConstNode",
                 "ConstDivByNode"]
    constant: Decimal
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def __post_init__(self):
        if not isinstance(self.constant, Decimal):
            self.constant = Decimal(str(self.constant))

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        local_trace = [] if trace is not None else None
        child_value = self.child.evaluate(bundle, local_trace)
        if child_value.is_undetermined:
            result = NumericValue.undetermined()
        else:
            result = NumericValue(value=child_value.value + self.constant)
        if trace is not None:
            trace.append(_arith_trace_entry(
                "plus_const", self, child_value, result, local_trace,
                extra={"constant": str(self.constant)}
            ))
        return result


@dataclass
class MinusConstNode:
    """child − constant"""
    child: Union[NumericLeaf, Constant, TimesConstNode, PlusConstNode,
                 "MinusConstNode", "ConstMinusNode", "DivByConstNode",
                 "ConstDivByNode"]
    constant: Decimal
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def __post_init__(self):
        if not isinstance(self.constant, Decimal):
            self.constant = Decimal(str(self.constant))

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        local_trace = [] if trace is not None else None
        child_value = self.child.evaluate(bundle, local_trace)
        if child_value.is_undetermined:
            result = NumericValue.undetermined()
        else:
            result = NumericValue(value=child_value.value - self.constant)
        if trace is not None:
            trace.append(_arith_trace_entry(
                "minus_const", self, child_value, result, local_trace,
                extra={"constant": str(self.constant)}
            ))
        return result


@dataclass
class ConstMinusNode:
    """constant − child"""
    constant: Decimal
    child: Union[NumericLeaf, Constant, TimesConstNode, PlusConstNode,
                 MinusConstNode, "ConstMinusNode", "DivByConstNode",
                 "ConstDivByNode"]
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def __post_init__(self):
        if not isinstance(self.constant, Decimal):
            self.constant = Decimal(str(self.constant))

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        local_trace = [] if trace is not None else None
        child_value = self.child.evaluate(bundle, local_trace)
        if child_value.is_undetermined:
            result = NumericValue.undetermined()
        else:
            result = NumericValue(value=self.constant - child_value.value)
        if trace is not None:
            trace.append(_arith_trace_entry(
                "const_minus", self, child_value, result, local_trace,
                extra={"constant": str(self.constant)}
            ))
        return result


@dataclass
class DivByConstNode:
    """child / constant"""
    child: Union[NumericLeaf, Constant, TimesConstNode, PlusConstNode,
                 MinusConstNode, ConstMinusNode, "DivByConstNode",
                 "ConstDivByNode"]
    constant: Decimal
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def __post_init__(self):
        if not isinstance(self.constant, Decimal):
            self.constant = Decimal(str(self.constant))
        if self.constant == 0:
            raise ValueError(
                "DivByConstNode constant must be nonzero. Policy text "
                "with a zero divisor is a Build-stage error."
            )

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        local_trace = [] if trace is not None else None
        child_value = self.child.evaluate(bundle, local_trace)
        if child_value.is_undetermined:
            result = NumericValue.undetermined()
        else:
            result = NumericValue(value=child_value.value / self.constant)
        if trace is not None:
            trace.append(_arith_trace_entry(
                "div_by_const", self, child_value, result, local_trace,
                extra={"constant": str(self.constant)}
            ))
        return result


@dataclass
class ConstDivByNode:
    """constant / child — yields UNDETERMINED if child is zero (avoids division by zero)."""
    constant: Decimal
    child: Union[NumericLeaf, Constant, TimesConstNode, PlusConstNode,
                 MinusConstNode, ConstMinusNode, DivByConstNode,
                 "ConstDivByNode"]
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def __post_init__(self):
        if not isinstance(self.constant, Decimal):
            self.constant = Decimal(str(self.constant))

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        local_trace = [] if trace is not None else None
        child_value = self.child.evaluate(bundle, local_trace)
        if child_value.is_undetermined:
            result = NumericValue.undetermined()
        elif child_value.value == 0:
            # Avoid division by zero. Policy reasoning treats this as
            # "we cannot compute the ratio because the denominator is
            # zero" — surface as UNDETERMINED.
            result = NumericValue.undetermined()
        else:
            result = NumericValue(value=self.constant / child_value.value)
        if trace is not None:
            trace.append(_arith_trace_entry(
                "const_div_by", self, child_value, result, local_trace,
                extra={"constant": str(self.constant)}
            ))
        return result


# ---------------------------------------------------------------------------
# Binary and variadic arithmetic nodes — combine MULTIPLE atom-valued
# operands. Distinct from the unary-vs-constant operators above, these
# compose two-or-more bound atoms (or sub-expressions) into a single
# numeric value.
#
# UNDETERMINED semantics:
#   - Binary: UNDETERMINED in any operand → UNDETERMINED result
#   - SumNode/MinusNode: UNDETERMINED in any operand → UNDETERMINED
#   - MaxNode/MinNode: UNDETERMINED in any operand → UNDETERMINED
#     (we cannot prove a value is the max if some inputs are unknown)
#
# These exist because Map cannot reliably compute values across atom
# boundaries — the LLM resists multi-fact arithmetic even when prompted.
# By moving derived quantities (sums, maxes, post-event totals) into
# engine arithmetic, we keep Map a pure extractor of stated values.
# ---------------------------------------------------------------------------


# Forward-declared type alias used by the new operators' child fields.
# Includes both the unary-vs-const operators (above) and the new
# binary/variadic operators (below) via string forward references.
NumericExpr = Union[
    "NumericLeaf", "Constant",
    "TimesConstNode", "PlusConstNode", "MinusConstNode", "ConstMinusNode",
    "DivByConstNode", "ConstDivByNode",
    "PlusNode", "MinusNode", "MulNode",
    "SumNode", "MaxNode", "MinNode",
]


@dataclass
class PlusNode:
    """left + right (binary; both operands are NumericExpressions)."""
    left: NumericExpr
    right: NumericExpr
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        left_trace = [] if trace is not None else None
        right_trace = [] if trace is not None else None
        l = self.left.evaluate(bundle, left_trace)
        r = self.right.evaluate(bundle, right_trace)
        if l.is_undetermined or r.is_undetermined:
            result = NumericValue.undetermined()
        else:
            result = NumericValue(value=l.value + r.value)
        if trace is not None:
            trace.append(_binary_trace_entry(
                "plus", self, l, r, result, left_trace, right_trace))
        return result


@dataclass
class MinusNode:
    """left - right (binary)."""
    left: NumericExpr
    right: NumericExpr
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        left_trace = [] if trace is not None else None
        right_trace = [] if trace is not None else None
        l = self.left.evaluate(bundle, left_trace)
        r = self.right.evaluate(bundle, right_trace)
        if l.is_undetermined or r.is_undetermined:
            result = NumericValue.undetermined()
        else:
            result = NumericValue(value=l.value - r.value)
        if trace is not None:
            trace.append(_binary_trace_entry(
                "minus", self, l, r, result, left_trace, right_trace))
        return result


@dataclass
class MulNode:
    """left * right (binary)."""
    left: NumericExpr
    right: NumericExpr
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        left_trace = [] if trace is not None else None
        right_trace = [] if trace is not None else None
        l = self.left.evaluate(bundle, left_trace)
        r = self.right.evaluate(bundle, right_trace)
        if l.is_undetermined or r.is_undetermined:
            result = NumericValue.undetermined()
        else:
            result = NumericValue(value=l.value * r.value)
        if trace is not None:
            trace.append(_binary_trace_entry(
                "mul", self, l, r, result, left_trace, right_trace))
        return result


@dataclass
class SumNode:
    """Variadic sum of N ≥ 2 children. Any UNDETERMINED → UNDETERMINED."""
    children: list
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def __post_init__(self):
        if len(self.children) < 2:
            raise ValueError(
                f"SumNode requires ≥ 2 children, got {len(self.children)}. "
                f"For a single child, the operand IS the sum."
            )

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        child_values = []
        child_traces = []
        for c in self.children:
            ct = [] if trace is not None else None
            cv = c.evaluate(bundle, ct)
            child_values.append(cv)
            child_traces.append(ct)
        if any(cv.is_undetermined for cv in child_values):
            result = NumericValue.undetermined()
        else:
            total = child_values[0].value
            for cv in child_values[1:]:
                total = total + cv.value
            result = NumericValue(value=total)
        if trace is not None:
            trace.append(_variadic_trace_entry(
                "sum", self, child_values, result, child_traces))
        return result


@dataclass
class MaxNode:
    """Variadic max of N ≥ 2 children. Any UNDETERMINED → UNDETERMINED.

    Rationale: even if one stated value is high, we cannot conclude it's
    the maximum if other inputs are unknown — an unknown value might be
    higher. This conservative semantics matches the architectural
    principle of not guessing.
    """
    children: list
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def __post_init__(self):
        if len(self.children) < 2:
            raise ValueError(
                f"MaxNode requires ≥ 2 children, got {len(self.children)}."
            )

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        child_values = []
        child_traces = []
        for c in self.children:
            ct = [] if trace is not None else None
            cv = c.evaluate(bundle, ct)
            child_values.append(cv)
            child_traces.append(ct)
        if any(cv.is_undetermined for cv in child_values):
            result = NumericValue.undetermined()
        else:
            max_val = max(cv.value for cv in child_values)
            result = NumericValue(value=max_val)
        if trace is not None:
            trace.append(_variadic_trace_entry(
                "max", self, child_values, result, child_traces))
        return result


@dataclass
class MinNode:
    """Variadic min of N ≥ 2 children. Any UNDETERMINED → UNDETERMINED."""
    children: list
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL

    def __post_init__(self):
        if len(self.children) < 2:
            raise ValueError(
                f"MinNode requires ≥ 2 children, got {len(self.children)}."
            )

    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> NumericValue:
        child_values = []
        child_traces = []
        for c in self.children:
            ct = [] if trace is not None else None
            cv = c.evaluate(bundle, ct)
            child_values.append(cv)
            child_traces.append(ct)
        if any(cv.is_undetermined for cv in child_values):
            result = NumericValue.undetermined()
        else:
            min_val = min(cv.value for cv in child_values)
            result = NumericValue(value=min_val)
        if trace is not None:
            trace.append(_variadic_trace_entry(
                "min", self, child_values, result, child_traces))
        return result


def _binary_trace_entry(node_kind, node, left_value, right_value, result,
                        left_trace, right_trace):
    return {
        "type": node_kind,
        "surface_label": getattr(node, "surface_label", ""),
        "provenance": node.provenance.value,
        "left_value": str(left_value),
        "right_value": str(right_value),
        "result": str(result),
        "left_trace": left_trace,
        "right_trace": right_trace,
    }


def _variadic_trace_entry(node_kind, node, child_values, result, child_traces):
    return {
        "type": node_kind,
        "surface_label": getattr(node, "surface_label", ""),
        "provenance": node.provenance.value,
        "child_values": [str(cv) for cv in child_values],
        "result": str(result),
        "children_trace": child_traces,
    }


# ---------------------------------------------------------------------------
# Comparison nodes — the bridge from numeric to Kleene-Boolean
#
# Take two numeric children, produce a Kleene value. Any UNDETERMINED
# input -> UNDETERMINED output. No clever vacuous-truth handling.
# ---------------------------------------------------------------------------


def _compare(left: NumericValue, right: NumericValue, op: str) -> Kleene:
    """Common logic for binary comparison: UNDETERMINED dominates."""
    if left.is_undetermined or right.is_undetermined:
        return Kleene.UNDETERMINED
    l, r = left.value, right.value
    if op == "eq":
        return Kleene.TRUE if l == r else Kleene.FALSE
    if op == "lt":
        return Kleene.TRUE if l < r else Kleene.FALSE
    if op == "leq":
        return Kleene.TRUE if l <= r else Kleene.FALSE
    if op == "gt":
        return Kleene.TRUE if l > r else Kleene.FALSE
    if op == "geq":
        return Kleene.TRUE if l >= r else Kleene.FALSE
    raise ValueError(f"Unknown comparison op: {op!r}")


@dataclass
class _CompareNodeBase:
    left: NumericExpr
    right: NumericExpr
    surface_label: str = ""
    source_span: str = ""
    provenance: Provenance = Provenance.STRUCTURAL


@dataclass
class EqNode(_CompareNodeBase):
    """left = right"""
    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> Kleene:
        return _evaluate_compare(self, "eq", bundle, trace)


@dataclass
class LtNode(_CompareNodeBase):
    """left < right (strict)"""
    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> Kleene:
        return _evaluate_compare(self, "lt", bundle, trace)


@dataclass
class LeqNode(_CompareNodeBase):
    """left ≤ right"""
    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> Kleene:
        return _evaluate_compare(self, "leq", bundle, trace)


@dataclass
class GtNode(_CompareNodeBase):
    """left > right (strict)"""
    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> Kleene:
        return _evaluate_compare(self, "gt", bundle, trace)


@dataclass
class GeqNode(_CompareNodeBase):
    """left ≥ right"""
    def evaluate(self, bundle: FactBundle, trace: Optional[list] = None) -> Kleene:
        return _evaluate_compare(self, "geq", bundle, trace)


def _evaluate_compare(node, op_name: str, bundle: FactBundle,
                      trace: Optional[list]) -> Kleene:
    left_trace = [] if trace is not None else None
    right_trace = [] if trace is not None else None
    left_value = node.left.evaluate(bundle, left_trace)
    right_value = node.right.evaluate(bundle, right_trace)
    result = _compare(left_value, right_value, op_name)
    if trace is not None:
        trace.append({
            "type": f"compare_{op_name}",
            "surface_label": node.surface_label,
            "provenance": node.provenance.value,
            "left_value": str(left_value),
            "right_value": str(right_value),
            "result": str(result),
            "left_trace": left_trace,
            "right_trace": right_trace,
        })
    return result


# ---------------------------------------------------------------------------
# Trace formatting
# ---------------------------------------------------------------------------


def _arith_trace_entry(node_kind, node, child_value, result, local_trace,
                       extra=None):
    entry = {
        "type": node_kind,
        "surface_label": getattr(node, "surface_label", ""),
        "provenance": node.provenance.value,
        "child_value": str(child_value),
        "result": str(result),
        "child_trace": local_trace,
    }
    if extra:
        entry.update(extra)
    return entry


def format_typed_trace(trace: list, indent: int = 0) -> str:
    """
    Format a trace that may include both typed and Boolean nodes.

    For Boolean-only traces, use engine.format_trace. For mixed traces
    (typed-arithmetic + Boolean composition), use this. It handles all
    node types defined here PLUS the Boolean types from engine.py.
    """
    out_lines = []
    prefix = "  " * indent
    for entry in trace:
        t = entry["type"]
        if t == "numeric_leaf":
            ev = f" [evidence: {entry['evidence']}]" if entry.get("evidence") else ""
            out_lines.append(
                f"{prefix}NUM_LEAF {entry['atom_id']} = {entry['value']}{ev}"
            )
        elif t == "constant":
            label = f" ({entry['label']})" if entry.get("label") else ""
            out_lines.append(f"{prefix}CONST = {entry['value']}{label}")
        elif t in ("times_const", "plus_const", "minus_const",
                   "const_minus", "div_by_const", "const_div_by"):
            label = entry.get("surface_label") or t.upper()
            out_lines.append(
                f"{prefix}{label} ({t}, const={entry['constant']}, "
                f"{entry['provenance']}) = {entry['result']}"
            )
            if entry.get("child_trace"):
                out_lines.append(format_typed_trace(entry["child_trace"],
                                                    indent + 1))
        elif t.startswith("compare_"):
            op = t.split("_", 1)[1].upper()
            label = entry.get("surface_label") or op
            out_lines.append(
                f"{prefix}{label} ({op}, left={entry['left_value']}, "
                f"right={entry['right_value']}, {entry['provenance']}) "
                f"= {entry['result']}"
            )
            if entry.get("left_trace"):
                out_lines.append(format_typed_trace(entry["left_trace"],
                                                    indent + 1))
            if entry.get("right_trace"):
                out_lines.append(format_typed_trace(entry["right_trace"],
                                                    indent + 1))
        elif t == "leaf":
            # Boolean leaf — fall through to existing format
            ev = f" [evidence: {entry['evidence']}]" if entry.get("evidence") else ""
            out_lines.append(
                f"{prefix}LEAF {entry['atom_id']} = {entry['value']}{ev}"
            )
        elif t in ("and", "or", "at_least"):
            label = (entry.get("surface_label")
                     or (f"AT-LEAST-{entry.get('n', '?')}" if t == "at_least"
                         else t.upper()))
            counts = f"t={entry['t']} f={entry['f']} u={entry['u']}"
            extra = f", n={entry['n']}" if t == "at_least" else ""
            out_lines.append(
                f"{prefix}{label} ({t.upper()}, k={entry['k']}{extra}, "
                f"{counts}, {entry['provenance']}) = {entry['result']}"
            )
            if entry.get("children_trace"):
                out_lines.append(format_typed_trace(entry["children_trace"],
                                                    indent + 1))
        elif t == "not":
            out_lines.append(
                f"{prefix}NOT ({entry['provenance']}) = {entry['result']}"
            )
            if entry.get("child_trace"):
                out_lines.append(format_typed_trace(entry["child_trace"],
                                                    indent + 1))
        else:
            out_lines.append(f"{prefix}?? unknown trace entry type: {t}")
    return "\n".join(out_lines)


# ---------------------------------------------------------------------------
# Type unions for static-checker hinting
# ---------------------------------------------------------------------------

NumericNode = Union[
    NumericLeaf, Constant,
    TimesConstNode, PlusConstNode, MinusConstNode, ConstMinusNode,
    DivByConstNode, ConstDivByNode,
]
ComparisonNode = Union[EqNode, LtNode, LeqNode, GtNode, GeqNode]

"""
RuleKit engine package.

Boolean layer: Kleene three-valued logic with AND/OR/NOT and AT-LEAST-N
operators over Boolean atoms. See ``boolean.py``.

Typed layer: numeric atoms, constant arithmetic (TIMES_CONST,
PLUS_CONST, MINUS_CONST, ConstMinus, DIV_BY_CONST, ConstDivBy), and
comparison operators (EQ, LT, LEQ, GT, GEQ) that bridge numerics to
Kleene-Boolean. See ``typed.py``.

Both layers share the same FactBundle; typed nodes compose with
Boolean nodes via the comparison operators that produce Kleene values
consumable by AndNode/OrNode/NotNode.
"""

from rulekit.engine.boolean import (
    Kleene,
    Provenance,
    Leaf,
    AndNode,
    OrNode,
    NotNode,
    AtLeastNode,
    CardinalityNode,
    FactBundle,
    Determination,
    EdgeMeta,
    invert,
    kleene_and,
    kleene_or,
    at_least_n,
    format_trace,
)

from rulekit.engine.typed import (
    NumericValue,
    AtomType,
    NumericLeaf,
    Constant,
    TimesConstNode,
    PlusConstNode,
    MinusConstNode,
    ConstMinusNode,
    DivByConstNode,
    ConstDivByNode,
    EqNode,
    LtNode,
    LeqNode,
    GtNode,
    GeqNode,
    format_typed_trace,
    get_numeric,
    NumericNode,
    ComparisonNode,
)

__all__ = [
    # Boolean layer
    "Kleene", "Provenance", "Leaf", "AndNode", "OrNode", "NotNode",
    "AtLeastNode", "CardinalityNode", "FactBundle", "Determination",
    "EdgeMeta", "invert", "kleene_and", "kleene_or", "at_least_n",
    "format_trace",
    # Typed layer
    "NumericValue", "AtomType",
    "NumericLeaf", "Constant",
    "TimesConstNode", "PlusConstNode", "MinusConstNode", "ConstMinusNode",
    "DivByConstNode", "ConstDivByNode",
    "EqNode", "LtNode", "LeqNode", "GtNode", "GeqNode",
    "format_typed_trace", "get_numeric",
    "NumericNode", "ComparisonNode",
]

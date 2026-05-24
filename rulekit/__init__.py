"""
RuleKit — typed Kleene engine for regulated adjudication.

A neuro-symbolic architecture for policy reasoning. The engine handles
the structural composition of typed atoms (Boolean and Numeric) over
the four ingredients of regulated decision-making: categorical
determinations, conjunctive requirements, disjunctive pathways, and
quantitative thresholds. The LLM is a constrained extractor at the
boundary, not a free-form reasoner.

Package layout:

- ``rulekit.engine`` — Kleene Boolean engine + typed numeric extension
- ``rulekit.schema`` — atom typing declarations
- ``rulekit.build`` — DAG construction from policy text + declared
  determinations (top-down decomposer pipeline)
- ``rulekit.map`` — evidence-to-atom binding substrates (Boolean and
  typed)

The package exposes the most-used symbols at the top level for backward
compatibility with the original flat layout.
"""

# Engine layer
from rulekit.engine import (
    Kleene, Provenance,
    Leaf, AndNode, OrNode, AtLeastNode, NotNode, CardinalityNode,
    FactBundle, Determination, EdgeMeta,
    invert, kleene_and, kleene_or, at_least_n,
    format_trace,
    # Typed
    NumericValue, AtomType,
    NumericLeaf, Constant,
    TimesConstNode, PlusConstNode, MinusConstNode, ConstMinusNode,
    DivByConstNode, ConstDivByNode,
    EqNode, LtNode, LeqNode, GtNode, GeqNode,
    format_typed_trace, get_numeric,
)

# Schema
from rulekit.schema import EvalMode, Atom, SchemaField, Schema

# Build pipeline — atom extraction (A1)
from rulekit.build import (
    ReaderVoice, A1Result, run_a1, check_atomicity,
    build_a1_prompt, parse_a1_response,
)

__all__ = [
    # Engine — Boolean
    "Kleene", "Provenance",
    "Leaf", "AndNode", "OrNode", "AtLeastNode", "NotNode", "CardinalityNode",
    "FactBundle", "Determination", "EdgeMeta",
    "invert", "kleene_and", "kleene_or", "at_least_n",
    "format_trace",
    # Engine — Typed
    "NumericValue", "AtomType",
    "NumericLeaf", "Constant",
    "TimesConstNode", "PlusConstNode", "MinusConstNode", "ConstMinusNode",
    "DivByConstNode", "ConstDivByNode",
    "EqNode", "LtNode", "LeqNode", "GtNode", "GeqNode",
    "format_typed_trace", "get_numeric",
    # Schema
    "EvalMode", "Atom", "SchemaField", "Schema",
    # Build (Extract)
    "ReaderVoice", "A1Result", "run_a1", "check_atomicity",
    "build_a1_prompt", "parse_a1_response",
]

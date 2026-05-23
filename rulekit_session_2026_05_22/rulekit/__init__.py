"""RuleKit — tree-based primitives for institutional reasoning."""
from .engine import (
    Kleene, Provenance,
    Leaf, AndNode, OrNode, AtLeastNode, NotNode, CardinalityNode,
    FactBundle, Determination, EdgeMeta,
    invert, kleene_and, kleene_or, at_least_n,
    format_trace,
)
from .schema import EvalMode, Atom, SchemaField, Schema
from .builder import (
    ReaderVoice, A1Result, run_a1, check_atomicity,
    build_a1_prompt, parse_a1_response,
)

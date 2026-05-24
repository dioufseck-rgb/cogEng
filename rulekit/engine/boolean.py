"""
RuleKit engine — Kleene three-valued logic with AND, OR, NOT as primary
operators plus AT-LEAST-N for cardinality cases that don't expand cleanly.

Vocabulary:
- AND: all children must hold.
- OR: at least one child must hold.
- NOT: exactly one child, polarity inverted.
- AT-LEAST-N: at least N of k children must hold (used when cardinality
  expansion would be unwieldy: N-choose-k > 6 or k > ~8).

Surface labels for transcribed operators live in metadata.

Kleene truth tables:
- AND:  TRUE if all children TRUE; FALSE if any FALSE; otherwise UNDETERMINED.
- OR:   TRUE if any child TRUE; FALSE if all FALSE; otherwise UNDETERMINED.
- NOT:  TRUE -> FALSE, FALSE -> TRUE, UNDETERMINED unchanged.
- AT-LEAST-N: TRUE if at least N children TRUE; FALSE if fewer than N
              children are TRUE-or-UNDETERMINED; otherwise UNDETERMINED.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class Kleene(Enum):
    TRUE = "true"
    FALSE = "false"
    UNDETERMINED = "undetermined"

    def __str__(self) -> str:
        return self.value


def invert(v: Kleene) -> Kleene:
    if v == Kleene.TRUE:
        return Kleene.FALSE
    if v == Kleene.FALSE:
        return Kleene.TRUE
    return Kleene.UNDETERMINED


def kleene_and(values: list[Kleene]) -> Kleene:
    """AND under Kleene: TRUE iff all TRUE; FALSE iff any FALSE; else UNDETERMINED."""
    if any(v == Kleene.FALSE for v in values):
        return Kleene.FALSE
    if all(v == Kleene.TRUE for v in values):
        return Kleene.TRUE
    return Kleene.UNDETERMINED


def kleene_or(values: list[Kleene]) -> Kleene:
    """OR under Kleene: TRUE iff any TRUE; FALSE iff all FALSE; else UNDETERMINED."""
    if any(v == Kleene.TRUE for v in values):
        return Kleene.TRUE
    if all(v == Kleene.FALSE for v in values):
        return Kleene.FALSE
    return Kleene.UNDETERMINED


def at_least_n(values: list[Kleene], n: int) -> Kleene:
    """
    AT-LEAST-N under Kleene cardinality semantics.
    TRUE if at least n children are TRUE.
    FALSE if fewer than n children could be TRUE (i.e., t + u < n).
    UNDETERMINED otherwise.
    """
    t = sum(1 for v in values if v == Kleene.TRUE)
    u = sum(1 for v in values if v == Kleene.UNDETERMINED)
    if t >= n:
        return Kleene.TRUE
    if t + u < n:
        return Kleene.FALSE
    return Kleene.UNDETERMINED


class Provenance(Enum):
    TRANSCRIBED = "transcribed"
    STRUCTURAL = "structural"
    INFERRED = "inferred"


@dataclass
class EdgeMeta:
    role: str = ""
    policy_reference: str = ""
    source_span: str = ""


@dataclass
class Leaf:
    atom_id: str

    def evaluate(self, bundle: "FactBundle", trace: Optional[list] = None) -> Kleene:
        value = bundle.get(self.atom_id)
        if trace is not None:
            trace.append({
                "type": "leaf",
                "atom_id": self.atom_id,
                "value": str(value),
                "evidence": bundle.evidence_for(self.atom_id),
            })
        return value


@dataclass
class AndNode:
    """All children must hold."""
    children: list[Union["Leaf", "AndNode", "OrNode", "NotNode", "AtLeastNode"]]
    children_meta: list[EdgeMeta] = field(default_factory=list)
    provenance: Provenance = Provenance.STRUCTURAL
    surface_label: str = ""
    source_span: str = ""
    confidence: Optional[float] = None
    latent_type: Optional[str] = None
    node_id: str = ""

    def evaluate(self, bundle, trace=None):
        local_trace = [] if trace is not None else None
        values = [c.evaluate(bundle, local_trace) for c in self.children]
        result = kleene_and(values)
        if trace is not None:
            trace.append(_node_trace_entry("and", self, values, result, local_trace))
        return result


@dataclass
class OrNode:
    """At least one child must hold."""
    children: list
    children_meta: list[EdgeMeta] = field(default_factory=list)
    provenance: Provenance = Provenance.STRUCTURAL
    surface_label: str = ""
    source_span: str = ""
    confidence: Optional[float] = None
    latent_type: Optional[str] = None
    node_id: str = ""

    def evaluate(self, bundle, trace=None):
        local_trace = [] if trace is not None else None
        values = [c.evaluate(bundle, local_trace) for c in self.children]
        result = kleene_or(values)
        if trace is not None:
            trace.append(_node_trace_entry("or", self, values, result, local_trace))
        return result


@dataclass
class AtLeastNode:
    """At least N of k children must hold (cardinality)."""
    n: int
    children: list
    children_meta: list[EdgeMeta] = field(default_factory=list)
    provenance: Provenance = Provenance.STRUCTURAL
    surface_label: str = ""
    source_span: str = ""
    confidence: Optional[float] = None
    latent_type: Optional[str] = None
    node_id: str = ""

    def evaluate(self, bundle, trace=None):
        local_trace = [] if trace is not None else None
        values = [c.evaluate(bundle, local_trace) for c in self.children]
        result = at_least_n(values, self.n)
        if trace is not None:
            entry = _node_trace_entry("at_least", self, values, result, local_trace)
            entry["n"] = self.n
            trace.append(entry)
        return result


@dataclass
class NotNode:
    child: Union[Leaf, AndNode, OrNode, AtLeastNode, "NotNode"]
    provenance: Provenance = Provenance.STRUCTURAL
    source_span: str = ""
    confidence: Optional[float] = None
    latent_type: Optional[str] = None

    def evaluate(self, bundle, trace=None):
        local_trace = [] if trace is not None else None
        child_value = self.child.evaluate(bundle, local_trace)
        result = invert(child_value)
        if trace is not None:
            trace.append({
                "type": "not",
                "provenance": self.provenance.value,
                "child_value": str(child_value),
                "result": str(result),
                "child_trace": local_trace,
            })
        return result


def _node_trace_entry(node_kind, node, values, result, local_trace):
    return {
        "type": node_kind,
        "k": len(node.children),
        "surface_label": getattr(node, "surface_label", ""),
        "provenance": node.provenance.value,
        "child_values": [str(v) for v in values],
        "t": sum(1 for v in values if v == Kleene.TRUE),
        "f": sum(1 for v in values if v == Kleene.FALSE),
        "u": sum(1 for v in values if v == Kleene.UNDETERMINED),
        "result": str(result),
        "children_trace": local_trace,
    }


# Backwards compatibility: CardinalityNode aliased to AtLeastNode
CardinalityNode = AtLeastNode


@dataclass
class FactBundle:
    values: dict[str, Kleene]
    evidence: dict[str, str] = field(default_factory=dict)

    def get(self, atom_id: str) -> Kleene:
        return self.values.get(atom_id, Kleene.UNDETERMINED)

    def evidence_for(self, atom_id: str) -> str:
        return self.evidence.get(atom_id, "")


@dataclass
class Determination:
    id: str
    description: str
    tree: Union[Leaf, AndNode, OrNode, NotNode, AtLeastNode]
    provenance: Provenance = Provenance.TRANSCRIBED
    polarity: Optional[str] = None
    linked_to: Optional[str] = None
    source_span: str = ""

    def evaluate(self, bundle: FactBundle) -> tuple[Kleene, list]:
        trace = []
        result = self.tree.evaluate(bundle, trace)
        return result, trace


def format_trace(trace: list, indent: int = 0) -> str:
    out_lines = []
    prefix = "  " * indent
    for entry in trace:
        if entry["type"] == "leaf":
            ev = f" [evidence: {entry['evidence']}]" if entry.get("evidence") else ""
            out_lines.append(f"{prefix}LEAF {entry['atom_id']} = {entry['value']}{ev}")
        elif entry["type"] == "and":
            label = entry.get("surface_label") or "AND"
            counts = f"t={entry['t']} f={entry['f']} u={entry['u']}"
            out_lines.append(
                f"{prefix}{label} (AND, k={entry['k']}, {counts}, {entry['provenance']}) = {entry['result']}"
            )
            if entry.get("children_trace"):
                out_lines.append(format_trace(entry["children_trace"], indent + 1))
        elif entry["type"] == "or":
            label = entry.get("surface_label") or "OR"
            counts = f"t={entry['t']} f={entry['f']} u={entry['u']}"
            out_lines.append(
                f"{prefix}{label} (OR, k={entry['k']}, {counts}, {entry['provenance']}) = {entry['result']}"
            )
            if entry.get("children_trace"):
                out_lines.append(format_trace(entry["children_trace"], indent + 1))
        elif entry["type"] == "at_least":
            label = entry.get("surface_label") or f"AT-LEAST-{entry['n']}"
            counts = f"t={entry['t']} f={entry['f']} u={entry['u']}"
            out_lines.append(
                f"{prefix}{label} (n={entry['n']}, k={entry['k']}, {counts}, {entry['provenance']}) = {entry['result']}"
            )
            if entry.get("children_trace"):
                out_lines.append(format_trace(entry["children_trace"], indent + 1))
        elif entry["type"] == "not":
            out_lines.append(f"{prefix}NOT ({entry['provenance']}) = {entry['result']}")
            if entry.get("child_trace"):
                out_lines.append(format_trace(entry["child_trace"], indent + 1))
    return "\n".join(out_lines)

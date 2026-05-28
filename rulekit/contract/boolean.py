"""
RuleKit contract: boolean-valued nodes.

A boolean-valued node evaluates to a Kleene value (TRUE/FALSE/UND) at
runtime. The boolean tree composes through AND/OR/NOT/AT_LEAST_N
operators, terminates at atom references (`AtomRef`), and bridges down
to numerics via comparison nodes (`ComparisonSpec`).

Children, condition references, comparison operands are all `NodeRef`s
(strings naming nodes in the program's node registry). They are not
nested model instances. This makes the DAG explicit and prevents
inline duplication of shared sub-trees.

This module depends on base.py. The discriminated union of all node
types is assembled in program.py to avoid circular imports between
boolean.py and numeric.py.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rulekit.contract.base import AtomId, NodeId, NodeRef, Provenance


class BooleanNodeBase(BaseModel):
    """Common fields for boolean-valued nodes.

    Every boolean node carries the audit metadata: a unique `node_id`,
    a `provenance` tag, a `surface_label` (the producer's human-readable
    name), and a `source_span` (the producer's traceback to source
    material).

    Inferred nodes additionally require `confidence` and `latent_type`
    so reviewers can audit the inference. This is enforced by the
    `_check_inferred_metadata` model validator.

    Transcribed nodes with empty `source_span` are also rejected.
    Structural and inferred nodes may have empty source_span — the
    producer is not citing source for them.
    """
    model_config = ConfigDict(extra="forbid")

    node_id: NodeId
    provenance: Provenance
    surface_label: str = ""
    source_span: str = ""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    latent_type: Optional[str] = None

    @model_validator(mode="after")
    def _check_inferred_metadata(self):
        if self.provenance == Provenance.INFERRED:
            if self.confidence is None:
                raise ValueError(
                    f"node {self.node_id!r}: provenance=INFERRED requires "
                    f"confidence to be set (0.0..1.0)"
                )
            if not self.latent_type:
                raise ValueError(
                    f"node {self.node_id!r}: provenance=INFERRED requires "
                    f"latent_type to be set (non-empty string)"
                )
        if self.provenance == Provenance.TRANSCRIBED and not self.source_span:
            raise ValueError(
                f"node {self.node_id!r}: provenance=TRANSCRIBED requires "
                f"source_span to be non-empty"
            )
        return self


class AtomRef(BooleanNodeBase):
    """A boolean leaf — references a BooleanAtom by id.

    The `atom_id` must name an atom in the program's `map_spec.atoms`
    whose `atom_type=="boolean"`. This is validated at the program
    level, not on the model in isolation (the model doesn't see the
    Map spec).
    """
    kind: Literal["atom_ref"] = "atom_ref"
    atom_id: AtomId


class AndNodeSpec(BooleanNodeBase):
    """All children must hold (Kleene AND)."""
    kind: Literal["and"] = "and"
    children: list[NodeRef] = Field(min_length=1)


class OrNodeSpec(BooleanNodeBase):
    """At least one child must hold (Kleene OR)."""
    kind: Literal["or"] = "or"
    children: list[NodeRef] = Field(min_length=1)


class NotNodeSpec(BooleanNodeBase):
    """Exactly one child, polarity inverted."""
    kind: Literal["not"] = "not"
    child: NodeRef


class AtLeastNodeSpec(BooleanNodeBase):
    """At least N of K children must hold (cardinality)."""
    kind: Literal["at_least"] = "at_least"
    n: int = Field(ge=1)
    children: list[NodeRef] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_n_against_children(self):
        if self.n > len(self.children):
            raise ValueError(
                f"node {self.node_id!r}: at_least n={self.n} cannot "
                f"exceed number of children ({len(self.children)})"
            )
        return self


class ComparisonSpec(BooleanNodeBase):
    """Numeric comparison — the bridge from numeric to boolean.

    Takes two NodeRefs to numeric-valued nodes (numeric atom refs,
    constants, arithmetic, conditional numeric, or named quantities)
    and produces a Kleene value.

    Operator semantics follow the typed engine's _compare:
        eq:  left == right
        lt:  left <  right (strict)
        leq: left <= right
        gt:  left >  right (strict)
        geq: left >= right

    Any UND operand yields UND. No vacuous-truth shortcuts.
    """
    kind: Literal["comparison"] = "comparison"
    operator: Literal["eq", "lt", "leq", "gt", "geq"]
    left: NodeRef
    right: NodeRef


# Type alias for code that wants to accept "any boolean node spec".
# The discriminated union for parsing is assembled in program.py.
AnyBooleanNodeSpec = (
    AtomRef
    | AndNodeSpec
    | OrNodeSpec
    | NotNodeSpec
    | AtLeastNodeSpec
    | ComparisonSpec
)


__all__ = [
    "BooleanNodeBase",
    "AtomRef",
    "AndNodeSpec",
    "OrNodeSpec",
    "NotNodeSpec",
    "AtLeastNodeSpec",
    "ComparisonSpec",
    "AnyBooleanNodeSpec",
]

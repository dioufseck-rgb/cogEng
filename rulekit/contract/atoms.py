"""
RuleKit contract: atoms.

An atom is a named proposition or quantity bound at runtime by Map.
Boolean atoms produce Kleene values (TRUE/FALSE/UND); numeric atoms
produce Decimal values (or UND).

`BooleanAtom` and `NumericAtom` are the two concrete subclasses. They
are assembled into a discriminated union (`AnyAtomSpec`) keyed by the
`atom_type` field so that JSON deserialization picks the right subclass
based on the value, not on field-order trial-and-error.

The contract does not export a non-discriminated base — callers that
want to type-annotate "any atom" should use `AnyAtomSpec`. The base
class `_AtomBase` is internal and not exported.

This module depends only on base.py. No node references; no engine
imports.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract.base import AtomId, EvaluationMode


class BindingBasis(str, Enum):
    """Epistemic basis for a Map atom binding."""

    EXPLICIT_POSITIVE = "explicit_positive"
    EXPLICIT_NEGATIVE = "explicit_negative"
    CLOSED_WORLD_ABSENCE = "closed_world_absence"
    OPEN_WORLD_ABSENCE = "open_world_absence"
    INFERRED_FROM_RECORD = "inferred_from_record"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    COMPUTED = "computed"
    LOOKED_UP = "looked_up"
    NOT_FOUND = "not_found"


class AtomBindingPolicy(BaseModel):
    """Rules for which Map bindings are epistemically acceptable.

    This is deliberately policy-level metadata, not engine logic. Map can
    propose a value and basis; the deterministic Map validator decides
    whether that basis is allowed for the atom before the engine consumes it.
    """

    model_config = ConfigDict(extra="forbid")

    allowed_bases_for_true: list[BindingBasis] = Field(
        default_factory=lambda: [
            BindingBasis.EXPLICIT_POSITIVE,
            BindingBasis.INFERRED_FROM_RECORD,
            BindingBasis.COMPUTED,
            BindingBasis.LOOKED_UP,
        ]
    )
    allowed_bases_for_false: list[BindingBasis] = Field(
        default_factory=lambda: [
            BindingBasis.EXPLICIT_NEGATIVE,
            BindingBasis.CLOSED_WORLD_ABSENCE,
            BindingBasis.COMPUTED,
            BindingBasis.LOOKED_UP,
        ]
    )
    required_source_types_for_true: list[str] = Field(default_factory=list)
    required_source_types_for_false: list[str] = Field(default_factory=list)
    open_world_absence_behavior: Literal[
        "undetermined",
        "human_review",
        "accept",
    ] = "undetermined"
    conflicting_evidence_behavior: Literal[
        "undetermined",
        "human_review",
        "accept",
    ] = "human_review"
    invalid_binding_behavior: Literal[
        "undetermined",
        "human_review",
        "error",
    ] = "undetermined"
    notes: str = ""


class _AtomBase(BaseModel):
    """Internal base for atom subclasses.

    Not exported. Callers should use BooleanAtom, NumericAtom, or the
    AnyAtomSpec union.

    Common fields:
        `atom_type` and `evaluation_mode` vary independently. A boolean
        atom may be CHARACTERIZED (LLM reads a narrative), COMPUTED
        (predicate over structured fields), or LOOKED_UP (table). A
        numeric atom may be any of the three as well.

        `extraction_template` is optional because not every atom needs
        one. CHARACTERIZED atoms typically carry the prompt fragment
        Map's narrative substrate uses. COMPUTED and LOOKED_UP atoms
        supply their rule in `notes` or via a handler registered
        externally.

        `undetermined_rule` documents when this atom produces UND. The
        contract does not enforce that Map honors it; it's audit
        metadata for reviewers.
    """
    model_config = ConfigDict(extra="forbid")

    id: AtomId
    statement: str = Field(min_length=1)
    source_span: str
    evaluation_mode: EvaluationMode
    extraction_template: Optional[str] = None
    undetermined_rule: str = ""
    notes: str = ""
    binding_policy: Optional[AtomBindingPolicy] = None


class BooleanAtom(_AtomBase):
    """An atom bound to a Kleene value (TRUE/FALSE/UND).

    Discriminator: `atom_type == "boolean"`.
    """
    atom_type: Literal["boolean"] = "boolean"


class NumericAtom(_AtomBase):
    """An atom bound to a Decimal value (or UND).

    Discriminator: `atom_type == "numeric"`.

    `numeric_unit` is advisory — it doesn't affect engine behavior.
    Downstream consumers (narrators, audit reports) can read it rather
    than parsing the statement.
    """
    atom_type: Literal["numeric"] = "numeric"
    numeric_unit: Optional[str] = None


# Discriminated union over atom subclasses. JSON deserialization picks
# the right subclass by inspecting the `atom_type` field. Use this as
# the value type for dicts/lists that hold "any atom" — most notably
# `MapSpec.atoms: dict[AtomId, AnyAtomSpec]`.
AnyAtomSpec = Annotated[
    Union[BooleanAtom, NumericAtom],
    Field(discriminator="atom_type"),
]


__all__ = [
    "BindingBasis",
    "AtomBindingPolicy",
    "BooleanAtom",
    "NumericAtom",
    "AnyAtomSpec",
]

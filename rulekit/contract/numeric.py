"""
RuleKit contract: numeric-valued nodes.

A numeric-valued node evaluates to a NumericValue (Decimal or UND) at
runtime. The numeric layer composes through unary, binary, and variadic
arithmetic, terminates at numeric atom references and constants,
includes conditional selection between two numeric branches, and can
defer computation to Map via NamedQuantitySpec.

Children, condition references, arithmetic operands are `NodeRef`s.

This module depends on base.py. The discriminated union of all node
types is assembled in program.py.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rulekit.contract.base import AtomId, NodeId, NodeRef, Provenance


class NumericNodeBase(BaseModel):
    """Common fields for numeric-valued nodes.

    Same shape as BooleanNodeBase. The two are kept separate (rather
    than sharing a parent) to make the boolean/numeric distinction
    visible in the type system. This costs duplication but pays in
    clarity at every callsite.
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


class NumericAtomRef(NumericNodeBase):
    """A numeric leaf — references a NumericAtom by id."""
    kind: Literal["numeric_atom_ref"] = "numeric_atom_ref"
    atom_id: AtomId


class ConstantSpec(NumericNodeBase):
    """A build-time numeric constant.

    Exactly one of `literal_value` or `constant_label` must be set.
    A literal value is a Decimal embedded directly in the spec.
    A constant_label references the program's `constants` registry.

    Decimal-via-string coercion: when JSON deserialization produces
    floats, Pydantic v2's Decimal validator goes through str() to
    avoid binary representation errors (0.0912 -> Decimal('0.0912'),
    not Decimal('0.0912000000000000058...')). This matches the
    engine's _to_decimal_constant behavior.
    """
    kind: Literal["constant"] = "constant"
    literal_value: Optional[Decimal] = None
    constant_label: Optional[str] = None

    @model_validator(mode="after")
    def _check_value_xor_label(self):
        if (self.literal_value is None) == (self.constant_label is None):
            raise ValueError(
                f"node {self.node_id!r}: ConstantSpec requires exactly "
                f"one of (literal_value, constant_label) — got "
                f"literal_value={self.literal_value!r}, "
                f"constant_label={self.constant_label!r}"
            )
        return self


class UnaryArithmeticSpec(NumericNodeBase):
    """child OP constant — six fixed-shape arithmetic operators.

    These mirror the engine's TimesConstNode, PlusConstNode, etc. One
    operand is a build-time constant (literal or named); the other is
    a numeric NodeRef.

    Operator semantics (engine names in parens):
        times_const   (TimesConstNode):  child * constant
        plus_const    (PlusConstNode):   child + constant
        minus_const   (MinusConstNode):  child - constant
        const_minus   (ConstMinusNode):  constant - child
        div_by_const  (DivByConstNode):  child / constant   (constant != 0)
        const_div_by  (ConstDivByNode):  constant / child   (UND if child == 0)
    """
    kind: Literal["unary_arithmetic"] = "unary_arithmetic"
    operator: Literal[
        "times_const",
        "plus_const",
        "minus_const",
        "const_minus",
        "div_by_const",
        "const_div_by",
    ]
    literal_constant: Optional[Decimal] = None
    constant_label: Optional[str] = None
    child: NodeRef

    @model_validator(mode="after")
    def _check_constant_xor(self):
        if (self.literal_constant is None) == (self.constant_label is None):
            raise ValueError(
                f"node {self.node_id!r}: UnaryArithmeticSpec requires "
                f"exactly one of (literal_constant, constant_label) — got "
                f"literal_constant={self.literal_constant!r}, "
                f"constant_label={self.constant_label!r}"
            )
        if self.operator == "div_by_const" and self.literal_constant is not None:
            if self.literal_constant == 0:
                raise ValueError(
                    f"node {self.node_id!r}: div_by_const with a literal "
                    f"zero divisor is a build-time error"
                )
        return self


class BinaryArithmeticSpec(NumericNodeBase):
    """Binary arithmetic — both operands are numeric NodeRefs.

    Mirrors engine's PlusNode, MinusNode, MulNode. Used when both
    operands are case-bound (case-stated salaries, two atom values
    that need to be summed/subtracted/multiplied).
    """
    kind: Literal["binary_arithmetic"] = "binary_arithmetic"
    operator: Literal["plus", "minus", "mul"]
    left: NodeRef
    right: NodeRef


class VariadicArithmeticSpec(NumericNodeBase):
    """Variadic sum / max / min over N >= 2 numeric NodeRefs.

    Mirrors engine's SumNode, MaxNode, MinNode. Used for aggregate
    sums (multiple contract salaries), maximums and minimums.

    Replaces the old DerivedAtomSpec computation kinds aggregate_sum,
    max_of, and min_of. Map no longer computes these — the engine does,
    via NodeRef children that Map binds individually.
    """
    kind: Literal["variadic_arithmetic"] = "variadic_arithmetic"
    operator: Literal["sum", "max", "min"]
    children: list[NodeRef] = Field(min_length=2)


class ConditionalNumericSpec(NumericNodeBase):
    """IF condition THEN if_true ELSE if_false.

    Mirrors engine's ConditionalNumericNode. The condition is a
    boolean NodeRef (atom_ref, boolean operator, or comparison).
    if_true and if_false are numeric NodeRefs.

    UND-conservative: when condition is UND, result is UND. Engine
    only evaluates the selected branch (audit honesty: we don't claim
    to have evaluated branches we didn't).
    """
    kind: Literal["conditional_numeric"] = "conditional_numeric"
    condition: NodeRef
    if_true: NodeRef
    if_false: NodeRef


class NamedQuantitySpec(NumericNodeBase):
    """A numeric quantity whose computation is delegated to Map.

    Used when the producer refers to a derived quantity that requires
    document-level interpretation outside the engine's arithmetic
    vocabulary, and the institution has implemented Map-side logic
    to compute it.

    The referenced atom must have evaluation_mode in
    {COMPUTED, LOOKED_UP}. This is checked at the program level.

    Replaces the legitimate remaining use of the old DerivedAtomSpec
    (computation_kind="named_quantity"). The other old computation_kinds
    are now expressed via VariadicArithmeticSpec and
    ConditionalNumericSpec.
    """
    kind: Literal["named_quantity"] = "named_quantity"
    atom_id: AtomId


AnyNumericNodeSpec = (
    NumericAtomRef
    | ConstantSpec
    | UnaryArithmeticSpec
    | BinaryArithmeticSpec
    | VariadicArithmeticSpec
    | ConditionalNumericSpec
    | NamedQuantitySpec
)


__all__ = [
    "NumericNodeBase",
    "NumericAtomRef",
    "ConstantSpec",
    "UnaryArithmeticSpec",
    "BinaryArithmeticSpec",
    "VariadicArithmeticSpec",
    "ConditionalNumericSpec",
    "NamedQuantitySpec",
    "AnyNumericNodeSpec",
]

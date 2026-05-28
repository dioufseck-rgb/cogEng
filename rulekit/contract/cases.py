"""
RuleKit contract: case input schema and test cases.

Per the contract's commitment C3, test cases are Map-input-shaped, not
bundle-shaped. A TestCase carries what Map will see at runtime — a
narrative string, structured records, or both — paired with the
expected determinations.

The CaseInputSchema declares the shape Map will see for cases under
this program. Both real cases at runtime and test cases at validation
time must conform to it.

The schema deliberately keeps the structured side simple: a flat
dict from field name to scalar type. Producers that need nested or
list-valued structured data can encode it in the narrative or extend
the program's `metadata.extras`. Keeping CaseInputSchema lean keeps
substrates portable.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rulekit.contract.base import AtomId


class CaseInputSchema(BaseModel):
    """Declares what shape Map will see for cases under this program.

    `has_narrative`: when True, each CaseInput must carry a non-empty
        narrative string.

    `structured_fields`: name -> scalar type. Each key is a structured
        field that may appear in a CaseInput's `structured` dict.

    Field types are intentionally limited to the four scalars the engine
    actually needs at the atom boundary: string, number, date, bool.
    Producers needing richer types can serialize them into strings (an
    array, a JSON-encoded object) and parse them in the COMPUTED
    handler. The contract does not interpret structured field values
    beyond presence and key membership.
    """
    model_config = ConfigDict(extra="forbid")

    has_narrative: bool = True
    structured_fields: dict[
        str, Literal["string", "number", "date", "bool"]
    ] = Field(default_factory=dict)


class CaseInput(BaseModel):
    """A single case, conforming to the program's CaseInputSchema.

    Conformance to the schema is checked at the program level (we need
    to see both this CaseInput and the schema to validate them
    together). The model itself just accepts the shape.
    """
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    narrative: Optional[str] = None
    structured: dict[str, Any] = Field(default_factory=dict)


class ExpectedOutcome(BaseModel):
    """An expected determination value for a test case.

    `expected_value` is the string form of the Kleene value the engine
    is expected to produce for `determination_id` when this test case
    runs through Map and Evaluate. The `rationale` field documents why
    this is the expected outcome — useful for audit and for the
    eventual narrator when explaining why an actual outcome diverged.
    """
    model_config = ConfigDict(extra="forbid")

    determination_id: AtomId
    expected_value: Literal["true", "false", "undetermined"]
    rationale: str = ""


class TestCase(BaseModel):
    """A test case: a Map-input plus expected determinations.

    `expected_load_bearing_atoms`: optional. When present, the
    sensitivity-degradation runner can validate that these atoms are
    the load-bearing ones — i.e., dropping any of them to UND shifts
    the determination. This is for the cases where producers want to
    pin not just the outcome but the reasoning structure that produced
    it.
    """
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    input: CaseInput
    expected_outcomes: list[ExpectedOutcome] = Field(min_length=1)
    expected_load_bearing_atoms: Optional[list[AtomId]] = None
    notes: str = ""

    @model_validator(mode="after")
    def _check_case_ids_match(self):
        if self.case_id != self.input.case_id:
            raise ValueError(
                f"TestCase.case_id ({self.case_id!r}) must equal "
                f"input.case_id ({self.input.case_id!r})"
            )
        return self


__all__ = [
    "CaseInputSchema",
    "CaseInput",
    "ExpectedOutcome",
    "TestCase",
]

"""
RuleKit contract: shared primitives.

This module has no dependencies on other contract modules and no engine
imports. It defines the identifier types and the enumerations that the
rest of the contract uses.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Annotated

from pydantic import AfterValidator


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

# AtomId and NodeId share the same regex. They are distinct types in
# documentation and intent (atoms live in the Map spec; nodes live in the
# node registry) but identical in shape — both are strings the producer
# chose, validated for safe characters. The contract does not enforce a
# naming convention beyond the character set; producers may use dotted
# prefixes (`fcba.x`), flat snake_case (`days_since_notice`), UUIDs, or
# anything else matching the regex.
_ID_REGEX = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.]*$")


def _validate_id(value: str) -> str:
    """Validate an identifier string against the contract's ID regex.

    Raises ValueError with a descriptive message on failure. Returns the
    value unchanged on success so it can be used as an AfterValidator.
    """
    if not isinstance(value, str):
        raise ValueError(
            f"Identifier must be a string, got {type(value).__name__}"
        )
    if not _ID_REGEX.match(value):
        raise ValueError(
            f"Identifier {value!r} does not match the contract's ID "
            f"regex. Must start with a letter and contain only letters, "
            f"digits, underscores, and dots."
        )
    return value


# Pydantic v2 idiom: Annotated[str, AfterValidator(...)] is the way to
# attach a validator to a primitive type without subclassing str. The
# result is usable as a field type and as a dict key.
AtomId = Annotated[str, AfterValidator(_validate_id)]
NodeId = Annotated[str, AfterValidator(_validate_id)]

# Alias used in node child/parent references for clarity in the models.
# Semantically identical to NodeId — a string that names a node in the
# program's node registry.
NodeRef = NodeId


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class Provenance(str, Enum):
    """Why a node exists.

    TRANSCRIBED: the producer drew this node directly from source
        material (a policy clause, a contract section, a config rule).
        Implies source_span is non-empty.

    STRUCTURAL: the node is implied by structural decomposition — an
        AND grouping of three sibling clauses where the source enumerated
        them but did not literally say "and". Source span may be empty.

    INFERRED: the node is the producer's interpretation when the source
        material is silent. Inferred nodes carry additional fields
        (confidence, latent_type) so reviewers can audit the inference.
    """

    TRANSCRIBED = "transcribed"
    STRUCTURAL = "structural"
    INFERRED = "inferred"


# ---------------------------------------------------------------------------
# Evaluation mode
# ---------------------------------------------------------------------------

class EvaluationMode(str, Enum):
    """How an atom's value is produced at runtime.

    CHARACTERIZED: bound by extraction. Typically the LLM Map substrate
        reads a case description and decides TRUE/FALSE/UND for boolean
        atoms or extracts a Decimal value for numeric atoms.

    COMPUTED: bound by deterministic code. Date math, arithmetic from
        case structured fields, derived quantities computed from other
        atoms via a registered handler.

    LOOKED_UP: bound by reference. Table lookup, external service call,
        registry consultation.
    """

    CHARACTERIZED = "characterized"
    COMPUTED = "computed"
    LOOKED_UP = "looked_up"


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "AtomId",
    "NodeId",
    "NodeRef",
    "Provenance",
    "EvaluationMode",
]

"""
Schema specification — typed field declarations binding atoms to map operations.

Each schema field corresponds to an atom and declares:
- evaluation_mode: how the truth value is produced (computed, characterized, looked_up)
- value_space: what values the field can take (always Kleene three-valued at the leaf interface)
- specification: the mode-specific spec (computation rule, prompt template, lookup table)
- undetermined_rules: when this field produces UNDETERMINED rather than TRUE/FALSE
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EvalMode(Enum):
    COMPUTED = "computed"           # deterministic code (arithmetic, date math)
    CHARACTERIZED = "characterized" # LLM substrate (textual judgment)
    LOOKED_UP = "looked_up"         # table or external service


@dataclass
class Atom:
    """A refined atom from the extraction stage.

    atom_type:
      - "boolean" (default): atom is bound to a Kleene three-valued truth value.
        Used at engine leaves and for atoms that Map evaluates as TRUE/FALSE/UND.
      - "numeric": atom is bound to a NumericValue (Decimal or UNDETERMINED).
        Used as a child of comparison nodes (LtNode, LeqNode, etc.) and
        arithmetic nodes (TimesConstNode, etc.) in the typed engine extension.

    The default is "boolean" for backward compatibility — existing PA/FCBA
    atoms continue to work without modification.
    """
    id: str
    statement: str                  # the atomic proposition in natural language
    source_span: str                # where in the policy this is drawn from
    notes: str = ""
    atom_type: str = "boolean"      # "boolean" | "numeric"


@dataclass
class SchemaField:
    """One field in the schema, bound to one atom."""
    atom_id: str
    evaluation_mode: EvalMode
    specification: str              # spec text or pointer to computation rule
    undetermined_rule: str          # when does this field produce UNDETERMINED
    domain_notes: str = ""          # institutional conventions, references, rationale


@dataclass
class Schema:
    """The full schema for one policy."""
    name: str
    atoms: dict[str, Atom]          # atom_id -> Atom
    fields: dict[str, SchemaField]  # atom_id -> SchemaField

    def validate(self) -> list[str]:
        """Check schema completeness — every atom has a field, every field references an atom."""
        errors = []
        for atom_id in self.atoms:
            if atom_id not in self.fields:
                errors.append(f"Atom {atom_id} has no schema field")
        for atom_id in self.fields:
            if atom_id not in self.atoms:
                errors.append(f"Schema field {atom_id} has no atom")
        return errors

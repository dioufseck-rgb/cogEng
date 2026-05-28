"""
RuleKit contract: Map spec.

The Map spec is the producer's specification of how Map binds evidence
to atoms. It consists of an atom catalog (every atom referenced by any
node in the program) plus per-atom extraction policy carried on the
atoms themselves.

This is the architectural change the contract makes explicit: the Map
substrate does not own extraction policy. The substrate is a runtime
executor of the Map spec — it reads the spec the producer shipped and
applies the extraction template, evaluation mode, and undetermined
rule each atom declares.

The advisory handler dicts (`computed_handlers`, `lookup_handlers`) let
the producer hint at how the runtime should resolve COMPUTED and
LOOKED_UP atoms. They are substrate-specific and the contract does not
constrain their values beyond "string keyed by AtomId".
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract.atoms import AnyAtomSpec
from rulekit.contract.base import AtomId


class MapSpec(BaseModel):
    """How Map binds evidence to atoms.

    `atoms` is keyed by AtomId and valued by AnyAtomSpec (the
    discriminated union of BooleanAtom and NumericAtom). JSON round-trip
    preserves the concrete subclass via the `atom_type` discriminator.

    Validation of atom-id coherence (every atom referenced by a node
    exists here; every key matches its atom's id) runs at the program
    level, not on the MapSpec in isolation.
    """
    model_config = ConfigDict(extra="forbid")

    atoms: dict[AtomId, AnyAtomSpec] = Field(default_factory=dict)
    default_extraction_template: Optional[str] = None
    computed_handlers: dict[AtomId, str] = Field(default_factory=dict)
    lookup_handlers: dict[AtomId, str] = Field(default_factory=dict)


__all__ = ["MapSpec"]

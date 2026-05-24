"""
Map primitive.

The Map primitive exercises the morphism from evidence space to atom
truth-value space. Given a body of evidence and a build's atom inventory,
Map produces a FactBundle that assigns each atom a Kleene value (TRUE,
FALSE, UNDETERMINED).

Map is run-time machinery. It is invoked per case, against a built DAG.
The build itself does not see cases. The Map primitive bridges them.

Different evidence types call for different Substrate implementations:
- NarrativeLLMSubstrate: maps natural-language case descriptions via LLM
- (future) StructuredSubstrate: maps structured records via lookups
- (future) HybridSubstrate: dispatches per atom-type

This module currently provides the narrative-LLM implementation. The
interface is open for additional implementations.
"""

from __future__ import annotations
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from rulekit.engine import Kleene, FactBundle
from rulekit.schema import Atom
from rulekit.build.decomposer import LLMCaller, _parse_json_response


# ---------------------------------------------------------------------------
# Substrate interface
# ---------------------------------------------------------------------------

class Substrate(ABC):
    """Abstract interface for binding evidence to atom truth values."""

    @abstractmethod
    def bind(self, evidence: str, atoms: dict[str, Atom]) -> FactBundle:
        """
        Map a body of evidence to a FactBundle for the given atom inventory.

        Returns a FactBundle where each atom in atoms has a Kleene value:
        - TRUE if the evidence supports the atom's statement
        - FALSE if the evidence contradicts the atom's statement
        - UNDETERMINED if the evidence does not address the atom

        Each atom should have a value in the returned bundle, even if
        UNDETERMINED.
        """
        ...


# ---------------------------------------------------------------------------
# Narrative LLM substrate
# ---------------------------------------------------------------------------

BIND_PROMPT = """You are mapping a case description to atomic propositions
for evaluation by a policy reasoning engine.

For each atom listed below, decide its truth value given the case
description:

- "true" if the case description supports the atom's claim, either
  explicitly or by reasonable inference from facts the description
  provides. Reasonable inference means a domain expert would agree
  the claim follows from what the description says.

- "false" if the case description contradicts the atom's claim, OR
  if the description enumerates a category that this claim falls
  outside of (e.g., the description lists every medication tried,
  and the atom asks about a medication not on the list).

- "undetermined" if the case description does not address the claim
  one way or the other. This is the default when in doubt. Do NOT
  assume claims are true just because they're consistent with the
  description; require positive support.

PRINCIPLES
============
- The case description is the SOLE source of evidence. Do not bring
  in outside knowledge about what is typical or expected.
- A claim's truth value depends on the description, not on the
  atom's plausibility in general.
- If the description establishes a category as exhaustive ("the
  patient tried medications X, Y, Z and no others"), then claims
  about other medications in the same domain are FALSE, not
  UNDETERMINED.
- If the description is silent on a topic, the relevant atoms are
  UNDETERMINED, not FALSE.

CASE DESCRIPTION
=================
{description}

ATOMS TO BIND
==============
{atom_listing}

OUTPUT FORMAT
==============
A JSON object mapping each atom_id to its truth value as a string:
"true", "false", or "undetermined". Include EVERY atom_id listed above.

Example:
{{
  "pa.a001": "true",
  "pa.a002": "false",
  "pa.a003": "undetermined",
  ...
}}

Output ONLY the JSON object. No preamble, no commentary, no markdown
code fences.
"""


class NarrativeLLMSubstrate(Substrate):
    """
    Maps a natural-language case description to atom truth values via
    a single LLM call.
    """

    def __init__(self, llm: LLMCaller, batch_size: Optional[int] = None):
        """
        Args:
            llm: LLM caller
            batch_size: if set, split atoms into batches of this size.
                None means a single call for all atoms (preferred when
                the atom count is moderate, say <100).
        """
        self.llm = llm
        self.batch_size = batch_size

    def bind(self, evidence: str, atoms: dict[str, Atom]) -> FactBundle:
        """Bind the evidence to the atom inventory."""
        if not atoms:
            return FactBundle(values={})

        atom_items = sorted(atoms.items())
        all_values: dict[str, Kleene] = {}

        if self.batch_size is None:
            # Single call
            all_values = self._bind_batch(evidence, atom_items)
        else:
            for i in range(0, len(atom_items), self.batch_size):
                batch = atom_items[i:i + self.batch_size]
                batch_values = self._bind_batch(evidence, batch)
                all_values.update(batch_values)

        # Ensure every atom has a value (default UNDETERMINED if the LLM
        # omitted any).
        for atom_id in atoms:
            if atom_id not in all_values:
                all_values[atom_id] = Kleene.UNDETERMINED

        return FactBundle(values=all_values)

    def _bind_batch(self, evidence: str,
                    atom_items: list[tuple[str, Atom]]) -> dict[str, Kleene]:
        """Issue one LLM call for a batch of atoms."""
        atom_listing = "\n".join(
            f"  {aid}: {atom.statement}"
            for aid, atom in atom_items
        )
        prompt = BIND_PROMPT.format(
            description=evidence,
            atom_listing=atom_listing,
        )
        raw = self.llm.call("map_bind", prompt)
        parsed = _parse_json_response(raw)
        values = {}
        for aid, _atom in atom_items:
            v = parsed.get(aid, "undetermined")
            values[aid] = _parse_kleene(v)
        return values


def _parse_kleene(v) -> Kleene:
    """Parse a string-or-other into a Kleene value."""
    if isinstance(v, Kleene):
        return v
    s = str(v).strip().lower()
    if s == "true":
        return Kleene.TRUE
    if s == "false":
        return Kleene.FALSE
    return Kleene.UNDETERMINED


# ---------------------------------------------------------------------------
# Top-level Map primitive
# ---------------------------------------------------------------------------

def map_case_to_bundle(evidence: str, atoms: dict[str, Atom],
                       substrate: Substrate) -> FactBundle:
    """
    Map evidence to a FactBundle using the given substrate.

    This is the Map primitive: a morphism from evidence space to atom
    truth-value space, mediated by the substrate.
    """
    return substrate.bind(evidence, atoms)

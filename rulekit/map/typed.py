"""
Typed Map substrate — extends Map to bind both Boolean and Numeric atoms.

The existing NarrativeLLMSubstrate in map_primitive.py binds only Boolean
atoms (Kleene values). This module adds a typed substrate that also binds
numeric atoms — extracting numeric values from case text via a focused
LLM extraction prompt — and produces a FactBundle containing both kinds
of values.

DESIGN
======
The substrate accepts a TYPED atom inventory: each atom is labeled with
an AtomType (BOOLEAN or NUMERIC). The substrate dispatches:
  - Boolean atoms go through the existing BIND_PROMPT pattern (true /
    false / undetermined classification)
  - Numeric atoms go through a separate NUMERIC_BIND_PROMPT that asks the
    LLM to extract a single numeric value (or report "undetermined")

This keeps the LLM's per-atom task small and focused, which is the
load-bearing property for the architecture's claim to be more reliable
than direct-LLM rule application.

The substrate is additive: the existing NarrativeLLMSubstrate continues
to work for Boolean-only DAGs. The typed substrate is opt-in for the
typed-engine DAGs.

LIMITS
=======
- Numeric atoms are bound one batch at a time, like Boolean atoms.
- The numeric prompt is deliberately strict: no arithmetic, no unit
  conversion, no inference beyond what the case literally states. The
  LLM is an extractor, not a calculator.
- Unit handling is the caller's responsibility (express atoms with their
  units, e.g., "team_salary in US dollars", and Map returns the bare
  number).
- For composite numerics that require a per-case computation (e.g.,
  aggregated_outgoing_salary across multiple players), the atom
  statement should explicitly describe the computation, and Map will
  perform it in the LLM call. This is the one case where Map does
  arithmetic, and it's justified because the alternative is N separate
  numeric atoms per player which the engine can't compose.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Optional, Union

from rulekit.engine import Kleene, FactBundle
from rulekit.schema import Atom
from rulekit.build.decomposer import LLMCaller, _parse_json_response
from rulekit.engine.typed import NumericValue, AtomType
from rulekit.map.boolean import Substrate, _parse_kleene, BIND_PROMPT


# ---------------------------------------------------------------------------
# Typed atom spec
# ---------------------------------------------------------------------------

class TypedAtom:
    """
    An atom annotated with its type. Wraps schema.Atom and adds AtomType.

    This is a lightweight wrapper to avoid modifying schema.Atom for
    backward compatibility. When schema integration happens, this will
    become a property on schema.Atom and TypedAtom will go away.
    """

    def __init__(self, atom: Atom, atom_type: AtomType):
        self.atom = atom
        self.atom_type = atom_type

    @property
    def id(self) -> str:
        return self.atom.id

    @property
    def statement(self) -> str:
        return self.atom.statement


# ---------------------------------------------------------------------------
# Numeric extraction prompt
# ---------------------------------------------------------------------------

NUMERIC_BIND_PROMPT = """You are extracting NUMERIC values from a case
description, for use by a policy reasoning engine.

For each numeric atom listed below, find its value in the case
description and return it as a number. If the case does not state the
value (or does not allow it to be computed from what the case states),
return "undetermined".

EXTRACTION RULES
=================
- Return a raw numeric value: e.g., 5150000 for "$5,150,000".
- Strip currency symbols and commas. The number must parse as a
  decimal.
- Do NOT do unit conversion the case doesn't ask for. Atom statements
  declare their expected unit.
- Do NOT do compound arithmetic across multiple atoms or across
  multiple operations. Each atom is extracted independently. The only
  per-case computation allowed is what the atom statement explicitly
  describes (e.g., "sum of player A's and player B's salaries").
- If the case states something with uncertainty ("approximately $5M",
  "between $4M and $6M"), return "undetermined" — the engine handles
  ambiguity better than a guessed value.
- If a value is implied but not stated, return "undetermined". Only
  extract values the case literally provides.
- For dates, return days-since-2000-01-01 only if the atom statement
  asks for this. Otherwise extract dates in whatever unit the atom
  asks for (year as integer, etc.).

CASE DESCRIPTION
=================
{description}

NUMERIC ATOMS TO EXTRACT
=========================
{atom_listing}

OUTPUT FORMAT
==============
A JSON object mapping each atom_id to its value as a number, or the
string "undetermined" if the value cannot be extracted. Include EVERY
atom_id listed above.

Example:
{{
  "team_a_salary": 158000000,
  "contract_first_year_salary": 5150000,
  "player_age": 28,
  "some_unknown_atom": "undetermined"
}}

Output ONLY the JSON object. No preamble, no commentary, no markdown
code fences.
"""


# ---------------------------------------------------------------------------
# Numeric value parsing
# ---------------------------------------------------------------------------

def _parse_numeric(v) -> NumericValue:
    """
    Parse an LLM-returned value into a NumericValue.

    Accepts: int, float, str (parsed as Decimal), "undetermined", None.
    Strict: anything else returns UNDETERMINED rather than guessing.
    """
    if v is None:
        return NumericValue.undetermined()
    if isinstance(v, NumericValue):
        return v
    if isinstance(v, (int, float, Decimal)):
        try:
            return NumericValue.of(v)
        except Exception:
            return NumericValue.undetermined()
    if isinstance(v, str):
        s = v.strip().lower()
        if s == "undetermined" or s == "" or s == "null":
            return NumericValue.undetermined()
        # Try to clean up: strip $ , spaces
        cleaned = re.sub(r"[$,\s]", "", v.strip())
        try:
            return NumericValue.of(Decimal(cleaned))
        except Exception:
            return NumericValue.undetermined()
    return NumericValue.undetermined()


# ---------------------------------------------------------------------------
# Typed substrate
# ---------------------------------------------------------------------------

class TypedNarrativeLLMSubstrate(Substrate):
    """
    Substrate that binds both Boolean and Numeric atoms from a narrative
    case description.

    The dispatch is on AtomType:
      - BOOLEAN atoms go through BIND_PROMPT (existing behavior)
      - NUMERIC atoms go through NUMERIC_BIND_PROMPT (new)

    The two passes are independent LLM calls. We could merge them in one
    prompt for efficiency, but separating them gives a cleaner per-atom
    task description and avoids the LLM getting confused about whether
    a given atom needs a truth value or a numeric value.
    """

    def __init__(self, llm: LLMCaller, batch_size: Optional[int] = None):
        self.llm = llm
        self.batch_size = batch_size

    def bind(self, evidence: str,
             atoms: dict[str, Atom]) -> FactBundle:
        """
        Backward-compatible interface: if called with untyped atoms
        (just schema.Atom values), treat them all as Boolean.

        For typed binding, use bind_typed() instead.
        """
        typed_atoms = {aid: TypedAtom(a, AtomType.BOOLEAN)
                       for aid, a in atoms.items()}
        return self.bind_typed(evidence, typed_atoms)

    def bind_typed(self, evidence: str,
                   typed_atoms: dict[str, TypedAtom]) -> FactBundle:
        """
        Bind a typed atom inventory to a FactBundle.

        Returns a FactBundle whose `values` dict contains:
          - Kleene values for BOOLEAN atoms
          - NumericValue instances for NUMERIC atoms
        """
        if not typed_atoms:
            return FactBundle(values={})

        # Partition by type
        boolean_atoms = {aid: ta.atom for aid, ta in typed_atoms.items()
                         if ta.atom_type == AtomType.BOOLEAN}
        numeric_atoms = {aid: ta.atom for aid, ta in typed_atoms.items()
                         if ta.atom_type == AtomType.NUMERIC}

        all_values: dict[str, Union[Kleene, NumericValue]] = {}

        # Bind Boolean atoms (existing pattern)
        if boolean_atoms:
            bool_items = sorted(boolean_atoms.items())
            for batch in self._batches(bool_items):
                values = self._bind_boolean_batch(evidence, batch)
                all_values.update(values)

        # Bind Numeric atoms
        if numeric_atoms:
            num_items = sorted(numeric_atoms.items())
            for batch in self._batches(num_items):
                values = self._bind_numeric_batch(evidence, batch)
                all_values.update(values)

        # Default any missing atom to UNDETERMINED of its declared type
        for aid, ta in typed_atoms.items():
            if aid not in all_values:
                if ta.atom_type == AtomType.NUMERIC:
                    all_values[aid] = NumericValue.undetermined()
                else:
                    all_values[aid] = Kleene.UNDETERMINED

        return FactBundle(values=all_values)

    # -- internal helpers --

    def _batches(self, items):
        if self.batch_size is None:
            yield items
            return
        for i in range(0, len(items), self.batch_size):
            yield items[i:i + self.batch_size]

    def _bind_boolean_batch(self, evidence,
                            atom_items) -> dict[str, Kleene]:
        atom_listing = "\n".join(
            f"  {aid}: {atom.statement}" for aid, atom in atom_items
        )
        prompt = BIND_PROMPT.format(
            description=evidence, atom_listing=atom_listing,
        )
        raw = self.llm.call("map_bind_boolean", prompt)
        parsed = _parse_json_response(raw)
        return {aid: _parse_kleene(parsed.get(aid, "undetermined"))
                for aid, _ in atom_items}

    def _bind_numeric_batch(self, evidence,
                            atom_items) -> dict[str, NumericValue]:
        atom_listing = "\n".join(
            f"  {aid}: {atom.statement}" for aid, atom in atom_items
        )
        prompt = NUMERIC_BIND_PROMPT.format(
            description=evidence, atom_listing=atom_listing,
        )
        raw = self.llm.call("map_bind_numeric", prompt)
        parsed = _parse_json_response(raw)
        return {aid: _parse_numeric(parsed.get(aid, "undetermined"))
                for aid, _ in atom_items}


# ---------------------------------------------------------------------------
# Top-level helper
# ---------------------------------------------------------------------------

def map_case_to_typed_bundle(evidence: str,
                              typed_atoms: dict[str, TypedAtom],
                              substrate: TypedNarrativeLLMSubstrate
                              ) -> FactBundle:
    """
    Typed Map primitive: morphism from evidence space to a FactBundle
    containing both Kleene and NumericValue values.
    """
    return substrate.bind_typed(evidence, typed_atoms)

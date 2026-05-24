"""
RuleKit Map primitive.

The Map primitive bridges evidence space to atom truth-value space. Map
takes a case description (or structured case record) and an atom
inventory, and produces a FactBundle assigning a value to each atom.

Two substrate implementations:

- ``boolean.py`` — ``NarrativeLLMSubstrate``: binds Boolean atoms from
  narrative case text via LLM classification.

- ``typed.py`` — ``TypedNarrativeLLMSubstrate``: binds both Boolean and
  Numeric atoms, dispatching on atom type. Numeric atoms get a separate,
  focused extraction prompt.

Map is run-time machinery. Build runs once per policy; Map runs once
per case against the built DAG.
"""

from rulekit.map.boolean import (
    Substrate,
    NarrativeLLMSubstrate,
    map_case_to_bundle,
    BIND_PROMPT,
    _parse_kleene,
)

from rulekit.map.typed import (
    TypedAtom,
    TypedNarrativeLLMSubstrate,
    map_case_to_typed_bundle,
    NUMERIC_BIND_PROMPT,
    _parse_numeric,
)

__all__ = [
    "Substrate", "NarrativeLLMSubstrate", "map_case_to_bundle",
    "BIND_PROMPT",
    "TypedAtom", "TypedNarrativeLLMSubstrate", "map_case_to_typed_bundle",
    "NUMERIC_BIND_PROMPT",
]

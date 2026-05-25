"""
Structured-output Map substrate — one-call extraction for the typed FactBundle.

Reframing the Map step: rather than N independent atom-extraction calls
(N = ~100+ in production cases), this substrate makes a SINGLE LLM call
per case. The atom registry becomes a JSON schema. The LLM does ONE
structured extraction against the case description, returning a complete
populated FactBundle in one response.

WHY THIS WORKS
==============
Map is not a chain of reasoning steps that must be kept independent for
correctness. The architecture's load-bearing claim is that the ENGINE
composes structural logic correctly given the facts — not that each fact
must be extracted independently.

The per-atom focus rationale (in TypedNarrativeLLMSubstrate's docstring)
applies to keeping the model's *task* simple per atom. A structured-
extraction prompt does that by treating each atom as a SCHEMA FIELD, not
a reasoning question. The LLM populates fields without reasoning about
their implications — that's the engine's job.

ARCHITECTURAL CONSEQUENCE
=========================
Per-case cost drops from O(N) calls to O(1). Wall time drops from
30-90 minutes to 30-90 seconds. Cost approaches parity with monolithic
LLM adjudication while preserving the substrate's auditability (each
field's binding is recorded individually) and the engine's correctness
guarantees.

DUPLICATE-AWARE PROMPTING
==========================
The atom registry may contain semantically-equivalent atoms with
distinct ids (e.g. `contract_first_year_salary` and
`new_contract_first_year_salary_plus_unlikely_bonuses` referring to the
same case quantity). The substrate clusters such atoms via LEXICAL
normalization (lowercase, strip punctuation, drop filler words) and
instructs the LLM to bind them consistently within each detected
cluster.

This is best-effort: the lexical normalizer catches near-identical
statements but does not detect semantic equivalence across paraphrased
statements. The substrate complements this by:
  - Asking the LLM directly to be consistent across semantically-
    equivalent atoms regardless of detection
  - Post-extraction, verifying detected clusters bound to the same
    value, logging inconsistencies as audit findings (not auto-merged)

Improved semantic dedup (sentence-embedding-based clustering) is a
candidate for post-sprint enhancement. For now, the LLM's own
consistency on equivalent statements is the primary mechanism.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from decimal import Decimal
from typing import Optional, Union

from rulekit.engine import Kleene, FactBundle
from rulekit.schema import Atom
from rulekit.build.decomposer import LLMCaller, _parse_json_response
from rulekit.engine.typed import NumericValue, AtomType
from rulekit.map.boolean import Substrate, _parse_kleene
from rulekit.map.typed import TypedAtom, _parse_numeric


STRUCTURED_BIND_PROMPT = """Extract atom values from the case description.

CASE
====
{description}

ATOMS (id : statement → bind to value)
======================================
{atom_listing}

OUTPUT REQUIREMENTS
===================
Return a single JSON object mapping each atom id to its bound value.

For BOOLEAN atoms: "true", "false", or "undetermined".
For NUMERIC atoms: a raw number (e.g., 35000000 for $35M; strip $ and ,)
  or the string "undetermined".

Bind to "undetermined" when the case is silent on a fact, or when a
numeric value would have to be guessed. Do not infer. Do not compute
unless the atom statement explicitly says to. Each atom is bound from
the case description alone — no outside knowledge about the policy or
domain.

Atoms with semantically-equivalent statements (e.g. multiple ids that
all refer to "contract first-year salary plus unlikely bonuses") MUST
receive the same value. Be consistent.

Output ONLY the JSON object. No preamble, no markdown.{duplicate_hint}
"""


def _compute_duplicate_clusters(typed_atoms: dict[str, TypedAtom]) -> list[list[str]]:
    """Cluster atoms with near-identical statements.

    Uses a simple normalized-statement hash. Atoms whose statements
    normalize to the same string are considered duplicates. Returns
    only clusters of size 2 or more (singletons are not duplicates).
    """
    def normalize(s: str) -> str:
        # Strip punctuation, lowercase, collapse whitespace, remove common
        # filler tokens and possessives that don't change meaning.
        s = s.lower()
        s = s.replace("'s", "")  # possessive
        s = s.replace("'", "")   # other apostrophes
        s = re.sub(r"[.,;:()\[\]{}\-_/]", " ", s)
        s = re.sub(r"\b(the|a|an|of|in|for|to|and|or|s|its)\b", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    clusters: dict[str, list[str]] = defaultdict(list)
    for aid, ta in typed_atoms.items():
        key = (ta.atom_type.name, normalize(ta.statement))
        clusters[key].append(aid)
    return [ids for ids in clusters.values() if len(ids) >= 2]


def _build_duplicate_hint(clusters: list[list[str]]) -> str:
    """Format duplicate-cluster information for the prompt."""
    if not clusters:
        return ""
    lines = ["\n\nDUPLICATE GROUPS (must bind identically within each group):"]
    for i, cluster in enumerate(clusters, 1):
        lines.append(f"  Group {i}: {', '.join(cluster)}")
    return "\n".join(lines)


class StructuredOutputSubstrate(Substrate):
    """Single-call structured-extraction substrate.

    Drop-in replacement for TypedNarrativeLLMSubstrate when you want
    one LLM call per case instead of one per atom.

    Args:
        llm: LLMCaller (used once per bind_typed call)
        max_tokens: response token budget (default 8192 — enough for
            ~200 atom bindings comfortably)
        detect_duplicates: when True, cluster semantically-equivalent
            atoms and signal them to the LLM. Default True.
    """

    def __init__(self, llm: LLMCaller, max_tokens: int = 8192,
                 detect_duplicates: bool = True):
        self.llm = llm
        self.max_tokens = max_tokens
        self.detect_duplicates = detect_duplicates
        self.last_audit: dict = {}  # populated after each bind_typed call

    def bind(self, evidence: str,
             atoms: dict[str, Atom]) -> FactBundle:
        """Backward-compat: treats all atoms as Boolean."""
        typed_atoms = {aid: TypedAtom(a, AtomType.BOOLEAN)
                       for aid, a in atoms.items()}
        return self.bind_typed(evidence, typed_atoms)

    def bind_typed(self, evidence: str,
                   typed_atoms: dict[str, TypedAtom]) -> FactBundle:
        """Single-call extraction over all typed atoms."""
        if not typed_atoms:
            self.last_audit = {"atoms": 0, "calls": 0}
            return FactBundle(values={})

        # Detect duplicates (atoms with same normalized statement)
        clusters = (_compute_duplicate_clusters(typed_atoms)
                    if self.detect_duplicates else [])

        # Build the atom listing
        listing_lines = []
        for aid in sorted(typed_atoms.keys()):
            ta = typed_atoms[aid]
            kind = "BOOL" if ta.atom_type == AtomType.BOOLEAN else "NUM"
            listing_lines.append(f"  [{kind}] {aid} : {ta.statement}")
        atom_listing = "\n".join(listing_lines)

        # Format the prompt
        prompt = STRUCTURED_BIND_PROMPT.format(
            description=evidence,
            atom_listing=atom_listing,
            duplicate_hint=_build_duplicate_hint(clusters),
        )

        # One call. Lower max_tokens than default since we expect
        # compact JSON.
        raw = self.llm.call(
            "map_structured_bind",
            prompt,
            max_tokens=self.max_tokens,
        )

        # Parse — _parse_json_response handles reasoning-then-JSON
        try:
            parsed = _parse_json_response(raw)
        except Exception as e:
            self.last_audit = {
                "error": f"JSON parse failed: {e}",
                "raw_response_preview": raw[:500] if raw else "",
                "atoms": len(typed_atoms),
                "calls": 1,
            }
            # Return all atoms as UNDETERMINED — better than crashing
            values = {}
            for aid, ta in typed_atoms.items():
                if ta.atom_type == AtomType.NUMERIC:
                    values[aid] = NumericValue.undetermined()
                else:
                    values[aid] = Kleene.UNDETERMINED
            return FactBundle(values=values)

        # Convert parsed values to FactBundle values
        all_values: dict[str, Union[Kleene, NumericValue]] = {}
        for aid, ta in typed_atoms.items():
            raw_val = parsed.get(aid)
            if ta.atom_type == AtomType.NUMERIC:
                all_values[aid] = _parse_numeric(raw_val)
            else:
                all_values[aid] = _parse_kleene(raw_val
                                                 if raw_val is not None
                                                 else "undetermined")

        # Verify duplicate clusters — same value? Log mismatches.
        cluster_findings = []
        for cluster in clusters:
            cluster_values = {aid: all_values[aid] for aid in cluster}
            distinct = set()
            for v in cluster_values.values():
                if isinstance(v, NumericValue):
                    distinct.add(("numeric",
                                  "undetermined" if v.is_undetermined()
                                  else str(v.value)))
                else:
                    distinct.add(("kleene", str(v)))
            if len(distinct) > 1:
                cluster_findings.append({
                    "cluster": cluster,
                    "distinct_values": [
                        {"atom_id": aid, "value": _value_to_str(v)}
                        for aid, v in cluster_values.items()
                    ],
                })

        self.last_audit = {
            "atoms": len(typed_atoms),
            "atoms_bound_to_value": sum(
                1 for v in all_values.values()
                if not _is_undetermined(v)),
            "atoms_undetermined": sum(
                1 for v in all_values.values()
                if _is_undetermined(v)),
            "calls": 1,
            "duplicate_clusters_detected": len(clusters),
            "duplicate_cluster_inconsistencies": cluster_findings,
            "raw_response_chars": len(raw),
        }

        return FactBundle(values=all_values)


def _is_undetermined(v) -> bool:
    if isinstance(v, NumericValue):
        return v.is_undetermined()
    if isinstance(v, Kleene):
        return v == Kleene.UNDETERMINED
    return False


def _value_to_str(v) -> str:
    if isinstance(v, NumericValue):
        return "undetermined" if v.is_undetermined() else str(v.value)
    if isinstance(v, Kleene):
        return str(v).replace("Kleene.", "")
    return str(v)


def map_case_to_typed_bundle_structured(
    evidence: str,
    typed_atoms: dict[str, TypedAtom],
    substrate: StructuredOutputSubstrate,
) -> FactBundle:
    """Top-level helper, parallel to map_case_to_typed_bundle."""
    return substrate.bind_typed(evidence, typed_atoms)

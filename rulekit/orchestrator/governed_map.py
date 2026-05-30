"""Evidence-aware LLM Map step with governed atom-binding prompts."""
from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from pydantic_core import to_jsonable_python

from rulekit.build.llm import LLMCaller, parse_json_response
from rulekit.contract import BindingBasis, DeterminationProgram
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
    MapExtractionRecord,
)
from rulekit.orchestrator.map_step import (
    MapStepContext,
    MapStepKind,
    MapStepResult,
    MapStepSpec,
)
from rulekit.orchestrator.map_validation import (
    EvidenceSource,
    evidence_sources_from_case_fields,
)


SOURCE_INVENTORY_PROMPT = """You are preparing evidence for a governed policy Map step.

Your job is NOT to decide the policy outcome. Your job is to inventory the
evidence sources and identify what each source can and cannot support.

For each source, return:
- source_id
- source_type
- title
- as_of_date if stated
- closed_world_scopes: factual universes where absence from this source can
  support a negative atom binding
- limitations

Closed-world absence is narrow. A personal statement or open narrative usually
does NOT support closed-world absence. Official checks, search results,
agency records, court records, or complete structured extracts may support it
only within their stated scope.

CASE NARRATIVE
==============
{narrative}

DECLARED SOURCES
================
{declared_sources}

Return ONLY this JSON shape:
{{
  "sources": [
    {{
      "source_id": "source id",
      "source_type": "source type",
      "title": "short title",
      "as_of_date": "YYYY-MM-DD or null",
      "closed_world_scopes": ["scope"],
      "limitations": "limitations"
    }}
  ]
}}
"""


ATOM_BINDING_PROMPT = """You are binding ONE atom for a governed policy engine.

You are NOT deciding the policy outcome. Decide only whether the evidence
supports this atom value, and on what epistemic basis.

Critical rules:
- Do NOT bind an atom to false merely because an open narrative does not mention it.
- If the only reason for false is "not mentioned", return value "undetermined"
  with basis "open_world_absence".
- If a source affirmatively says a fact is absent and that source has a relevant
  closed-world scope, false may use basis "closed_world_absence".
- If sources conflict, return status "undetermined" and basis
  "conflicting_evidence"; do not choose a winner.
- If the atom cannot be answered from the evidence, return status
  "undetermined" and basis "not_found".
- For numeric atoms, extract only stated or directly computed values requested
  by the atom; otherwise return "undetermined".

ATOM
====
{atom_json}

ATOM BINDING POLICY
===================
{policy_json}

SOURCE INVENTORY
================
{sources_json}

CASE NARRATIVE
==============
{narrative}

RELEVANT EVIDENCE
=================
{evidence_text}

Allowed basis values:
explicit_positive, explicit_negative, closed_world_absence, open_world_absence,
inferred_from_record, conflicting_evidence, computed, looked_up, not_found.

Return ONLY this JSON shape:
{{
  "atom_id": "{atom_id}",
  "status": "bound|undetermined|error",
  "value": true,
  "basis": "explicit_positive",
  "source_ids": ["source id"],
  "evidence": "short exact evidence or summary",
  "explanation": "why this basis is appropriate",
  "confidence": 0.0
}}
"""


class GovernedEvidenceMapStep:
    """Map step that asks the LLM for evidence basis, then records it."""

    def __init__(
        self,
        llm: LLMCaller,
        *,
        map_step_id: str = "map_governed_evidence",
        atom_ids: list[str] | None = None,
        max_atoms: int | None = None,
        stream: bool = True,
    ):
        self.llm = llm
        self.atom_ids = atom_ids
        self.max_atoms = max_atoms
        self.stream = stream
        self.spec = MapStepSpec(
            map_step_id=map_step_id,
            name="Governed evidence Map step",
            description="Inventories case sources and binds atoms with epistemic basis.",
            kind=MapStepKind.STOCHASTIC,
            input_schema={"case": "evidence packet", "program": "DeterminationProgram"},
            output_schema={"map_record": "MapExtractionRecord"},
        )

    def run(
        self,
        program: DeterminationProgram,
        case: CaseExample,
        context: MapStepContext,
    ) -> MapStepResult:
        started = perf_counter()
        declared_sources = evidence_sources_from_case_fields(case.structured_fields)
        artifacts: dict[str, Any] = {"atoms": {}}
        sources, source_artifacts = self._inventory_sources(case, declared_sources)
        artifacts["source_inventory"] = source_artifacts
        evidence_by_atom = _evidence_by_atom(case.structured_fields)
        bindings: dict[str, AtomBindingRecord] = {}
        selected_atoms = self._selected_atom_ids(program)
        for atom_id in selected_atoms:
            atom = program.map_spec.atoms[atom_id]
            prompt = build_atom_binding_prompt(
                program,
                atom_id,
                case,
                sources,
                evidence_text=evidence_by_atom.get(atom_id) or case.narrative,
            )
            raw = self.llm.call(
                f"map_governed_atom:{atom_id}",
                prompt,
                stream=self.stream,
            )
            parsed = _parse_binding_payload(atom_id, raw)
            artifacts["atoms"][atom_id] = {
                "prompt": prompt,
                "raw_response": raw,
                "parsed": parsed,
            }
            bindings[atom_id] = _binding_from_payload(atom_id, atom.atom_type, parsed)
        for atom_id, atom in program.map_spec.atoms.items():
            if atom_id not in bindings:
                bindings[atom_id] = AtomBindingRecord(
                    atom_id=atom_id,
                    atom_type=atom.atom_type,
                    value="undetermined",
                    status=AtomBindingStatus.UNDETERMINED,
                    basis=BindingBasis.NOT_FOUND,
                    source=context.substrate_id,
                )
        return MapStepResult(
            map_record=MapExtractionRecord(
                map_record_id=new_id("map"),
                program_id=context.program_id,
                program_version=context.program_version,
                case_id=case.case_id,
                bindings=bindings,
                substrate_id=context.substrate_id,
                latency_s=perf_counter() - started,
                metadata={
                    "map_step_id": self.spec.map_step_id,
                    "source_inventory": [
                        source.model_dump(mode="json") for source in sources
                    ],
                    "prompt_artifacts": artifacts,
                },
            )
        )

    def _inventory_sources(
        self,
        case: CaseExample,
        declared_sources: list[EvidenceSource],
    ) -> tuple[list[EvidenceSource], dict[str, Any]]:
        prompt = build_source_inventory_prompt(case, declared_sources)
        raw = self.llm.call("map_governed_source_inventory", prompt, stream=self.stream)
        parsed = parse_json_response(raw)
        sources_payload = parsed.get("sources", []) if isinstance(parsed, dict) else []
        sources = [
            EvidenceSource.model_validate(source)
            for source in sources_payload
            if isinstance(source, dict)
        ]
        if not sources:
            sources = declared_sources
        return sources, {"prompt": prompt, "raw_response": raw, "parsed": parsed}

    def _selected_atom_ids(self, program: DeterminationProgram) -> list[str]:
        if self.atom_ids:
            selected = [atom_id for atom_id in self.atom_ids if atom_id in program.map_spec.atoms]
        else:
            selected = list(program.map_spec.atoms)
        if self.max_atoms is not None:
            selected = selected[: self.max_atoms]
        return selected


def build_source_inventory_prompt(
    case: CaseExample,
    declared_sources: list[EvidenceSource],
) -> str:
    return SOURCE_INVENTORY_PROMPT.format(
        narrative=case.narrative,
        declared_sources=json.dumps(
            [source.model_dump(mode="json") for source in declared_sources],
            indent=2,
            sort_keys=True,
        ),
    )


def build_atom_binding_prompt(
    program: DeterminationProgram,
    atom_id: str,
    case: CaseExample,
    sources: list[EvidenceSource],
    *,
    evidence_text: str,
) -> str:
    atom = program.map_spec.atoms[atom_id]
    return ATOM_BINDING_PROMPT.format(
        atom_id=atom_id,
        atom_json=json.dumps(to_jsonable_python(atom), indent=2, sort_keys=True),
        policy_json=json.dumps(
            to_jsonable_python(getattr(atom, "binding_policy", None)),
            indent=2,
            sort_keys=True,
        ),
        sources_json=json.dumps(
            [source.model_dump(mode="json") for source in sources],
            indent=2,
            sort_keys=True,
        ),
        narrative=case.narrative,
        evidence_text=evidence_text,
    )


def _parse_binding_payload(atom_id: str, raw: str) -> dict[str, Any]:
    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        return {
            "atom_id": atom_id,
            "status": "error",
            "value": "undetermined",
            "basis": "not_found",
            "source_ids": [],
            "evidence": None,
            "explanation": f"could not parse LLM JSON response: {exc}",
            "confidence": None,
        }
    return parsed if isinstance(parsed, dict) else {}


def _binding_from_payload(
    atom_id: str,
    atom_type: str,
    payload: dict[str, Any],
) -> AtomBindingRecord:
    try:
        status = AtomBindingStatus(str(payload.get("status", "undetermined")).lower())
    except ValueError:
        status = AtomBindingStatus.ERROR
    raw_basis = payload.get("basis")
    try:
        basis = BindingBasis(str(raw_basis).lower()) if raw_basis else BindingBasis.NOT_FOUND
    except ValueError:
        basis = BindingBasis.NOT_FOUND
    return AtomBindingRecord(
        atom_id=atom_id,
        atom_type=atom_type,
        value=payload.get("value", "undetermined"),
        status=status,
        basis=basis,
        source_ids=[str(item) for item in payload.get("source_ids", [])],
        evidence=payload.get("evidence"),
        explanation=payload.get("explanation"),
        confidence=payload.get("confidence"),
        source="governed_llm",
        metadata={"raw_atom_id": payload.get("atom_id")},
    )


def _evidence_by_atom(structured_fields: dict[str, Any]) -> dict[str, str]:
    evidence = structured_fields.get("evidence")
    if not isinstance(evidence, dict):
        return {}
    return {str(key): str(value) for key, value in evidence.items()}


__all__ = [
    "GovernedEvidenceMapStep",
    "SOURCE_INVENTORY_PROMPT",
    "ATOM_BINDING_PROMPT",
    "build_source_inventory_prompt",
    "build_atom_binding_prompt",
]

"""Evidence-aware LLM Map step with governed atom-binding prompts."""
from __future__ import annotations

import json
from math import ceil
from time import perf_counter
from typing import Any

from pydantic_core import to_jsonable_python

from rulekit.build.llm import LLMCaller, parse_json_response
from rulekit.contract import (
    BindingBasis,
    DeterminationProgram,
    safe_program_to_engine,
)
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.evaluation import evaluate_determination_with_map_record
from rulekit.orchestrator.exercise import (
    extract_leaf_path,
    fact_bundle_from_values,
    fact_values_from_map_record,
)
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
    MapExtractionRecord,
)
from rulekit.orchestrator.map_step import (
    apply_case_default_bindings,
    MapStepContext,
    MapStepKind,
    MapStepResult,
    MapStepSpec,
    PreboundFactsMapStep,
)
from rulekit.orchestrator.map_validation import (
    EvidenceSource,
    evidence_sources_from_case_fields,
)
from rulekit.orchestrator.step import RunCost


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


BATCH_ATOM_BINDING_PROMPT = """You are binding MULTIPLE atoms for a governed policy engine.

You are NOT deciding the policy outcome. Decide only whether the evidence
supports each atom value, and on what epistemic basis.

Critical rules:
- Treat each atom independently.
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
- Return one binding object for every atom in ATOMS.

SOURCE INVENTORY
================
{sources_json}

CASE NARRATIVE
==============
{narrative}

ATOMS
=====
{atoms_json}

Allowed basis values:
explicit_positive, explicit_negative, closed_world_absence, open_world_absence,
inferred_from_record, conflicting_evidence, computed, looked_up, not_found.

Return ONLY this JSON shape:
{{
  "bindings": [
    {{
      "atom_id": "atom id from ATOMS",
      "status": "bound|undetermined|error",
      "value": true,
      "basis": "explicit_positive",
      "source_ids": ["source id"],
      "evidence": "short exact evidence or summary",
      "explanation": "why this basis is appropriate",
      "confidence": 0.0
    }}
  ]
}}
"""


SINGLE_MAP_PROMPT = """You are producing a governed Map record for a policy engine.

You are NOT deciding policy outcomes. Your job is only:
1. inventory the evidence sources, and
2. bind every listed atom independently with value, epistemic basis, source ids,
   evidence, explanation, and confidence.

The deterministic RuleKit engine will decide the policy determinations later.
Do not infer a binding from the desired or likely determination outcome.

Critical binding rules:
- Treat each atom independently.
- Return one binding object for every atom in ATOMS.
- Do NOT bind an atom to false merely because an open narrative does not mention it.
- If the only reason for false is "not mentioned", return status "undetermined"
  and basis "open_world_absence".
- If a source affirmatively says a fact is absent and that source has a relevant
  closed-world scope, false may use basis "closed_world_absence".
- If sources conflict, return status "undetermined" and basis
  "conflicting_evidence"; do not choose a winner.
- If the atom cannot be answered from the evidence, return status
  "undetermined" and basis "not_found".
- For numeric atoms, extract only stated or directly computed values requested
  by the atom; otherwise return "undetermined".

For each source, return:
- source_id
- source_type
- title
- as_of_date if stated
- closed_world_scopes: factual universes where absence from this source can
  support a negative atom binding
- limitations

Allowed basis values:
explicit_positive, explicit_negative, closed_world_absence, open_world_absence,
inferred_from_record, conflicting_evidence, computed, looked_up, not_found.

CASE NARRATIVE
==============
{narrative}

DECLARED SOURCES
================
{declared_sources}

ATOMS
=====
{atoms_json}

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
  ],
  "bindings": [
    {{
      "atom_id": "atom id from ATOMS",
      "status": "bound|undetermined|error",
      "value": true,
      "basis": "explicit_positive",
      "source_ids": ["source id"],
      "evidence": "short exact evidence or summary",
      "explanation": "why this basis is appropriate",
      "confidence": 0.0
    }}
  ]
}}
"""


REPAIR_ATOM_BINDING_PROMPT = """You are repairing selected atom bindings for a governed policy engine.

You are NOT deciding policy outcomes. The deterministic engine has already
identified these atoms as unresolved on a load-bearing trace. Your job is only
to revisit the listed atom bindings from the case packet and return improved
bindings where the evidence supports them.

Rules:
- Treat each atom independently.
- Do not change an atom just to make a determination true or false.
- If the case packet still does not support a value, keep it undetermined.
- If a conditional support atom is phrased like "if needed", "if applicable",
  "if initial fail", or "when applicable", and the triggering condition is
  clearly absent, it may bind true with basis "inferred_from_record" because the
  branch is not applicable.
- Return one binding object for every atom in REPAIR_ATOMS.

Allowed basis values:
explicit_positive, explicit_negative, closed_world_absence, open_world_absence,
inferred_from_record, conflicting_evidence, computed, looked_up, not_found.

CASE NARRATIVE
==============
{narrative}

SOURCE INVENTORY
================
{sources_json}

REPAIR_ATOMS
============
{repair_atoms_json}

Return ONLY this JSON shape:
{{
  "bindings": [
    {{
      "atom_id": "atom id from REPAIR_ATOMS",
      "status": "bound|undetermined|error",
      "value": true,
      "basis": "explicit_positive",
      "source_ids": ["source id"],
      "evidence": "short exact evidence or summary",
      "explanation": "why this basis is appropriate",
      "confidence": 0.0
    }}
  ]
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
        pricing: dict[tuple[str, str], tuple[float, float]] | None = None,
        batch_size: int = 1,
        single_map_call: bool = False,
    ):
        self.llm = llm
        self.atom_ids = atom_ids
        self.max_atoms = max_atoms
        self.stream = stream
        self.pricing = pricing or {}
        self.batch_size = max(1, batch_size)
        self.single_map_call = single_map_call
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
        call_metrics: list[dict[str, Any]] = []
        evidence_by_atom = _evidence_by_atom(case.structured_fields)
        prebound_result = PreboundFactsMapStep(
            map_step_id=f"{self.spec.map_step_id}_prebind"
        ).run(program, case, context)
        bindings: dict[str, AtomBindingRecord] = {
            atom_id: binding.model_copy(deep=True)
            for atom_id, binding in prebound_result.map_record.bindings.items()
        }
        selected_atoms = self._selected_atom_ids(program)
        llm_atoms, llm_atom_selection = _initial_llm_atom_selection(
            program,
            context,
            prebound_result.map_record,
            selected_atoms,
        )
        artifacts["prebinding"] = {
            "llm_atom_ids": llm_atoms,
            "llm_atom_selection": llm_atom_selection,
            "selected_atom_count": len(selected_atoms),
            "prebound_skip_count": len(selected_atoms) - len(llm_atoms),
            "prebound_map_record_id": prebound_result.map_record.map_record_id,
            "default_binding_count": prebound_result.map_record.metadata.get(
                "default_binding_count",
                0,
            ),
        }
        if self.single_map_call:
            sources = self._bind_single_map_call(
                program,
                case,
                llm_atoms,
                declared_sources,
                evidence_by_atom,
                artifacts,
                call_metrics,
                bindings,
            )
        else:
            if llm_atoms:
                sources, source_artifacts = self._inventory_sources(
                    case,
                    declared_sources,
                    call_metrics,
                )
                artifacts["source_inventory"] = source_artifacts
            else:
                sources = declared_sources
                artifacts["source_inventory"] = {
                    "skipped": True,
                    "reason": "all selected atoms were prebound",
                    "parsed": {
                        "sources": [
                            source.model_dump(mode="json") for source in declared_sources
                        ]
                    },
                }
        if self.single_map_call:
            pass
        elif self.batch_size == 1:
            self._bind_atoms_one_by_one(
                program,
                case,
                sources,
                evidence_by_atom,
                artifacts,
                call_metrics,
                bindings,
                atom_ids=llm_atoms,
            )
        else:
            self._bind_atoms_in_batches(
                program,
                case,
                llm_atoms,
                sources,
                evidence_by_atom,
                artifacts,
                call_metrics,
                bindings,
            )
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
        default_count = apply_case_default_bindings(
            program,
            case,
            bindings,
            source=context.substrate_id,
        )
        total_default_count = (
            int(prebound_result.map_record.metadata.get("default_binding_count", 0))
            + default_count
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
                cost=_aggregate_call_metrics(call_metrics),
                metadata={
                    "map_step_id": self.spec.map_step_id,
                    "source_inventory": [
                        source.model_dump(mode="json") for source in sources
                    ],
                    "default_binding_count": total_default_count,
                    "prebound_default_binding_count": prebound_result.map_record.metadata.get(
                        "default_binding_count",
                        0,
                    ),
                    "post_llm_default_binding_count": default_count,
                    "selected_atom_count": len(selected_atoms),
                    "llm_atom_count": len(llm_atoms),
                    "prebound_skip_count": len(selected_atoms) - len(llm_atoms),
                    "llm_atom_selection": llm_atom_selection,
                    "llm_call_metrics": call_metrics,
                    "prompt_artifacts": artifacts,
                    "single_map_call": self.single_map_call,
                },
            )
        )

    def repair_bindings(
        self,
        program: DeterminationProgram,
        case: CaseExample,
        map_record: MapExtractionRecord,
        atom_ids: list[str],
        *,
        reasons: dict[str, list[str]] | None = None,
    ) -> MapExtractionRecord:
        selected = [atom_id for atom_id in atom_ids if atom_id in program.map_spec.atoms]
        if not selected:
            return map_record
        repaired = map_record.model_copy(deep=True)
        sources = _sources_from_map_record(repaired)
        if not sources:
            sources = evidence_sources_from_case_fields(case.structured_fields)
        evidence_by_atom = _evidence_by_atom(case.structured_fields)
        prompt = build_repair_atom_binding_prompt(
            program,
            selected,
            case,
            sources,
            repaired,
            evidence_by_atom=evidence_by_atom,
            reasons=reasons or {},
        )
        raw, cost, metrics = self._call_llm("map_governed_repair", prompt)
        parsed_by_atom = _parse_batch_binding_payloads(selected, raw)
        artifacts = repaired.metadata.setdefault("prompt_artifacts", {})
        repair_artifacts = artifacts.setdefault("repairs", [])
        repair_artifacts.append(
            {
                "atom_ids": selected,
                "prompt": prompt,
                "raw_response": raw,
                "parsed": parsed_by_atom,
                "metrics": cost.model_dump(mode="json"),
            }
        )
        atoms_artifacts = artifacts.setdefault("atoms", {})
        for atom_id in selected:
            atom = program.map_spec.atoms[atom_id]
            parsed = parsed_by_atom.get(atom_id) or _error_payload(
                atom_id,
                "repair response did not include this atom",
            )
            repaired.bindings[atom_id] = _binding_from_payload(
                atom_id,
                atom.atom_type,
                parsed,
            )
            repaired.bindings[atom_id].metadata["repaired"] = True
            atoms_artifacts.setdefault(atom_id, {})["repair"] = {
                "parsed": parsed,
                "metrics": cost.model_dump(mode="json"),
            }
        call_metrics = repaired.metadata.setdefault("llm_call_metrics", [])
        call_metrics.append(metrics)
        repaired.cost = _aggregate_call_metrics(call_metrics)
        repaired.latency_s = (repaired.latency_s or 0.0) + (cost.latency_s or 0.0)
        repaired.metadata["repair_count"] = repaired.metadata.get("repair_count", 0) + 1
        repaired.metadata["repaired_atoms"] = sorted(
            set(repaired.metadata.get("repaired_atoms", [])) | set(selected)
        )
        return repaired

    def _bind_single_map_call(
        self,
        program: DeterminationProgram,
        case: CaseExample,
        selected_atoms: list[str],
        declared_sources: list[EvidenceSource],
        evidence_by_atom: dict[str, str],
        artifacts: dict[str, Any],
        call_metrics: list[dict[str, Any]],
        bindings: dict[str, AtomBindingRecord],
    ) -> list[EvidenceSource]:
        if not selected_atoms:
            artifacts["single_map"] = {
                "atom_ids": [],
                "skipped": True,
                "reason": "all selected atoms were prebound",
            }
            artifacts["source_inventory"] = {
                "skipped": True,
                "reason": "all selected atoms were prebound",
                "parsed": {
                    "sources": [
                        source.model_dump(mode="json") for source in declared_sources
                    ]
                },
                "from_single_map_call": True,
            }
            return declared_sources
        prompt = build_single_map_prompt(
            program,
            selected_atoms,
            case,
            declared_sources,
            evidence_by_atom=evidence_by_atom,
        )
        raw, cost, metrics = self._call_llm("map_governed_single_map", prompt)
        call_metrics.append(metrics)
        sources, parsed_by_atom, parsed = _parse_single_map_payload(
            selected_atoms,
            raw,
            declared_sources,
        )
        artifacts["single_map"] = {
            "atom_ids": selected_atoms,
            "prompt": prompt,
            "raw_response": raw,
            "parsed": parsed,
            "metrics": cost.model_dump(mode="json"),
        }
        artifacts["source_inventory"] = {
            "prompt": prompt,
            "raw_response": raw,
            "parsed": {"sources": [source.model_dump(mode="json") for source in sources]},
            "metrics": cost.model_dump(mode="json"),
            "from_single_map_call": True,
        }
        for atom_id in selected_atoms:
            atom = program.map_spec.atoms[atom_id]
            parsed_binding = parsed_by_atom.get(atom_id) or _error_payload(
                atom_id,
                "single-map response did not include this atom",
            )
            artifacts["atoms"][atom_id] = {
                "single_map": True,
                "parsed": parsed_binding,
                "metrics": cost.model_dump(mode="json"),
            }
            bindings[atom_id] = _binding_from_payload(
                atom_id,
                atom.atom_type,
                parsed_binding,
            )
        return sources

    def _bind_atoms_one_by_one(
        self,
        program: DeterminationProgram,
        case: CaseExample,
        sources: list[EvidenceSource],
        evidence_by_atom: dict[str, str],
        artifacts: dict[str, Any],
        call_metrics: list[dict[str, Any]],
        bindings: dict[str, AtomBindingRecord],
        atom_ids: list[str] | None = None,
    ) -> None:
        selected = atom_ids if atom_ids is not None else self._selected_atom_ids(program)
        for atom_id in selected:
            atom = program.map_spec.atoms[atom_id]
            prompt = build_atom_binding_prompt(
                program,
                atom_id,
                case,
                sources,
                evidence_text=evidence_by_atom.get(atom_id) or case.narrative,
            )
            raw, cost, metrics = self._call_llm(
                f"map_governed_atom:{atom_id}",
                prompt,
            )
            call_metrics.append(metrics)
            parsed = _parse_binding_payload(atom_id, raw)
            artifacts["atoms"][atom_id] = {
                "prompt": prompt,
                "raw_response": raw,
                "parsed": parsed,
                "metrics": cost.model_dump(mode="json"),
            }
            bindings[atom_id] = _binding_from_payload(atom_id, atom.atom_type, parsed)

    def _bind_atoms_in_batches(
        self,
        program: DeterminationProgram,
        case: CaseExample,
        selected_atoms: list[str],
        sources: list[EvidenceSource],
        evidence_by_atom: dict[str, str],
        artifacts: dict[str, Any],
        call_metrics: list[dict[str, Any]],
        bindings: dict[str, AtomBindingRecord],
    ) -> None:
        artifacts["batches"] = []
        for index, atom_ids in enumerate(_chunks(selected_atoms, self.batch_size), start=1):
            prompt = build_batch_atom_binding_prompt(
                program,
                atom_ids,
                case,
                sources,
                evidence_by_atom=evidence_by_atom,
            )
            raw, cost, metrics = self._call_llm(
                f"map_governed_atom_batch:{index}",
                prompt,
            )
            call_metrics.append(metrics)
            parsed_by_atom = _parse_batch_binding_payloads(atom_ids, raw)
            batch_artifact = {
                "atom_ids": atom_ids,
                "prompt": prompt,
                "raw_response": raw,
                "parsed": parsed_by_atom,
                "metrics": cost.model_dump(mode="json"),
            }
            artifacts["batches"].append(batch_artifact)
            for atom_id in atom_ids:
                atom = program.map_spec.atoms[atom_id]
                parsed = parsed_by_atom.get(atom_id) or _error_payload(
                    atom_id,
                    "batch response did not include this atom",
                )
                artifacts["atoms"][atom_id] = {
                    "batch_index": index,
                    "prompt": prompt,
                    "raw_response": raw,
                    "parsed": parsed,
                    "metrics": cost.model_dump(mode="json"),
                }
                bindings[atom_id] = _binding_from_payload(
                    atom_id,
                    atom.atom_type,
                    parsed,
                )

    def _inventory_sources(
        self,
        case: CaseExample,
        declared_sources: list[EvidenceSource],
        call_metrics: list[dict[str, Any]],
    ) -> tuple[list[EvidenceSource], dict[str, Any]]:
        prompt = build_source_inventory_prompt(case, declared_sources)
        raw, cost, metrics = self._call_llm("map_governed_source_inventory", prompt)
        call_metrics.append(metrics)
        parsed = parse_json_response(raw)
        sources_payload = parsed.get("sources", []) if isinstance(parsed, dict) else []
        sources = [
            EvidenceSource.model_validate(source)
            for source in sources_payload
            if isinstance(source, dict)
        ]
        if not sources:
            sources = declared_sources
        return sources, {
            "prompt": prompt,
            "raw_response": raw,
            "parsed": parsed,
            "metrics": cost.model_dump(mode="json"),
        }

    def _selected_atom_ids(self, program: DeterminationProgram) -> list[str]:
        if self.atom_ids:
            selected = [atom_id for atom_id in self.atom_ids if atom_id in program.map_spec.atoms]
        else:
            selected = list(program.map_spec.atoms)
        if self.max_atoms is not None:
            selected = selected[: self.max_atoms]
        return selected

    def _call_llm(
        self,
        stage_name: str,
        prompt: str,
    ) -> tuple[str, RunCost, dict[str, Any]]:
        started = perf_counter()
        raw = self.llm.call(stage_name, prompt, stream=self.stream)
        latency_s = perf_counter() - started
        cost = _estimate_run_cost(
            provider=self.llm.provider,
            model=self.llm.model,
            prompt=prompt,
            response=raw,
            latency_s=latency_s,
            pricing=self.pricing,
        )
        metrics = {
            "stage_name": stage_name,
            "provider": self.llm.provider,
            "model": self.llm.model,
            "pricing_basis": (
                "configured_usd_per_million_tokens"
                if cost.estimated_cost_usd is not None
                else "not_configured"
            ),
            **cost.model_dump(mode="json"),
        }
        return raw, cost, metrics


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


def build_batch_atom_binding_prompt(
    program: DeterminationProgram,
    atom_ids: list[str],
    case: CaseExample,
    sources: list[EvidenceSource],
    *,
    evidence_by_atom: dict[str, str],
) -> str:
    atoms_payload = []
    for atom_id in atom_ids:
        atom = program.map_spec.atoms[atom_id]
        atoms_payload.append(
            {
                "atom": to_jsonable_python(atom),
                "binding_policy": to_jsonable_python(
                    getattr(atom, "binding_policy", None)
                ),
                "relevant_evidence": evidence_by_atom.get(atom_id) or case.narrative,
            }
        )
    return BATCH_ATOM_BINDING_PROMPT.format(
        sources_json=json.dumps(
            [source.model_dump(mode="json") for source in sources],
            indent=2,
            sort_keys=True,
        ),
        narrative=case.narrative,
        atoms_json=json.dumps(atoms_payload, indent=2, sort_keys=True),
    )


def build_single_map_prompt(
    program: DeterminationProgram,
    atom_ids: list[str],
    case: CaseExample,
    declared_sources: list[EvidenceSource],
    *,
    evidence_by_atom: dict[str, str],
) -> str:
    atoms_payload = []
    for atom_id in atom_ids:
        atom = program.map_spec.atoms[atom_id]
        atoms_payload.append(
            {
                "atom": to_jsonable_python(atom),
                "binding_policy": to_jsonable_python(
                    getattr(atom, "binding_policy", None)
                ),
                "relevant_evidence": evidence_by_atom.get(atom_id) or case.narrative,
            }
        )
    return SINGLE_MAP_PROMPT.format(
        narrative=case.narrative,
        declared_sources=json.dumps(
            [source.model_dump(mode="json") for source in declared_sources],
            indent=2,
            sort_keys=True,
        ),
        atoms_json=json.dumps(atoms_payload, indent=2, sort_keys=True),
    )


def build_repair_atom_binding_prompt(
    program: DeterminationProgram,
    atom_ids: list[str],
    case: CaseExample,
    sources: list[EvidenceSource],
    map_record: MapExtractionRecord,
    *,
    evidence_by_atom: dict[str, str],
    reasons: dict[str, list[str]],
) -> str:
    atoms_payload = []
    for atom_id in atom_ids:
        atom = program.map_spec.atoms[atom_id]
        current = map_record.bindings.get(atom_id)
        atoms_payload.append(
            {
                "atom": to_jsonable_python(atom),
                "binding_policy": to_jsonable_python(
                    getattr(atom, "binding_policy", None)
                ),
                "current_binding": (
                    current.model_dump(mode="json") if current is not None else None
                ),
                "repair_reasons": reasons.get(atom_id, []),
                "relevant_evidence": evidence_by_atom.get(atom_id) or case.narrative,
            }
        )
    return REPAIR_ATOM_BINDING_PROMPT.format(
        narrative=case.narrative,
        sources_json=json.dumps(
            [source.model_dump(mode="json") for source in sources],
            indent=2,
            sort_keys=True,
        ),
        repair_atoms_json=json.dumps(atoms_payload, indent=2, sort_keys=True),
    )


def _parse_binding_payload(atom_id: str, raw: str) -> dict[str, Any]:
    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        return _error_payload(atom_id, f"could not parse LLM JSON response: {exc}")
    return parsed if isinstance(parsed, dict) else {}


def _parse_batch_binding_payloads(atom_ids: list[str], raw: str) -> dict[str, dict[str, Any]]:
    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        return {
            atom_id: _error_payload(atom_id, f"could not parse LLM JSON response: {exc}")
            for atom_id in atom_ids
        }
    if not isinstance(parsed, dict):
        return {
            atom_id: _error_payload(atom_id, "batch response was not a JSON object")
            for atom_id in atom_ids
        }
    bindings = parsed.get("bindings", [])
    if not isinstance(bindings, list):
        return {
            atom_id: _error_payload(atom_id, "batch response did not include bindings")
            for atom_id in atom_ids
        }
    by_atom: dict[str, dict[str, Any]] = {}
    for item in bindings:
        if isinstance(item, dict) and item.get("atom_id") is not None:
            by_atom[str(item["atom_id"])] = item
    return by_atom


def _parse_single_map_payload(
    atom_ids: list[str],
    raw: str,
    declared_sources: list[EvidenceSource],
) -> tuple[list[EvidenceSource], dict[str, dict[str, Any]], dict[str, Any]]:
    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        return (
            declared_sources,
            {
                atom_id: _error_payload(atom_id, f"could not parse LLM JSON response: {exc}")
                for atom_id in atom_ids
            },
            {"parse_error": str(exc), "raw": raw},
        )
    if not isinstance(parsed, dict):
        return (
            declared_sources,
            {
                atom_id: _error_payload(atom_id, "single-map response was not a JSON object")
                for atom_id in atom_ids
            },
            {"parse_error": "single-map response was not a JSON object", "raw": raw},
        )

    sources_payload = parsed.get("sources", [])
    sources = [
        EvidenceSource.model_validate(source)
        for source in sources_payload
        if isinstance(source, dict)
    ]
    if not sources:
        sources = declared_sources

    bindings = parsed.get("bindings", [])
    if not isinstance(bindings, list):
        return (
            sources,
            {
                atom_id: _error_payload(atom_id, "single-map response did not include bindings")
                for atom_id in atom_ids
            },
            parsed,
        )
    by_atom: dict[str, dict[str, Any]] = {}
    for item in bindings:
        if isinstance(item, dict) and item.get("atom_id") is not None:
            by_atom[str(item["atom_id"])] = item
    return sources, by_atom, parsed


def _error_payload(atom_id: str, explanation: str) -> dict[str, Any]:
    return {
        "atom_id": atom_id,
        "status": "error",
        "value": "undetermined",
        "basis": "not_found",
        "source_ids": [],
        "evidence": None,
        "explanation": explanation,
        "confidence": None,
    }


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


def _sources_from_map_record(map_record: MapExtractionRecord) -> list[EvidenceSource]:
    payload = map_record.metadata.get("source_inventory", [])
    if not isinstance(payload, list):
        return []
    sources: list[EvidenceSource] = []
    for item in payload:
        if isinstance(item, dict):
            sources.append(EvidenceSource.model_validate(item))
    return sources


def _binding_needs_llm_mapping(binding: AtomBindingRecord | None) -> bool:
    if binding is None:
        return True
    default_kind = binding.metadata.get("default_kind")
    if default_kind in {"evidence_gap", "out_of_scope", "branch_not_applicable"}:
        return False
    if binding.status == AtomBindingStatus.ERROR:
        return True
    value = binding.value
    if binding.status == AtomBindingStatus.BOUND and str(value).lower() != "undetermined":
        return False
    if binding.metadata.get("case_default"):
        return False
    if value is None or str(value).lower() == "undetermined":
        return True
    return binding.basis in {
        BindingBasis.CONFLICTING_EVIDENCE,
        BindingBasis.OPEN_WORLD_ABSENCE,
        BindingBasis.NOT_FOUND,
    }


def _initial_llm_atom_selection(
    program: DeterminationProgram,
    context: MapStepContext,
    prebound_map_record: MapExtractionRecord,
    selected_atoms: list[str],
) -> tuple[list[str], dict[str, Any]]:
    static_atoms = [
        atom_id
        for atom_id in selected_atoms
        if _binding_needs_llm_mapping(prebound_map_record.bindings.get(atom_id))
    ]
    determinations = context.metadata.get("determinations")
    if not isinstance(determinations, list) or not determinations:
        return static_atoms, {
            "mode": "static_unresolved",
            "reason": "no requested determinations in Map context",
            "static_unresolved_count": len(static_atoms),
        }

    try:
        runtime = safe_program_to_engine(program)
        bundle = fact_bundle_from_values(
            program,
            fact_values_from_map_record(prebound_map_record),
            evidence={
                atom_id: binding.evidence
                for atom_id, binding in prebound_map_record.bindings.items()
                if binding.evidence
            },
        )
    except Exception as exc:
        return static_atoms, {
            "mode": "static_unresolved",
            "reason": f"prebound sufficiency evaluation failed: {exc}",
            "static_unresolved_count": len(static_atoms),
        }

    selected_set = set(selected_atoms)
    trace_atoms: list[str] = []
    disposition_summaries: list[dict[str, Any]] = []
    for det_id in [str(item) for item in determinations]:
        if det_id not in program.determinations:
            continue
        try:
            evaluation = evaluate_determination_with_map_record(
                program,
                runtime,
                det_id,
                bundle,
                prebound_map_record,
            )
        except Exception as exc:
            disposition_summaries.append(
                {
                    "determination_id": det_id,
                    "outcome": "error",
                    "reason": str(exc),
                }
            )
            continue
        outcome = str(evaluation.outcome)
        load_bearing = extract_leaf_path(evaluation.trace)
        disposition_summaries.append(
            {
                "determination_id": det_id,
                "outcome": outcome,
                "load_bearing_count": len(load_bearing),
            }
        )
        if outcome != "undetermined":
            continue
        for atom_id in load_bearing:
            if atom_id not in selected_set:
                continue
            if atom_id in trace_atoms:
                continue
            if _binding_needs_llm_mapping(prebound_map_record.bindings.get(atom_id)):
                trace_atoms.append(atom_id)

    return trace_atoms, {
        "mode": "trace_guided_unresolved",
        "static_unresolved_count": len(static_atoms),
        "trace_unresolved_count": len(trace_atoms),
        "dispositions": disposition_summaries,
    }


def _evidence_by_atom(structured_fields: dict[str, Any]) -> dict[str, str]:
    evidence = structured_fields.get("evidence")
    if not isinstance(evidence, dict):
        return {}
    return {str(key): str(value) for key, value in evidence.items()}


def _estimate_run_cost(
    *,
    provider: str,
    model: str,
    prompt: str,
    response: str,
    latency_s: float,
    pricing: dict[tuple[str, str], tuple[float, float]],
) -> RunCost:
    input_tokens = _estimate_tokens(prompt)
    output_tokens = _estimate_tokens(response)
    estimated_cost_usd = None
    price = _lookup_price(pricing, provider, model)
    if price is not None:
        input_price, output_price = price
        estimated_cost_usd = (
            input_tokens * input_price + output_tokens * output_price
        ) / 1_000_000
    return RunCost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=estimated_cost_usd,
        latency_s=latency_s,
    )


def _lookup_price(
    pricing: dict[tuple[str, str], tuple[float, float]],
    provider: str,
    model: str,
) -> tuple[float, float] | None:
    return pricing.get((provider, model)) or pricing.get((provider, "*"))


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, ceil(len(text) / 4))


def _aggregate_call_metrics(call_metrics: list[dict[str, Any]]) -> RunCost:
    input_tokens = sum(metric.get("input_tokens") or 0 for metric in call_metrics)
    output_tokens = sum(metric.get("output_tokens") or 0 for metric in call_metrics)
    costs = [
        metric["estimated_cost_usd"]
        for metric in call_metrics
        if metric.get("estimated_cost_usd") is not None
    ]
    return RunCost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=sum(costs) if costs else None,
        latency_s=sum(metric.get("latency_s") or 0.0 for metric in call_metrics),
    )


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


__all__ = [
    "GovernedEvidenceMapStep",
    "SOURCE_INVENTORY_PROMPT",
    "ATOM_BINDING_PROMPT",
    "BATCH_ATOM_BINDING_PROMPT",
    "SINGLE_MAP_PROMPT",
    "REPAIR_ATOM_BINDING_PROMPT",
    "build_source_inventory_prompt",
    "build_atom_binding_prompt",
    "build_batch_atom_binding_prompt",
    "build_single_map_prompt",
    "build_repair_atom_binding_prompt",
]

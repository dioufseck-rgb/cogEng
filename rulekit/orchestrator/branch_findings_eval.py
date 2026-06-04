"""Branch-level LLM findings with deterministic final disposition composition."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic_core import to_jsonable_python

from rulekit.build.llm import LLMCaller, parse_json_response
from rulekit.contract import DeterminationProgram
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.config import load_policy_workspace_seed
from rulekit.orchestrator.direct_disposition_eval import pricing_from_specs
from rulekit.orchestrator.governed_map import _estimate_run_cost
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.map_governance_eval import parse_model_spec
from rulekit.runtime import load_program, load_runtime_cases


BRANCH_FINDINGS_PROMPT = """You are producing branch-level findings for a policy engine.

You are NOT deciding the final disposition directly. Your job is to evaluate
each listed branch at the branch level, preserving applicability, satisfaction,
and whether the branch blocks final compliance. A deterministic composer will
compute the final disposition from your branch findings.

Important:
- Return only JSON.
- Do not invent facts not in the case packet.
- Work at the branch level, not microscopic atom level.
- Each branch finding must include material_findings: branch-scoped audit slots
  that explain the conclusion. These are not microscopic policy atoms. They
  are the few material facts needed to audit applicability, satisfaction,
  non-applicability, blocking, uncertainty, or routing.
- Prefer stable material slot names such as branch_applicability,
  triggering_event, timing, required_action, content_or_scope,
  correction_or_treatment, notice_or_reporting, exception_or_short_circuit,
  failure_fact, uncertainty, and evidence_conflict.
- A branch can be not applicable. If a determination is described as
  "satisfied or not applicable", then not applicable usually means outcome
  true and blocks_final false.
- For event-validity branches such as frivolous termination validity, no event
  invoked means outcome false but blocks_final false.
- Do not import a failure from one branch into another branch unless that
  branch itself requires it.
- If a branch is applicable and failed, set blocks_final true.
- If a branch is applicable and genuinely unresolved, set blocks_final
  "undetermined".
- If a branch is satisfied or not applicable, set blocks_final false.
- Routing is separate from substantive compliance. Return routing in
  routing_findings, not as a final-disposition blocker unless the policy says
  routing itself changes the final disposition.

POLICY SUMMARY
==============
{policy_text}

ACTIVE PERSPECTIVE
==================
{active_perspective_json}

PROFILE GUIDANCE
================
{profile_guidance_json}

BRANCH DETERMINATIONS
=====================
{branch_determinations_json}

ROUTING DETERMINATIONS
======================
{routing_determinations_json}

CASE PACKET
===========
{case_json}

Return ONLY this JSON shape:
{{
  "case_id": "{case_id}",
  "branch_findings": [
    {{
      "determination_id": "id from BRANCH DETERMINATIONS",
      "applicable": true,
      "satisfied": true,
      "outcome": "true|false|undetermined",
      "blocks_final": true,
      "decisive_branch": "short branch label",
      "rationale": "brief reason grounded in the case packet",
      "critical_facts": ["fact"],
      "material_findings": [
        {{
          "slot": "notice_timing",
          "value": "within_5_business_days",
          "status": "established|not_applicable|undetermined|conflicting",
          "basis": "explicit|inferred|profile_default|not_applicable|missing|conflicting",
          "evidence": "short evidence from the case packet",
          "source_ids": ["narrative"],
          "supports": "applicability|satisfaction|blocking|routing|context"
        }}
      ],
      "confidence": 0.0
    }}
  ],
  "routing_findings": [
    {{
      "determination_id": "id from ROUTING DETERMINATIONS",
      "outcome": "true|false|undetermined",
      "rationale": "brief reason grounded in the case packet",
      "material_findings": [
        {{
          "slot": "routing_trigger",
          "value": "none",
          "status": "established|not_applicable|undetermined|conflicting",
          "basis": "explicit|inferred|profile_default|not_applicable|missing|conflicting",
          "evidence": "short evidence from the case packet",
          "source_ids": ["narrative"],
          "supports": "routing"
        }}
      ],
      "confidence": 0.0
    }}
  ],
  "case_level_notes": "brief note or empty string"
}}
"""


def run_branch_findings_eval(
    *,
    program_path: str | Path,
    cases_path: str | Path,
    model_specs: list[str],
    output_dir: str | Path,
    seed_path: str | Path | None = None,
    case_ids: list[str] | None = None,
    determinations: list[str] | None = None,
    final_determination: str | None = None,
    routing_determination: str | None = None,
    max_tokens: int = 12000,
    timeout: float = 180.0,
    max_retries: int = 2,
    pricing: dict[tuple[str, str], tuple[float, float]] | None = None,
) -> dict[str, Any]:
    program = load_program(program_path)
    cases = load_runtime_cases(cases_path)
    if case_ids:
        allowed = set(case_ids)
        cases = [case for case in cases if case.case_id in allowed]
    selected = determinations or list(program.determinations)
    final_id = final_determination or _default_final_determination(program, selected)
    routing_id = routing_determination or _default_routing_determination(program, selected)
    policy_text = _policy_text(program, seed_path)
    references = _expected_outcomes_from_cases(cases)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for spec in model_specs:
        provider, model = parse_model_spec(spec)
        run_dir = output / _safe_name(f"{provider}_{model}")
        run_dir.mkdir(parents=True, exist_ok=True)
        llm = LLMCaller(
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
        )
        result = _run_for_model(
            llm=llm,
            program=program,
            cases=cases,
            policy_text=policy_text,
            selected_determinations=selected,
            final_determination=final_id,
            routing_determination=routing_id,
            references=references,
            pricing=pricing or {},
        )
        _write_run_artifacts(run_dir, result)
        summary = summarize_branch_findings_run(provider, model, result)
        (run_dir / "summary.json").write_text(_json(summary), encoding="utf-8")
        runs.append(summary)
    aggregate = {
        "program": str(program_path),
        "cases": str(cases_path),
        "seed": str(seed_path) if seed_path else None,
        "model_count": len(model_specs),
        "final_determination": final_id,
        "routing_determination": routing_id,
        "runs": runs,
    }
    (output / "summary.json").write_text(_json(aggregate), encoding="utf-8")
    return aggregate


def summarize_branch_findings_run(
    provider: str,
    model: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    dispositions = result["dispositions"]
    outcome_counts = Counter(item["outcome"] for item in dispositions)
    det_agreement = _agreement(dispositions)
    final_id = result["final_determination"]
    routing_id = result.get("routing_determination")
    final_rows = [item for item in dispositions if item["determination_id"] == final_id]
    routing_rows = [
        item for item in dispositions if routing_id and item["determination_id"] == routing_id
    ]
    final_agreement = _agreement(final_rows)
    routing_agreement = _agreement(routing_rows)
    return {
        "provider": provider,
        "model": model,
        "case_count": result["case_count"],
        "map_mode": "branch_findings_llm",
        "final_determination": final_id,
        "routing_determination": routing_id,
        "disposition_count": len(dispositions),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "final_agreement": final_agreement,
        "routing_agreement": routing_agreement,
        "determination_agreement": det_agreement,
        "material_finding_metrics": _material_finding_metrics(result["case_runs"]),
        "cost_metrics": _cost_metrics(result["case_runs"]),
    }


def compose_final_from_branch_findings(findings: list[dict[str, Any]]) -> str:
    blockers = [_normalize_blocker(item.get("blocks_final")) for item in findings]
    if any(value == "true" for value in blockers):
        return "false"
    if any(value == "undetermined" for value in blockers):
        return "undetermined"
    return "true"


def build_branch_findings_prompt(
    *,
    program: DeterminationProgram,
    policy_text: str,
    case: CaseExample,
    branch_determinations: list[str],
    routing_determinations: list[str],
) -> str:
    case_payload = {
        "case_id": case.case_id,
        "title": case.title,
        "narrative": case.narrative,
        "structured_fields": case.structured_fields,
    }
    return BRANCH_FINDINGS_PROMPT.format(
        policy_text=policy_text,
        active_perspective_json=json.dumps(_active_perspective(program), indent=2, sort_keys=True),
        profile_guidance_json=json.dumps(_profile_guidance(program), indent=2, sort_keys=True),
        branch_determinations_json=json.dumps(
            _determination_payload(program, branch_determinations),
            indent=2,
            sort_keys=True,
        ),
        routing_determinations_json=json.dumps(
            _determination_payload(program, routing_determinations),
            indent=2,
            sort_keys=True,
        ),
        case_json=json.dumps(case_payload, indent=2, sort_keys=True),
        case_id=case.case_id,
    )


def _run_for_model(
    *,
    llm: LLMCaller,
    program: DeterminationProgram,
    cases: list[CaseExample],
    policy_text: str,
    selected_determinations: list[str],
    final_determination: str,
    routing_determination: str | None,
    references: dict[tuple[str, str], str],
    pricing: dict[tuple[str, str], tuple[float, float]],
) -> dict[str, Any]:
    routing_ids = [routing_determination] if routing_determination else []
    branch_ids = [
        det_id
        for det_id in selected_determinations
        if det_id not in {final_determination, *routing_ids}
    ]
    case_runs: list[dict[str, Any]] = []
    dispositions: list[dict[str, Any]] = []
    for case in cases:
        prompt = build_branch_findings_prompt(
            program=program,
            policy_text=policy_text,
            case=case,
            branch_determinations=branch_ids,
            routing_determinations=routing_ids,
        )
        started = perf_counter()
        raw = llm.call(f"branch_findings:{case.case_id}", prompt, stream=True)
        latency_s = perf_counter() - started
        cost = _estimate_run_cost(
            provider=llm.provider,
            model=llm.model,
            prompt=prompt,
            response=raw,
            latency_s=latency_s,
            pricing=pricing,
        )
        parsed = _parse_payload(case.case_id, raw)
        branch_findings = _normalize_branch_findings(parsed, branch_ids)
        routing_findings = _normalize_routing_findings(parsed, routing_ids)
        final_outcome = compose_final_from_branch_findings(branch_findings)
        case_runs.append(
            {
                "case_id": case.case_id,
                "prompt": prompt,
                "raw_response": raw,
                "parsed": parsed,
                "branch_findings": branch_findings,
                "routing_findings": routing_findings,
                "computed_final_outcome": final_outcome,
                "cost": cost.model_dump(mode="json"),
            }
        )
        dispositions.extend(
            _dispositions_for_case(
                case=case,
                branch_findings=branch_findings,
                routing_findings=routing_findings,
                final_determination=final_determination,
                final_outcome=final_outcome,
                selected_determinations=selected_determinations,
                references=references,
                cost=cost.model_dump(mode="json"),
            )
        )
    return {
        "program": {
            "name": program.metadata.name,
            "version": program.metadata.version,
            "determination_count": len(program.determinations),
            "atom_count": len(program.map_spec.atoms),
            "node_count": len(program.nodes),
        },
        "case_count": len(cases),
        "map_mode": "branch_findings_llm",
        "final_determination": final_determination,
        "routing_determination": routing_determination,
        "case_runs": case_runs,
        "dispositions": dispositions,
    }


def _dispositions_for_case(
    *,
    case: CaseExample,
    branch_findings: list[dict[str, Any]],
    routing_findings: list[dict[str, Any]],
    final_determination: str,
    final_outcome: str,
    selected_determinations: list[str],
    references: dict[tuple[str, str], str],
    cost: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id = {item["determination_id"]: item for item in branch_findings + routing_findings}
    rows: list[dict[str, Any]] = []
    for det_id in selected_determinations:
        if det_id == final_determination:
            outcome = final_outcome
            rationale = "Deterministically composed from branch findings."
            confidence = None
        else:
            item = by_id.get(det_id, {})
            outcome = _normalize_outcome(item.get("outcome"))
            rationale = item.get("rationale")
            confidence = item.get("confidence")
        reference = references.get((case.case_id, det_id))
        rows.append(
            {
                "disposition_id": new_id("branch_disp"),
                "case_id": case.case_id,
                "case_title": case.title,
                "determination_id": det_id,
                "outcome": outcome,
                "reference_outcome": reference,
                "matches_reference": None if reference is None else outcome == reference,
                "rationale": rationale,
                "confidence": confidence,
                "cost": cost,
            }
        )
    return rows


def _normalize_branch_findings(payload: dict[str, Any], branch_ids: list[str]) -> list[dict[str, Any]]:
    raw_items = payload.get("branch_findings")
    by_id = {
        str(item.get("determination_id")): item
        for item in raw_items
        if isinstance(item, dict) and item.get("determination_id")
    } if isinstance(raw_items, list) else {}
    findings: list[dict[str, Any]] = []
    for det_id in branch_ids:
        item = by_id.get(det_id, {})
        findings.append(
            {
                "determination_id": det_id,
                "applicable": _normalize_boolish(item.get("applicable")),
                "satisfied": _normalize_boolish(item.get("satisfied")),
                "outcome": _normalize_outcome(item.get("outcome")),
                "blocks_final": _normalize_blocker(item.get("blocks_final")),
                "decisive_branch": item.get("decisive_branch"),
                "rationale": item.get("rationale"),
                "critical_facts": item.get("critical_facts") if isinstance(item.get("critical_facts"), list) else [],
                "material_findings": _normalize_material_findings(item.get("material_findings")),
                "confidence": _normalize_confidence(item.get("confidence")),
            }
        )
    return findings


def _normalize_routing_findings(payload: dict[str, Any], routing_ids: list[str]) -> list[dict[str, Any]]:
    raw_items = payload.get("routing_findings")
    by_id = {
        str(item.get("determination_id")): item
        for item in raw_items
        if isinstance(item, dict) and item.get("determination_id")
    } if isinstance(raw_items, list) else {}
    findings: list[dict[str, Any]] = []
    for det_id in routing_ids:
        item = by_id.get(det_id, {})
        findings.append(
            {
                "determination_id": det_id,
                "outcome": _normalize_outcome(item.get("outcome")),
                "rationale": item.get("rationale"),
                "material_findings": _normalize_material_findings(item.get("material_findings")),
                "confidence": _normalize_confidence(item.get("confidence")),
            }
        )
    return findings


def _parse_payload(case_id: str, raw: str) -> dict[str, Any]:
    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        return {
            "case_id": case_id,
            "branch_findings": [],
            "routing_findings": [],
            "case_level_notes": f"could not parse LLM JSON response: {exc}",
        }
    return parsed if isinstance(parsed, dict) else {}


def _default_final_determination(program: DeterminationProgram, selected: list[str]) -> str:
    for candidate in selected:
        if candidate.endswith("dispute_resolution_compliant"):
            return candidate
    for candidate in selected:
        if "compliant" in candidate or "eligible" in candidate:
            return candidate
    return selected[-1]


def _default_routing_determination(
    program: DeterminationProgram,
    selected: list[str],
) -> str | None:
    for candidate in selected:
        det = program.determinations.get(candidate)
        if det is not None and det.determination_kind == "routing":
            return candidate
    for candidate in selected:
        if "human_review" in candidate:
            return candidate
    return None


def _determination_payload(
    program: DeterminationProgram,
    determinations: list[str],
) -> list[dict[str, Any]]:
    return [
        {
            "determination_id": det_id,
            "description": program.determinations[det_id].description,
            "determination_kind": program.determinations[det_id].determination_kind,
            "source_span": program.determinations[det_id].source_span,
        }
        for det_id in determinations
    ]


def _agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    compared = [item for item in rows if item.get("reference_outcome") is not None]
    agree = [item for item in compared if item["outcome"] == item["reference_outcome"]]
    return {
        "compared_count": len(compared),
        "reference_agree_count": len(agree),
        "reference_disagree_count": len(compared) - len(agree),
        "agreement_rate": len(agree) / len(compared) if compared else None,
    }


def _expected_outcomes_from_cases(
    cases: list[CaseExample],
) -> dict[tuple[str, str], str]:
    references: dict[tuple[str, str], str] = {}
    for case in cases:
        for expected in case.expected_outcomes:
            references[(case.case_id, expected.determination_id)] = expected.expected_value
    return references


def _policy_text(program: DeterminationProgram, seed_path: str | Path | None) -> str:
    if seed_path:
        return load_policy_workspace_seed(seed_path).policy_text
    if program.metadata.description:
        return program.metadata.description
    return "No raw policy text was supplied. Use the determination descriptions and case packet."


def _active_perspective(program: DeterminationProgram) -> dict[str, Any]:
    active = program.metadata.extras.get("active_perspective")
    return active if isinstance(active, dict) else {}


def _profile_guidance(program: DeterminationProgram) -> list[dict[str, Any]]:
    profile = program.metadata.extras.get("map_profile")
    if not isinstance(profile, dict):
        return []
    rules = profile.get("default_rules")
    if not isinstance(rules, list):
        return []
    active = _active_perspective(program).get("perspective_id")
    guidance: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        allowed = _string_list(rule.get("perspectives") or rule.get("perspective_ids"))
        if allowed and str(active) not in allowed:
            continue
        guidance.append(
            {
                key: rule[key]
                for key in (
                    "id",
                    "kind",
                    "atom_ids",
                    "value",
                    "basis",
                    "if_any",
                    "if_all",
                    "unless_any",
                    "unless_all",
                    "evidence",
                )
                if key in rule
            }
        )
    return guidance


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def _normalize_outcome(value: Any) -> str:
    normalized = str(value).strip().lower()
    if normalized in {"true", "false", "undetermined"}:
        return normalized
    return "undetermined"


def _normalize_blocker(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return _normalize_outcome(value)


def _normalize_boolish(value: Any) -> bool | str:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "false", "undetermined"}:
        return normalized if normalized == "undetermined" else normalized == "true"
    return "undetermined"


def _normalize_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


_MATERIAL_STATUSES = {"established", "not_applicable", "undetermined", "conflicting"}
_MATERIAL_BASES = {
    "explicit",
    "inferred",
    "profile_default",
    "not_applicable",
    "missing",
    "conflicting",
}
_MATERIAL_SUPPORTS = {
    "applicability",
    "satisfaction",
    "blocking",
    "routing",
    "context",
}


def _normalize_material_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    findings: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        findings.append(
            {
                "slot": _clean_string(item.get("slot")) or "unspecified",
                "value": item.get("value", "undetermined"),
                "status": _normalize_choice(
                    item.get("status"),
                    choices=_MATERIAL_STATUSES,
                    fallback="undetermined",
                ),
                "basis": _normalize_choice(
                    item.get("basis"),
                    choices=_MATERIAL_BASES,
                    fallback="missing",
                ),
                "evidence": _clean_string(item.get("evidence")),
                "source_ids": _string_list(item.get("source_ids")),
                "supports": _normalize_choice(
                    item.get("supports"),
                    choices=_MATERIAL_SUPPORTS,
                    fallback="context",
                ),
            }
        )
    return findings


def _normalize_choice(value: Any, *, choices: set[str], fallback: str) -> str:
    normalized = str(value).strip().lower()
    return normalized if normalized in choices else fallback


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _material_finding_metrics(case_runs: list[dict[str, Any]]) -> dict[str, Any]:
    material_findings: list[dict[str, Any]] = []
    finding_count = 0
    for case_run in case_runs:
        branch_findings = case_run.get("branch_findings") or []
        routing_findings = case_run.get("routing_findings") or []
        finding_count += len(branch_findings) + len(routing_findings)
        for finding in [*branch_findings, *routing_findings]:
            if isinstance(finding, dict):
                material_findings.extend(finding.get("material_findings") or [])

    status_counts = Counter(item.get("status") for item in material_findings)
    basis_counts = Counter(item.get("basis") for item in material_findings)
    support_counts = Counter(item.get("supports") for item in material_findings)
    return {
        "finding_count": finding_count,
        "material_finding_count": len(material_findings),
        "avg_material_findings_per_finding": (
            len(material_findings) / finding_count if finding_count else 0.0
        ),
        "status_counts": dict(sorted(status_counts.items())),
        "basis_counts": dict(sorted(basis_counts.items())),
        "support_counts": dict(sorted(support_counts.items())),
    }


def _cost_metrics(case_runs: list[dict[str, Any]]) -> dict[str, Any]:
    costs = [case_run.get("cost") or {} for case_run in case_runs]
    configured = [
        cost["estimated_cost_usd"]
        for cost in costs
        if cost.get("estimated_cost_usd") is not None
    ]
    total_latency = sum(cost.get("latency_s") or 0.0 for cost in costs)
    return {
        "case_count": len(case_runs),
        "llm_call_count": len(case_runs),
        "estimated_input_tokens": sum(cost.get("input_tokens") or 0 for cost in costs),
        "estimated_output_tokens": sum(cost.get("output_tokens") or 0 for cost in costs),
        "estimated_total_tokens": sum(cost.get("total_tokens") or 0 for cost in costs),
        "llm_latency_s": total_latency,
        "avg_llm_call_latency_s": total_latency / len(case_runs) if case_runs else 0.0,
        "estimated_cost_usd": sum(configured) if configured else None,
        "pricing_basis": (
            "configured_usd_per_million_tokens" if configured else "not_configured"
        ),
        "token_count_basis": "estimated_from_character_count",
    }


def _write_run_artifacts(output_dir: Path, result: dict[str, Any]) -> None:
    (output_dir / "results.json").write_text(_json(result), encoding="utf-8")
    (output_dir / "dispositions.json").write_text(
        _json(result["dispositions"]),
        encoding="utf-8",
    )
    prompts_dir = output_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    for case_run in result["case_runs"]:
        case_dir = prompts_dir / _safe_name(case_run["case_id"])
        case_dir.mkdir(exist_ok=True)
        (case_dir / "prompt.txt").write_text(case_run["prompt"], encoding="utf-8")
        (case_dir / "raw.txt").write_text(case_run["raw_response"], encoding="utf-8")
        (case_dir / "parsed.json").write_text(_json(case_run["parsed"]), encoding="utf-8")
        (case_dir / "branch_findings.json").write_text(
            _json(case_run["branch_findings"]),
            encoding="utf-8",
        )
        (case_dir / "routing_findings.json").write_text(
            _json(case_run["routing_findings"]),
            encoding="utf-8",
        )


def _json(payload: Any) -> str:
    return json.dumps(to_jsonable_python(payload), indent=2, sort_keys=True)


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:80]


__all__ = [
    "BRANCH_FINDINGS_PROMPT",
    "build_branch_findings_prompt",
    "compose_final_from_branch_findings",
    "pricing_from_specs",
    "run_branch_findings_eval",
    "summarize_branch_findings_run",
]

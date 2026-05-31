"""Direct-LLM disposition baseline for comparison with governed RuleKit runs."""
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
from rulekit.orchestrator.governed_map import _estimate_run_cost
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.map_governance_eval import parse_model_spec, parse_price_spec
from rulekit.runtime import load_program, load_runtime_cases


DIRECT_DISPOSITION_PROMPT = """You are adjudicating a policy case directly.

This is a baseline for research. Unlike RuleKit, you are being asked to decide
the policy dispositions yourself from the policy summary and case packet.

Important:
- Return only JSON.
- Do not invent facts not in the case packet.
- Use "undetermined" when required facts are missing, conflicting, or too
  approximate for a policy determination.
- Use "true" when the determination is satisfied.
- Use "false" when the determination is not satisfied.
- If the case has missing, inconsistent, pending, or complex facts, mark
  human-review-related determinations accordingly.

POLICY SUMMARY
==============
{policy_text}

SELECTED DETERMINATIONS
=======================
{determinations_json}

CASE PACKET
===========
{case_json}

Return ONLY this JSON shape:
{{
  "case_id": "{case_id}",
  "determinations": [
    {{
      "determination_id": "id from SELECTED DETERMINATIONS",
      "outcome": "true|false|undetermined",
      "rationale": "brief reason based on the case packet",
      "confidence": 0.0
    }}
  ],
  "case_level_notes": "brief note or empty string"
}}
"""


def run_direct_disposition_eval(
    *,
    program_path: str | Path,
    cases_path: str | Path,
    model_specs: list[str],
    output_dir: str | Path,
    seed_path: str | Path | None = None,
    determinations: list[str] | None = None,
    reference_dispositions_path: str | Path | None = None,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    max_retries: int = 2,
    pricing: dict[tuple[str, str], tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Run one direct adjudication prompt per case for each provider/model."""
    program = load_program(program_path)
    cases = load_runtime_cases(cases_path)
    selected_determinations = determinations or list(program.determinations)
    policy_text = _policy_text(program, seed_path)
    references = _load_reference_dispositions(reference_dispositions_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for spec in model_specs:
        provider, model = parse_model_spec(spec)
        run_dir = output_dir / _safe_name(f"{provider}_{model}")
        run_dir.mkdir(parents=True, exist_ok=True)
        llm = LLMCaller(
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
        )
        result = _run_direct_for_model(
            llm=llm,
            program=program,
            cases=cases,
            policy_text=policy_text,
            determinations=selected_determinations,
            references=references,
            pricing=pricing or {},
        )
        _write_run_artifacts(run_dir, result)
        summary = summarize_direct_run(provider, model, result)
        (run_dir / "summary.json").write_text(_json(summary), encoding="utf-8")
        runs.append(summary)
    aggregate = {
        "program": str(program_path),
        "cases": str(cases_path),
        "seed": str(seed_path) if seed_path else None,
        "reference_dispositions": (
            str(reference_dispositions_path) if reference_dispositions_path else None
        ),
        "model_count": len(model_specs),
        "runs": runs,
    }
    (output_dir / "summary.json").write_text(_json(aggregate), encoding="utf-8")
    return aggregate


def pricing_from_specs(specs: list[str]) -> dict[tuple[str, str], tuple[float, float]]:
    return dict(parse_price_spec(item) for item in specs)


def summarize_direct_run(
    provider: str,
    model: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    agreement = Counter()
    outcome_counts = Counter()
    for disposition in result["dispositions"]:
        outcome_counts[disposition["outcome"]] += 1
        if disposition.get("reference_outcome") is None:
            agreement["uncompared_count"] += 1
        elif disposition["outcome"] == disposition["reference_outcome"]:
            agreement["reference_agree_count"] += 1
        else:
            agreement["reference_disagree_count"] += 1
    total_compared = agreement["reference_agree_count"] + agreement["reference_disagree_count"]
    return {
        "provider": provider,
        "model": model,
        "case_count": result["case_count"],
        "disposition_count": len(result["dispositions"]),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "reference_agreement": {
            **dict(sorted(agreement.items())),
            "compared_count": total_compared,
            "agreement_rate": (
                agreement["reference_agree_count"] / total_compared
                if total_compared
                else None
            ),
        },
        "cost_metrics": _cost_metrics(result["case_runs"]),
    }


def _run_direct_for_model(
    *,
    llm: LLMCaller,
    program: DeterminationProgram,
    cases: list[CaseExample],
    policy_text: str,
    determinations: list[str],
    references: dict[tuple[str, str], str],
    pricing: dict[tuple[str, str], tuple[float, float]],
) -> dict[str, Any]:
    dispositions: list[dict[str, Any]] = []
    case_runs: list[dict[str, Any]] = []
    for case in cases:
        prompt = build_direct_disposition_prompt(
            program=program,
            policy_text=policy_text,
            case=case,
            determinations=determinations,
        )
        started = perf_counter()
        raw = llm.call(f"direct_disposition:{case.case_id}", prompt, stream=True)
        latency_s = perf_counter() - started
        cost = _estimate_run_cost(
            provider=llm.provider,
            model=llm.model,
            prompt=prompt,
            response=raw,
            latency_s=latency_s,
            pricing=pricing,
        )
        parsed = _parse_direct_payload(case.case_id, raw)
        case_run = {
            "case_id": case.case_id,
            "prompt": prompt,
            "raw_response": raw,
            "parsed": parsed,
            "cost": cost.model_dump(mode="json"),
        }
        case_runs.append(case_run)
        parsed_by_id = {
            item.get("determination_id"): item
            for item in parsed.get("determinations", [])
            if isinstance(item, dict)
        }
        for det_id in determinations:
            item = parsed_by_id.get(det_id, {})
            outcome = _normalize_outcome(item.get("outcome"))
            reference_outcome = references.get((case.case_id, det_id))
            dispositions.append(
                {
                    "disposition_id": new_id("direct_disp"),
                    "case_id": case.case_id,
                    "case_title": case.title,
                    "determination_id": det_id,
                    "outcome": outcome,
                    "reference_outcome": reference_outcome,
                    "matches_reference": (
                        None
                        if reference_outcome is None
                        else outcome == reference_outcome
                    ),
                    "rationale": item.get("rationale"),
                    "confidence": item.get("confidence"),
                    "cost": cost.model_dump(mode="json"),
                }
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
        "map_mode": "direct_llm_disposition",
        "case_runs": case_runs,
        "dispositions": dispositions,
    }


def build_direct_disposition_prompt(
    *,
    program: DeterminationProgram,
    policy_text: str,
    case: CaseExample,
    determinations: list[str],
) -> str:
    determination_payload = [
        {
            "determination_id": det_id,
            "description": program.determinations[det_id].description,
            "source_span": program.determinations[det_id].source_span,
        }
        for det_id in determinations
    ]
    case_payload = {
        "case_id": case.case_id,
        "title": case.title,
        "narrative": case.narrative,
        "structured_fields": case.structured_fields,
    }
    return DIRECT_DISPOSITION_PROMPT.format(
        policy_text=policy_text,
        determinations_json=json.dumps(
            determination_payload,
            indent=2,
            sort_keys=True,
        ),
        case_json=json.dumps(case_payload, indent=2, sort_keys=True),
        case_id=case.case_id,
    )


def _policy_text(program: DeterminationProgram, seed_path: str | Path | None) -> str:
    if seed_path:
        return load_policy_workspace_seed(seed_path).policy_text
    if program.metadata.description:
        return program.metadata.description
    return (
        "No raw policy text was supplied. Use the determination descriptions "
        "and case packet only."
    )


def _parse_direct_payload(case_id: str, raw: str) -> dict[str, Any]:
    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        return {
            "case_id": case_id,
            "determinations": [],
            "case_level_notes": f"could not parse LLM JSON response: {exc}",
        }
    return parsed if isinstance(parsed, dict) else {}


def _normalize_outcome(value: Any) -> str:
    normalized = str(value).strip().lower()
    if normalized in {"true", "false", "undetermined"}:
        return normalized
    return "undetermined"


def _load_reference_dispositions(
    path: str | Path | None,
) -> dict[tuple[str, str], str]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("reference dispositions file must be a list")
    references: dict[tuple[str, str], str] = {}
    for item in payload:
        if isinstance(item, dict):
            references[(item["case_id"], item["determination_id"])] = str(item["outcome"])
    return references


def _cost_metrics(case_runs: list[dict[str, Any]]) -> dict[str, Any]:
    costs = [case_run.get("cost") or {} for case_run in case_runs]
    configured_costs = [
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
        "avg_llm_call_latency_s": total_latency / len(case_runs)
        if case_runs
        else 0.0,
        "estimated_cost_usd": sum(configured_costs) if configured_costs else None,
        "pricing_basis": (
            "configured_usd_per_million_tokens"
            if configured_costs
            else "not_configured"
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
        (case_dir / "parsed.json").write_text(
            _json(case_run["parsed"]),
            encoding="utf-8",
        )


def _json(payload: Any) -> str:
    return json.dumps(to_jsonable_python(payload), indent=2, sort_keys=True)


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:64]


__all__ = [
    "DIRECT_DISPOSITION_PROMPT",
    "build_direct_disposition_prompt",
    "pricing_from_specs",
    "run_direct_disposition_eval",
    "summarize_direct_run",
]

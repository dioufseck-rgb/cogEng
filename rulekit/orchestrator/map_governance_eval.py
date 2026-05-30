"""Live evaluation harness for governed Map prompts across LLM providers."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from rulekit.build.llm import LLMCaller
from rulekit.orchestrator.governed_map import GovernedEvidenceMapStep
from rulekit.orchestrator.map_validation import MapValidationReport
from rulekit.runtime import adjudicate_cases, load_program, load_runtime_cases


def run_map_governance_eval(
    *,
    program_path: str | Path,
    cases_path: str | Path,
    model_specs: list[str],
    output_dir: str | Path,
    determinations: list[str] | None = None,
    atom_ids: list[str] | None = None,
    max_atoms: int | None = None,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Run governed Map over the same packet suite for each provider/model."""
    program = load_program(program_path)
    cases = load_runtime_cases(cases_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for spec in model_specs:
        provider, model = parse_model_spec(spec)
        safe_model = _safe_name(f"{provider}_{model}")
        run_dir = output_dir / safe_model
        run_dir.mkdir(parents=True, exist_ok=True)
        llm = LLMCaller(
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
        )
        map_step = GovernedEvidenceMapStep(
            llm,
            atom_ids=atom_ids,
            max_atoms=max_atoms,
        )
        result = adjudicate_cases(
            program,
            cases,
            determinations=determinations,
            map_step=map_step,
            program_id=program.metadata.name,
            program_version=program.metadata.version,
        )
        _write_run_artifacts(run_dir, result)
        summary = summarize_governed_run(provider, model, result, cases)
        (run_dir / "summary.json").write_text(_json(summary), encoding="utf-8")
        runs.append(summary)
    aggregate = {
        "program": str(program_path),
        "cases": str(cases_path),
        "model_count": len(model_specs),
        "runs": runs,
    }
    (output_dir / "summary.json").write_text(_json(aggregate), encoding="utf-8")
    return aggregate


def parse_model_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise ValueError("model spec must be PROVIDER:MODEL")
    provider, model = spec.split(":", 1)
    if provider not in {"anthropic", "openai", "gemini"}:
        raise ValueError("provider must be anthropic, openai, or gemini")
    if not model:
        raise ValueError("model cannot be empty")
    return provider, model


def summarize_governed_run(
    provider: str,
    model: str,
    result: dict[str, Any],
    cases: list[Any] | None = None,
) -> dict[str, Any]:
    reports = [
        MapValidationReport.model_validate(item)
        for item in result.get("map_validation_reports", [])
    ]
    expected_by_case = {
        case.case_id: case.metadata.get("expected_bindings", {})
        for case in (cases or [])
    }
    status_counts = Counter()
    action_counts = Counter()
    basis_counts = Counter()
    for report in reports:
        for entry in report.entries:
            status_counts[entry.status.value] += 1
            action_counts[entry.action.value] += 1
            if entry.basis:
                basis_counts[entry.basis.value] += 1
    expected_metrics = _expected_binding_metrics(
        result.get("map_records", []),
        reports,
        expected_by_case,
    )
    return {
        "provider": provider,
        "model": model,
        "case_count": result["case_count"],
        "disposition_count": result["disposition_count"],
        "matched_disposition_count": result["matched_disposition_count"],
        "mismatch_count": result["mismatch_count"],
        "validation_status_counts": dict(sorted(status_counts.items())),
        "validation_action_counts": dict(sorted(action_counts.items())),
        "basis_counts": dict(sorted(basis_counts.items())),
        "expected_binding_metrics": expected_metrics,
        "map_mode": result["map_mode"],
    }


def _expected_binding_metrics(
    map_records: list[dict[str, Any]],
    reports: list[MapValidationReport],
    expected_by_case: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    report_entries = {
        (report.case_id, entry.atom_id): entry
        for report in reports
        for entry in report.entries
    }
    metrics = Counter()
    failure_modes = Counter()
    details: list[dict[str, Any]] = []
    for record in map_records:
        case_id = record.get("case_id")
        expected_atoms = expected_by_case.get(case_id, {})
        artifacts = record.get("metadata", {}).get("prompt_artifacts", {}).get("atoms", {})
        bindings = record.get("bindings", {})
        for atom_id, expected in expected_atoms.items():
            metrics["expected_binding_count"] += 1
            parsed = artifacts.get(atom_id, {}).get("parsed", {})
            binding = bindings.get(atom_id, {})
            entry = report_entries.get((case_id, atom_id))
            detail = {
                "case_id": case_id,
                "atom_id": atom_id,
                "expected": expected,
                "raw_status": parsed.get("status"),
                "raw_value": parsed.get("value"),
                "raw_basis": parsed.get("basis"),
                "sanitized_status": binding.get("status"),
                "sanitized_value": binding.get("value"),
                "sanitized_basis": binding.get("basis"),
                "validation_action": entry.action.value if entry else None,
            }
            if "ideal_status" in expected:
                metrics["status_expectation_count"] += 1
                if parsed.get("status") == expected["ideal_status"]:
                    metrics["raw_status_match_count"] += 1
            if "ideal_basis" in expected:
                metrics["basis_expectation_count"] += 1
                if parsed.get("basis") == expected["ideal_basis"]:
                    metrics["raw_basis_match_count"] += 1
            if "ideal_value" in expected:
                metrics["value_expectation_count"] += 1
                if parsed.get("value") == expected["ideal_value"]:
                    metrics["raw_value_match_count"] += 1
            if "ideal_validation_action" in expected:
                metrics["validation_action_expectation_count"] += 1
                if entry and entry.action.value == expected["ideal_validation_action"]:
                    metrics["validation_action_match_count"] += 1
            failure_mode = expected.get("failure_mode")
            if failure_mode:
                failure_modes[failure_mode] += _failure_observed(failure_mode, parsed, entry)
            details.append(detail)
    payload = dict(sorted(metrics.items()))
    payload["observed_failure_modes"] = dict(sorted(failure_modes.items()))
    payload["details"] = details
    return payload


def _failure_observed(
    failure_mode: str,
    parsed: dict[str, Any],
    entry: Any,
) -> int:
    if failure_mode == "false_from_open_world_silence":
        return int(parsed.get("status") == "bound" and parsed.get("value") is False)
    if failure_mode == "overbroad_closed_world_absence":
        return int(
            parsed.get("status") == "bound"
            and parsed.get("value") is False
            and parsed.get("basis") == "closed_world_absence"
            and entry is not None
            and entry.action.value != "accept"
        )
    return 0


def _write_run_artifacts(output_dir: Path, result: dict[str, Any]) -> None:
    (output_dir / "results.json").write_text(_json(result), encoding="utf-8")
    (output_dir / "map_records.json").write_text(
        _json(result["map_records"]),
        encoding="utf-8",
    )
    (output_dir / "map_validation_reports.json").write_text(
        _json(result["map_validation_reports"]),
        encoding="utf-8",
    )
    (output_dir / "dispositions.json").write_text(
        _json(result["dispositions"]),
        encoding="utf-8",
    )
    prompts_dir = output_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    for record in result["map_records"]:
        case_dir = prompts_dir / _safe_name(record["case_id"])
        case_dir.mkdir(exist_ok=True)
        artifacts = record.get("metadata", {}).get("prompt_artifacts", {})
        source = artifacts.get("source_inventory")
        if source:
            (case_dir / "source_inventory_prompt.txt").write_text(
                source.get("prompt", ""),
                encoding="utf-8",
            )
            (case_dir / "source_inventory_raw.txt").write_text(
                source.get("raw_response", ""),
                encoding="utf-8",
            )
            (case_dir / "source_inventory_parsed.json").write_text(
                _json(source.get("parsed")),
                encoding="utf-8",
            )
        atoms = artifacts.get("atoms", {})
        atom_dir = case_dir / "atoms"
        atom_dir.mkdir(exist_ok=True)
        for atom_id, artifact in atoms.items():
            stem = _safe_name(atom_id)
            (atom_dir / f"{stem}.prompt.txt").write_text(
                artifact.get("prompt", ""),
                encoding="utf-8",
            )
            (atom_dir / f"{stem}.raw.txt").write_text(
                artifact.get("raw_response", ""),
                encoding="utf-8",
            )
            (atom_dir / f"{stem}.parsed.json").write_text(
                _json(artifact.get("parsed")),
                encoding="utf-8",
            )


def _json(payload: Any) -> str:
    return json.dumps(to_jsonable_python(payload), indent=2, sort_keys=True)


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:120]


__all__ = [
    "run_map_governance_eval",
    "parse_model_spec",
    "summarize_governed_run",
]

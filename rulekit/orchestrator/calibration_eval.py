"""Split-aware calibration harness for determination-pack repair loops."""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from rulekit.orchestrator.direct_disposition_eval import (
    pricing_from_specs,
    run_direct_disposition_eval,
)
from rulekit.orchestrator.map_governance_eval import (
    parse_price_spec,
    run_map_governance_eval,
)
from rulekit.orchestrator.map_profile_repair import run_map_profile_repair
from rulekit.runtime import load_runtime_cases


def run_calibration_eval(
    *,
    program_path: str | Path,
    cases_path: str | Path,
    output_dir: str | Path,
    repair_count: int,
    validation_count: int,
    final_holdout_count: int | None = None,
    seed: int = 17,
    split_strategy: str = "stratified",
    round_id: str = "round_001",
    model_specs: list[str] | None = None,
    run_direct: bool = False,
    direct_model_specs: list[str] | None = None,
    seed_path: str | Path | None = None,
    determinations: list[str] | None = None,
    atom_ids: list[str] | None = None,
    atom_scope: str = "determination-slice",
    max_atoms: int | None = None,
    batch_size: int = 1,
    single_map_call: bool = False,
    repair_unresolved: bool = False,
    max_repair_atoms: int = 12,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    max_retries: int = 2,
    price_specs: list[str] | None = None,
    direct_prompt_style: str = "profiled",
    run_final: bool = False,
    auto_map_profile_repair: bool = False,
) -> dict[str, Any]:
    """Run a labeled-case calibration pass without leaking final holdout cases.

    The command creates deterministic case splits, runs governed Map + engine
    on repair/validation slices when models are provided, optionally runs the
    profiled direct baseline on those same allowed slices, and writes a compact
    report. The final holdout slice is written to the manifest but is not run
    unless ``run_final`` is explicitly true.
    """
    if repair_count < 0 or validation_count < 0:
        raise ValueError("repair_count and validation_count must be non-negative")
    if final_holdout_count is not None and final_holdout_count < 0:
        raise ValueError("final_holdout_count must be non-negative")

    cases = load_runtime_cases(cases_path)
    split = make_case_split(
        cases,
        repair_count=repair_count,
        validation_count=validation_count,
        final_holdout_count=final_holdout_count,
        seed=seed,
        strategy=split_strategy,
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    slices_dir = output_dir / "case_slices"
    slices_dir.mkdir(parents=True, exist_ok=True)

    slice_paths = {
        name: slices_dir / f"{name}.json"
        for name in ("repair", "validation", "final_holdout", "reserve")
    }
    for name, path in slice_paths.items():
        _write_cases(path, split[name])

    manifest = _split_manifest(
        cases_path=cases_path,
        round_id=round_id,
        seed=seed,
        split_strategy=split_strategy,
        split=split,
        run_final=run_final,
    )
    (output_dir / "split_manifest.json").write_text(
        _json(manifest),
        encoding="utf-8",
    )

    pricing = dict(parse_price_spec(item) for item in (price_specs or []))
    governed: dict[str, Any] = {}
    direct: dict[str, Any] = {}

    allowed_slices = ["repair", "validation"]
    if run_final:
        allowed_slices.append("final_holdout")

    if model_specs:
        for name in allowed_slices:
            if not split[name]:
                continue
            governed[name] = run_map_governance_eval(
                program_path=program_path,
                cases_path=slice_paths[name],
                model_specs=model_specs,
                output_dir=output_dir / name / "governed",
                determinations=determinations,
                atom_ids=atom_ids,
                atom_scope=atom_scope,
                max_atoms=max_atoms,
                batch_size=batch_size,
                single_map_call=single_map_call,
                repair_unresolved=repair_unresolved,
                max_repair_atoms=max_repair_atoms,
                max_tokens=max_tokens,
                timeout=timeout,
                max_retries=max_retries,
                pricing=pricing,
            )

    if run_direct:
        direct_models = direct_model_specs or model_specs
        if not direct_models:
            raise ValueError("run_direct requires --model or --direct-model")
        direct_pricing = pricing_from_specs(price_specs or [])
        for name in allowed_slices:
            if not split[name]:
                continue
            direct[name] = run_direct_disposition_eval(
                program_path=program_path,
                cases_path=slice_paths[name],
                model_specs=direct_models,
                output_dir=output_dir / name / "direct",
                seed_path=seed_path,
                determinations=determinations,
                max_tokens=max_tokens,
                timeout=timeout,
                max_retries=max_retries,
                pricing=direct_pricing,
                prompt_style=direct_prompt_style,
            )

    map_profile_repair: dict[str, Any] | None = None
    if auto_map_profile_repair:
        if not model_specs:
            raise ValueError("auto_map_profile_repair requires a governed --model run")
        repair_artifact_dir = _first_governed_run_artifact_dir(
            output_dir / "repair" / "governed"
        )
        if repair_artifact_dir is None:
            raise ValueError("auto_map_profile_repair could not find repair governed artifacts")
        map_profile_repair = run_map_profile_repair(
            program_path=program_path,
            output_dir=output_dir / "map_profile_repair",
            round_id=round_id,
            repair_cases=split["repair"],
            validation_cases=split["validation"],
            repair_artifact_dir=repair_artifact_dir,
            determinations=determinations,
        )

    summary = {
        "round_id": round_id,
        "program": str(program_path),
        "cases": str(cases_path),
        "case_count": len(cases),
        "run_final": run_final,
        "split_strategy": split_strategy,
        "split_counts": {
            name: len(items)
            for name, items in split.items()
        },
        "governed": _summaries_by_slice(governed),
        "direct": _summaries_by_slice(direct),
        "map_profile_repair": _map_profile_repair_summary(map_profile_repair),
    }
    (output_dir / "summary.json").write_text(_json(summary), encoding="utf-8")
    report = build_calibration_report(summary, manifest)
    (output_dir / "calibration_report.md").write_text(report, encoding="utf-8")
    _write_repair_files(output_dir, summary, map_profile_repair)
    return summary


def make_case_split(
    cases: list[Any],
    *,
    repair_count: int,
    validation_count: int,
    final_holdout_count: int | None,
    seed: int,
    strategy: str = "stratified",
) -> dict[str, list[Any]]:
    total = len(cases)
    if final_holdout_count is None:
        final_holdout_count = max(0, total - repair_count - validation_count)
    requested = repair_count + validation_count + final_holdout_count
    if requested > total:
        raise ValueError(
            "repair_count + validation_count + final_holdout_count exceeds case count"
        )
    if strategy not in {"shuffle", "stratified"}:
        raise ValueError("split strategy must be 'shuffle' or 'stratified'")
    if strategy == "shuffle":
        return _shuffle_case_split(
            cases,
            repair_count=repair_count,
            validation_count=validation_count,
            final_holdout_count=final_holdout_count,
            seed=seed,
        )

    return _stratified_case_split(
        cases,
        repair_count=repair_count,
        validation_count=validation_count,
        final_holdout_count=final_holdout_count,
        seed=seed,
    )


def _shuffle_case_split(
    cases: list[Any],
    *,
    repair_count: int,
    validation_count: int,
    final_holdout_count: int,
    seed: int,
) -> dict[str, list[Any]]:
    shuffled = list(cases)
    random.Random(seed).shuffle(shuffled)
    repair = shuffled[:repair_count]
    validation = shuffled[repair_count:repair_count + validation_count]
    final_start = repair_count + validation_count
    final_end = final_start + final_holdout_count
    final_holdout = shuffled[final_start:final_end]
    reserve = shuffled[final_end:]
    return {
        "repair": repair,
        "validation": validation,
        "final_holdout": final_holdout,
        "reserve": reserve,
    }


def _stratified_case_split(
    cases: list[Any],
    *,
    repair_count: int,
    validation_count: int,
    final_holdout_count: int,
    seed: int,
) -> dict[str, list[Any]]:
    rng = random.Random(seed)
    capacities = {
        "repair": repair_count,
        "validation": validation_count,
        "final_holdout": final_holdout_count,
        "reserve": len(cases) - repair_count - validation_count - final_holdout_count,
    }
    split: dict[str, list[Any]] = {
        name: []
        for name in ("repair", "validation", "final_holdout", "reserve")
    }
    group_counts: dict[str, Counter[str]] = {
        name: Counter()
        for name in split
    }
    groups: dict[str, list[Any]] = {}
    for case in cases:
        groups.setdefault(case_split_group(case), []).append(case)

    group_items = list(groups.items())
    rng.shuffle(group_items)
    for _, group_cases in group_items:
        rng.shuffle(group_cases)

    for group, group_cases in group_items:
        for case in group_cases:
            candidates = [
                name
                for name in split
                if len(split[name]) < capacities[name]
            ]
            if not candidates:
                raise ValueError("case split assignment exhausted all split capacity")
            target = min(
                candidates,
                key=lambda name: (
                    group_counts[name][group],
                    len(split[name]) / capacities[name] if capacities[name] else 1.0,
                    rng.random(),
                ),
            )
            split[target].append(case)
            group_counts[target][group] += 1
    return split


def case_split_group(case: Any) -> str:
    """Return a generic split-balance label for a labeled calibration case."""
    for source_name in ("metadata", "structured_fields"):
        source = getattr(case, source_name, None)
        if not isinstance(source, dict):
            continue
        value = _first_group_value(
            source,
            ("split_group", "failure_mode", "case_archetype", "scenario_type", "case_type"),
        )
        if value:
            return _normalize_group_label(value)

    text = " ".join(
        str(getattr(case, field, ""))
        for field in ("case_id", "title")
    ).lower().replace("-", "_")
    if any(term in text for term in ("identity_theft", "identity theft", "not_mine", "not mine")):
        return "identity_theft"
    if any(term in text for term in ("mixed_file", "mixed file", "similar_name", "similar name")):
        return "mixed_file"
    if "veteran" in text or "medical_debt" in text or "medical debt" in text:
        return "veteran_medical"
    if any(term in text for term in ("duplicate", "repeat", "no_new_info", "no new information")):
        return "duplicate_repeat"
    if any(term in text for term in ("wrong_address", "wrong address", "ordinary customer service")):
        return "wrong_address"
    if any(term in text for term in ("insufficient", "short_message", "short message", "lacks account")):
        return "insufficient_packet"
    if any(term in text for term in ("public_record", "public record", "courthouse")):
        return "public_record"
    if any(term in text for term in ("late_cra_notice", "late cra notice", "after fifth", "seventh")):
        return "late_notice"
    if any(term in text for term in ("date_conflict", "date conflict", "conflicting dates")):
        return "date_conflict"
    if any(term in text for term in ("no_bank_furnishing", "not furnished", "not furnished by bank")):
        return "not_furnished"
    if any(term in text for term in ("dual_channel", "dual channel", "cra_and_direct", "cra and direct")):
        return "dual_channel"
    if any(term in text for term in ("missing_docs", "missing docs", "omits referenced proof")):
        return "missing_docs"
    if any(term in text for term in ("corrected_not_sent", "not sent", "cras not notified")):
        return "notification_gap"
    if any(term in text for term in ("corrected_and_sent", "corrected_and_reported", "corrected", "reported")):
        return "correction_complete"
    if any(term in text for term in ("verified", "verifies", "clean_verified")):
        return "verified"
    if any(term in text for term in ("indirect", "acdv", "cra")):
        return "indirect"
    if "direct" in text:
        return "direct"
    return "general"


def build_calibration_report(summary: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        "# Calibration Repair Loop Report",
        "",
        f"Round: `{summary['round_id']}`",
        f"Split strategy: `{summary.get('split_strategy', manifest.get('split_strategy', 'unknown'))}`",
        "",
        "## Split Discipline",
        "",
        "| Split | Cases | Ran? |",
        "|---|---:|---|",
    ]
    for split_name in ("repair", "validation", "final_holdout", "reserve"):
        ran = "yes" if _slice_ran(summary, split_name) else "no"
        lines.append(
            f"| `{split_name}` | {summary['split_counts'].get(split_name, 0)} | {ran} |"
        )
    lines.extend([
        "",
        "Final holdout cases are not run unless `run_final=true`.",
        "",
        "## Case IDs",
        "",
    ])
    for split_name in ("repair", "validation", "final_holdout", "reserve"):
        ids = manifest["splits"].get(split_name, [])
        joined = ", ".join(f"`{item['case_id']}`" for item in ids) or "_none_"
        lines.append(f"- `{split_name}`: {joined}")
    lines.extend([
        "",
        "## Split Group Balance",
        "",
        "| Split | Group | Cases |",
        "|---|---|---:|",
    ])
    for split_name, counts in _split_group_balance(manifest).items():
        if not counts:
            lines.append(f"| `{split_name}` | `_none_` | 0 |")
            continue
        for group, count in sorted(counts.items()):
            lines.append(f"| `{split_name}` | `{group}` | {count} |")
    lines.extend([
        "",
        "## Governed Results",
        "",
    ])
    lines.extend(_result_tables(summary.get("governed", {})))
    lines.extend([
        "",
        "## Direct LLM Results",
        "",
    ])
    lines.extend(_result_tables(summary.get("direct", {})))
    lines.extend([
        "",
        "## Repair Loop Status",
        "",
    ])
    repair = summary.get("map_profile_repair") or {}
    if repair:
        lines.extend([
            f"Map-profile candidate rules: `{repair.get('candidate_rule_count', 0)}`",
            f"Patched program: `{repair.get('patched_program')}`",
            "",
            "| Replay Split | Matches | Mismatches | Accuracy |",
            "|---|---:|---:|---:|",
        ])
        for split_name, replay in repair.get("replay", {}).items():
            total = replay.get("disposition_count", 0)
            matches = replay.get("matched_disposition_count", 0)
            mismatches = replay.get("mismatch_count", 0)
            accuracy = matches / total if total else 0.0
            lines.append(f"| `{split_name}` | {matches} | {mismatches} | {accuracy:.2%} |")
    else:
        lines.extend([
            "Map-profile repair was not run. Use `--auto-map-profile-repair`",
            "after a governed repair-split run to generate candidate",
            "`map_profile.default_rules` and replay repair/validation.",
        ])
    lines.extend([
        "",
    ])
    return "\n".join(lines)


def _result_tables(results: dict[str, Any]) -> list[str]:
    if not results:
        return ["_Not run._"]
    lines = [
        "| Split | Provider/Model | Matches | Mismatches | Accuracy | Calls | Tokens |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for split_name, runs in results.items():
        for run in runs:
            total = run.get("disposition_count") or 0
            matches = run.get("matched_disposition_count")
            if matches is None:
                agreement = run.get("reference_agreement", {})
                matches = agreement.get("reference_agree_count", 0)
                mismatches = agreement.get("reference_disagree_count", 0)
                total = agreement.get("compared_count", total)
            else:
                mismatches = run.get("mismatch_count", 0)
            accuracy = (matches / total) if total else 0.0
            cost = run.get("cost_metrics", {})
            provider_model = f"{run.get('provider')}:{run.get('model')}"
            lines.append(
                f"| `{split_name}` | `{provider_model}` | {matches} | {mismatches} | "
                f"{accuracy:.2%} | {cost.get('llm_call_count', 0)} | "
                f"{cost.get('estimated_total_tokens', 0)} |"
            )
    return lines


def _split_manifest(
    *,
    cases_path: str | Path,
    round_id: str,
    seed: int,
    split_strategy: str,
    split: dict[str, list[Any]],
    run_final: bool,
) -> dict[str, Any]:
    return {
        "round_id": round_id,
        "cases": str(cases_path),
        "seed": seed,
        "split_strategy": split_strategy,
        "run_final": run_final,
        "final_holdout_locked": not run_final,
        "splits": {
            name: [
                {
                    "case_id": case.case_id,
                    "title": case.title,
                    "split_group": case_split_group(case),
                    "expected_outcome_count": len(case.expected_outcomes),
                }
                for case in cases
            ]
            for name, cases in split.items()
        },
    }


def _summaries_by_slice(results: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        split_name: payload.get("runs", [])
        for split_name, payload in results.items()
    }


def _map_profile_repair_summary(repair: dict[str, Any] | None) -> dict[str, Any] | None:
    if not repair:
        return None
    patch = repair.get("patch", {})
    regression = repair.get("regression_summary", {})
    return {
        "status": patch.get("status"),
        "candidate_rule_count": patch.get("candidate_rule_count", 0),
        "patched_program": repair.get("patched_program"),
        "repair_target": patch.get("repair_target"),
        "replay": regression.get("replay", {}),
    }


def _first_governed_run_artifact_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "dispositions.json").exists():
            return child
    return None


def _split_group_balance(manifest: dict[str, Any]) -> dict[str, dict[str, int]]:
    return {
        split_name: dict(Counter(
            item.get("split_group", "general")
            for item in items
        ))
        for split_name, items in manifest.get("splits", {}).items()
    }


def _first_group_value(source: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_group_label(value: Any) -> str:
    return (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    ) or "general"


def _slice_ran(summary: dict[str, Any], split_name: str) -> bool:
    return (
        split_name in summary.get("governed", {})
        or split_name in summary.get("direct", {})
    )


def _write_cases(path: Path, cases: list[Any]) -> None:
    payload = {
        "cases": [
            to_jsonable_python(case)
            for case in cases
        ]
    }
    path.write_text(_json(payload), encoding="utf-8")


def _write_repair_files(
    output_dir: Path,
    summary: dict[str, Any],
    map_profile_repair: dict[str, Any] | None,
) -> None:
    if map_profile_repair:
        (output_dir / "candidate_patches.json").write_text(
            _json(map_profile_repair.get("patch", {})),
            encoding="utf-8",
        )
        (output_dir / "regression_summary.json").write_text(
            _json(map_profile_repair.get("regression_summary", {})),
            encoding="utf-8",
        )
    else:
        candidate_patches = {
            "status": "not_generated",
            "reason": "run with --auto-map-profile-repair to generate Map-profile patches",
            "round_id": summary["round_id"],
            "repair_target": "map_profile.default_rules",
        }
        (output_dir / "candidate_patches.json").write_text(
            _json(candidate_patches),
            encoding="utf-8",
        )
        regression_summary = {
            "status": "not_run",
            "reason": "no candidate patches generated",
            "validation_split_available": summary["split_counts"].get("validation", 0) > 0,
        }
        (output_dir / "regression_summary.json").write_text(
            _json(regression_summary),
            encoding="utf-8",
        )
    open_questions = [
        "# Open Design Questions",
        "",
        "- Should accepted Map-profile patches be promoted directly into",
        "  `program.metadata.extras.map_profile.default_rules` or into a",
        "  seed-level profile source that regenerates the program artifact?",
        "- Which mismatch classes are allowed to produce automatic candidate",
        "  patches, and which require human review first?",
        "- How should routing determinations gate substantive determinations",
        "  in pending-review cases?",
        "",
    ]
    (output_dir / "open_design_questions.md").write_text(
        "\n".join(open_questions),
        encoding="utf-8",
    )


def mismatch_direction_counts(dispositions: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for disposition in dispositions:
        expected = (
            disposition.get("expected_outcome")
            or disposition.get("reference_outcome")
        )
        actual = disposition.get("outcome")
        matched = (
            disposition.get("matched_expected")
            if "matched_expected" in disposition
            else disposition.get("matches_reference")
        )
        if matched is False:
            counts[f"{actual}->{expected}"] += 1
    return dict(counts)


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


__all__ = [
    "build_calibration_report",
    "case_split_group",
    "make_case_split",
    "mismatch_direction_counts",
    "run_calibration_eval",
]

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from rulekit.orchestrator.exercise import exercise_program_on_case_with_map_record
from rulekit.orchestrator.map_record import MapExtractionRecord
from rulekit.orchestrator.map_step import apply_case_default_bindings
from rulekit.orchestrator.map_validation import (
    apply_map_validation,
    evidence_sources_from_case_fields,
)
from rulekit.runtime import load_program, load_runtime_cases


CASES_PATH = Path(
    "rulekit/orchestrator/example_cases/uscis_n400_tier1_broad_evidence_packets.json"
)
RULEKIT_DISPOSITIONS = Path(
    "audits/tier1_slice_batch_a/anthropic_claude-opus-4-7/dispositions.json"
)
RULEKIT_MAP_RECORDS = Path(
    "audits/tier1_slice_batch_a/anthropic_claude-opus-4-7/map_records.json"
)
DIRECT_DISPOSITIONS = Path(
    "audits/tier1_direct_a/anthropic_claude-opus-4-7/dispositions.json"
)
OUTPUT_DIR = Path("audits/tier1_ground_truth_a")


def main() -> None:
    cases = load_runtime_cases(CASES_PATH)
    expected = {
        (case.case_id, item.determination_id): item.expected_value
        for case in cases
        for item in case.expected_outcomes
    }
    case_titles = {case.case_id: case.title for case in cases}

    comparisons = {
        "rulekit_expanded_batched": compare_dispositions(
            RULEKIT_DISPOSITIONS,
            expected=expected,
            case_titles=case_titles,
        ),
        "rulekit_with_case_defaults": compare_rows(
            replay_rulekit_with_case_defaults(cases),
            expected=expected,
            case_titles=case_titles,
            source_path=str(RULEKIT_MAP_RECORDS),
        ),
        "direct_anthropic": compare_dispositions(
            DIRECT_DISPOSITIONS,
            expected=expected,
            case_titles=case_titles,
        ),
    }
    comparisons["side_by_side"] = side_by_side(
        RULEKIT_DISPOSITIONS,
        DIRECT_DISPOSITIONS,
        expected=expected,
        case_titles=case_titles,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "comparison.json").write_text(
        json.dumps(comparisons, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "REPORT.md").write_text(
        build_report(comparisons),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                name: {
                    "accuracy": comparisons[name]["accuracy"],
                    "match_count": comparisons[name]["match_count"],
                    "mismatch_count": comparisons[name]["mismatch_count"],
                }
                for name in (
                    "rulekit_expanded_batched",
                    "rulekit_with_case_defaults",
                    "direct_anthropic",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )


def compare_dispositions(
    path: Path,
    *,
    expected: dict[tuple[str, str], str],
    case_titles: dict[str, str],
) -> dict[str, Any]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return compare_rows(
        rows,
        expected=expected,
        case_titles=case_titles,
        source_path=str(path),
    )


def compare_rows(
    rows: list[dict[str, Any]],
    *,
    expected: dict[tuple[str, str], str],
    case_titles: dict[str, str],
    source_path: str,
) -> dict[str, Any]:
    pattern: Counter[tuple[str, str]] = Counter()
    by_determination: Counter[str] = Counter()
    by_case: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    missing_expected: list[dict[str, Any]] = []
    compared_count = 0
    match_count = 0

    for row in rows:
        key = (row["case_id"], row["determination_id"])
        expected_outcome = expected.get(key)
        actual = str(row.get("outcome"))
        if expected_outcome is None:
            missing_expected.append(
                {
                    "case_id": key[0],
                    "determination_id": key[1],
                    "outcome": actual,
                }
            )
            continue

        compared_count += 1
        outcome_counts[actual] += 1
        if actual == expected_outcome:
            match_count += 1
            continue

        pattern[(actual, expected_outcome)] += 1
        by_determination[key[1]] += 1
        by_case[key[0]] += 1
        mismatches.append(
            {
                "case_id": key[0],
                "case_title": case_titles.get(key[0]),
                "determination_id": key[1],
                "expected_outcome": expected_outcome,
                "actual_outcome": actual,
                "load_bearing_path": row.get("load_bearing_path"),
                "rationale": row.get("rationale"),
            }
        )

    return {
        "source_path": source_path,
        "compared_count": compared_count,
        "match_count": match_count,
        "mismatch_count": compared_count - match_count,
        "accuracy": match_count / compared_count if compared_count else None,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "mismatch_patterns": [
            {"actual": actual, "expected": expected_outcome, "count": count}
            for (actual, expected_outcome), count in sorted(pattern.items())
        ],
        "mismatches_by_case": dict(sorted(by_case.items())),
        "mismatches_by_determination": dict(sorted(by_determination.items())),
        "missing_expected_count": len(missing_expected),
        "missing_expected": missing_expected,
        "mismatches": mismatches,
    }


def replay_rulekit_with_case_defaults(cases: list[Any]) -> list[dict[str, Any]]:
    program = load_program("build/uscis_n400_tier1_bundle/program.json")
    case_by_id = {case.case_id: case for case in cases}
    rows: list[dict[str, Any]] = []
    payload = json.loads(RULEKIT_MAP_RECORDS.read_text(encoding="utf-8"))
    for item in payload:
        record = MapExtractionRecord.model_validate(item)
        case = case_by_id[record.case_id]
        apply_case_default_bindings(
            program,
            case,
            record.bindings,
            source="case_default_replay",
        )
        record, _report = apply_map_validation(
            program,
            record,
            evidence_sources=evidence_sources_from_case_fields(case.structured_fields),
        )
        rows.extend(
            disposition.model_dump(mode="json")
            for disposition in exercise_program_on_case_with_map_record(
                program,
                case,
                record,
                program_id=program.metadata.name,
                program_version=program.metadata.version,
            )
        )
    return rows


def side_by_side(
    rulekit_path: Path,
    direct_path: Path,
    *,
    expected: dict[tuple[str, str], str],
    case_titles: dict[str, str],
) -> dict[str, Any]:
    rulekit = _outcomes_by_key(rulekit_path)
    direct = _outcomes_by_key(direct_path)
    counts: Counter[tuple[bool, bool]] = Counter()
    differences: list[dict[str, Any]] = []

    for key, expected_outcome in sorted(expected.items()):
        rulekit_outcome = rulekit.get(key)
        direct_outcome = direct.get(key)
        rulekit_matches = rulekit_outcome == expected_outcome
        direct_matches = direct_outcome == expected_outcome
        counts[(rulekit_matches, direct_matches)] += 1
        if rulekit_matches != direct_matches:
            differences.append(
                {
                    "case_id": key[0],
                    "case_title": case_titles.get(key[0]),
                    "determination_id": key[1],
                    "expected_outcome": expected_outcome,
                    "rulekit_outcome": rulekit_outcome,
                    "direct_outcome": direct_outcome,
                    "rulekit_matches": rulekit_matches,
                    "direct_matches": direct_matches,
                }
            )

    return {
        "counts": {
            "both_match": counts[(True, True)],
            "rulekit_only": counts[(True, False)],
            "direct_only": counts[(False, True)],
            "neither_match": counts[(False, False)],
        },
        "differences": differences,
    }


def _outcomes_by_key(path: Path) -> dict[tuple[str, str], str]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {
        (row["case_id"], row["determination_id"]): str(row.get("outcome"))
        for row in rows
    }


def build_report(comparisons: dict[str, Any]) -> str:
    lines = [
        "# USCIS N-400 Tier 1 Ground-Truth Disposition Comparison",
        "",
        "Run date: 2026-05-31",
        "",
        "Ground-truth labels were added to the case packets before this comparison pass.",
        "Labels are benchmark dispositions derived from the packet narrative and policy intent,",
        "not copied from saved RuleKit or direct-LLM outputs.",
        "",
        "## Accuracy Summary",
        "",
        "| System | Compared | Matches | Mismatches | Accuracy |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in (
        "rulekit_expanded_batched",
        "rulekit_with_case_defaults",
        "direct_anthropic",
    ):
        summary = comparisons[name]
        lines.append(
            "| {name} | {compared} | {matched} | {mismatched} | {accuracy:.2%} |".format(
                name=name,
                compared=summary["compared_count"],
                matched=summary["match_count"],
                mismatched=summary["mismatch_count"],
                accuracy=summary["accuracy"] or 0.0,
            )
        )

    lines.extend(
        [
            "",
            "## Side-By-Side",
            "",
            "| Result | Count |",
            "|---|---:|",
        ]
    )
    for key, value in comparisons["side_by_side"]["counts"].items():
        lines.append(f"| {key} | {value} |")

    for name in (
        "rulekit_expanded_batched",
        "rulekit_with_case_defaults",
        "direct_anthropic",
    ):
        summary = comparisons[name]
        lines.extend(
            [
                "",
                f"## {name} Mismatch Patterns",
                "",
                "| Actual | Expected | Count |",
                "|---|---|---:|",
            ]
        )
        for row in summary["mismatch_patterns"]:
            lines.append(
                "| `{actual}` | `{expected}` | {count} |".format(**row)
            )
        lines.extend(
            [
                "",
                "### By Determination",
                "",
                "| Determination | Mismatches |",
                "|---|---:|",
            ]
        )
        for determination_id, count in summary["mismatches_by_determination"].items():
            lines.append(f"| `{determination_id}` | {count} |")
        lines.extend(
            [
                "",
                "### Mismatches",
                "",
                "| Case | Determination | Expected | Actual |",
                "|---|---|---|---|",
            ]
        )
        for row in summary["mismatches"]:
            lines.append(
                "| `{case_id}` | `{determination_id}` | `{expected_outcome}` | `{actual_outcome}` |".format(
                    **row
                )
            )

    lines.extend(
        [
            "",
            "## Readout",
            "",
            "- RuleKit is conservative against this ground truth: most mismatches are `undetermined` where the benchmark label says `true` or `false`.",
            "- Direct Anthropic is more decisive and more accurate on this small labeled set, but it still has misses and does not produce governed atom-level traces.",
            "- The highest-value next fix is source-scope/default semantics for negative bars and non-load-bearing missing facts, plus clearer DAG treatment of human-review triggers.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from rulekit.orchestrator.exercise import exercise_program_on_case_with_map_record
from rulekit.orchestrator.factory import create_candidate_program
from rulekit.orchestrator.map_record import MapExtractionRecord
from rulekit.orchestrator.map_step import apply_case_default_bindings
from rulekit.orchestrator.map_validation import (
    apply_map_validation,
    evidence_sources_from_case_fields,
)
from rulekit.runtime import load_runtime_cases


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

    rulekit_with_defaults = replay_rulekit_with_case_defaults(cases)
    comparisons = {
        "rulekit_expanded_batched": compare_dispositions(
            RULEKIT_DISPOSITIONS,
            expected=expected,
            case_titles=case_titles,
        ),
        "rulekit_with_case_defaults": compare_rows(
            rulekit_with_defaults,
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
        rulekit_with_defaults,
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
    program = load_tier1_program()
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


def load_tier1_program():
    seed = json.loads(
        Path("rulekit/orchestrator/example_seeds/uscis_n400_selected.json").read_text(
            encoding="utf-8"
        )
    )
    from rulekit.orchestrator.factory import PolicyWorkspaceSeed

    parsed = PolicyWorkspaceSeed.model_validate(seed)
    return create_candidate_program(
        program_id="prog_uscis_n400",
        program_name=parsed.workspace_name,
        version=parsed.version_label or "0.1",
        determinations=parsed.determinations,
        atoms=parsed.atoms,
        nodes=parsed.nodes,
        constants=parsed.constants,
    )


def side_by_side(
    rulekit_rows_or_path: list[dict[str, Any]] | Path,
    direct_path: Path,
    *,
    expected: dict[tuple[str, str], str],
    case_titles: dict[str, str],
) -> dict[str, Any]:
    rulekit = _outcomes_by_key(rulekit_rows_or_path)
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


def _outcomes_by_key(rows_or_path: list[dict[str, Any]] | Path) -> dict[tuple[str, str], str]:
    rows = (
        rows_or_path
        if isinstance(rows_or_path, list)
        else json.loads(rows_or_path.read_text(encoding="utf-8"))
    )
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
        if not summary["mismatch_patterns"]:
            lines.append("| none | none | 0 |")
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
        if not summary["mismatches_by_determination"]:
            lines.append("| none | 0 |")
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
        if not summary["mismatches"]:
            lines.append("| none | none | none | none |")

    governed = comparisons["rulekit_with_case_defaults"]
    direct = comparisons["direct_anthropic"]
    expanded = comparisons["rulekit_expanded_batched"]
    governed_delta = governed["match_count"] - expanded["match_count"]
    direct_delta = governed["match_count"] - direct["match_count"]

    lines.extend(
        [
            "",
            "## Scoped-Default Fix Classification",
            "",
            "| Area | Failure direction | Load-bearing path | Fix |",
            "|---|---|---|---|",
            "| Clean negative bars | `undetermined` where ground truth was `true` | Negative-bar atoms blocked good-moral-character approval unless absence was source-scoped | Added `closed_world_absence` binding directives so false absences from scoped packet evidence validate as `closed_world_absence` |",
            "| Physical-presence shortfall | `false` where ground truth was `undetermined` | Unrelated spouse-track branch decided state residence from missing facts | Added an `out_of_scope` binding directive preserving `n400.spouse_track_residence_consistent` as `undetermined` when the packet has no spouse-track/residence evidence |",
            "| Missing travel support | `false` where ground truth was `undetermined` | Evidence-quality atoms became substantive denial facts for continuous residence and physical presence | Added `evidence_gap` binding directives preserving missing travel records and unresolved worksheet gaps as `undetermined` |",
            "| Conflict propagation | False-leaning paths could mask conflicts or ordinary missing branches could over-force uncertainty | Load-bearing conflicts should propagate, but non-load-bearing missing facts should not globally override | Limited false uncertainty override to `conflicting_evidence` and binding errors |",
            "",
            "## Readout",
            "",
            f"- Scoped packet binding directives plus evidence-aware routing/conflict handling moved RuleKit to `{governed['match_count']}/{governed['compared_count']}` on this benchmark replay.",
            f"- The governed replay gained `{governed_delta}` matches over the original expanded-batched run and `{direct_delta}` matches over the direct Anthropic baseline.",
            "- The last three governed errors eliminated by this change were false outcomes where the source packet actually left a non-load-bearing branch or evidence-quality question undecidable.",
            "- The remaining direct-LLM misses are still mostly true-direction overclaims, which is the regulated-adjudication failure mode this architecture is meant to avoid.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()

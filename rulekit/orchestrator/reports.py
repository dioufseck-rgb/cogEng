"""Governance report skeletons for orchestrator projections."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import Enum
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import DeterminationProgram
from rulekit.orchestrator.disposition import DispositionRecord
from rulekit.orchestrator.ids import report_id as new_report_id
from rulekit.orchestrator.step import StepRunResult, utc_now
from rulekit.orchestrator.workspace import PolicySource


class GovernanceReportKind(str, Enum):
    COVERAGE = "coverage"
    VARIANCE = "variance"
    REGRESSION = "regression"
    SOURCE_TEXT_COVERAGE = "source_text_coverage"
    SENSITIVITY = "sensitivity"


class GovernanceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(default_factory=new_report_id)
    kind: GovernanceReportKind
    workspace_id: str
    trajectory_id: str | None = None
    case_suite_id: str | None = None
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)


def generate_coverage_report(
    dispositions: list[DispositionRecord],
    *,
    workspace_id: str = "unknown",
    trajectory_id: str | None = None,
    case_suite_id: str | None = None,
) -> GovernanceReport:
    by_determination = Counter(d.determination_id for d in dispositions)
    matched = sum(1 for d in dispositions if d.matched_expected is True)
    compared = sum(1 for d in dispositions if d.matched_expected is not None)
    return GovernanceReport(
        kind=GovernanceReportKind.COVERAGE,
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        case_suite_id=case_suite_id,
        payload={
            "disposition_count": len(dispositions),
            "determinations_seen": dict(sorted(by_determination.items())),
            "compared_count": compared,
            "matched_count": matched,
            "match_rate": matched / compared if compared else None,
        },
    )


def generate_regression_report(
    old_dispositions: list[DispositionRecord],
    new_dispositions: list[DispositionRecord],
    *,
    workspace_id: str = "unknown",
    trajectory_id: str | None = None,
) -> GovernanceReport:
    def key(d: DispositionRecord) -> tuple[str, str]:
        return (d.case_id, d.determination_id)

    old = {key(d): d.outcome for d in old_dispositions}
    new = {key(d): d.outcome for d in new_dispositions}
    all_keys = sorted(set(old) | set(new))
    changes = [
        {
            "case_id": case_id,
            "determination_id": det_id,
            "old": old.get((case_id, det_id)),
            "new": new.get((case_id, det_id)),
        }
        for case_id, det_id in all_keys
        if old.get((case_id, det_id)) != new.get((case_id, det_id))
    ]
    return GovernanceReport(
        kind=GovernanceReportKind.REGRESSION,
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        payload={"change_count": len(changes), "changes": changes},
    )


def generate_variance_report(
    step_runs: list[StepRunResult],
    *,
    workspace_id: str = "unknown",
    trajectory_id: str | None = None,
) -> GovernanceReport:
    normalized = [
        json.dumps(run.output_payload, sort_keys=True, default=str)
        for run in step_runs
    ]
    unique_outputs = len(set(normalized))
    return GovernanceReport(
        kind=GovernanceReportKind.VARIANCE,
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        payload={
            "run_count": len(step_runs),
            "unique_output_count": unique_outputs,
            "all_outputs_equal": unique_outputs <= 1,
            "status_counts": dict(Counter(run.status.value for run in step_runs)),
            "run_ids": [run.run_id for run in step_runs],
        },
    )


def generate_source_text_coverage_report(
    program: DeterminationProgram,
    policy: str | PolicySource,
    *,
    workspace_id: str = "unknown",
    trajectory_id: str | None = None,
) -> GovernanceReport:
    """Approximate source coverage by exact source-span occurrence.

    `source_span` is intentionally producer-defined in the contract, so
    this report is a conservative structural projection: it checks which
    non-empty spans are exact substrings of the policy text and estimates
    character coverage from those matches.
    """
    policy_text = policy.content if isinstance(policy, PolicySource) else policy
    policy_text = policy_text or ""
    spans = _collect_source_spans(program)
    matched = []
    unmatched = []
    covered_positions: set[int] = set()
    for span in spans:
        idx = policy_text.find(span)
        if idx >= 0:
            matched.append(span)
            covered_positions.update(range(idx, idx + len(span)))
        else:
            unmatched.append(span)
    return GovernanceReport(
        kind=GovernanceReportKind.SOURCE_TEXT_COVERAGE,
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        payload={
            "policy_char_count": len(policy_text),
            "source_span_count": len(spans),
            "matched_span_count": len(matched),
            "unmatched_span_count": len(unmatched),
            "estimated_covered_char_count": len(covered_positions),
            "estimated_covered_fraction": (
                len(covered_positions) / len(policy_text) if policy_text else None
            ),
            "unmatched_spans": unmatched,
        },
    )


def generate_sensitivity_report(
    dispositions: list[DispositionRecord],
    *,
    workspace_id: str = "unknown",
    trajectory_id: str | None = None,
    case_suite_id: str | None = None,
) -> GovernanceReport:
    """Summarize load-bearing atom paths observed in dispositions.

    This is not counterfactual recomputation yet. It is the v0.1
    approximation over existing traces: atoms that repeatedly appear on
    load-bearing/evaluated paths are surfaced for reviewer attention.
    """
    atom_counts = Counter(
        atom_id
        for disposition in dispositions
        for atom_id in disposition.load_bearing_path
    )
    mismatch_atom_counts = Counter(
        atom_id
        for disposition in dispositions
        if disposition.matched_expected is False
        for atom_id in disposition.load_bearing_path
    )
    by_case = {
        disposition.case_id: disposition.load_bearing_path
        for disposition in dispositions
    }
    return GovernanceReport(
        kind=GovernanceReportKind.SENSITIVITY,
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        case_suite_id=case_suite_id,
        payload={
            "disposition_count": len(dispositions),
            "unique_load_bearing_atom_count": len(atom_counts),
            "load_bearing_atom_counts": dict(sorted(atom_counts.items())),
            "mismatch_load_bearing_atom_counts": dict(
                sorted(mismatch_atom_counts.items())
            ),
            "load_bearing_path_by_case": by_case,
        },
    )


def _collect_source_spans(program: DeterminationProgram) -> list[str]:
    spans: set[str] = set()
    for atom in program.map_spec.atoms.values():
        if atom.source_span:
            spans.add(atom.source_span)
    for node in program.nodes.values():
        source_span = getattr(node, "source_span", "")
        if source_span:
            spans.add(source_span)
    for determination in program.determinations.values():
        if determination.source_span:
            spans.add(determination.source_span)
    return sorted(spans)


__all__ = [
    "GovernanceReportKind",
    "GovernanceReport",
    "generate_coverage_report",
    "generate_regression_report",
    "generate_variance_report",
    "generate_source_text_coverage_report",
    "generate_sensitivity_report",
]

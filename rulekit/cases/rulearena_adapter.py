"""
RuleArena case adapter.

RuleArena (https://github.com/SkyRiver-2000/RuleArena) is an academic
benchmark for rule-based reasoning. Each case file (e.g.
RuleArena/nba/annotated_problems/comp_0.json) is a JSON array of cases;
each case has the following fields:

    n_teams, n_players, n_operations  (counts; structural metadata)
    team_situations                   (list[str]: pre-operation team state)
    player_situations                 (list[str]: pre-operation player state)
    operations                        (list[str]: operations under
                                       adjudication, prefixed A./B./C./...)
    answer                            (bool: True if illegal)
    illegal_operation                 (str: 'A', 'B', ... — which op
                                       is illegal; or empty string)
    problematic_team                  (str: 'A', 'B', ... — which team
                                       commits the illegal op)
    relevant_rules                    (list[str]: ground-truth rule
                                       families involved)

This adapter converts one RuleArena case + an operation index into an
AdaptedCase that the run-time pipeline consumes.

Multi-operation cases are handled by selecting which operation to
adjudicate: the adapter is called once per (case, operation_letter)
pair. For sprint scope we focus on single-operation cases, but the
adapter is general.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


@dataclass
class AdaptedCase:
    """One adjudication-ready case.

    `description` is the narrative-form evidence passed to Map. `ground_truth`
    is optional structured truth used for measurement (None when adjudicating
    real cases without known answers). `metadata` carries provenance.
    """
    case_id: str
    description: str
    ground_truth: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _operation_letter_to_index(letter: str) -> int:
    """Convert 'A' -> 0, 'B' -> 1, ..."""
    return ord(letter.upper()) - ord("A")


def _index_to_operation_letter(idx: int) -> str:
    """Convert 0 -> 'A', 1 -> 'B', ..."""
    return chr(ord("A") + idx)


def adapt_ruleArena_case(
    raw_case: dict,
    operation_letter: str,
    case_id: Optional[str] = None,
) -> AdaptedCase:
    """Adapt one RuleArena case to an AdaptedCase, focused on one operation.

    Args:
        raw_case: a dict from a RuleArena comp_*.json entry
        operation_letter: 'A', 'B', 'C', ... — which operation to
            highlight as the one under adjudication
        case_id: optional identifier; if not provided, synthesized from
            the operation letter and case provenance

    The description that comes out is structured for Map:

        TEAMS:
          - [team_situations bullets]

        PLAYERS:
          - [player_situations bullets]

        OPERATIONS:
          - A. ...
          - B. ...   (if more than one)

        OPERATION UNDER ADJUDICATION: [operation_letter]
          [the highlighted operation, repeated for emphasis]

    The repeat at the end makes the focal operation lexically prominent
    so per-atom Map calls anchor on it.
    """
    op_idx = _operation_letter_to_index(operation_letter)
    operations = raw_case.get("operations", [])
    if op_idx < 0 or op_idx >= len(operations):
        raise ValueError(
            f"Operation letter {operation_letter!r} is out of range for case "
            f"with {len(operations)} operations."
        )
    focal_operation = operations[op_idx]

    # Build the description in well-structured prose
    parts = []
    teams = raw_case.get("team_situations", [])
    if teams:
        parts.append("TEAMS:")
        for t in teams:
            parts.append(f"  - {t}")
        parts.append("")

    players = raw_case.get("player_situations", [])
    if players:
        parts.append("PLAYERS:")
        for p in players:
            parts.append(f"  - {p}")
        parts.append("")

    if len(operations) > 1:
        parts.append("ALL OPERATIONS PROPOSED IN THIS CASE:")
        for op in operations:
            parts.append(f"  - {op}")
        parts.append("")

    parts.append(f"OPERATION UNDER ADJUDICATION: {operation_letter}")
    parts.append(f"  {focal_operation}")

    description = "\n".join(parts)

    # Ground truth — only meaningful for the operation under adjudication
    answer = raw_case.get("answer")
    illegal_op = raw_case.get("illegal_operation", "")
    problematic_team = raw_case.get("problematic_team", "")
    ground_truth = {
        "is_illegal": bool(answer) and (illegal_op.upper() == operation_letter.upper()),
        "case_answer": bool(answer),  # the whole case verdict
        "illegal_operation_letter": illegal_op,
        "problematic_team_letter": problematic_team,
        "operation_under_adjudication": operation_letter,
        "relevant_rules": raw_case.get("relevant_rules", []),
    }

    metadata = {
        "source": "RuleArena",
        "n_teams": raw_case.get("n_teams"),
        "n_players": raw_case.get("n_players"),
        "n_operations": raw_case.get("n_operations"),
        "operation_letter": operation_letter,
        "raw_case": raw_case,  # full provenance
    }

    if case_id is None:
        case_id = f"ruleArena_op_{operation_letter}"

    return AdaptedCase(
        case_id=case_id,
        description=description,
        ground_truth=ground_truth,
        metadata=metadata,
    )


def load_ruleArena_cases(
    json_path: str,
    indices: Optional[Iterable[int]] = None,
    only_single_op: bool = False,
) -> list[AdaptedCase]:
    """Load and adapt cases from a RuleArena comp_*.json file.

    Args:
        json_path: path to a comp_*.json file (a JSON array of cases)
        indices: optional set of case indices to load (0-based into the
            JSON array). If None, all cases are loaded.
        only_single_op: if True, skip cases with n_operations > 1.
            Multi-op cases would produce multiple AdaptedCases (one per
            operation) when not filtered.

    Returns one AdaptedCase per (case, operation) pair. For single-op
    cases that's one case-letter "A". For multi-op cases unfiltered,
    that's one AdaptedCase per letter.

    case_id format: "<basename>_<case_index>_op_<letter>"
        e.g. "comp_0_0_op_A" — comp_0.json's case index 0, operation A
    """
    with open(json_path, encoding="utf-8") as f:
        raw_cases = json.load(f)

    if not isinstance(raw_cases, list):
        raise ValueError(
            f"Expected {json_path} to be a JSON list of cases, got "
            f"{type(raw_cases).__name__}."
        )

    basename = os.path.splitext(os.path.basename(json_path))[0]
    selected_indices = (
        set(indices) if indices is not None else set(range(len(raw_cases)))
    )

    adapted: list[AdaptedCase] = []
    for i, raw in enumerate(raw_cases):
        if i not in selected_indices:
            continue
        n_ops = raw.get("n_operations", len(raw.get("operations", [])))
        if only_single_op and n_ops != 1:
            continue
        for op_idx in range(n_ops):
            letter = _index_to_operation_letter(op_idx)
            case_id = f"{basename}_{i}_op_{letter}"
            adapted.append(adapt_ruleArena_case(raw, letter, case_id=case_id))

    return adapted


def filter_cases_by_relevant_rules(
    cases: list[AdaptedCase],
    supported_rules: set[str],
    strict: bool = True,
) -> tuple[list[AdaptedCase], list[AdaptedCase]]:
    """Partition cases by whether their relevant_rules are covered.

    Args:
        cases: adapted cases (with ground_truth.relevant_rules populated)
        supported_rules: the set of rule family names the built DAG covers
        strict: if True, a case is "supported" only if every rule in
            relevant_rules is in supported_rules. If False, any overlap
            is sufficient.

    Returns (supported_cases, unsupported_cases). Useful for the
    Phase 2A pre-filter step: select cases the built DAG can plausibly
    adjudicate before spending Map budget on cases that will fail
    structurally.
    """
    supported = []
    unsupported = []
    for case in cases:
        rules = set((case.ground_truth or {}).get("relevant_rules", []))
        if strict:
            covered = rules.issubset(supported_rules)
        else:
            covered = bool(rules & supported_rules)
        (supported if covered else unsupported).append(case)
    return supported, unsupported

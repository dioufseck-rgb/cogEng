"""Readable ID helpers for RuleKit Orchestrator objects."""
from __future__ import annotations

from uuid import uuid4


def new_id(prefix: str) -> str:
    """Return a readable prefixed UUID identifier."""
    cleaned = prefix.strip().rstrip("_")
    if not cleaned:
        raise ValueError("ID prefix must be non-empty")
    return f"{cleaned}_{uuid4().hex}"


def workspace_id() -> str:
    return new_id("ws")


def policy_id() -> str:
    return new_id("pol")


def case_suite_id() -> str:
    return new_id("suite")


def case_id() -> str:
    return new_id("case")


def program_id() -> str:
    return new_id("prog")


def trajectory_id() -> str:
    return new_id("traj")


def branch_id() -> str:
    return new_id("br")


def event_id() -> str:
    return new_id("evt")


def run_id() -> str:
    return new_id("run")


def dialogue_id() -> str:
    return new_id("dlg")


def turn_id() -> str:
    return new_id("turn")


def intervention_id() -> str:
    return new_id("int")


def hint_id() -> str:
    return new_id("hint")


def report_id() -> str:
    return new_id("rep")


def multi_run_id() -> str:
    return new_id("mr")


__all__ = [
    "new_id",
    "workspace_id",
    "policy_id",
    "case_suite_id",
    "case_id",
    "program_id",
    "trajectory_id",
    "branch_id",
    "event_id",
    "run_id",
    "dialogue_id",
    "turn_id",
    "intervention_id",
    "hint_id",
    "report_id",
    "multi_run_id",
]

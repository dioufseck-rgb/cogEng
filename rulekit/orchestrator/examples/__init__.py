"""Orchestrator examples."""
from rulekit.orchestrator.examples.fcba_stub import (
    build_fcba_candidate_program,
    build_fcba_stub_graph,
    build_fcba_workspace,
    run_fcba_stub,
)
from rulekit.orchestrator.examples.generic_policy_stub import (
    build_generic_candidate_program,
    build_generic_stub_graph,
    build_generic_workspace,
    run_generic_stub,
)

__all__ = [
    "build_fcba_stub_graph",
    "build_fcba_workspace",
    "build_fcba_candidate_program",
    "run_fcba_stub",
    "build_generic_stub_graph",
    "build_generic_workspace",
    "build_generic_candidate_program",
    "run_generic_stub",
]

"""Orchestrator-specific exceptions."""
from __future__ import annotations


class OrchestratorError(Exception):
    """Base class for orchestrator errors."""


class OrchestratorValidationError(OrchestratorError, ValueError):
    """Raised when an orchestrator object fails semantic validation."""


class DialogueBudgetError(OrchestratorValidationError):
    """Raised when a dialogue exceeds its allowed turn budget."""


class BranchError(OrchestratorValidationError):
    """Raised when a trajectory branch operation is invalid."""


__all__ = [
    "OrchestratorError",
    "OrchestratorValidationError",
    "DialogueBudgetError",
    "BranchError",
]

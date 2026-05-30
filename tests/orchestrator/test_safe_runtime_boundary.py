from __future__ import annotations

import pytest

from rulekit.contract import (
    AtomRef,
    CaseInputSchema,
    DeterminationProgram,
    DeterminationSpec,
    ProgramMetadata,
    ProgramValidationError,
    Provenance,
    safe_program_to_engine,
)

from tests.orchestrator.test_exercise import _program


def test_safe_program_to_engine_accepts_valid_program():
    runtime = safe_program_to_engine(_program())

    assert "fcba.billing_error" in runtime.determinations


def test_safe_program_to_engine_rejects_invalid_program_before_engine():
    program = DeterminationProgram(
        metadata=ProgramMetadata(name="Invalid", version="0.1"),
        nodes={
            "n_missing": AtomRef(
                node_id="n_missing",
                provenance=Provenance.TRANSCRIBED,
                source_span="missing atom",
                atom_id="atom.missing",
            )
        },
        determinations={
            "det.invalid": DeterminationSpec(
                id="det.invalid",
                description="Invalid determination.",
                root_node="n_missing",
            )
        },
        case_input_schema=CaseInputSchema(has_narrative=True),
    )

    with pytest.raises(ProgramValidationError) as excinfo:
        safe_program_to_engine(program)

    assert "atom.missing" in str(excinfo.value)
    assert not excinfo.value.report.ok

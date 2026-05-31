from __future__ import annotations

from rulekit.build.llm import LLMCaller
from rulekit.contract import (
    AtomBindingPolicy,
    AtomRef,
    BindingBasis,
    BooleanAtom,
    DeterminationProgram,
    DeterminationSpec,
    EvaluationMode,
    MapSpec,
    NotNodeSpec,
    ProductionRecord,
    ProgramMetadata,
    Provenance,
)
from rulekit.orchestrator.cases import CaseExample, ExpectedOutcome
from rulekit.orchestrator.governed_map import GovernedEvidenceMapStep
from rulekit.orchestrator.map_governance_eval import atoms_for_determinations
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
    MapExtractionRecord,
)
from rulekit.orchestrator.map_step import MapStepContext, PreboundFactsMapStep
from rulekit.orchestrator.map_validation import (
    EvidenceSource,
    MapBindingValidationAction,
    apply_map_validation,
    validate_map_record,
)
from rulekit.runtime import adjudicate_cases


def test_map_validation_rejects_false_from_open_world_absence():
    program = _program()
    record = _map_record(
        AtomBindingRecord(
            atom_id="n400.aggravated_felony_after_1990",
            atom_type="boolean",
            value=False,
            status=AtomBindingStatus.BOUND,
            basis=BindingBasis.OPEN_WORLD_ABSENCE,
        )
    )

    sanitized, report = apply_map_validation(program, record)

    entry = report.entries[0]
    assert report.ok is False
    assert entry.action == MapBindingValidationAction.COERCE_UNDETERMINED
    assert sanitized.bindings["n400.aggravated_felony_after_1990"].status == (
        AtomBindingStatus.UNDETERMINED
    )
    assert sanitized.bindings["n400.aggravated_felony_after_1990"].value == "undetermined"


def test_map_validation_accepts_closed_world_absence_with_required_source_type():
    program = _program()
    record = _map_record(
        AtomBindingRecord(
            atom_id="n400.aggravated_felony_after_1990",
            atom_type="boolean",
            value=False,
            status=AtomBindingStatus.BOUND,
            basis=BindingBasis.CLOSED_WORLD_ABSENCE,
            source_ids=["fbi_check"],
        )
    )

    report = validate_map_record(
        program,
        record,
        evidence_sources=[
            EvidenceSource(
                source_id="fbi_check",
                source_type="criminal_history_check",
                closed_world_scopes=["criminal_convictions"],
            )
        ],
    )

    assert report.ok is True
    assert report.entries[0].action == MapBindingValidationAction.ACCEPT


def test_prebound_map_step_reads_declared_binding_basis_and_validation_affects_engine():
    program = _program()
    case = CaseExample(
        case_id="open_world_silence",
        title="Narrative silence",
        narrative="The applicant says they want to naturalize. No criminal history source is provided.",
        structured_fields={
            "facts": {"n400.aggravated_felony_after_1990": False},
            "binding_bases": {
                "n400.aggravated_felony_after_1990": "open_world_absence",
            },
        },
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="n400.no_aggravated_felony_bar",
                expected_value="undetermined",
            )
        ],
    )

    result = adjudicate_cases(program, [case], map_step=PreboundFactsMapStep())

    assert result["mismatch_count"] == 0
    assert result["map_records"][0]["bindings"]["n400.aggravated_felony_after_1990"][
        "status"
    ] == "undetermined"
    assert result["map_validation_reports"][0]["ok"] is False


def test_governed_map_step_records_prompts_basis_and_raw_responses():
    program = _program()
    case = CaseExample(
        case_id="closed_world_packet",
        title="Closed-world packet",
        narrative="The packet includes an FBI criminal history check showing no felony convictions.",
        structured_fields={
            "evidence_sources": [
                {
                    "source_id": "fbi_check",
                    "source_type": "criminal_history_check",
                    "title": "FBI criminal history check",
                    "closed_world_scopes": ["criminal_convictions"],
                }
            ],
            "evidence": {
                "n400.aggravated_felony_after_1990": "FBI check: no felony convictions found."
            },
        },
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="n400.no_aggravated_felony_bar",
                expected_value="true",
            )
        ],
    )
    llm = LLMCaller(
        offline_responses={
            "map_governed_source_inventory": (
                '{"sources":[{"source_id":"fbi_check","source_type":"criminal_history_check",'
                '"title":"FBI check","as_of_date":null,'
                '"closed_world_scopes":["criminal_convictions"],"limitations":""}]}'
            ),
            "map_governed_atom:n400.aggravated_felony_after_1990": (
                '{"atom_id":"n400.aggravated_felony_after_1990","status":"bound",'
                '"value":false,"basis":"closed_world_absence","source_ids":["fbi_check"],'
                '"evidence":"no felony convictions found","explanation":"official check",'
                '"confidence":0.95}'
            ),
        }
    )
    step = GovernedEvidenceMapStep(llm, atom_ids=["n400.aggravated_felony_after_1990"])

    result = step.run(
        program,
        case,
        MapStepContext(program_id="prog", substrate_id=step.spec.map_step_id),
    )

    binding = result.map_record.bindings["n400.aggravated_felony_after_1990"]
    assert binding.value is False
    assert binding.basis == BindingBasis.CLOSED_WORLD_ABSENCE
    assert result.map_record.cost is not None
    assert result.map_record.cost.input_tokens > 0
    assert result.map_record.cost.output_tokens > 0
    assert result.map_record.cost.latency_s >= 0
    artifacts = result.map_record.metadata["prompt_artifacts"]
    assert "source_inventory" in artifacts
    assert "n400.aggravated_felony_after_1990" in artifacts["atoms"]
    assert artifacts["source_inventory"]["metrics"]["input_tokens"] > 0
    assert artifacts["atoms"]["n400.aggravated_felony_after_1990"]["metrics"][
        "output_tokens"
    ] > 0


def test_governed_map_step_can_bind_atoms_in_batches():
    program = _program()
    case = CaseExample(
        case_id="closed_world_packet",
        title="Closed-world packet",
        narrative="The packet includes an FBI criminal history check showing no felony convictions.",
        structured_fields={
            "evidence_sources": [
                {
                    "source_id": "fbi_check",
                    "source_type": "criminal_history_check",
                    "title": "FBI criminal history check",
                    "closed_world_scopes": ["criminal_convictions"],
                }
            ],
        },
        expected_outcomes=[],
    )
    llm = LLMCaller(
        offline_responses={
            "map_governed_source_inventory": (
                '{"sources":[{"source_id":"fbi_check","source_type":"criminal_history_check",'
                '"title":"FBI check","as_of_date":null,'
                '"closed_world_scopes":["criminal_convictions"],"limitations":""}]}'
            ),
            "map_governed_atom_batch:1": (
                '{"bindings":[{"atom_id":"n400.aggravated_felony_after_1990",'
                '"status":"bound","value":false,"basis":"closed_world_absence",'
                '"source_ids":["fbi_check"],"evidence":"no felony convictions found",'
                '"explanation":"official check","confidence":0.95}]}'
            ),
        }
    )
    step = GovernedEvidenceMapStep(
        llm,
        atom_ids=["n400.aggravated_felony_after_1990"],
        batch_size=4,
    )

    result = step.run(
        program,
        case,
        MapStepContext(program_id="prog", substrate_id=step.spec.map_step_id),
    )

    binding = result.map_record.bindings["n400.aggravated_felony_after_1990"]
    artifacts = result.map_record.metadata["prompt_artifacts"]
    assert binding.value is False
    assert binding.basis == BindingBasis.CLOSED_WORLD_ABSENCE
    assert len(artifacts["batches"]) == 1
    assert artifacts["atoms"]["n400.aggravated_felony_after_1990"]["batch_index"] == 1


def test_governed_map_step_applies_case_default_bindings_to_undetermined_atoms():
    program = _program()
    case = CaseExample(
        case_id="default_packet",
        title="Default packet",
        narrative="The packet contains a clean FBI criminal history check.",
        structured_fields={
            "evidence_sources": [
                {
                    "source_id": "fbi_check",
                    "source_type": "criminal_history_check",
                    "title": "FBI criminal history check",
                    "closed_world_scopes": ["criminal_convictions"],
                }
            ],
            "default_bindings": {
                "n400.aggravated_felony_after_1990": {
                    "value": False,
                    "basis": "closed_world_absence",
                    "source_ids": ["fbi_check"],
                    "evidence": "FBI check reports no aggravated felony conviction.",
                }
            },
        },
        expected_outcomes=[],
    )
    llm = LLMCaller(
        offline_responses={
            "map_governed_source_inventory": (
                '{"sources":[{"source_id":"fbi_check","source_type":"criminal_history_check",'
                '"title":"FBI check","as_of_date":null,'
                '"closed_world_scopes":["criminal_convictions"],"limitations":""}]}'
            ),
            "map_governed_atom:n400.aggravated_felony_after_1990": (
                '{"atom_id":"n400.aggravated_felony_after_1990","status":"undetermined",'
                '"value":"undetermined","basis":"not_found","source_ids":[],'
                '"evidence":null,"explanation":"not found","confidence":0.4}'
            ),
        }
    )
    step = GovernedEvidenceMapStep(llm, atom_ids=["n400.aggravated_felony_after_1990"])

    result = step.run(
        program,
        case,
        MapStepContext(program_id="prog", substrate_id=step.spec.map_step_id),
    )

    binding = result.map_record.bindings["n400.aggravated_felony_after_1990"]
    assert binding.value is False
    assert binding.basis == BindingBasis.CLOSED_WORLD_ABSENCE
    assert binding.metadata["case_default"] is True
    assert result.map_record.metadata["default_binding_count"] == 1


def test_case_default_binding_groups_apply_to_multiple_atoms():
    program = _program()
    case = CaseExample(
        case_id="default_group_packet",
        title="Default group packet",
        narrative="The packet contains a clean FBI criminal history check.",
        structured_fields={
            "default_binding_groups": [
                {
                    "atom_ids": ["n400.aggravated_felony_after_1990"],
                    "value": False,
                    "basis": "explicit_negative",
                    "evidence": "No aggravated felony issue is present.",
                }
            ]
        },
        expected_outcomes=[],
    )
    llm = LLMCaller(
        offline_responses={
            "map_governed_source_inventory": '{"sources":[]}',
            "map_governed_atom:n400.aggravated_felony_after_1990": (
                '{"atom_id":"n400.aggravated_felony_after_1990","status":"undetermined",'
                '"value":"undetermined","basis":"not_found","source_ids":[],'
                '"evidence":null,"explanation":"not found","confidence":0.4}'
            ),
        }
    )
    step = GovernedEvidenceMapStep(llm, atom_ids=["n400.aggravated_felony_after_1990"])

    result = step.run(
        program,
        case,
        MapStepContext(program_id="prog", substrate_id=step.spec.map_step_id),
    )

    binding = result.map_record.bindings["n400.aggravated_felony_after_1990"]
    assert binding.value is False
    assert binding.basis == BindingBasis.EXPLICIT_NEGATIVE


def test_case_default_source_scoped_absence_resolves_to_closed_world_basis():
    program = _program()
    case = CaseExample(
        case_id="case_default_source_scope",
        title="source scoped default",
        narrative="FBI check reports no aggravated felony convictions.",
        structured_fields={
            "default_bindings": {
                "n400.aggravated_felony_after_1990": {
                    "value": False,
                    "basis": "source_scoped_absence",
                    "source_ids": ["fbi_check"],
                    "evidence": "FBI check reports no aggravated felony convictions.",
                }
            }
        },
    )

    result = PreboundFactsMapStep().run(
        program,
        case,
        MapStepContext(program_id="prog_n400"),
    )

    binding = result.map_record.bindings["n400.aggravated_felony_after_1990"]
    assert binding.value is False
    assert binding.basis == BindingBasis.CLOSED_WORLD_ABSENCE


def test_atoms_for_determinations_returns_reachable_atoms():
    atoms = atoms_for_determinations(
        _program(),
        ["n400.no_aggravated_felony_bar"],
    )

    assert atoms == ["n400.aggravated_felony_after_1990"]


def _program() -> DeterminationProgram:
    atom_id = "n400.aggravated_felony_after_1990"
    return DeterminationProgram(
        metadata=ProgramMetadata(name="GMC governance test", version="0.1"),
        map_spec=MapSpec(
            atoms={
                atom_id: BooleanAtom(
                    id=atom_id,
                    statement="The applicant has an aggravated felony conviction after November 29, 1990.",
                    source_span="test",
                    evaluation_mode=EvaluationMode.CHARACTERIZED,
                    binding_policy=AtomBindingPolicy(
                        allowed_bases_for_false=[
                            BindingBasis.CLOSED_WORLD_ABSENCE,
                            BindingBasis.EXPLICIT_NEGATIVE,
                        ],
                        required_source_types_for_false=["criminal_history_check"],
                    ),
                )
            }
        ),
        nodes={
            "n_bar": AtomRef(
                node_id="n_bar",
                provenance=Provenance.STRUCTURAL,
                atom_id=atom_id,
            ),
            "n_no_bar": NotNodeSpec(
                node_id="n_no_bar",
                provenance=Provenance.STRUCTURAL,
                child="n_bar",
                surface_label="placeholder",
            ),
        },
        determinations={
            "n400.no_aggravated_felony_bar": DeterminationSpec(
                id="n400.no_aggravated_felony_bar",
                description="No aggravated felony bar is established.",
                root_node="n_no_bar",
            )
        },
        production_record=ProductionRecord(produced_by="test"),
    )


def _map_record(binding: AtomBindingRecord) -> MapExtractionRecord:
    return MapExtractionRecord(
        map_record_id="map_test",
        program_id="prog",
        case_id="case",
        bindings={binding.atom_id: binding},
    )

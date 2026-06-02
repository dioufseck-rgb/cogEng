from __future__ import annotations

from rulekit.build.llm import LLMCaller
from rulekit.contract import (
    AtomBindingPolicy,
    AtomRef,
    AndNodeSpec,
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


def test_claimant_asserted_proposition_does_not_bind_as_established_fact():
    program = _payment_program()
    case = CaseExample(
        case_id="member_assertion",
        title="Member assertion only",
        narrative="The member says the payment was on time.",
        structured_fields={
            "evidence_sources": [
                {
                    "source_id": "member_statement",
                    "source_type": "member_statement",
                    "source_posture": "claimant_assertion",
                    "title": "Member narrative",
                }
            ],
            "propositions": [
                {
                    "proposition_id": "p1",
                    "atom_id": "test.payment_timely",
                    "value": True,
                    "assertion_status": "asserted",
                    "source_posture": "claimant_assertion",
                    "speaker": "member",
                    "source_ids": ["member_statement"],
                    "evidence_text": "The member says the payment was on time.",
                }
            ],
        },
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="test.payment_timely_determination",
                expected_value="undetermined",
            )
        ],
    )

    result = adjudicate_cases(program, [case], map_step=PreboundFactsMapStep())

    binding = result["map_records"][0]["bindings"]["test.payment_timely"]
    assert result["matched_disposition_count"] == 1
    assert binding["status"] == "undetermined"
    assert binding["value"] == "undetermined"
    assert binding["metadata"]["assertion_status"] == "asserted"
    assert binding["metadata"]["source_posture"] == "claimant_assertion"


def test_established_record_proposition_binds_when_source_posture_is_allowed():
    program = _payment_program()
    case = CaseExample(
        case_id="record_established",
        title="Record established",
        narrative="The bank ledger shows the payment posted before the due date.",
        structured_fields={
            "evidence_sources": [
                {
                    "source_id": "bank_ledger",
                    "source_type": "ledger",
                    "source_posture": "institutional_record",
                    "title": "Bank ledger",
                }
            ],
            "propositions": [
                {
                    "proposition_id": "p1",
                    "atom_id": "test.payment_timely",
                    "value": True,
                    "assertion_status": "established",
                    "source_posture": "institutional_record",
                    "source_ids": ["bank_ledger"],
                    "evidence_text": "Ledger shows payment posted before due date.",
                }
            ],
        },
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="test.payment_timely_determination",
                expected_value="true",
            )
        ],
    )

    result = adjudicate_cases(program, [case], map_step=PreboundFactsMapStep())

    binding = result["map_records"][0]["bindings"]["test.payment_timely"]
    assert result["matched_disposition_count"] == 1
    assert binding["status"] == "bound"
    assert binding["value"] is True
    assert binding["basis"] == "explicit_positive"


def test_profile_concept_vocabulary_expands_only_established_propositions():
    program = _payment_program()
    program.metadata.extras["map_profile"] = {
        "concepts": {
            "payment_posted_before_due_date": {
                "lexical_cues": [
                    "paid before the due date",
                    "posted before the due date",
                ],
                "atom_bindings": [
                    {
                        "id": "payment_timely_from_record",
                        "atom_id": "test.payment_timely",
                        "value": True,
                        "accepted_assertion_statuses": ["established"],
                        "accepted_source_postures": ["institutional_record"],
                    }
                ],
            }
        }
    }
    asserted_case = CaseExample(
        case_id="asserted_concept",
        title="Asserted concept",
        narrative="The member says payment was posted before the due date.",
        structured_fields={
            "propositions": [
                {
                    "proposition_id": "p1",
                    "canonical_concept": "payment_posted_before_due_date",
                    "assertion_status": "asserted",
                    "source_posture": "claimant_assertion",
                    "evidence_text": "The member says payment was posted before the due date.",
                }
            ]
        },
    )
    established_case = CaseExample(
        case_id="established_concept",
        title="Established concept",
        narrative="The bank ledger shows payment was posted before the due date.",
        structured_fields={
            "propositions": [
                {
                    "proposition_id": "p1",
                    "canonical_concept": "payment_posted_before_due_date",
                    "assertion_status": "established",
                    "source_posture": "institutional_record",
                    "evidence_text": "The bank ledger shows payment was posted before the due date.",
                }
            ]
        },
    )

    asserted = PreboundFactsMapStep().run(
        program,
        asserted_case,
        MapStepContext(program_id="profile_vocab"),
    )
    established = PreboundFactsMapStep().run(
        program,
        established_case,
        MapStepContext(program_id="profile_vocab"),
    )

    assert asserted.map_record.bindings["test.payment_timely"].status == (
        AtomBindingStatus.UNDETERMINED
    )
    assert established.map_record.bindings["test.payment_timely"].value is True


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


def test_governed_map_incremental_sufficiency_rechecks_load_bearing_atoms():
    program = _two_atom_program()
    case = CaseExample(
        case_id="incremental_packet",
        title="Incremental packet",
        narrative="The packet establishes condition A and condition B.",
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="test.compliant",
                expected_value="true",
            )
        ],
    )
    llm = LLMCaller(
        offline_responses={
            "map_governed_source_inventory": '{"sources":[]}',
            "map_governed_incremental_round:1:1": (
                '{"bindings":[{"atom_id":"test.a","status":"bound","value":true,'
                '"basis":"explicit_positive","source_ids":[],"evidence":"A",'
                '"explanation":"A established","confidence":0.9}]}'
            ),
            "map_governed_incremental_round:2:1": (
                '{"bindings":[{"atom_id":"test.b","status":"bound","value":true,'
                '"basis":"explicit_positive","source_ids":[],"evidence":"B",'
                '"explanation":"B established","confidence":0.9}]}'
            ),
        }
    )
    step = GovernedEvidenceMapStep(
        llm,
        atom_ids=["test.a", "test.b"],
        batch_size=1,
        incremental_sufficiency=True,
    )

    result = adjudicate_cases(
        program,
        [case],
        determinations=["test.compliant"],
        map_step=step,
    )

    record = result["map_records"][0]
    artifacts = record["metadata"]["prompt_artifacts"]
    assert result["matched_disposition_count"] == 1
    assert record["metadata"]["incremental_sufficiency"] is True
    assert record["bindings"]["test.a"]["value"] is True
    assert record["bindings"]["test.b"]["value"] is True
    assert artifacts["incremental_sufficiency"]["attempted_atoms"] == [
        "test.a",
        "test.b",
    ]
    assert len(artifacts["incremental_sufficiency"]["rounds"]) == 2
    assert artifacts["incremental_sufficiency"]["rounds"][0]["selected_atoms"] == [
        "test.a"
    ]
    assert artifacts["incremental_sufficiency"]["rounds"][1]["selected_atoms"] == [
        "test.b"
    ]


def test_governed_map_step_can_bind_single_map_call():
    program = _program()
    case = CaseExample(
        case_id="single_map_packet",
        title="Single map packet",
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
            "map_governed_single_map": (
                '{"sources":[{"source_id":"fbi_check","source_type":"criminal_history_check",'
                '"title":"FBI check","as_of_date":null,'
                '"closed_world_scopes":["criminal_convictions"],"limitations":""}],'
                '"bindings":[{"atom_id":"n400.aggravated_felony_after_1990",'
                '"status":"bound","value":false,"basis":"closed_world_absence",'
                '"source_ids":["fbi_check"],"evidence":"no felony convictions found",'
                '"explanation":"official check","confidence":0.95}]}'
            ),
        }
    )
    step = GovernedEvidenceMapStep(
        llm,
        atom_ids=["n400.aggravated_felony_after_1990"],
        single_map_call=True,
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
    assert result.map_record.metadata["single_map_call"] is True
    assert len(result.map_record.metadata["llm_call_metrics"]) == 1
    assert artifacts["source_inventory"]["from_single_map_call"] is True
    assert artifacts["atoms"]["n400.aggravated_felony_after_1990"]["single_map"] is True


def test_runtime_repair_unresolved_uses_load_bearing_trace():
    program = _program()
    case = CaseExample(
        case_id="repair_packet",
        title="Repair packet",
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
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="n400.no_aggravated_felony_bar",
                expected_value="true",
            )
        ],
    )
    llm = LLMCaller(
        offline_responses={
            "map_governed_single_map": (
                '{"sources":[{"source_id":"fbi_check","source_type":"criminal_history_check",'
                '"title":"FBI check","as_of_date":null,'
                '"closed_world_scopes":["criminal_convictions"],"limitations":""}],'
                '"bindings":[{"atom_id":"n400.aggravated_felony_after_1990",'
                '"status":"undetermined","value":"undetermined","basis":"not_found",'
                '"source_ids":[],"evidence":null,"explanation":"not found",'
                '"confidence":0.2}]}'
            ),
            "map_governed_repair": (
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
        single_map_call=True,
    )

    result = adjudicate_cases(
        program,
        [case],
        determinations=["n400.no_aggravated_felony_bar"],
        map_step=step,
        repair_unresolved=True,
    )

    disposition = result["dispositions"][0]
    binding = result["map_records"][0]["bindings"]["n400.aggravated_felony_after_1990"]
    assert disposition["outcome"] == "true"
    assert disposition["matched_expected"] is True
    assert disposition["metadata"]["repair"]["atom_ids"] == [
        "n400.aggravated_felony_after_1990"
    ]
    assert binding["value"] is False
    assert binding["metadata"]["repaired"] is True


def test_governed_map_prunes_atoms_already_bound_by_packet_directives():
    program = _program()
    case = CaseExample(
        case_id="prebound_packet",
        title="Prebound packet",
        narrative="FBI check reports no aggravated felony convictions.",
        structured_fields={
            "binding_directives": [
                {
                    "kind": "closed_world_absence",
                    "atom_ids": ["n400.aggravated_felony_after_1990"],
                    "source_ids": ["fbi_check"],
                    "evidence": "FBI check reports no aggravated felony convictions.",
                }
            ]
        },
    )
    step = GovernedEvidenceMapStep(
        LLMCaller(offline_responses={}),
        atom_ids=["n400.aggravated_felony_after_1990"],
        single_map_call=True,
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
    assert result.map_record.metadata["llm_atom_count"] == 0
    assert result.map_record.metadata["prebound_skip_count"] == 1
    assert result.map_record.metadata["llm_call_metrics"] == []
    assert artifacts["single_map"]["skipped"] is True


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


def test_binding_directive_closed_world_absence_expands_to_validated_default():
    program = _program()
    case = CaseExample(
        case_id="directive_source_scope",
        title="source scoped directive",
        narrative="FBI check reports no aggravated felony convictions.",
        structured_fields={
            "binding_directives": [
                {
                    "kind": "closed_world_absence",
                    "atom_ids": ["n400.aggravated_felony_after_1990"],
                    "source_ids": ["fbi_check"],
                    "evidence": "FBI check reports no aggravated felony convictions.",
                }
            ]
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
    assert binding.metadata["default_kind"] == "closed_world_absence"


def test_binding_directive_evidence_gap_preserves_uncertainty():
    program = _program()
    case = CaseExample(
        case_id="directive_evidence_gap",
        title="evidence gap directive",
        narrative="The packet does not include the required source.",
        structured_fields={
            "binding_directives": [
                {
                    "kind": "evidence_gap",
                    "atom_ids": ["n400.aggravated_felony_after_1990"],
                    "evidence": "The required source is missing.",
                }
            ]
        },
    )

    result = PreboundFactsMapStep().run(
        program,
        case,
        MapStepContext(program_id="prog_n400"),
    )

    binding = result.map_record.bindings["n400.aggravated_felony_after_1990"]
    assert binding.value == "undetermined"
    assert binding.status == AtomBindingStatus.UNDETERMINED
    assert binding.basis == BindingBasis.NOT_FOUND
    assert binding.metadata["default_kind"] == "evidence_gap"


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


def _two_atom_program() -> DeterminationProgram:
    return DeterminationProgram(
        metadata=ProgramMetadata(name="Incremental governance test", version="0.1"),
        map_spec=MapSpec(
            atoms={
                "test.a": BooleanAtom(
                    id="test.a",
                    statement="Condition A is established.",
                    source_span="test",
                    evaluation_mode=EvaluationMode.CHARACTERIZED,
                ),
                "test.b": BooleanAtom(
                    id="test.b",
                    statement="Condition B is established.",
                    source_span="test",
                    evaluation_mode=EvaluationMode.CHARACTERIZED,
                ),
            }
        ),
        nodes={
            "n_a": AtomRef(
                node_id="n_a",
                provenance=Provenance.STRUCTURAL,
                atom_id="test.a",
            ),
            "n_b": AtomRef(
                node_id="n_b",
                provenance=Provenance.STRUCTURAL,
                atom_id="test.b",
            ),
            "n_root": AndNodeSpec(
                node_id="n_root",
                provenance=Provenance.STRUCTURAL,
                children=["n_a", "n_b"],
            ),
        },
        determinations={
            "test.compliant": DeterminationSpec(
                id="test.compliant",
                description="Both conditions are satisfied.",
                root_node="n_root",
            )
        },
        production_record=ProductionRecord(produced_by="test"),
    )


def _payment_program() -> DeterminationProgram:
    atom_id = "test.payment_timely"
    return DeterminationProgram(
        metadata=ProgramMetadata(name="Payment posture test", version="0.1"),
        map_spec=MapSpec(
            atoms={
                atom_id: BooleanAtom(
                    id=atom_id,
                    statement="The payment was made on time.",
                    source_span="test",
                    evaluation_mode=EvaluationMode.CHARACTERIZED,
                    binding_policy=AtomBindingPolicy(
                        required_source_postures_for_true=["institutional_record"],
                    ),
                )
            }
        ),
        nodes={
            "n_payment_timely": AtomRef(
                node_id="n_payment_timely",
                provenance=Provenance.STRUCTURAL,
                atom_id=atom_id,
            )
        },
        determinations={
            "test.payment_timely_determination": DeterminationSpec(
                id="test.payment_timely_determination",
                description="The payment was timely.",
                root_node="n_payment_timely",
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

"""FCRA dispute reinvestigation example policy seed.

This is a bounded engineering fixture for exercising RuleKit on a
life-sized statutory workflow. It models selected obligations in
15 U.S.C. 1681i(a): reinvestigation timing, results notice timing, and
correction/deletion when information is inaccurate, incomplete, or
unverifiable. It is not a complete FCRA compliance program.
"""

from __future__ import annotations

from rulekit.orchestrator.factory import (
    AtomDeclaration,
    CaseDeclaration,
    DeterminationDeclaration,
    NodeDeclaration,
    NodeKind,
    PolicyWorkspaceSeed,
)


def fcra_dispute_seed() -> PolicyWorkspaceSeed:
    return PolicyWorkspaceSeed(
        workspace_name="FCRA Dispute Workspace",
        policy_title="FCRA dispute reinvestigation timing",
        policy_text=(
            "Under 15 U.S.C. 1681i(a), when a consumer disputes the "
            "completeness or accuracy of information in a file and the "
            "consumer reporting agency receives notice directly or through "
            "a reseller, the agency must conduct a reasonable reinvestigation "
            "within 30 days. If the consumer provides additional relevant "
            "information during that 30-day period, the completion period is "
            "extended to 45 days. The agency must provide written notice of "
            "the results not later than 5 business days after completion. If "
            "the disputed information is inaccurate, incomplete, or cannot be "
            "verified, the agency must delete or modify the item as appropriate."
        ),
        version_label="15 U.S.C. 1681i(a) bounded fixture",
        atoms=[
            AtomDeclaration(
                atom_id="fcra.consumer_disputed_item",
                statement="The consumer disputed an item in the consumer's file.",
                source_span="15 U.S.C. 1681i(a)(1)(A)",
            ),
            AtomDeclaration(
                atom_id="fcra.dispute_about_completeness_or_accuracy",
                statement="The dispute concerns the completeness or accuracy of the item.",
                source_span="15 U.S.C. 1681i(a)(1)(A)",
            ),
            AtomDeclaration(
                atom_id="fcra.notice_received_by_cra_or_reseller",
                statement="The consumer reporting agency received notice directly or through a reseller.",
                source_span="15 U.S.C. 1681i(a)(1)(A)",
            ),
            AtomDeclaration(
                atom_id="fcra.dispute_frivolous_or_irrelevant",
                statement="The dispute was determined to be frivolous or irrelevant.",
                source_span="15 U.S.C. 1681i(a)(3)",
            ),
            AtomDeclaration(
                atom_id="fcra.additional_relevant_info_in_initial_period",
                statement="The consumer provided additional relevant information during the initial 30-day period.",
                source_span="15 U.S.C. 1681i(a)(1)(B)",
            ),
            AtomDeclaration(
                atom_id="fcra.reinvestigation_completed",
                statement="The consumer reporting agency completed the reinvestigation.",
                source_span="15 U.S.C. 1681i(a)(1)(A)",
            ),
            AtomDeclaration(
                atom_id="fcra.days_to_complete_reinvestigation",
                statement="The number of calendar days from receipt of the dispute notice to completion of the reinvestigation.",
                source_span="15 U.S.C. 1681i(a)(1)",
                atom_type="numeric",
                numeric_unit="days",
            ),
            AtomDeclaration(
                atom_id="fcra.results_notice_provided",
                statement="The consumer reporting agency provided notice of the reinvestigation results to the consumer.",
                source_span="15 U.S.C. 1681i(a)(6)",
            ),
            AtomDeclaration(
                atom_id="fcra.business_days_to_results_notice",
                statement="The number of business days from completion of the reinvestigation to notice of results.",
                source_span="15 U.S.C. 1681i(a)(6)",
                atom_type="numeric",
                numeric_unit="business_days",
            ),
            AtomDeclaration(
                atom_id="fcra.item_found_inaccurate",
                statement="The disputed item was found to be inaccurate.",
                source_span="15 U.S.C. 1681i(a)(5)(A)",
            ),
            AtomDeclaration(
                atom_id="fcra.item_found_incomplete",
                statement="The disputed item was found to be incomplete.",
                source_span="15 U.S.C. 1681i(a)(5)(A)",
            ),
            AtomDeclaration(
                atom_id="fcra.item_unverifiable",
                statement="The disputed item could not be verified.",
                source_span="15 U.S.C. 1681i(a)(5)(A)",
            ),
            AtomDeclaration(
                atom_id="fcra.item_deleted_or_modified",
                statement="The disputed item was deleted or modified as appropriate.",
                source_span="15 U.S.C. 1681i(a)(5)(A)",
            ),
        ],
        nodes=[
            _atom("n_disputed", "fcra.consumer_disputed_item"),
            _atom("n_accuracy", "fcra.dispute_about_completeness_or_accuracy"),
            _atom("n_notice_received", "fcra.notice_received_by_cra_or_reseller"),
            _atom("n_frivolous", "fcra.dispute_frivolous_or_irrelevant"),
            NodeDeclaration(node_id="n_not_frivolous", kind=NodeKind.NOT, child="n_frivolous"),
            NodeDeclaration(
                node_id="n_valid_reinvestigation_trigger",
                kind=NodeKind.AND,
                children=[
                    "n_disputed",
                    "n_accuracy",
                    "n_notice_received",
                    "n_not_frivolous",
                ],
                surface_label="non-frivolous disputed accuracy item received by CRA/reseller",
                source_span="15 U.S.C. 1681i(a)(1)(A), (a)(3)",
            ),
            _atom("n_additional_info", "fcra.additional_relevant_info_in_initial_period"),
            NodeDeclaration(node_id="n_30", kind=NodeKind.CONSTANT, literal_value=30),
            NodeDeclaration(node_id="n_45", kind=NodeKind.CONSTANT, literal_value=45),
            NodeDeclaration(
                node_id="n_allowed_completion_days",
                kind=NodeKind.CONDITIONAL_NUMERIC,
                condition="n_additional_info",
                if_true="n_45",
                if_false="n_30",
                surface_label="30 days, extended to 45 when additional relevant information is received",
                source_span="15 U.S.C. 1681i(a)(1)(A)-(B)",
            ),
            _num("n_completion_days", "fcra.days_to_complete_reinvestigation"),
            NodeDeclaration(
                node_id="n_completion_within_allowed_days",
                kind=NodeKind.COMPARISON,
                operator="leq",
                left="n_completion_days",
                right="n_allowed_completion_days",
                surface_label="reinvestigation completed within the applicable statutory period",
                source_span="15 U.S.C. 1681i(a)(1)",
            ),
            _atom("n_reinvestigation_completed", "fcra.reinvestigation_completed"),
            NodeDeclaration(
                node_id="n_reinvestigation_timely",
                kind=NodeKind.AND,
                children=[
                    "n_valid_reinvestigation_trigger",
                    "n_reinvestigation_completed",
                    "n_completion_within_allowed_days",
                ],
                surface_label="timely reinvestigation obligation satisfied",
                source_span="15 U.S.C. 1681i(a)(1)",
            ),
            _atom("n_results_notice", "fcra.results_notice_provided"),
            _num("n_notice_business_days", "fcra.business_days_to_results_notice"),
            NodeDeclaration(node_id="n_5", kind=NodeKind.CONSTANT, literal_value=5),
            NodeDeclaration(
                node_id="n_notice_within_5_business_days",
                kind=NodeKind.COMPARISON,
                operator="leq",
                left="n_notice_business_days",
                right="n_5",
                surface_label="results notice within 5 business days after completion",
                source_span="15 U.S.C. 1681i(a)(6)",
            ),
            NodeDeclaration(
                node_id="n_results_notice_timely",
                kind=NodeKind.AND,
                children=[
                    "n_reinvestigation_completed",
                    "n_results_notice",
                    "n_notice_within_5_business_days",
                ],
                surface_label="results notice obligation satisfied",
                source_span="15 U.S.C. 1681i(a)(6)",
            ),
            _atom("n_inaccurate", "fcra.item_found_inaccurate"),
            _atom("n_incomplete", "fcra.item_found_incomplete"),
            _atom("n_unverifiable", "fcra.item_unverifiable"),
            NodeDeclaration(
                node_id="n_defect_found",
                kind=NodeKind.OR,
                children=["n_inaccurate", "n_incomplete", "n_unverifiable"],
                surface_label="item inaccurate, incomplete, or unverifiable",
                source_span="15 U.S.C. 1681i(a)(5)(A)",
            ),
            NodeDeclaration(node_id="n_no_defect_found", kind=NodeKind.NOT, child="n_defect_found"),
            _atom("n_deleted_or_modified", "fcra.item_deleted_or_modified"),
            NodeDeclaration(
                node_id="n_correction_obligation_satisfied",
                kind=NodeKind.OR,
                children=["n_no_defect_found", "n_deleted_or_modified"],
                surface_label="if correction was required, the item was deleted or modified",
                source_span="15 U.S.C. 1681i(a)(5)(A)",
            ),
            NodeDeclaration(
                node_id="n_overall_compliant",
                kind=NodeKind.AND,
                children=[
                    "n_reinvestigation_timely",
                    "n_results_notice_timely",
                    "n_correction_obligation_satisfied",
                ],
                surface_label="selected 1681i(a) dispute-resolution obligations satisfied",
                source_span="15 U.S.C. 1681i(a)(1), (a)(5), (a)(6)",
            ),
        ],
        determinations=[
            DeterminationDeclaration(
                determination_id="fcra.valid_reinvestigation_trigger",
                description="A non-frivolous dispute triggered the reinvestigation obligation.",
                root_node="n_valid_reinvestigation_trigger",
                source_span="15 U.S.C. 1681i(a)(1)(A), (a)(3)",
            ),
            DeterminationDeclaration(
                determination_id="fcra.reinvestigation_timely",
                description="The reinvestigation was completed within the applicable statutory period.",
                root_node="n_reinvestigation_timely",
                source_span="15 U.S.C. 1681i(a)(1)",
            ),
            DeterminationDeclaration(
                determination_id="fcra.results_notice_timely",
                description="Notice of the reinvestigation results was timely.",
                root_node="n_results_notice_timely",
                source_span="15 U.S.C. 1681i(a)(6)",
            ),
            DeterminationDeclaration(
                determination_id="fcra.correction_obligation_satisfied",
                description="The item was deleted or modified when correction was required.",
                root_node="n_correction_obligation_satisfied",
                source_span="15 U.S.C. 1681i(a)(5)(A)",
            ),
            DeterminationDeclaration(
                determination_id="fcra.selected_dispute_obligations_satisfied",
                description="Selected FCRA dispute-resolution obligations were satisfied.",
                root_node="n_overall_compliant",
                source_span="15 U.S.C. 1681i(a)(1), (a)(5), (a)(6)",
            ),
        ],
        cases=_cases(),
    )


def _atom(node_id: str, atom_id: str) -> NodeDeclaration:
    return NodeDeclaration(node_id=node_id, kind=NodeKind.ATOM_REF, atom_id=atom_id)


def _num(node_id: str, atom_id: str) -> NodeDeclaration:
    return NodeDeclaration(node_id=node_id, kind=NodeKind.NUMERIC_ATOM_REF, atom_id=atom_id)


def _cases() -> list[CaseDeclaration]:
    return [
        _case(
            "fcra_timely_verified",
            "Timely verified dispute",
            "A valid non-frivolous accuracy dispute was completed in 28 days; results notice was sent 3 business days later; the item was verified.",
            {
                "fcra.days_to_complete_reinvestigation": 28,
                "fcra.business_days_to_results_notice": 3,
            },
            expected="true",
        ),
        _case(
            "fcra_extension_and_correction",
            "45-day extension with correction",
            "The consumer submitted additional relevant information during the initial period. The reinvestigation completed in 42 days, notice was sent after 5 business days, and an incomplete item was modified.",
            {
                "fcra.additional_relevant_info_in_initial_period": True,
                "fcra.days_to_complete_reinvestigation": 42,
                "fcra.business_days_to_results_notice": 5,
                "fcra.item_found_incomplete": True,
                "fcra.item_deleted_or_modified": True,
            },
            expected="true",
        ),
        _case(
            "fcra_late_reinvestigation",
            "Late reinvestigation",
            "No additional information extended the period. The reinvestigation was completed after 40 days.",
            {
                "fcra.days_to_complete_reinvestigation": 40,
                "fcra.business_days_to_results_notice": 3,
            },
            expected="false",
        ),
        _case(
            "fcra_late_notice",
            "Late results notice",
            "The reinvestigation completed in 25 days but the results notice was sent 8 business days after completion.",
            {
                "fcra.days_to_complete_reinvestigation": 25,
                "fcra.business_days_to_results_notice": 8,
            },
            expected="false",
        ),
        _case(
            "fcra_unverifiable_not_deleted",
            "Unverifiable item not corrected",
            "The reinvestigation completed in 20 days and notice was timely, but the item could not be verified and was not deleted or modified.",
            {
                "fcra.days_to_complete_reinvestigation": 20,
                "fcra.business_days_to_results_notice": 2,
                "fcra.item_unverifiable": True,
                "fcra.item_deleted_or_modified": False,
            },
            expected="false",
        ),
        _case(
            "fcra_missing_completion_days",
            "Missing completion date",
            "The record shows a valid dispute and timely notice, but the completion date is missing.",
            {
                "fcra.days_to_complete_reinvestigation": "undetermined",
                "fcra.business_days_to_results_notice": 2,
            },
            expected="undetermined",
        ),
    ]


def _case(
    case_id: str,
    title: str,
    narrative: str,
    facts: dict[str, object],
    *,
    expected: str,
) -> CaseDeclaration:
    base_facts = {
        "fcra.consumer_disputed_item": True,
        "fcra.dispute_about_completeness_or_accuracy": True,
        "fcra.notice_received_by_cra_or_reseller": True,
        "fcra.dispute_frivolous_or_irrelevant": False,
        "fcra.additional_relevant_info_in_initial_period": False,
        "fcra.reinvestigation_completed": True,
        "fcra.results_notice_provided": True,
        "fcra.item_found_inaccurate": False,
        "fcra.item_found_incomplete": False,
        "fcra.item_unverifiable": False,
        "fcra.item_deleted_or_modified": False,
    }
    base_facts.update(facts)
    return CaseDeclaration(
        case_id=case_id,
        title=title,
        narrative=narrative,
        structured_fields={"facts": base_facts},
        expected_outcomes={
            "fcra.selected_dispute_obligations_satisfied": expected,
        },
    )


__all__ = ["fcra_dispute_seed"]

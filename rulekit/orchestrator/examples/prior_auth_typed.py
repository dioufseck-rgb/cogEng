"""Typed prior-authorization example seed.

This is a domain example, not a domain-specific runtime. It demonstrates
how a governed disposition program can combine boolean findings, numeric
facts, arithmetic, comparisons, complements, and review-grade test cases.
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


def prior_auth_typed_seed() -> PolicyWorkspaceSeed:
    """Return a typed seed for a generic prior-authorization policy."""
    return PolicyWorkspaceSeed(
        workspace_name="Prior Authorization Typed Workspace",
        policy_title="Physical therapy continuation policy",
        policy_text=(
            "Continuation of physical therapy is approved when the patient has "
            "a documented functional limitation, has completed at least six "
            "weeks of conservative therapy, and has not materially improved. "
            "Material improvement means the documented pain score improved by "
            "more than two points from baseline. Coverage may also be approved "
            "as an exception when severe limitation is documented and the "
            "provider attests that delay would risk material deterioration. "
            "If facts needed to apply the rule are missing, the request should "
            "be routed for human review."
        ),
        policy_id="pol_prior_auth_typed",
        version_label="draft_typed",
        constants={
            "minimum_prior_therapy_weeks": "6",
            "maximum_material_improvement_points": "2",
        },
        atoms=[
            AtomDeclaration(
                atom_id="pa.functional_limitation",
                statement="The patient has a documented functional limitation.",
                source_span="documented functional limitation",
                extraction_template=(
                    "Return true when the record states a functional limitation; "
                    "false when it states no limitation; otherwise undetermined."
                ),
                undetermined_rule="Missing or ambiguous functional status requires review.",
            ),
            AtomDeclaration(
                atom_id="pa.severe_limitation",
                statement="The patient has a documented severe limitation.",
                source_span="severe limitation is documented",
                extraction_template="Return true only when severe limitation is documented.",
            ),
            AtomDeclaration(
                atom_id="pa.provider_delay_risk_attestation",
                statement=(
                    "The provider attests that delay would risk material deterioration."
                ),
                source_span="provider attests that delay would risk material deterioration",
                extraction_template=(
                    "Return true when the provider makes the delay-risk attestation."
                ),
            ),
            AtomDeclaration(
                atom_id="pa.prior_therapy_weeks",
                statement="The number of completed prior conservative therapy weeks.",
                source_span="completed at least six weeks of conservative therapy",
                atom_type="numeric",
                numeric_unit="weeks",
                extraction_template="Extract the completed prior therapy duration in weeks.",
                undetermined_rule="If duration is not stated, route for human review.",
            ),
            AtomDeclaration(
                atom_id="pa.baseline_pain_score",
                statement="The baseline documented pain score.",
                source_span="pain score improved",
                atom_type="numeric",
                numeric_unit="points",
                extraction_template="Extract the baseline pain score as a number.",
            ),
            AtomDeclaration(
                atom_id="pa.current_pain_score",
                statement="The current documented pain score.",
                source_span="pain score improved",
                atom_type="numeric",
                numeric_unit="points",
                extraction_template="Extract the current pain score as a number.",
            ),
        ],
        nodes=[
            NodeDeclaration(
                node_id="n_functional_limitation",
                kind=NodeKind.ATOM_REF,
                atom_id="pa.functional_limitation",
                source_span="documented functional limitation",
            ),
            NodeDeclaration(
                node_id="n_severe_limitation",
                kind=NodeKind.ATOM_REF,
                atom_id="pa.severe_limitation",
                source_span="severe limitation is documented",
            ),
            NodeDeclaration(
                node_id="n_delay_risk",
                kind=NodeKind.ATOM_REF,
                atom_id="pa.provider_delay_risk_attestation",
                source_span="provider attests that delay would risk material deterioration",
            ),
            NodeDeclaration(
                node_id="n_prior_therapy_weeks",
                kind=NodeKind.NUMERIC_ATOM_REF,
                atom_id="pa.prior_therapy_weeks",
                source_span="completed at least six weeks",
            ),
            NodeDeclaration(
                node_id="n_minimum_weeks",
                kind=NodeKind.CONSTANT,
                constant_label="minimum_prior_therapy_weeks",
                surface_label="Minimum prior therapy weeks",
                source_span="at least six weeks",
            ),
            NodeDeclaration(
                node_id="n_completed_minimum_duration",
                kind=NodeKind.COMPARISON,
                operator="geq",
                left="n_prior_therapy_weeks",
                right="n_minimum_weeks",
                surface_label="Completed required prior therapy duration",
                source_span="completed at least six weeks",
            ),
            NodeDeclaration(
                node_id="n_baseline_pain",
                kind=NodeKind.NUMERIC_ATOM_REF,
                atom_id="pa.baseline_pain_score",
                source_span="baseline pain score",
            ),
            NodeDeclaration(
                node_id="n_current_pain",
                kind=NodeKind.NUMERIC_ATOM_REF,
                atom_id="pa.current_pain_score",
                source_span="current pain score",
            ),
            NodeDeclaration(
                node_id="n_pain_improvement",
                kind=NodeKind.BINARY_ARITHMETIC,
                operator="minus",
                left="n_baseline_pain",
                right="n_current_pain",
                surface_label="Pain score improvement",
                source_span="pain score improved",
            ),
            NodeDeclaration(
                node_id="n_material_improvement_limit",
                kind=NodeKind.CONSTANT,
                constant_label="maximum_material_improvement_points",
                surface_label="Material improvement threshold",
                source_span="more than two points",
            ),
            NodeDeclaration(
                node_id="n_not_materially_improved",
                kind=NodeKind.COMPARISON,
                operator="leq",
                left="n_pain_improvement",
                right="n_material_improvement_limit",
                surface_label="No material pain improvement",
                source_span="improved by more than two points",
            ),
            NodeDeclaration(
                node_id="n_standard_path",
                kind=NodeKind.AND,
                children=[
                    "n_functional_limitation",
                    "n_completed_minimum_duration",
                    "n_not_materially_improved",
                ],
                surface_label="Standard approval path",
                source_span=(
                    "functional limitation, completed at least six weeks, "
                    "and has not materially improved"
                ),
            ),
            NodeDeclaration(
                node_id="n_exception_path",
                kind=NodeKind.AND,
                children=["n_severe_limitation", "n_delay_risk"],
                surface_label="Exception approval path",
                source_span="severe limitation is documented and provider attests",
            ),
            NodeDeclaration(
                node_id="n_approved_root",
                kind=NodeKind.OR,
                children=["n_standard_path", "n_exception_path"],
                surface_label="Prior authorization approval",
                source_span="approved when standard path or exception path applies",
            ),
        ],
        determinations=[
            DeterminationDeclaration(
                determination_id="pa.approved",
                description="The prior-authorization request is approved.",
                root_node="n_approved_root",
                polarity="positive",
                source_span="Continuation of physical therapy is approved",
            ),
            DeterminationDeclaration(
                determination_id="pa.denied",
                description="The prior-authorization request is denied.",
                composition="complement",
                linked_to="pa.approved",
                polarity="negative",
                source_span="Requests not satisfying approval criteria are denied.",
            ),
        ],
        cases=[
            CaseDeclaration(
                case_id="case_standard_approved",
                title="Standard path approved",
                narrative=(
                    "The patient has a documented functional limitation, completed "
                    "8 weeks of therapy, and pain changed from 8 to 7."
                ),
                structured_fields={
                    "facts": {
                        "pa.functional_limitation": True,
                        "pa.severe_limitation": False,
                        "pa.provider_delay_risk_attestation": False,
                        "pa.prior_therapy_weeks": 8,
                        "pa.baseline_pain_score": 8,
                        "pa.current_pain_score": 7,
                    }
                },
                expected_outcomes={"pa.approved": "true", "pa.denied": "false"},
            ),
            CaseDeclaration(
                case_id="case_materially_improved_denied",
                title="Denied after material improvement",
                narrative=(
                    "The patient has a functional limitation and completed 8 weeks, "
                    "but pain improved from 8 to 3. No severe exception applies."
                ),
                structured_fields={
                    "facts": {
                        "pa.functional_limitation": True,
                        "pa.severe_limitation": False,
                        "pa.provider_delay_risk_attestation": False,
                        "pa.prior_therapy_weeks": 8,
                        "pa.baseline_pain_score": 8,
                        "pa.current_pain_score": 3,
                    }
                },
                expected_outcomes={"pa.approved": "false", "pa.denied": "true"},
            ),
            CaseDeclaration(
                case_id="case_exception_approved",
                title="Exception path approved",
                narrative=(
                    "The patient has severe limitation and the provider attests "
                    "delay would risk deterioration, despite only 2 weeks of therapy."
                ),
                structured_fields={
                    "facts": {
                        "pa.functional_limitation": False,
                        "pa.severe_limitation": True,
                        "pa.provider_delay_risk_attestation": True,
                        "pa.prior_therapy_weeks": 2,
                        "pa.baseline_pain_score": 8,
                        "pa.current_pain_score": 7,
                    }
                },
                expected_outcomes={"pa.approved": "true", "pa.denied": "false"},
            ),
            CaseDeclaration(
                case_id="case_missing_duration_review",
                title="Missing duration requires review",
                narrative=(
                    "The patient has a functional limitation and pain changed from "
                    "8 to 7, but the therapy duration is not documented. No severe "
                    "exception is documented."
                ),
                structured_fields={
                    "facts": {
                        "pa.functional_limitation": True,
                        "pa.severe_limitation": False,
                        "pa.provider_delay_risk_attestation": False,
                        "pa.baseline_pain_score": 8,
                        "pa.current_pain_score": 7,
                    }
                },
                expected_outcomes={
                    "pa.approved": "undetermined",
                    "pa.denied": "undetermined",
                },
            ),
        ],
        metadata={
            "example": "prior-auth-typed",
            "domain": "prior_authorization",
            "human_review_policy": (
                "Treat undetermined approval/denial outcomes as human review required."
            ),
        },
    )


__all__ = ["prior_auth_typed_seed"]

"""
Replay the previous run results through the NEW policy logic without
making any substrate calls.

The previous run produced traces for all five cases. We have the
substrate's per-leaf outputs (value, confidence, signals) captured in
the printed trace. This script reconstructs minimal NodeResult objects
from that information and pushes them through the new
_compute_pa_disposition and _compute_routing_tier_pa to project what
the new policy would produce.

This is for design validation, not for production. The actual rerun
should be done against the substrate. But this lets us check the
policy changes are correctly tuned before spending the API calls.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DERIVE = _HERE.parent / "derive_design"
sys.path.insert(0, str(_DERIVE))
sys.path.insert(0, str(_HERE))

from derive_orchestrator import NodeResult, EscalationSignals
from disposition_router import DispositionRouter, RoutingTier
from case_loader import load_tree
PA_APPEAL_TREE, TREE_METADATA = load_tree(_HERE / "pa_appeal_tree.json")


def make_signals(*signal_names):
    sigs = EscalationSignals()
    for name in signal_names:
        setattr(sigs, name, True)
    return sigs


def make_result(node_id, value=None, confidence=0.0, signals=None,
                short_circuited=False, escalation_reason="", reasoning=""):
    return NodeResult(
        node_id=node_id,
        value=value,
        confidence=confidence,
        cited_facts=[],
        reasoning=reasoning,
        escalation_signals=signals or EscalationSignals(),
        escalation_reason=escalation_reason,
        short_circuited=short_circuited,
        error=None,
    )


# Reconstruct traces from the prior printed output for each case.
# Each entry captures: value, confidence, signals fired.

CASE_TRACES = {
    # =========================================================================
    "achebe": {
        # disposition: uphold + hold
        "root.acdf_appeal": ("compose", None, 1.0, []),
        "denial_procedurally_adequate": ("compose", None, 0.85, ["esc"]),
        "denial_specifies_criteria": ("char", True, 0.85, ["contested_reading"]),
        "denial_specifies_clinical_reason": ("char", True, 0.92, []),
        "denial_provides_imr_rights": ("char", False, 0.95, ["insufficient_facts"]),
        "denial_factual_basis_correct": ("char", "PARTIALLY_INACCURATE", 0.85, ["contested_reading"]),
        "plan_criteria_satisfied": ("compose", False, 0.95, []),
        "diagnosis_requirement_met": ("compose", None, 0.95, ["esc"]),
        "cervical_radiculopathy_diagnosed": ("char", False, 0.95, []),
        "cervical_myelopathy_diagnosed": ("char", False, 0.85, ["contested_reading", "contradictory_facts"]),
        "disc_herniation_with_neurological_deficit": ("char", True, 0.85, ["contested_reading"]),
        "conservative_treatment_met": ("compose", False, 0.95, []),
        "pt_requirement_met": ("char", False, 0.95, []),
        "pharmacotherapy_requirement_met": ("char", None, 0.0, [], True),
        "interventional_requirement_met_or_waived": ("char", None, 0.0, [], True),
        "imaging_requirement_met": ("char", None, 0.0, [], True),
        "physician_documentation_complete": ("compose", None, 0.0, [], True),
        "no_exclusion_applies": ("compose", None, 0.0, [], True),
        "regulatory_carve_out_applies": ("compose", None, 0.85, ["esc"]),
        "cic_10169_5_carve_out": ("compose", None, 0.85, ["esc"]),
        "pt_contraindicated_or_futile": ("char", False, 0.75, ["contested_reading"]),
        "functional_plateau_documented": ("char", False, 0.85, ["insufficient_facts"]),
        "structural_neurological_compromise": ("char", False, 0.75, ["contested_reading", "requires_institutional_judgment"]),
        "apl_22_014_carve_out": ("compose", None, 0.75, ["esc"]),
        "objective_progressive_pathology": ("char", False, 0.95, ["insufficient_facts"]),
        "conservative_failed_to_arrest": ("char", False, 0.85, ["contested_reading"]),
        "surgery_indicated_clinically": ("char", True, 0.75, ["contested_reading"]),
        "clinical_standard_supports_surgery": ("char", "TIER_3", 0.85, ["contested_reading", "requires_institutional_judgment", "contradictory_facts"]),
    },
    # =========================================================================
    "turner": {
        # was: overturn_procedural_defect + hold
        # expected GT: overturn_procedural_defect + auto/gate
        "root.acdf_appeal": ("compose", None, 1.0, []),
        "denial_procedurally_adequate": ("compose", False, 1.0, []),
        "denial_specifies_criteria": ("char", False, 0.95, ["contested_reading"]),
        "denial_specifies_clinical_reason": ("char", False, 0.90, ["contested_reading"]),
        "denial_provides_imr_rights": ("char", False, 1.0, []),
        "denial_factual_basis_correct": ("char", "INACCURATE", 0.85, ["contested_reading"]),
        "plan_criteria_satisfied": ("compose", False, 0.95, []),
        "diagnosis_requirement_met": ("compose", True, 0.95, []),
        "cervical_radiculopathy_diagnosed": ("char", True, 0.95, []),
        "cervical_myelopathy_diagnosed": ("char", None, 0.0, [], True),
        "disc_herniation_with_neurological_deficit": ("char", None, 0.0, [], True),
        "conservative_treatment_met": ("compose", False, 0.95, []),
        "pt_requirement_met": ("char", False, 0.95, []),
        "pharmacotherapy_requirement_met": ("char", None, 0.0, [], True),
        "interventional_requirement_met_or_waived": ("char", None, 0.0, [], True),
        "imaging_requirement_met": ("char", None, 0.0, [], True),
        "physician_documentation_complete": ("compose", None, 0.0, [], True),
        "no_exclusion_applies": ("compose", None, 0.0, [], True),
        "regulatory_carve_out_applies": ("compose", None, 0.85, ["esc"]),
        "cic_10169_5_carve_out": ("compose", None, 0.85, ["esc"]),
        "pt_contraindicated_or_futile": ("char", False, 0.85, ["contested_reading"]),
        "functional_plateau_documented": ("char", False, 0.85, ["contested_reading"]),
        "structural_neurological_compromise": ("char", False, 0.85, ["contested_reading"]),
        "apl_22_014_carve_out": ("compose", None, 0.85, ["esc"]),
        "objective_progressive_pathology": ("char", False, 0.85, ["insufficient_facts"]),
        "conservative_failed_to_arrest": ("char", False, 0.85, ["contested_reading"]),
        "surgery_indicated_clinically": ("char", False, 0.85, ["contested_reading"]),
        "clinical_standard_supports_surgery": ("char", "TIER_3", 0.85, ["contested_reading"]),
    },
    # =========================================================================
    "harris": {
        # was: overturn_factual_error_in_denial + hold
        # expected GT: overturn_factual_error_in_denial + gate
        "root.acdf_appeal": ("compose", None, 1.0, []),
        "denial_procedurally_adequate": ("compose", None, 0.0, ["esc"]),
        "denial_specifies_criteria": ("char", None, 0.85, ["contested_reading"]),
        "denial_specifies_clinical_reason": ("char", None, 0.75, ["contested_reading"]),
        "denial_provides_imr_rights": ("char", None, 0.0, ["esc"]),
        "denial_factual_basis_correct": ("char", "INACCURATE", 0.95, []),
        "plan_criteria_satisfied": ("compose", None, 0.0, ["esc"]),
        "diagnosis_requirement_met": ("compose", True, 1.0, []),
        "cervical_radiculopathy_diagnosed": ("char", True, 1.0, []),
        "cervical_myelopathy_diagnosed": ("char", None, 0.0, [], True),
        "disc_herniation_with_neurological_deficit": ("char", None, 0.0, [], True),
        "conservative_treatment_met": ("compose", True, 0.95, []),
        "pt_requirement_met": ("char", True, 0.95, []),
        "pharmacotherapy_requirement_met": ("char", True, 0.95, []),
        "interventional_requirement_met_or_waived": ("char", True, 1.0, []),
        "imaging_requirement_met": ("char", True, 0.90, []),
        "physician_documentation_complete": ("compose", None, 0.0, ["esc"]),
        "attestation_conservative_treatment": ("char", None, 0.0, ["contested_reading"]),
        "clinical_rationale_for_surgery": ("char", True, 0.95, []),
        "functional_limitations_described": ("char", None, 0.65, ["contested_reading", "low_confidence_in_value"]),
        "surgical_risks_alternatives_addressed": ("char", None, 0.0, ["insufficient_facts"]),
        "no_exclusion_applies": ("compose", True, 0.92, []),
        "exclusion_3_1_axial_pain_only": ("char", True, 0.95, []),
        "exclusion_3_3_imaging_inconsistent": ("char", True, 0.92, []),
        "exclusion_3_4_experimental_procedure": ("char", True, 0.95, []),
        "regulatory_carve_out_applies": ("compose", True, 0.95, []),
        "cic_10169_5_carve_out": ("compose", True, 0.95, []),
        "pt_contraindicated_or_futile": ("char", True, 0.95, []),
        "functional_plateau_documented": ("char", None, 0.0, [], True),
        "structural_neurological_compromise": ("char", None, 0.0, [], True),
        "apl_22_014_carve_out": ("compose", None, 0.0, [], True),
        "clinical_standard_supports_surgery": ("char", "TIER_2", 0.85, ["contested_reading"]),
    },
    # =========================================================================
    "clark": {
        # was: overturn_procedural_defect + hold
        # expected GT: overturn_plan_criteria_met + auto/gate
        "root.acdf_appeal": ("compose", None, 1.0, []),
        "denial_procedurally_adequate": ("compose", False, 0.95, []),
        "denial_specifies_criteria": ("char", False, 0.95, ["contested_reading"]),
        "denial_specifies_clinical_reason": ("char", False, 0.85, ["contested_reading"]),
        "denial_provides_imr_rights": ("char", False, 0.95, []),
        "denial_factual_basis_correct": ("char", "PARTIALLY_INACCURATE", 0.85, ["contested_reading"]),
        "plan_criteria_satisfied": ("compose", None, 0.0, ["esc"]),
        "diagnosis_requirement_met": ("compose", True, 1.0, []),
        "cervical_radiculopathy_diagnosed": ("char", True, 1.0, []),
        "cervical_myelopathy_diagnosed": ("char", None, 0.0, [], True),
        "disc_herniation_with_neurological_deficit": ("char", None, 0.0, [], True),
        "conservative_treatment_met": ("compose", None, 0.85, ["esc"]),
        "pt_requirement_met": ("char", True, 1.0, []),
        "pharmacotherapy_requirement_met": ("char", None, 0.85, ["contested_reading"]),
        "interventional_requirement_met_or_waived": ("char", True, 1.0, []),
        "imaging_requirement_met": ("char", True, 0.95, []),
        "physician_documentation_complete": ("compose", None, 0.0, ["esc"]),
        "attestation_conservative_treatment": ("char", None, 0.0, ["contested_reading"]),
        "clinical_rationale_for_surgery": ("char", None, 0.0, ["contested_reading"]),
        "functional_limitations_described": ("char", None, 0.0, ["insufficient_facts"]),
        "surgical_risks_alternatives_addressed": ("char", None, 0.0, ["insufficient_facts"]),
        "no_exclusion_applies": ("compose", True, 0.95, []),
        "exclusion_3_1_axial_pain_only": ("char", True, 1.0, []),
        "exclusion_3_3_imaging_inconsistent": ("char", True, 0.98, []),
        "exclusion_3_4_experimental_procedure": ("char", True, 0.95, []),
        "regulatory_carve_out_applies": ("compose", True, 0.95, []),
        "cic_10169_5_carve_out": ("compose", True, 0.95, []),
        "pt_contraindicated_or_futile": ("char", False, 0.95, []),
        "functional_plateau_documented": ("char", True, 0.95, []),
        "structural_neurological_compromise": ("char", None, 0.0, [], True),
        "apl_22_014_carve_out": ("compose", None, 0.0, [], True),
        "clinical_standard_supports_surgery": ("char", "TIER_2", 0.85, ["contested_reading"]),
    },
    # =========================================================================
    "kamau": {
        # was: overturn_procedural_defect + hold
        # expected GT: overturn_plan_criteria_met + gate
        "root.acdf_appeal": ("compose", None, 1.0, []),
        "denial_procedurally_adequate": ("compose", False, 0.95, []),
        "denial_specifies_criteria": ("char", False, 0.95, []),
        "denial_specifies_clinical_reason": ("char", None, 0.0, [], True),
        "denial_provides_imr_rights": ("char", None, 0.0, [], True),
        "denial_factual_basis_correct": ("char", "INACCURATE", 0.95, []),
        "plan_criteria_satisfied": ("compose", None, 0.0, ["esc"]),
        "diagnosis_requirement_met": ("compose", True, 1.0, []),
        "cervical_radiculopathy_diagnosed": ("char", True, 1.0, []),
        "cervical_myelopathy_diagnosed": ("char", None, 0.0, [], True),
        "disc_herniation_with_neurological_deficit": ("char", None, 0.0, [], True),
        "conservative_treatment_met": ("compose", None, 0.85, ["esc"]),
        "pt_requirement_met": ("char", True, 0.95, []),
        "pharmacotherapy_requirement_met": ("char", None, 0.85, ["contested_reading"]),
        "interventional_requirement_met_or_waived": ("char", True, 1.0, []),
        "imaging_requirement_met": ("char", True, 0.98, []),
        "physician_documentation_complete": ("compose", None, 0.0, ["esc"]),
        "attestation_conservative_treatment": ("char", None, 0.85, ["contested_reading"]),
        "clinical_rationale_for_surgery": ("char", True, 0.95, []),
        "functional_limitations_described": ("char", None, 0.0, ["insufficient_facts"]),
        "surgical_risks_alternatives_addressed": ("char", None, 0.0, ["insufficient_facts"]),
        "no_exclusion_applies": ("compose", True, 0.95, []),
        "exclusion_3_1_axial_pain_only": ("char", True, 1.0, []),
        "exclusion_3_3_imaging_inconsistent": ("char", True, 0.98, []),
        "exclusion_3_4_experimental_procedure": ("char", True, 0.95, []),
        "regulatory_carve_out_applies": ("compose", True, 0.95, []),
        "cic_10169_5_carve_out": ("compose", True, 0.95, []),
        "pt_contraindicated_or_futile": ("char", None, 0.85, ["contested_reading"]),
        "functional_plateau_documented": ("char", True, 0.95, []),
        "structural_neurological_compromise": ("char", None, 0.0, [], True),
        "apl_22_014_carve_out": ("compose", None, 0.0, [], True),
        "clinical_standard_supports_surgery": ("char", "TIER_2", 0.92, ["contested_reading"]),
    },
}


# Ground truth from the case files
GROUND_TRUTH = {
    "achebe": ("uphold", ["gate"]),
    "turner": ("overturn_procedural_defect", ["auto", "gate"]),
    "harris": ("overturn_factual_error_in_denial", ["gate"]),
    "clark": ("overturn_plan_criteria_met", ["auto", "gate"]),
    "kamau": ("overturn_plan_criteria_met", ["gate"]),
}


def reconstruct_trace(trace_dict):
    """Build a trace dict the orchestrator can consume."""
    trace = {}
    for node_id, entry in trace_dict.items():
        if len(entry) == 5:
            node_type, value, conf, signals, short_circuited = entry
        else:
            node_type, value, conf, signals = entry
            short_circuited = False

        # 'esc' is a marker indicating compose-level escalation.
        # When set, we add a placeholder signal so escalation_flag is True
        # on the reconstructed node (real orchestrator propagates child
        # signals; we just need ANY signal here for flag detection).
        is_esc = "esc" in signals
        char_signals = [s for s in signals if s != "esc"]
        if is_esc and not char_signals:
            # Add a placeholder so the property escalation_flag returns True
            char_signals = ["contested_reading"]

        result = make_result(
            node_id=node_id,
            value=value,
            confidence=conf,
            signals=make_signals(*char_signals),
            short_circuited=short_circuited,
            reasoning="(from prior run)",
        )
        trace[node_id] = result
    return trace


def project_for_case(case_key):
    """Run the new policy logic against the reconstructed trace."""
    router = DispositionRouter(
        tree=PA_APPEAL_TREE,
        tree_metadata=TREE_METADATA,
    )
    trace = reconstruct_trace(CASE_TRACES[case_key])

    determination = router.derive_determination(
        trace=trace,
        tree_version="1.0",
    )

    return (determination.disposition, determination.secondary_grounds,
            determination.routing_tier, len(determination.routing_reasons))


def main():
    print("=" * 78)
    print("POLICY PROJECTION — what the NEW policy would produce")
    print("=" * 78)
    print("(replaying prior substrate outputs through new disposition")
    print(" hierarchy and routing tier logic)")
    print()
    print(f"{'Case':<10} {'New Disposition':<35} {'Tier':<11} {'GT Match'}")
    print("-" * 78)

    for case_key in ["achebe", "turner", "harris", "clark", "kamau"]:
        primary, secondary, tier, signal_count = project_for_case(case_key)
        gt_disp, gt_tiers = GROUND_TRUTH[case_key]

        disp_match = "✓" if primary == gt_disp else "✗"
        tier_match = "✓" if tier.value in gt_tiers else "✗"

        print(f"{case_key:<10} {primary:<35} {tier.value:<11} "
              f"d:{disp_match} t:{tier_match}")
        if secondary:
            sec_str = ", ".join(secondary)
            print(f"           secondary: {sec_str}")

    print()
    print("(Substrate outputs were captured from the prior run. This")
    print(" projection only re-runs the disposition + routing logic.")
    print(" To confirm against live substrate behavior, run run_cases.py.)")


if __name__ == "__main__":
    main()

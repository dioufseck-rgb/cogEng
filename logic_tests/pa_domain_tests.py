"""
Tier 2 synthetic domain tests for the PA appeal tree.

These tests validate the PA tree's domain encoding — the disposition rules,
routing tier mapping, and predicate evaluation — independently of any
substrate behavior. Leaves are not evaluated; we construct synthetic trace
dicts and pass them to the DispositionRouter directly.

Tier 2 isolates a different concern from tier 1:
  - Tier 1 asks: does the engine compose AND/OR/NOT correctly?
  - Tier 2 asks: does the PA tree correctly encode CC-SPINE-2024 + Cal regs?

Where a tier 2 test fails, the issue is in the tree's domain encoding or in
the disposition router's predicate evaluation. Where they all pass, the
domain logic is correct given the (mocked) leaf values, and any end-to-end
mismatch with ground truth is due to substrate calibration, not the tree.

Tests are written as plain functions named test_*. The runner at the bottom
collects them all.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

# Make the engine and tree available
_HERE = Path(__file__).resolve().parent
_DERIVE = _HERE.parent / "derive_design"
_PA_FULL = _HERE.parent / "pa_full"
sys.path.insert(0, str(_DERIVE))

from disposition_router import (  # noqa: E402
    DispositionRouter,
    RoutingTier,
    Determination,
)
from derive_orchestrator import NodeResult, EscalationSignals  # noqa: E402


# =============================================================================
# Load the PA tree once
# =============================================================================

_TREE_JSON = _PA_FULL / "pa_appeal_tree.json"
_TREE_DATA = json.loads(_TREE_JSON.read_text())
PA_TREE = _TREE_DATA["tree"]
PA_METADATA = _TREE_DATA["tree_metadata"]


# =============================================================================
# Harness primitives
# =============================================================================

def node(
    node_id: str,
    value=None,
    confidence: float = 0.95,
    escalated: bool = False,
    signals: dict = None,
    short_circuited: bool = False,
) -> NodeResult:
    """Build a synthetic NodeResult for the trace.

    signals: dict mapping signal name (insufficient_facts, contested_reading,
             requires_institutional_judgment, contradictory_facts,
             low_confidence_in_value) to True.
    """
    esc_signals = EscalationSignals()
    if signals:
        for name, on in signals.items():
            if on:
                setattr(esc_signals, name, True)
    return NodeResult(
        node_id=node_id,
        value=value,
        confidence=confidence,
        escalation_signals=esc_signals,
        escalation_reason="mock" if escalated else "",
        short_circuited=short_circuited,
        reasoning=f"synthetic {node_id}={value}",
    )


def _all_compose_descendants(parent_id):
    """Yield (id, node_spec) for every compose descendant under parent_id."""
    node_spec = PA_TREE.get(parent_id)
    if not node_spec or node_spec.get("type") != "compose":
        return
    for child_id in node_spec.get("children", []):
        child = PA_TREE.get(child_id)
        if child and child.get("type") == "compose":
            yield child_id, child
            yield from _all_compose_descendants(child_id)


def _all_char_descendants(parent_id):
    """Yield ids of every char leaf in the subtree under parent_id."""
    node_spec = PA_TREE.get(parent_id)
    if not node_spec:
        return
    if node_spec.get("type") == "char":
        yield parent_id
        return
    for child_id in node_spec.get("children", []):
        yield from _all_char_descendants(child_id)


def saturate_required(trace_partial, fill_value=False, fill_conf=0.95):
    """
    Ensure all required_nodes (and their compose descendants) have a value
    in the trace. Anything missing gets filled with the fill_value.

    This is a convenience so tests don't have to populate every single
    leaf — just specify the ones that matter for what you're testing.
    """
    trace = dict(trace_partial)
    required = PA_METADATA.get("required_nodes", [])

    # Fill required nodes themselves
    for rid in required:
        if rid not in trace:
            trace[rid] = node(rid, value=fill_value, confidence=fill_conf)

    # Fill all compose descendants of required nodes
    for rid in required:
        for desc_id, _ in _all_compose_descendants(rid):
            if desc_id not in trace:
                trace[desc_id] = node(desc_id, value=fill_value, confidence=fill_conf)

    # Fill all char descendants of required nodes
    for rid in required:
        for leaf_id in _all_char_descendants(rid):
            if leaf_id not in trace:
                trace[leaf_id] = node(leaf_id, value=fill_value, confidence=fill_conf)

    return trace


def derive(trace) -> Determination:
    """Run the disposition router against a synthetic trace."""
    router = DispositionRouter(PA_TREE, PA_METADATA)
    return router.derive_determination(trace, tree_version="tier2_test")


# =============================================================================
# Test cases — disposition rules fire under their predicates
# =============================================================================

def test_uphold_when_nothing_supports_overturn():
    """Cleanly compliant denial, no plan criteria met, no carve-out, TIER_3."""
    trace = saturate_required({
        # Procedural: adequate (does not trigger fallback)
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True, 0.95),
        # Factual: accurate (does not trigger rank 1)
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        # Plan criteria: not met (does not trigger rank 2)
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False, 0.95),
        # Clinical: TIER_3 (does not trigger rank 3 which requires TIER_1)
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3", 0.95),
        # Carve-out: not applicable (does not trigger rank 4)
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False, 0.95),
    })
    det = derive(trace)
    if det.disposition != "uphold":
        return f"expected uphold, got {det.disposition}"
    return True


def test_overturn_factual_error_in_denial_fires_at_rank1():
    """Rank 1: INACCURATE factual basis with high confidence."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "INACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.disposition != "overturn_factual_error_in_denial":
        return f"expected overturn_factual_error_in_denial, got {det.disposition}"
    return True


def test_overturn_factual_error_does_not_fire_below_confidence_threshold():
    """INACCURATE at confidence 0.85 < threshold 0.9 → rank 1 should not fire."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "INACCURATE", 0.85),  # below 0.9
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.disposition == "overturn_factual_error_in_denial":
        return f"rank 1 should not fire below confidence threshold, got {det.disposition}"
    return True


def test_overturn_plan_criteria_met_fires_at_rank2():
    """Rank 2: apparently_true on plan_criteria_satisfied."""
    # apparently_true means True OR (escalated with no hard-false descendant).
    # Easiest path: value is True.
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", True, 0.95),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    }, fill_value=True)  # descendants also true so apparently_true holds
    det = derive(trace)
    if det.disposition != "overturn_plan_criteria_met":
        return f"expected overturn_plan_criteria_met, got {det.disposition}"
    return True


def test_overturn_clinical_standard_controls_fires_at_rank3():
    """Rank 3: TIER_1 clinical standard."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_1", 0.95),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.disposition != "overturn_clinical_standard_controls":
        return f"expected overturn_clinical_standard_controls, got {det.disposition}"
    return True


def test_overturn_clinical_standard_does_not_fire_on_TIER_2():
    """TIER_2 should not trigger rank 3 (only TIER_1 does)."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_2", 0.95),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.disposition == "overturn_clinical_standard_controls":
        return f"rank 3 should not fire on TIER_2, got {det.disposition}"
    return True


def test_overturn_regulatory_carve_out_fires_at_rank4():
    """Rank 4: regulatory_carve_out_applies = True."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", True, 0.95),
    })
    det = derive(trace)
    if det.disposition != "overturn_regulatory_carve_out":
        return f"expected overturn_regulatory_carve_out, got {det.disposition}"
    return True


def test_overturn_procedural_defect_fires_at_rank5_fallback():
    """Rank 5 (fallback_only): procedurally inadequate denial AND no other rule fires."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", False, 0.95),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.disposition != "overturn_procedural_defect":
        return f"expected overturn_procedural_defect, got {det.disposition}"
    return True


def test_procedural_defect_does_not_fire_when_denial_adequate():
    """If denial_procedurally_adequate is True, fallback shouldn't even consider firing."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.disposition == "overturn_procedural_defect":
        return f"procedural_defect should not fire when denial is adequate, got {det.disposition}"
    return True


# =============================================================================
# Test cases — rank ordering: higher rank wins, lower rank goes to secondary
# =============================================================================

def test_rank1_beats_rank2_when_both_apply():
    """Both factual_error (rank 1) AND plan_criteria_met (rank 2) trigger.
    rank 1 should be primary; rank 2 should be in secondary_grounds."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "INACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", True, 0.95),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    }, fill_value=True)
    det = derive(trace)
    if det.disposition != "overturn_factual_error_in_denial":
        return f"expected rank 1 primary, got {det.disposition}"
    if "overturn_plan_criteria_met" not in det.secondary_grounds:
        return f"expected rank 2 in secondary, got {det.secondary_grounds}"
    return True


def test_rank2_beats_rank3_when_both_apply():
    """plan_criteria_met (rank 2) AND clinical_standard TIER_1 (rank 3) both trigger."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", True, 0.95),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_1", 0.95),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    }, fill_value=True)
    det = derive(trace)
    if det.disposition != "overturn_plan_criteria_met":
        return f"expected rank 2 primary, got {det.disposition}"
    if "overturn_clinical_standard_controls" not in det.secondary_grounds:
        return f"expected rank 3 in secondary, got {det.secondary_grounds}"
    return True


def test_rank3_beats_rank4_when_both_apply():
    """TIER_1 clinical (rank 3) AND carve_out (rank 4) both trigger."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_1", 0.95),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", True, 0.95),
    })
    det = derive(trace)
    if det.disposition != "overturn_clinical_standard_controls":
        return f"expected rank 3 primary, got {det.disposition}"
    if "overturn_regulatory_carve_out" not in det.secondary_grounds:
        return f"expected rank 4 in secondary, got {det.secondary_grounds}"
    return True


def test_normal_rules_beat_fallback_even_at_higher_rank_number():
    """rank 5 is fallback_only. If any rank 1-4 fires, rank 5 should not fire.
    But if rank 5 ALSO triggers (denial defective + e.g. carve-out applies),
    procedural_defect should appear in secondary_grounds."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", False),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", True, 0.95),
    })
    det = derive(trace)
    if det.disposition != "overturn_regulatory_carve_out":
        return f"expected rank 4 primary (rank 5 is fallback), got {det.disposition}"
    if "overturn_procedural_defect" not in det.secondary_grounds:
        return f"expected fallback in secondary, got {det.secondary_grounds}"
    return True


def test_all_normal_rules_in_secondary_when_all_apply():
    """All four normal ranks (1-4) trigger. Rank 1 primary; ranks 2,3,4 secondary."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "INACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", True, 0.95),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_1", 0.95),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", True, 0.95),
    }, fill_value=True)
    det = derive(trace)
    if det.disposition != "overturn_factual_error_in_denial":
        return f"expected rank 1 primary, got {det.disposition}"
    expected_secondary = {
        "overturn_plan_criteria_met",
        "overturn_clinical_standard_controls",
        "overturn_regulatory_carve_out",
    }
    actual_secondary = set(det.secondary_grounds)
    if not expected_secondary.issubset(actual_secondary):
        return f"missing secondary grounds: expected {expected_secondary}, got {actual_secondary}"
    return True


# =============================================================================
# Test cases — predicate evaluator edge cases
# =============================================================================

def test_value_predicate_string_match():
    """{value: 'INACCURATE'} matches when leaf returns 'INACCURATE'."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "INACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    return det.disposition == "overturn_factual_error_in_denial"


def test_value_predicate_partially_inaccurate_does_not_match():
    """{value: 'INACCURATE'} should NOT match 'PARTIALLY_INACCURATE'."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "PARTIALLY_INACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.disposition == "overturn_factual_error_in_denial":
        return f"PARTIALLY_INACCURATE should not match value:INACCURATE, got {det.disposition}"
    return True


def test_apparently_true_matches_True_value():
    """apparently_true predicate matches when value is True."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", True, 0.95),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    }, fill_value=True)
    det = derive(trace)
    return det.disposition == "overturn_plan_criteria_met"


def test_apparently_true_does_not_match_False_value():
    """apparently_true predicate does NOT match when value is hard False."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False, 0.95),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.disposition == "overturn_plan_criteria_met":
        return f"plan_criteria_met should not fire on hard False, got {det.disposition}"
    return True


def test_apparently_true_matches_escalated_when_no_hard_false_descendant():
    """apparently_true should match value=None+escalated when no descendant is hard-false."""
    # Set parent to escalated; fill descendants with True so no hard-false exists.
    overrides = {
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied",
                                         value=None, confidence=0.85,
                                         escalated=True,
                                         signals={"contested_reading": True}),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    }
    trace = saturate_required(overrides, fill_value=True)
    det = derive(trace)
    if det.disposition != "overturn_plan_criteria_met":
        return f"apparently_true should match escalated-with-no-false-descendant, got {det.disposition}"
    return True


def test_apparently_true_does_not_match_escalated_with_hard_false_descendant():
    """When parent is escalated but a critical descendant is hard False,
    apparently_true should NOT match."""
    # Set parent to escalated; force a descendant of plan_criteria_satisfied to False.
    plan_children = PA_TREE.get("plan_criteria_satisfied", {}).get("children", [])
    if not plan_children:
        return f"setup failed: plan_criteria_satisfied has no children"

    overrides = {
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied",
                                         value=None, confidence=0.85, escalated=True),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
        # First child of plan_criteria_satisfied is hard False
        plan_children[0]: node(plan_children[0], value=False, confidence=0.95),
    }
    trace = saturate_required(overrides, fill_value=True)
    det = derive(trace)
    if det.disposition == "overturn_plan_criteria_met":
        return f"apparently_true should not match when descendant is hard False, got {det.disposition}"
    return True


# =============================================================================
# Test cases — required_nodes / indeterminate handling
# =============================================================================

def test_missing_required_node_produces_indeterminate():
    """If a required_node is absent from trace, disposition is indeterminate, tier HOLD."""
    required = PA_METADATA.get("required_nodes", [])
    # Build a trace with one required node missing
    trace = {}
    for rid in required[1:]:  # skip first required
        trace[rid] = node(rid, value=True, confidence=0.95)
    det = derive(trace)
    expected_disp = PA_METADATA.get("indeterminate_disposition")
    if det.disposition != expected_disp:
        return f"expected {expected_disp}, got {det.disposition}"
    if det.routing_tier != RoutingTier.HOLD:
        return f"expected HOLD tier, got {det.routing_tier}"
    return True


def test_all_required_present_produces_real_disposition():
    """When all required_nodes have values, disposition is not indeterminate."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    return det.disposition != PA_METADATA.get("indeterminate_disposition")


# =============================================================================
# Test cases — routing tier signal mapping
# =============================================================================

def test_no_signals_produces_AUTO_tier():
    """Clean trace with no escalation signals → AUTO tier."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.routing_tier != RoutingTier.AUTO:
        return f"clean trace expected AUTO, got {det.routing_tier} (signals: {det.routing_reasons})"
    return True


def test_contradictory_facts_on_critical_produces_HOLD():
    """contradictory_facts is a HOLD-severity signal. On a critical leaf → HOLD."""
    # Use overturn_factual_error path so denial_factual_basis_correct is critical
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "INACCURATE", 0.95,
                                              signals={"contradictory_facts": True}),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.routing_tier != RoutingTier.HOLD:
        return f"contradictory_facts on critical expected HOLD, got {det.routing_tier}"
    return True


def test_contested_reading_on_critical_produces_GATE():
    """contested_reading is a GATE-severity signal. On critical → GATE."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "INACCURATE", 0.95,
                                              signals={"contested_reading": True}),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    })
    det = derive(trace)
    if det.routing_tier != RoutingTier.GATE:
        return f"contested_reading on critical expected GATE, got {det.routing_tier}"
    return True


def test_three_gate_signals_total_escalates_to_GATE():
    """gate_total >= 3 should also trigger GATE per tier rules."""
    # Three contested_reading signals on non-critical leaves
    overrides = {
        "denial_procedurally_adequate": node("denial_procedurally_adequate", True),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_3"),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", False),
    }
    trace = saturate_required(overrides)
    # Now add gate signals on three char leaves
    leaves_with_signals = [
        "cervical_radiculopathy_diagnosed",
        "pt_requirement_met",
        "pharmacotherapy_requirement_met",
    ]
    for lid in leaves_with_signals:
        trace[lid] = node(lid, value=False, confidence=0.85,
                          signals={"contested_reading": True})
    det = derive(trace)
    # Uphold disposition, but tier should be GATE due to 3 gate signals
    if det.routing_tier not in (RoutingTier.GATE, RoutingTier.HOLD):
        return f"three gate signals expected GATE or HOLD, got {det.routing_tier}"
    return True


# =============================================================================
# Test cases — the five live PA case shapes, reproduced synthetically
# =============================================================================
# Each test below corresponds to one of the live cases run earlier this
# session, with the EXACT trace shape the engine produced — but using only
# the leaf values, with no substrate involvement. We assert the same
# disposition that came out of the live run. If the synthetic version
# produces a different disposition than the live run, the issue is in the
# tree's domain encoding, not the substrate.

def test_synthetic_achebe_shape():
    """achebe live: procedural inadequate + accurate + plan F + TIER_2 + carve_out escalated
    Live result: overturn_procedural_defect (fallback)."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", False, 0.95),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "ACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False, 0.95),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_2", 0.85),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies",
                                              None, 0.85, escalated=True),
    })
    det = derive(trace)
    if det.disposition != "overturn_procedural_defect":
        return f"achebe shape expected overturn_procedural_defect, got {det.disposition}"
    return True


def test_synthetic_clark_shape():
    """clark live: denial inadequate + partially_inaccurate + plan F + TIER_2 + carve_out T
    Live result: overturn_regulatory_carve_out (rank 4 beats fallback rank 5)."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", False, 0.95),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "PARTIALLY_INACCURATE", 0.85),
        "plan_criteria_satisfied": node("plan_criteria_satisfied", False, 0.85),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_2", 0.95),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", True, 0.95),
    })
    det = derive(trace)
    if det.disposition != "overturn_regulatory_carve_out":
        return f"clark shape expected overturn_regulatory_carve_out, got {det.disposition}"
    # And procedural_defect should appear as secondary (fallback still triggers)
    if "overturn_procedural_defect" not in det.secondary_grounds:
        return f"clark shape expected procedural_defect in secondary, got {det.secondary_grounds}"
    return True


def test_synthetic_kamau_shape():
    """kamau live: denial inadequate + INACCURATE@0.95 + plan escalated + TIER_2 + carve_out T
    Live result: overturn_factual_error_in_denial (rank 1, beats all others)."""
    trace = saturate_required({
        "denial_procedurally_adequate": node("denial_procedurally_adequate", False, 0.95),
        "denial_factual_basis_correct": node("denial_factual_basis_correct",
                                              "INACCURATE", 0.95),
        "plan_criteria_satisfied": node("plan_criteria_satisfied",
                                         None, 0.85, escalated=True),
        "clinical_standard_supports_surgery": node("clinical_standard_supports_surgery",
                                                    "TIER_2", 0.95),
        "regulatory_carve_out_applies": node("regulatory_carve_out_applies", True, 0.95),
    })
    det = derive(trace)
    if det.disposition != "overturn_factual_error_in_denial":
        return f"kamau shape expected overturn_factual_error_in_denial, got {det.disposition}"
    return True


# =============================================================================
# Runner
# =============================================================================

def collect_tests():
    import inspect
    current_module = sys.modules[__name__]
    return [
        (name, fn)
        for name, fn in inspect.getmembers(current_module, inspect.isfunction)
        if name.startswith("test_")
    ]


def main():
    tests = collect_tests()
    print(f"Running {len(tests)} tier 2 synthetic-domain tests...")
    print("=" * 70)

    passed = []
    failed = []
    errored = []

    for name, fn in tests:
        try:
            result = fn()
            if result is True:
                passed.append(name)
                print(f"  ✓ {name}")
            else:
                failed.append((name, result))
                print(f"  ✗ {name}: {result}")
        except Exception as e:
            errored.append((name, e))
            print(f"  E {name}: {type(e).__name__}: {e}")

    print("=" * 70)
    print(f"Results: {len(passed)} passed, {len(failed)} failed, {len(errored)} errored")
    print()

    if failed:
        print("FAILURES:")
        for name, result in failed:
            print(f"  {name}: {result}")
        print()
    if errored:
        print("ERRORS:")
        for name, exc in errored:
            print(f"  {name}: {type(exc).__name__}: {exc}")
        print()

    return 0 if not failed and not errored else 1


if __name__ == "__main__":
    sys.exit(main())

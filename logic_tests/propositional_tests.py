"""
Tier 1 logic test harness for RuleKit's compositional engine.

This module tests the engine's pure logical correctness — independent of any
domain content, any substrate calls, any policy. We construct trees over
abstract propositions (p, q, r, ...) with mocked leaf values, walk them
through the engine, and verify the engine's output matches the formal
semantics of classical propositional logic (and three-valued extensions for
escalation handling).

A FAILURE here is a real engine bug. A PASS is evidence that the engine's
compositional layer is sound for the tested operator set.

Usage:
    python3 propositional_tests.py

The harness has three primitives:

    prop(name, value, escalated=False)
        Build a synthetic char leaf with a given truth value.
    tree(structure)
        Build a tree dict from a nested compose/leaf structure.
    evaluate(tree_dict)
        Run the engine on the tree and return the root NodeResult.

Tests are written as plain Python functions named test_*. The runner at the
bottom collects them, runs each, and reports pass/fail with detail.
"""

from __future__ import annotations
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional

# Make derive_orchestrator importable
_DERIVE = Path(__file__).resolve().parent.parent / "derive_design"
sys.path.insert(0, str(_DERIVE))

from derive_orchestrator import (  # noqa: E402
    DeriveOrchestrator,
    NodeResult,
    CaseFactBundle,
    EscalationSignals,
)


# =============================================================================
# Harness primitives
# =============================================================================

class MockCharacterize:
    """
    Substitute for the real substrate-calling characterize_fn.

    Returns pre-specified NodeResult values for each leaf, indexed by node_id.
    Counts calls so tests can detect unexpected substrate invocation.
    """

    def __init__(self, leaf_values: dict):
        """
        leaf_values: dict mapping node_id -> dict with keys:
            value: bool | None
            escalated: bool (default False)
            confidence: float (default 0.95)
            signal: str (optional, one of the EscalationSignals fields)
        """
        self.leaf_values = leaf_values
        self.call_count = 0
        self.calls = []

    def __call__(self, request: dict) -> NodeResult:
        self.call_count += 1
        node_id = request["node_id"]
        self.calls.append(node_id)
        spec = self.leaf_values.get(node_id)
        if spec is None:
            return NodeResult(
                node_id=node_id,
                value=None,
                confidence=0.0,
                error=f"no mock value for {node_id}",
            )

        value = spec.get("value")
        confidence = spec.get("confidence", 0.95)
        escalated = spec.get("escalated", False)
        signal_name = spec.get("signal")

        signals = EscalationSignals()
        if signal_name:
            setattr(signals, signal_name, True)
        elif escalated:
            signals.low_confidence_in_value = True

        return NodeResult(
            node_id=node_id,
            value=value,
            confidence=confidence,
            escalation_signals=signals,
            escalation_reason="mock escalation" if escalated else "",
            reasoning=f"mock leaf {node_id} = {value}",
        )

    def summary(self):
        return {
            "total_calls": self.call_count,
            "total_latency_ms": 0,
            "avg_latency_ms": 0,
            "errors": 0,
            "escalations": sum(1 for n in self.calls),  # crude
        }


def leaf(name: str) -> dict:
    """Build a synthetic char leaf node dict."""
    return {
        "id": name,
        "type": "char",
        "policy_ref": "logic_test",
        "condition_text": f"mock leaf {name}",
        "definitions": [],
        "expected_output_type": "boolean",
        "inputs": [],
    }


def AND(node_id: str, *children: str) -> dict:
    """Build a compose AND node."""
    return {
        "id": node_id,
        "type": "compose",
        "op": "AND",
        "children": list(children),
    }


def OR(node_id: str, *children: str) -> dict:
    """Build a compose OR node."""
    return {
        "id": node_id,
        "type": "compose",
        "op": "OR",
        "children": list(children),
    }


def NOT(node_id: str, child: str) -> dict:
    """Build a compose NOT node. Requires exactly one child."""
    return {
        "id": node_id,
        "type": "compose",
        "op": "NOT",
        "children": [child],
    }


def build_tree(*nodes: dict) -> dict:
    """Build a tree dict from a list of node dicts."""
    return {node["id"]: node for node in nodes}


def evaluate(
    tree_dict: dict,
    root_id: str,
    leaf_values: dict,
) -> tuple[NodeResult, MockCharacterize]:
    """
    Evaluate a tree against mocked leaf values.

    Returns (root_result, mock_characterize) so tests can inspect both the
    composition result and the leaf call pattern.
    """
    # Build a minimal CaseFactBundle (the engine requires one but our leaves
    # are mocked so it isn't actually used)
    facts = CaseFactBundle(
        case_id="logic_test",
        retrieve_facts={},
        extract_facts={},
    )

    mock = MockCharacterize(leaf_values)

    # Tree metadata is minimal; we're testing pure composition
    metadata = {
        "tree_id": "logic_test",
        "version": "1.0",
        "root_node_id": root_id,
    }

    orch = DeriveOrchestrator(
        tree=tree_dict,
        tree_metadata=metadata,
        characterize_fn=mock,
        escalation_threshold=0.7,
    )

    # Initialize the per-run state that derive() normally sets up. We bypass
    # derive() so we get pure compositional evaluation without disposition
    # or routing applied.
    orch.facts = facts
    orch.trace = {}
    orch.short_circuit_log = {}

    result = orch._evaluate_node(root_id)
    return result, mock


# =============================================================================
# Test cases — Classical propositional logic
# =============================================================================
# Conventions:
#   T = True leaf at confidence 0.95
#   F = False leaf at confidence 0.95
#   p, q, r = abstract propositions (leaf names)
#
# Each test asserts (or returns failure) for one logical identity.

T = {"value": True, "confidence": 0.95}
F = {"value": False, "confidence": 0.95}
E = {"value": None, "escalated": True, "confidence": 0.70}  # escalated leaf


# --- Identity / Constants ---

def test_AND_single_true():
    """AND(true) = true"""
    tree = build_tree(AND("root", "p"), leaf("p"))
    result, _ = evaluate(tree, "root", {"p": T})
    return result.value is True


def test_AND_single_false():
    """AND(false) = false"""
    tree = build_tree(AND("root", "p"), leaf("p"))
    result, _ = evaluate(tree, "root", {"p": F})
    return result.value is False


def test_OR_single_true():
    """OR(true) = true"""
    tree = build_tree(OR("root", "p"), leaf("p"))
    result, _ = evaluate(tree, "root", {"p": T})
    return result.value is True


def test_OR_single_false():
    """OR(false) = false"""
    tree = build_tree(OR("root", "p"), leaf("p"))
    result, _ = evaluate(tree, "root", {"p": F})
    return result.value is False


# --- Binary AND truth table ---

def test_AND_TT():
    """AND(T, T) = T"""
    tree = build_tree(AND("root", "p", "q"), leaf("p"), leaf("q"))
    result, _ = evaluate(tree, "root", {"p": T, "q": T})
    return result.value is True


def test_AND_TF():
    """AND(T, F) = F"""
    tree = build_tree(AND("root", "p", "q"), leaf("p"), leaf("q"))
    result, _ = evaluate(tree, "root", {"p": T, "q": F})
    return result.value is False


def test_AND_FT():
    """AND(F, T) = F"""
    tree = build_tree(AND("root", "p", "q"), leaf("p"), leaf("q"))
    result, _ = evaluate(tree, "root", {"p": F, "q": T})
    return result.value is False


def test_AND_FF():
    """AND(F, F) = F"""
    tree = build_tree(AND("root", "p", "q"), leaf("p"), leaf("q"))
    result, _ = evaluate(tree, "root", {"p": F, "q": F})
    return result.value is False


# --- Binary OR truth table ---

def test_OR_TT():
    """OR(T, T) = T"""
    tree = build_tree(OR("root", "p", "q"), leaf("p"), leaf("q"))
    result, _ = evaluate(tree, "root", {"p": T, "q": T})
    return result.value is True


def test_OR_TF():
    """OR(T, F) = T"""
    tree = build_tree(OR("root", "p", "q"), leaf("p"), leaf("q"))
    result, _ = evaluate(tree, "root", {"p": T, "q": F})
    return result.value is True


def test_OR_FT():
    """OR(F, T) = T"""
    tree = build_tree(OR("root", "p", "q"), leaf("p"), leaf("q"))
    result, _ = evaluate(tree, "root", {"p": F, "q": T})
    return result.value is True


def test_OR_FF():
    """OR(F, F) = F"""
    tree = build_tree(OR("root", "p", "q"), leaf("p"), leaf("q"))
    result, _ = evaluate(tree, "root", {"p": F, "q": F})
    return result.value is False


# --- Commutativity ---

def test_AND_commutative():
    """AND(p, q) = AND(q, p) across all (p,q) ∈ {T,F}²"""
    tree_pq = build_tree(AND("root", "p", "q"), leaf("p"), leaf("q"))
    tree_qp = build_tree(AND("root", "q", "p"), leaf("p"), leaf("q"))
    for p in [T, F]:
        for q in [T, F]:
            r1, _ = evaluate(tree_pq, "root", {"p": p, "q": q})
            r2, _ = evaluate(tree_qp, "root", {"p": p, "q": q})
            if r1.value != r2.value:
                return False
    return True


def test_OR_commutative():
    """OR(p, q) = OR(q, p) across all (p,q) ∈ {T,F}²"""
    tree_pq = build_tree(OR("root", "p", "q"), leaf("p"), leaf("q"))
    tree_qp = build_tree(OR("root", "q", "p"), leaf("p"), leaf("q"))
    for p in [T, F]:
        for q in [T, F]:
            r1, _ = evaluate(tree_pq, "root", {"p": p, "q": q})
            r2, _ = evaluate(tree_qp, "root", {"p": p, "q": q})
            if r1.value != r2.value:
                return False
    return True


# --- Associativity ---

def test_AND_associative():
    """AND(AND(p,q), r) = AND(p, AND(q,r))"""
    tree_left = build_tree(
        AND("root", "pq", "r"),
        AND("pq", "p", "q"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    tree_right = build_tree(
        AND("root", "p", "qr"),
        AND("qr", "q", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    for p in [T, F]:
        for q in [T, F]:
            for r in [T, F]:
                r1, _ = evaluate(tree_left, "root", {"p": p, "q": q, "r": r})
                r2, _ = evaluate(tree_right, "root", {"p": p, "q": q, "r": r})
                if r1.value != r2.value:
                    return False
    return True


def test_OR_associative():
    """OR(OR(p,q), r) = OR(p, OR(q,r))"""
    tree_left = build_tree(
        OR("root", "pq", "r"),
        OR("pq", "p", "q"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    tree_right = build_tree(
        OR("root", "p", "qr"),
        OR("qr", "q", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    for p in [T, F]:
        for q in [T, F]:
            for r in [T, F]:
                r1, _ = evaluate(tree_left, "root", {"p": p, "q": q, "r": r})
                r2, _ = evaluate(tree_right, "root", {"p": p, "q": q, "r": r})
                if r1.value != r2.value:
                    return False
    return True


# --- Distributivity ---

def test_AND_distributes_over_OR():
    """AND(p, OR(q, r)) = OR(AND(p, q), AND(p, r))"""
    tree_lhs = build_tree(
        AND("root", "p", "qr"),
        OR("qr", "q", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    tree_rhs = build_tree(
        OR("root", "pq", "pr"),
        AND("pq", "p", "q"),
        AND("pr", "p", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    for p in [T, F]:
        for q in [T, F]:
            for r in [T, F]:
                r1, _ = evaluate(tree_lhs, "root", {"p": p, "q": q, "r": r})
                r2, _ = evaluate(tree_rhs, "root", {"p": p, "q": q, "r": r})
                if r1.value != r2.value:
                    return False
    return True


def test_OR_distributes_over_AND():
    """OR(p, AND(q, r)) = AND(OR(p, q), OR(p, r))"""
    tree_lhs = build_tree(
        OR("root", "p", "qr"),
        AND("qr", "q", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    tree_rhs = build_tree(
        AND("root", "pq", "pr"),
        OR("pq", "p", "q"),
        OR("pr", "p", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    for p in [T, F]:
        for q in [T, F]:
            for r in [T, F]:
                r1, _ = evaluate(tree_lhs, "root", {"p": p, "q": q, "r": r})
                r2, _ = evaluate(tree_rhs, "root", {"p": p, "q": q, "r": r})
                if r1.value != r2.value:
                    return False
    return True


# --- Idempotence ---

def test_AND_idempotent():
    """AND(p, p) = p — NOTE: requires distinct node ids per child instance"""
    # Tree engine indexes by node_id, so we can't literally pass the same id twice.
    # Test the semantic equivalent: AND of two leaves with same value behaves as the value.
    for p in [T, F]:
        tree = build_tree(AND("root", "p1", "p2"), leaf("p1"), leaf("p2"))
        result, _ = evaluate(tree, "root", {"p1": p, "p2": p})
        if result.value != p["value"]:
            return False
    return True


def test_OR_idempotent():
    """OR(p, p) = p (semantic equivalent with distinct leaf ids)"""
    for p in [T, F]:
        tree = build_tree(OR("root", "p1", "p2"), leaf("p1"), leaf("p2"))
        result, _ = evaluate(tree, "root", {"p1": p, "p2": p})
        if result.value != p["value"]:
            return False
    return True


# --- Short-circuit behavior ---

def test_AND_short_circuits_on_false():
    """AND short-circuits when first child is false; later children not evaluated"""
    tree = build_tree(AND("root", "p", "q", "r"), leaf("p"), leaf("q"), leaf("r"))
    result, mock = evaluate(tree, "root", {"p": F, "q": T, "r": T})
    # Engine should have evaluated p (returning F), then short-circuited
    # without calling q or r
    return (
        result.value is False
        and mock.call_count == 1
        and mock.calls == ["p"]
    )


def test_OR_short_circuits_on_true():
    """OR short-circuits when first child is true; later children not evaluated"""
    tree = build_tree(OR("root", "p", "q", "r"), leaf("p"), leaf("q"), leaf("r"))
    result, mock = evaluate(tree, "root", {"p": T, "q": F, "r": F})
    return (
        result.value is True
        and mock.call_count == 1
        and mock.calls == ["p"]
    )


def test_AND_no_short_circuit_when_all_true():
    """When no child is false, all are evaluated"""
    tree = build_tree(AND("root", "p", "q", "r"), leaf("p"), leaf("q"), leaf("r"))
    result, mock = evaluate(tree, "root", {"p": T, "q": T, "r": T})
    return (
        result.value is True
        and mock.call_count == 3
    )


def test_OR_no_short_circuit_when_all_false():
    """When no child is true, all are evaluated"""
    tree = build_tree(OR("root", "p", "q", "r"), leaf("p"), leaf("q"), leaf("r"))
    result, mock = evaluate(tree, "root", {"p": F, "q": F, "r": F})
    return (
        result.value is False
        and mock.call_count == 3
    )


# --- Three-valued / escalation handling ---

def test_AND_escalated_child_propagates_escalation():
    """AND with one escalated child returns escalated (value=None)"""
    tree = build_tree(AND("root", "p", "q"), leaf("p"), leaf("q"))
    p_esc = {"value": None, "escalated": True, "confidence": 0.7}
    result, _ = evaluate(tree, "root", {"p": p_esc, "q": T})
    return result.value is None and result.escalation_flag


def test_OR_escalated_child_with_true_short_circuits():
    """OR with escalated p then true q: should still return True (q is definitive)
    Question: does engine evaluate q after p is escalated?"""
    tree = build_tree(OR("root", "p", "q"), leaf("p"), leaf("q"))
    p_esc = {"value": None, "escalated": True, "confidence": 0.7}
    result, mock = evaluate(tree, "root", {"p": p_esc, "q": T})
    # Engine evaluates p (escalated), then q (true). q's True should resolve OR.
    return result.value is True


def test_AND_false_dominates_escalation():
    """AND with one false child and one escalated child: false should dominate"""
    tree = build_tree(AND("root", "p", "q"), leaf("p"), leaf("q"))
    q_esc = {"value": None, "escalated": True, "confidence": 0.7}
    # Order matters for short-circuit: F first
    result, _ = evaluate(tree, "root", {"p": F, "q": q_esc})
    return result.value is False  # F short-circuits before reaching escalated q


# --- Nesting ---

def test_nested_AND_OR():
    """AND(p, OR(q, r)) evaluated across truth table"""
    tree = build_tree(
        AND("root", "p", "qr"),
        OR("qr", "q", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    # Expected: p AND (q OR r)
    expectations = {
        (False, False, False): False,
        (False, False, True): False,
        (False, True, False): False,
        (False, True, True): False,
        (True, False, False): False,
        (True, False, True): True,
        (True, True, False): True,
        (True, True, True): True,
    }
    for (pv, qv, rv), expected in expectations.items():
        vals = {
            "p": T if pv else F,
            "q": T if qv else F,
            "r": T if rv else F,
        }
        result, _ = evaluate(tree, "root", vals)
        if result.value != expected:
            return False
    return True


def test_nested_OR_AND():
    """OR(p, AND(q, r)) evaluated across truth table"""
    tree = build_tree(
        OR("root", "p", "qr"),
        AND("qr", "q", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    expectations = {
        (False, False, False): False,
        (False, False, True): False,
        (False, True, False): False,
        (False, True, True): True,
        (True, False, False): True,
        (True, False, True): True,
        (True, True, False): True,
        (True, True, True): True,
    }
    for (pv, qv, rv), expected in expectations.items():
        vals = {
            "p": T if pv else F,
            "q": T if qv else F,
            "r": T if rv else F,
        }
        result, _ = evaluate(tree, "root", vals)
        if result.value != expected:
            return False
    return True


# =============================================================================
# Test cases — NOT operator and three-valued logic
# =============================================================================
# Organized in scope tiers, from smallest to largest:
#   Tier A: unary NOT truth table over {T, F, escalated}
#   Tier B: structural identities (double negation, involution)
#   Tier C: NOT composed with AND and OR — De Morgan, excluded middle, non-contradiction
#   Tier D: NOT under escalation — escalation propagation through De Morgan
#   Tier E: deeper nesting — NOT under multiple layers
#   Tier F: degenerate cases — NOT requires exactly one child


# --- Tier A: NOT truth table ---

def test_NOT_T_is_F():
    """NOT(T) = F"""
    tree = build_tree(NOT("root", "p"), leaf("p"))
    result, _ = evaluate(tree, "root", {"p": T})
    return result.value is False


def test_NOT_F_is_T():
    """NOT(F) = T"""
    tree = build_tree(NOT("root", "p"), leaf("p"))
    result, _ = evaluate(tree, "root", {"p": F})
    return result.value is True


def test_NOT_escalated_is_escalated():
    """NOT(escalated) = escalated (Strong Kleene)"""
    tree = build_tree(NOT("root", "p"), leaf("p"))
    result, _ = evaluate(tree, "root", {"p": E})
    return (
        result.value is None
        and result.escalation_flag is True
    )


def test_NOT_preserves_confidence():
    """NOT(v at conf=c) has confidence c"""
    tree = build_tree(NOT("root", "p"), leaf("p"))
    for spec in [T, F]:
        result, _ = evaluate(tree, "root", {"p": spec})
        if abs(result.confidence - spec["confidence"]) > 1e-9:
            return False
    return True


# --- Tier B: structural identities ---

def test_NOT_double_negation():
    """NOT(NOT(p)) = p across {T, F}"""
    tree = build_tree(
        NOT("root", "inner"),
        NOT("inner", "p"),
        leaf("p"),
    )
    for spec, expected in [(T, True), (F, False)]:
        result, _ = evaluate(tree, "root", {"p": spec})
        if result.value != expected:
            return False
    return True


def test_NOT_double_negation_preserves_escalation():
    """NOT(NOT(escalated)) = escalated (escalation survives double negation)"""
    tree = build_tree(
        NOT("root", "inner"),
        NOT("inner", "p"),
        leaf("p"),
    )
    result, _ = evaluate(tree, "root", {"p": E})
    return result.value is None and result.escalation_flag is True


# --- Tier C: NOT composed with AND and OR ---

def test_excluded_middle_classical():
    """OR(p, NOT(p)) = T for both p ∈ {T, F}"""
    tree = build_tree(
        OR("root", "p", "notp"),
        NOT("notp", "p"),
        leaf("p"),
    )
    # Note: engine doesn't reuse leaf evaluations across structurally distinct
    # paths in compose ops, but it does cache by node_id. Since both 'p' references
    # are to the same node_id, the second access pulls from trace.
    for spec in [T, F]:
        result, _ = evaluate(tree, "root", {"p": spec})
        if result.value is not True:
            return False
    return True


def test_excluded_middle_under_escalation():
    """OR(p, NOT(p)) when p is escalated: engine should escalate (not assert T)"""
    tree = build_tree(
        OR("root", "p", "notp"),
        NOT("notp", "p"),
        leaf("p"),
    )
    result, _ = evaluate(tree, "root", {"p": E})
    # Under Strong Kleene: p=esc, NOT(p)=esc, OR(esc, esc)=esc
    # Excluded middle does NOT hold when truth value is unknown — this is
    # the intuitionistic-like behavior we want for compliance reasoning.
    return result.value is None and result.escalation_flag is True


def test_non_contradiction_classical():
    """AND(p, NOT(p)) = F for both p ∈ {T, F}"""
    tree = build_tree(
        AND("root", "p", "notp"),
        NOT("notp", "p"),
        leaf("p"),
    )
    for spec in [T, F]:
        result, _ = evaluate(tree, "root", {"p": spec})
        if result.value is not False:
            return False
    return True


def test_non_contradiction_under_escalation():
    """AND(p, NOT(p)) when p is escalated: AND of esc and esc → escalated"""
    tree = build_tree(
        AND("root", "p", "notp"),
        NOT("notp", "p"),
        leaf("p"),
    )
    result, _ = evaluate(tree, "root", {"p": E})
    # AND of two escalated children: neither short-circuits to False, both flag
    # → engine returns escalated. This is correct under Strong Kleene.
    return result.value is None and result.escalation_flag is True


# --- De Morgan's laws across the full {T, F} domain ---

def test_DeMorgan_NOT_AND_equals_OR_NOTs():
    """NOT(AND(p, q)) = OR(NOT(p), NOT(q)) for all (p,q) ∈ {T,F}²"""
    tree_lhs = build_tree(
        NOT("root", "and_pq"),
        AND("and_pq", "p", "q"),
        leaf("p"), leaf("q"),
    )
    tree_rhs = build_tree(
        OR("root", "not_p", "not_q"),
        NOT("not_p", "p"),
        NOT("not_q", "q"),
        leaf("p"), leaf("q"),
    )
    for p in [T, F]:
        for q in [T, F]:
            r1, _ = evaluate(tree_lhs, "root", {"p": p, "q": q})
            r2, _ = evaluate(tree_rhs, "root", {"p": p, "q": q})
            if r1.value != r2.value:
                return False
    return True


def test_DeMorgan_NOT_OR_equals_AND_NOTs():
    """NOT(OR(p, q)) = AND(NOT(p), NOT(q)) for all (p,q) ∈ {T,F}²"""
    tree_lhs = build_tree(
        NOT("root", "or_pq"),
        OR("or_pq", "p", "q"),
        leaf("p"), leaf("q"),
    )
    tree_rhs = build_tree(
        AND("root", "not_p", "not_q"),
        NOT("not_p", "p"),
        NOT("not_q", "q"),
        leaf("p"), leaf("q"),
    )
    for p in [T, F]:
        for q in [T, F]:
            r1, _ = evaluate(tree_lhs, "root", {"p": p, "q": q})
            r2, _ = evaluate(tree_rhs, "root", {"p": p, "q": q})
            if r1.value != r2.value:
                return False
    return True


# --- Tier D: De Morgan under escalation ---
# Strong Kleene predicts these still hold pointwise: if both sides evaluate to
# the same value (incl. escalated) on every input, the identity is preserved.

def test_DeMorgan_NOT_AND_under_escalation():
    """NOT(AND(p, q)) = OR(NOT(p), NOT(q)) across full {T, F, escalated}² domain"""
    tree_lhs = build_tree(
        NOT("root", "and_pq"),
        AND("and_pq", "p", "q"),
        leaf("p"), leaf("q"),
    )
    tree_rhs = build_tree(
        OR("root", "not_p", "not_q"),
        NOT("not_p", "p"),
        NOT("not_q", "q"),
        leaf("p"), leaf("q"),
    )
    mismatches = []
    for p_name, p in [("T", T), ("F", F), ("E", E)]:
        for q_name, q in [("T", T), ("F", F), ("E", E)]:
            r1, _ = evaluate(tree_lhs, "root", {"p": p, "q": q})
            r2, _ = evaluate(tree_rhs, "root", {"p": p, "q": q})
            # Compare both value and escalation flag
            if r1.value != r2.value or r1.escalation_flag != r2.escalation_flag:
                mismatches.append((p_name, q_name, r1.value, r1.escalation_flag,
                                   r2.value, r2.escalation_flag))
    if mismatches:
        # Return the mismatches as failure detail
        return f"mismatches: {mismatches}"
    return True


def test_DeMorgan_NOT_OR_under_escalation():
    """NOT(OR(p, q)) = AND(NOT(p), NOT(q)) across full {T, F, escalated}² domain"""
    tree_lhs = build_tree(
        NOT("root", "or_pq"),
        OR("or_pq", "p", "q"),
        leaf("p"), leaf("q"),
    )
    tree_rhs = build_tree(
        AND("root", "not_p", "not_q"),
        NOT("not_p", "p"),
        NOT("not_q", "q"),
        leaf("p"), leaf("q"),
    )
    mismatches = []
    for p_name, p in [("T", T), ("F", F), ("E", E)]:
        for q_name, q in [("T", T), ("F", F), ("E", E)]:
            r1, _ = evaluate(tree_lhs, "root", {"p": p, "q": q})
            r2, _ = evaluate(tree_rhs, "root", {"p": p, "q": q})
            if r1.value != r2.value or r1.escalation_flag != r2.escalation_flag:
                mismatches.append((p_name, q_name, r1.value, r1.escalation_flag,
                                   r2.value, r2.escalation_flag))
    if mismatches:
        return f"mismatches: {mismatches}"
    return True


# --- Tier E: deeper nesting ---

def test_triple_NOT():
    """NOT(NOT(NOT(p))) = NOT(p)"""
    tree = build_tree(
        NOT("root", "n2"),
        NOT("n2", "n1"),
        NOT("n1", "p"),
        leaf("p"),
    )
    for spec, expected in [(T, False), (F, True)]:
        result, _ = evaluate(tree, "root", {"p": spec})
        if result.value != expected:
            return False
    return True


def test_NOT_distributes_over_nested_AND_OR():
    """NOT(AND(p, OR(q, r))) = OR(NOT(p), AND(NOT(q), NOT(r))) — combined De Morgan"""
    tree_lhs = build_tree(
        NOT("root", "and_p_qr"),
        AND("and_p_qr", "p", "qr"),
        OR("qr", "q", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    tree_rhs = build_tree(
        OR("root", "not_p", "and_notq_notr"),
        NOT("not_p", "p"),
        AND("and_notq_notr", "not_q", "not_r"),
        NOT("not_q", "q"),
        NOT("not_r", "r"),
        leaf("p"), leaf("q"), leaf("r"),
    )
    for p in [T, F]:
        for q in [T, F]:
            for r in [T, F]:
                r1, _ = evaluate(tree_lhs, "root", {"p": p, "q": q, "r": r})
                r2, _ = evaluate(tree_rhs, "root", {"p": p, "q": q, "r": r})
                if r1.value != r2.value:
                    return False
    return True


# --- Tier F: degenerate / error cases ---

def test_NOT_requires_exactly_one_child():
    """NOT with two children should produce an error result, not crash"""
    tree = build_tree(
        {"id": "root", "type": "compose", "op": "NOT", "children": ["p", "q"]},
        leaf("p"), leaf("q"),
    )
    try:
        result, _ = evaluate(tree, "root", {"p": T, "q": F})
        # Engine should return an error NodeResult, not crash
        return result.value is None and result.error is not None
    except Exception:
        return False  # crash is failure


# =============================================================================
# Test cases — Larger-scope structural tests
# =============================================================================
# Tier G: build trees of increasing width and depth and verify well-defined
# logical properties hold. Tests realistic structural patterns at sizes
# comparable to real policy trees.


def _truth_table_inputs(n_vars: int):
    """Yield all 2^n assignments of n variables to {T, F}."""
    from itertools import product
    for vals in product([T, F], repeat=n_vars):
        yield dict(zip([f"p{i}" for i in range(n_vars)], vals))


def test_wide_AND_n5_all_true():
    """AND of 5 true children = True"""
    tree = build_tree(
        AND("root", "p0", "p1", "p2", "p3", "p4"),
        *[leaf(f"p{i}") for i in range(5)],
    )
    vals = {f"p{i}": T for i in range(5)}
    result, mock = evaluate(tree, "root", vals)
    return result.value is True and mock.call_count == 5


def test_wide_AND_n5_one_false_short_circuits():
    """AND of 5 children where the 3rd is False: only p0, p1, p2 evaluated"""
    tree = build_tree(
        AND("root", "p0", "p1", "p2", "p3", "p4"),
        *[leaf(f"p{i}") for i in range(5)],
    )
    vals = {f"p{i}": T for i in range(5)}
    vals["p2"] = F
    result, mock = evaluate(tree, "root", vals)
    return (
        result.value is False
        and mock.call_count == 3
        and mock.calls == ["p0", "p1", "p2"]
    )


def test_wide_OR_n5_one_true_short_circuits():
    """OR of 5 children where the 3rd is True: only p0, p1, p2 evaluated"""
    tree = build_tree(
        OR("root", "p0", "p1", "p2", "p3", "p4"),
        *[leaf(f"p{i}") for i in range(5)],
    )
    vals = {f"p{i}": F for i in range(5)}
    vals["p2"] = T
    result, mock = evaluate(tree, "root", vals)
    return (
        result.value is True
        and mock.call_count == 3
        and mock.calls == ["p0", "p1", "p2"]
    )


def test_wide_AND_n8_truth_table():
    """AND of 8 children: value is conjunction of all"""
    nodes = [leaf(f"p{i}") for i in range(8)]
    tree = build_tree(
        AND("root", *[f"p{i}" for i in range(8)]),
        *nodes,
    )
    # Sample 16 random assignments rather than exhaust 256
    import random
    rng = random.Random(42)
    for _ in range(16):
        vals = {f"p{i}": rng.choice([T, F]) for i in range(8)}
        expected = all(vals[f"p{i}"]["value"] is True for i in range(8))
        result, _ = evaluate(tree, "root", vals)
        if result.value != expected:
            return False
    return True


def test_deep_AND_chain_n6():
    """AND(AND(AND(AND(AND(AND(p0, p1), p2), p3), p4), p5)) — deeply nested AND"""
    tree = build_tree(
        AND("root", "ch4", "p5"),
        AND("ch4", "ch3", "p4"),
        AND("ch3", "ch2", "p3"),
        AND("ch2", "ch1", "p2"),
        AND("ch1", "p0", "p1"),
        *[leaf(f"p{i}") for i in range(6)],
    )
    # All true → True
    vals_all_true = {f"p{i}": T for i in range(6)}
    r1, _ = evaluate(tree, "root", vals_all_true)
    if r1.value is not True:
        return False
    # One false anywhere → False
    for i in range(6):
        vals = dict(vals_all_true)
        vals[f"p{i}"] = F
        r, _ = evaluate(tree, "root", vals)
        if r.value is not False:
            return False
    return True


def test_balanced_tree_AND_OR_depth_3():
    """A balanced tree mixing AND and OR, depth 3, verified against expected formula.

    Structure: AND(OR(AND(p0, p1), AND(p2, p3)), OR(AND(p4, p5), AND(p6, p7)))
    Formula:   ((p0 ∧ p1) ∨ (p2 ∧ p3)) ∧ ((p4 ∧ p5) ∨ (p6 ∧ p7))
    """
    tree = build_tree(
        AND("root", "left_or", "right_or"),
        OR("left_or", "and01", "and23"),
        OR("right_or", "and45", "and67"),
        AND("and01", "p0", "p1"),
        AND("and23", "p2", "p3"),
        AND("and45", "p4", "p5"),
        AND("and67", "p6", "p7"),
        *[leaf(f"p{i}") for i in range(8)],
    )
    # Sample assignments; compute expected with Python booleans
    import random
    rng = random.Random(7)
    for _ in range(20):
        bool_vals = [rng.choice([True, False]) for _ in range(8)]
        b = bool_vals
        expected = (
            ((b[0] and b[1]) or (b[2] and b[3]))
            and
            ((b[4] and b[5]) or (b[6] and b[7]))
        )
        vals = {f"p{i}": T if b[i] else F for i in range(8)}
        result, _ = evaluate(tree, "root", vals)
        if result.value != expected:
            return False
    return True


def test_balanced_tree_with_NOT_depth_3():
    """Balanced tree mixing AND, OR, NOT, depth 3.

    Structure: OR(AND(NOT(p0), p1), AND(p2, NOT(p3)))
    Formula:   (¬p0 ∧ p1) ∨ (p2 ∧ ¬p3)
    """
    tree = build_tree(
        OR("root", "left", "right"),
        AND("left", "n0", "p1"),
        AND("right", "p2", "n3"),
        NOT("n0", "p0"),
        NOT("n3", "p3"),
        *[leaf(f"p{i}") for i in range(4)],
    )
    for assignment in _truth_table_inputs(4):
        b = [assignment[f"p{i}"]["value"] for i in range(4)]
        expected = ((not b[0]) and b[1]) or (b[2] and (not b[3]))
        result, _ = evaluate(tree, "root", assignment)
        if result.value != expected:
            return False
    return True


def test_realistic_policy_shape():
    """A tree shaped like a small policy: 4 top-level branches AND-composed,
    each branch is OR over alternative satisfactions, with NOT for exclusions.

    Structure:
        root = AND(
            diagnosis_branch,     OR(diag_a, diag_b, diag_c)
            treatment_branch,     AND(pt_done, pharma_done)
            no_exclusions,        NOT(OR(excl_1, excl_2))
            documentation,        AND(doc_a, doc_b)
        )
    """
    tree = build_tree(
        AND("root", "diagnosis", "treatment", "no_exclusions", "documentation"),
        OR("diagnosis", "diag_a", "diag_b", "diag_c"),
        AND("treatment", "pt_done", "pharma_done"),
        NOT("no_exclusions", "any_exclusion"),
        OR("any_exclusion", "excl_1", "excl_2"),
        AND("documentation", "doc_a", "doc_b"),
        leaf("diag_a"), leaf("diag_b"), leaf("diag_c"),
        leaf("pt_done"), leaf("pharma_done"),
        leaf("excl_1"), leaf("excl_2"),
        leaf("doc_a"), leaf("doc_b"),
    )

    # Scenario 1: Clean approval — one diagnosis, treatment done, no exclusions, docs complete
    vals = {
        "diag_a": T, "diag_b": F, "diag_c": F,
        "pt_done": T, "pharma_done": T,
        "excl_1": F, "excl_2": F,
        "doc_a": T, "doc_b": T,
    }
    r, _ = evaluate(tree, "root", vals)
    if r.value is not True:
        return f"clean approval expected True, got {r.value}"

    # Scenario 2: Exclusion fires → root False
    vals = {
        "diag_a": T, "diag_b": F, "diag_c": F,
        "pt_done": T, "pharma_done": T,
        "excl_1": T, "excl_2": F,  # exclusion fires
        "doc_a": T, "doc_b": T,
    }
    r, _ = evaluate(tree, "root", vals)
    if r.value is not False:
        return f"exclusion firing expected False, got {r.value}"

    # Scenario 3: No qualifying diagnosis → root False (AND short-circuits at diagnosis branch)
    vals = {
        "diag_a": F, "diag_b": F, "diag_c": F,
        "pt_done": T, "pharma_done": T,
        "excl_1": F, "excl_2": F,
        "doc_a": T, "doc_b": T,
    }
    r, _ = evaluate(tree, "root", vals)
    if r.value is not False:
        return f"no diagnosis expected False, got {r.value}"

    # Scenario 4: Treatment incomplete, but engine short-circuits before reaching it
    # since diagnosis_branch evaluates first under AND
    vals = {
        "diag_a": T, "diag_b": F, "diag_c": F,
        "pt_done": F, "pharma_done": T,  # pt not done
        "excl_1": F, "excl_2": F,
        "doc_a": T, "doc_b": T,
    }
    r, mock = evaluate(tree, "root", vals)
    if r.value is not False:
        return f"incomplete treatment expected False, got {r.value}"
    # Engine should NOT have evaluated docs (short-circuited after treatment False)
    if "doc_a" in mock.calls or "doc_b" in mock.calls:
        return f"short-circuit failed: docs were evaluated after treatment False"

    return True


def test_escalation_propagates_through_mixed_tree():
    """In a realistic mixed tree, an escalated leaf in a non-short-circuited path
    propagates escalation to the root."""
    tree = build_tree(
        AND("root", "branch_a", "branch_b"),
        OR("branch_a", "p0", "p1"),
        OR("branch_b", "p2", "p3"),
        leaf("p0"), leaf("p1"), leaf("p2"), leaf("p3"),
    )
    # branch_a: OR(T, ...) short-circuits to T
    # branch_b: OR(escalated, F) → escalated
    # root: AND(T, escalated) → escalated
    vals = {"p0": T, "p1": F, "p2": E, "p3": F}
    r, _ = evaluate(tree, "root", vals)
    return r.value is None and r.escalation_flag is True


def test_escalation_does_not_propagate_when_dominated():
    """An escalated leaf in a path that gets short-circuited by F doesn't propagate."""
    tree = build_tree(
        AND("root", "must_be_true", "escalated_branch"),
        OR("escalated_branch", "p1", "p2"),
        leaf("must_be_true"),
        leaf("p1"), leaf("p2"),
    )
    # must_be_true = F → AND short-circuits → escalated_branch never evaluated
    vals = {"must_be_true": F, "p1": E, "p2": E}
    r, mock = evaluate(tree, "root", vals)
    return (
        r.value is False
        and not r.escalation_flag
        and "p1" not in mock.calls
        and "p2" not in mock.calls
    )


# =============================================================================
# Test cases — Property-based / randomly generated trees
# =============================================================================
# Tier H: build trees by random structural generation, compute the expected
# result with native Python booleans, and verify the engine matches. This is
# the strongest evidence of compositional correctness at realistic scale —
# if N random trees and assignments all agree, the engine's behavior matches
# classical logic on every structure it generated.


def _gen_random_tree(rng, max_depth: int, prop_pool: list[str], node_counter: list[int]):
    """
    Recursively generate a random tree. Returns (node_dicts, root_id, expr_fn)
    where expr_fn is a Python callable that takes a dict {var: bool} and
    returns the expected boolean.

    node_counter is a mutable [int] used to generate unique compose-node IDs.
    """
    # Base case: at max depth, return a leaf
    if max_depth == 0 or rng.random() < 0.3:
        var = rng.choice(prop_pool)
        return [leaf(var)], var, (lambda assignment, v=var: assignment[v])

    # Recursive case: pick an operator
    op_choice = rng.choices(["AND", "OR", "NOT"], weights=[0.4, 0.4, 0.2])[0]
    node_counter[0] += 1
    node_id = f"c{node_counter[0]}"

    if op_choice == "NOT":
        child_nodes, child_id, child_fn = _gen_random_tree(
            rng, max_depth - 1, prop_pool, node_counter
        )
        return (
            [NOT(node_id, child_id)] + child_nodes,
            node_id,
            lambda assignment, f=child_fn: not f(assignment),
        )

    # AND or OR with 2 or 3 children
    n_children = rng.choice([2, 3])
    children_nodes = []
    children_ids = []
    children_fns = []
    for _ in range(n_children):
        cn, cid, cfn = _gen_random_tree(rng, max_depth - 1, prop_pool, node_counter)
        children_nodes.extend(cn)
        children_ids.append(cid)
        children_fns.append(cfn)

    if op_choice == "AND":
        compose_node = AND(node_id, *children_ids)
        compose_fn = lambda assignment, fns=children_fns: all(f(assignment) for f in fns)
    else:  # OR
        compose_node = OR(node_id, *children_ids)
        compose_fn = lambda assignment, fns=children_fns: any(f(assignment) for f in fns)

    return [compose_node] + children_nodes, node_id, compose_fn


def _run_property_test(n_trials: int, max_depth: int, n_vars: int, seed: int) -> tuple[bool, str]:
    """
    Generate n_trials random trees of up to max_depth, evaluate each on a random
    assignment, and verify engine matches Python-computed truth.

    Returns (success, detail_string).
    """
    import random
    rng = random.Random(seed)
    prop_pool = [f"p{i}" for i in range(n_vars)]

    mismatches = []
    total_nodes = 0
    total_leaves = 0

    for trial in range(n_trials):
        node_counter = [0]
        nodes, root_id, expr_fn = _gen_random_tree(
            rng, max_depth, prop_pool, node_counter
        )

        # Deduplicate node dicts by id (random gen can produce duplicate leaf entries)
        seen = {}
        for n in nodes:
            seen[n["id"]] = n
        unique_nodes = list(seen.values())

        tree = {n["id"]: n for n in unique_nodes}
        leaf_nodes = [n for n in unique_nodes if n["type"] == "char"]
        total_nodes += len(unique_nodes)
        total_leaves += len(leaf_nodes)

        # Generate a random boolean assignment for the variables used
        bool_assignment = {v: rng.choice([True, False]) for v in prop_pool}
        engine_assignment = {
            v: (T if bool_assignment[v] else F) for v in prop_pool
        }

        # Filter engine assignment to only the leaves actually in the tree
        engine_assignment = {
            n["id"]: engine_assignment[n["id"]] for n in leaf_nodes
        }

        expected = expr_fn(bool_assignment)
        try:
            result, _ = evaluate(tree, root_id, engine_assignment)
        except Exception as e:
            mismatches.append((trial, "exception", str(e)))
            continue

        if result.value != expected:
            mismatches.append((trial, expected, result.value))

    avg_nodes = total_nodes / n_trials
    avg_leaves = total_leaves / n_trials
    detail = (f"trials={n_trials}, avg_nodes={avg_nodes:.1f}, "
              f"avg_leaves={avg_leaves:.1f}, mismatches={len(mismatches)}")
    if mismatches:
        detail += f" -- first mismatch: {mismatches[0]}"
        return False, detail
    return True, detail


# Property tests at increasing scope

def test_property_random_trees_depth_3():
    """50 random trees of depth ≤ 3 over 4 variables. Engine vs Python boolean."""
    success, detail = _run_property_test(n_trials=50, max_depth=3, n_vars=4, seed=1)
    return True if success else detail


def test_property_random_trees_depth_5():
    """50 random trees of depth ≤ 5 over 6 variables."""
    success, detail = _run_property_test(n_trials=50, max_depth=5, n_vars=6, seed=2)
    return True if success else detail


def test_property_random_trees_depth_7():
    """30 random trees of depth ≤ 7 over 8 variables — realistic policy-tree scale."""
    success, detail = _run_property_test(n_trials=30, max_depth=7, n_vars=8, seed=3)
    return True if success else detail


def test_property_random_trees_high_NOT_ratio():
    """30 random trees with biased NOT generation — exercises NOT under nesting."""
    import random
    rng = random.Random(42)

    # Custom generator with higher NOT weight
    def _gen_not_heavy(rng, max_depth, prop_pool, node_counter):
        if max_depth == 0 or rng.random() < 0.25:
            var = rng.choice(prop_pool)
            return [leaf(var)], var, (lambda assignment, v=var: assignment[v])

        op_choice = rng.choices(["AND", "OR", "NOT"], weights=[0.3, 0.3, 0.4])[0]
        node_counter[0] += 1
        node_id = f"c{node_counter[0]}"

        if op_choice == "NOT":
            cn, cid, cfn = _gen_not_heavy(rng, max_depth - 1, prop_pool, node_counter)
            return ([NOT(node_id, cid)] + cn, node_id,
                    lambda a, f=cfn: not f(a))

        n_children = rng.choice([2, 3])
        children_nodes, children_ids, children_fns = [], [], []
        for _ in range(n_children):
            cn, cid, cfn = _gen_not_heavy(rng, max_depth - 1, prop_pool, node_counter)
            children_nodes.extend(cn)
            children_ids.append(cid)
            children_fns.append(cfn)

        if op_choice == "AND":
            return ([AND(node_id, *children_ids)] + children_nodes, node_id,
                    lambda a, fns=children_fns: all(f(a) for f in fns))
        else:
            return ([OR(node_id, *children_ids)] + children_nodes, node_id,
                    lambda a, fns=children_fns: any(f(a) for f in fns))

    prop_pool = [f"p{i}" for i in range(5)]
    mismatches = []
    for trial in range(30):
        node_counter = [0]
        nodes, root_id, expr_fn = _gen_not_heavy(rng, 5, prop_pool, node_counter)
        seen = {}
        for n in nodes:
            seen[n["id"]] = n
        unique_nodes = list(seen.values())
        tree = {n["id"]: n for n in unique_nodes}
        leaf_nodes = [n for n in unique_nodes if n["type"] == "char"]

        bool_assignment = {v: rng.choice([True, False]) for v in prop_pool}
        engine_assignment = {
            n["id"]: (T if bool_assignment[n["id"]] else F)
            for n in leaf_nodes
        }

        expected = expr_fn(bool_assignment)
        try:
            result, _ = evaluate(tree, root_id, engine_assignment)
        except Exception as e:
            mismatches.append((trial, "exception", str(e)))
            continue
        if result.value != expected:
            mismatches.append((trial, expected, result.value))

    return len(mismatches) == 0


def test_property_stress_500_trees_depth_5():
    """500 random trees of depth ≤ 5 over 5 variables — stress test."""
    success, detail = _run_property_test(n_trials=500, max_depth=5, n_vars=5, seed=100)
    return True if success else detail


def test_property_stress_200_trees_depth_8():
    """200 random trees of depth ≤ 8 over 6 variables — deeper structure."""
    success, detail = _run_property_test(n_trials=200, max_depth=8, n_vars=6, seed=200)
    return True if success else detail


def test_property_shared_leaves_intensive():
    """Force many shared-leaf scenarios by using a small variable pool over
    deep trees. This is exactly the case the engine fix addresses."""
    # 3 variables forces heavy sharing across leaves of compose nodes
    success, detail = _run_property_test(n_trials=200, max_depth=6, n_vars=3, seed=300)
    return True if success else detail


# =============================================================================
# Runner
# =============================================================================

def collect_tests():
    """Find all test_* functions in this module."""
    import inspect
    current_module = sys.modules[__name__]
    return [
        (name, fn)
        for name, fn in inspect.getmembers(current_module, inspect.isfunction)
        if name.startswith("test_")
    ]


def main():
    tests = collect_tests()
    print(f"Running {len(tests)} tier 1 logic tests...")
    print("=" * 70)

    passed = []
    failed = []
    errored = []

    for name, fn in tests:
        try:
            result = fn()
            if result is True:
                passed.append(name)
                status = "✓"
            else:
                failed.append((name, result))
                status = "✗"
            print(f"  {status} {name}")
        except Exception as e:
            errored.append((name, e))
            print(f"  E {name}: {type(e).__name__}: {e}")

    print("=" * 70)
    print(f"Results: {len(passed)} passed, {len(failed)} failed, {len(errored)} errored")
    print()

    if failed:
        print("FAILURES:")
        for name, result in failed:
            print(f"  {name}: returned {result!r}")
        print()
    if errored:
        print("ERRORS:")
        for name, exc in errored:
            print(f"  {name}: {type(exc).__name__}: {exc}")
        print()

    return 0 if not failed and not errored else 1


if __name__ == "__main__":
    sys.exit(main())

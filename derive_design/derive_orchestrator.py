"""
Derive: the runtime orchestrator.

Walks a reasoning tree from the root with short-circuit evaluation. At each
leaf, routes to the appropriate handler:
  - char leaves → characterize call (substrate)
  - retrieve leaves → resolve from the case's fact bundle
  - compute leaves → deterministic computation from prior node results

At internal nodes, composes children's results per the logical operator.
Builds the trace as the walk progresses. Applies the routing function at
the root to determine the final outcome.

The orchestrator is deterministic. All substrate work happens in
characterize calls. All substrate variation traces to characterize behavior.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from enum import Enum


# =========================================================================
# Types
# =========================================================================

class Disposition(Enum):
    """
    The substantive answer the system arrived at after evaluating the rule.
    Always computed from the tree. Independent of routing tier.
    """
    COVERED_FULL_REPAIR = "covered_full_repair"
    COVERED_TOTAL_LOSS = "covered_total_loss"
    COVERED_WITH_BETTERMENT_DEDUCTION = "covered_with_betterment_deduction"
    DENIED_INSURING_AGREEMENT_FAILED = "denied_insuring_agreement_failed"
    DENIED_BY_EXCLUSION = "denied_by_exclusion"
    INDETERMINATE_INSUFFICIENT_FACTS = "indeterminate_insufficient_facts"


class RoutingTier(Enum):
    """
    Four-tier governance model. Determined from the trace's escalation
    signal profile plus any case-level routing policy. Orthogonal to
    disposition.

    AUTO: system commits to the disposition autonomously. No human in
          the loop.
    SPOT_CHECK: system commits, but a sampled fraction get post-hoc
                human review for quality assurance. The case proceeds
                while review happens.
    GATE: system produces a tentative disposition, but commitment is
          blocked until a human reviews and approves. Case stops until
          reviewer acts.
    HOLD: system does not produce a committed disposition. Case is
          queued for full human adjudication. The substrate's tentative
          view is available as input but the determination is the
          adjudicator's.
    """
    AUTO = "auto"
    SPOT_CHECK = "spot_check"
    GATE = "gate"
    HOLD = "hold"


@dataclass
class EscalationSignals:
    """
    Explicit escalation triggers from a characterize call. Each signal
    represents a distinct epistemic situation that warrants human review.

    insufficient_facts: required facts are missing from the inputs
    contradictory_facts: the available facts conflict and the substrate
                         cannot principlely resolve them from the facts alone
    low_confidence_in_value: the substrate committed to a value but its
                             confidence is below the threshold for autonomous
                             determination
    contested_reading: the condition admits multiple defensible readings
                       producing different evaluations; the substrate may
                       have high confidence in its own reading but
                       recognizes that the choice between readings is
                       institutional judgment
    requires_institutional_judgment: more general signal that the
                                     condition cannot be evaluated by
                                     reference to facts and definitions
                                     alone; a human decision-maker is
                                     needed
    """
    insufficient_facts: bool = False
    contradictory_facts: bool = False
    low_confidence_in_value: bool = False
    contested_reading: bool = False
    requires_institutional_judgment: bool = False

    @property
    def any_signal(self) -> bool:
        return any([
            self.insufficient_facts,
            self.contradictory_facts,
            self.low_confidence_in_value,
            self.contested_reading,
            self.requires_institutional_judgment,
        ])


@dataclass
class NodeResult:
    """Result of evaluating a single node."""
    node_id: str
    value: Any  # boolean, number, etc.; None if no committed value
    confidence: float
    cited_facts: list[str] = field(default_factory=list)
    reasoning: str = ""
    escalation_signals: EscalationSignals = field(default_factory=EscalationSignals)
    escalation_reason: str = ""
    short_circuited: bool = False
    error: Optional[str] = None

    @property
    def escalation_flag(self) -> bool:
        """True if any escalation signal is set. Convenience accessor."""
        return self.escalation_signals.any_signal


@dataclass
class Determination:
    """
    The structured output of derive. Three independent dimensions:

    - disposition: the substantive answer (covered/denied/indeterminate)
    - routing_tier: the routing decision (auto/spot_check/gate/hold)
    - confidence: substrate's calibrated certainty in the disposition

    For AUTO and SPOT_CHECK: the system commits to the disposition.
    For GATE: the disposition is tentative pending human approval.
    For HOLD: the disposition is informational only; the human adjudicates.
    """
    disposition: Disposition
    routing_tier: RoutingTier
    confidence: float = 1.0
    payable_amount: Optional[float] = None
    denial_reason: Optional[dict] = None
    routing_reasons: list = field(default_factory=list)
    trace: dict = field(default_factory=dict)
    tree_version: str = ""

    @property
    def is_tentative(self) -> bool:
        """True for GATE and HOLD; False for AUTO and SPOT_CHECK."""
        return self.routing_tier in (RoutingTier.GATE, RoutingTier.HOLD)

    @property
    def requires_human_review(self) -> bool:
        """True if the case will receive human review before/instead of commitment."""
        return self.routing_tier != RoutingTier.AUTO


@dataclass
class CaseFactBundle:
    """The consolidated case facts available to characterize and retrieve."""
    extract_facts: dict[str, Any]  # field_name → fact value(s)
    retrieve_facts: dict[str, Any]  # query_or_field → typed value
    case_id: str = ""


# =========================================================================
# Orchestrator
# =========================================================================

class DeriveOrchestrator:

    def __init__(
        self,
        tree: dict,
        tree_metadata: dict,
        characterize_fn: Callable,
        escalation_threshold: float = 0.7,
    ):
        """
        tree: the reasoning tree as a dict of node_id → node_spec
        tree_metadata: version info etc.
        characterize_fn: callable that takes a characterize request and returns
                        a NodeResult. May be a substrate call or a stub.
        escalation_threshold: minimum confidence for committed evaluations
        """
        self.tree = tree
        self.tree_metadata = tree_metadata
        self.characterize_fn = characterize_fn
        self.escalation_threshold = escalation_threshold

    def derive(self, facts: CaseFactBundle) -> Determination:
        """
        Walk the tree against the case facts, produce the determination.
        """
        self.facts = facts
        self.trace = {}  # node_id → NodeResult, populated as we walk
        # short_circuit_log: parent_node_id → list of child_node_ids that
        # were not evaluated because the parent short-circuited. Recorded
        # locally per parent so leaves that other parents need still get
        # real evaluation when reached.
        self.short_circuit_log = {}

        root_id = self.tree_metadata["root_node_id"]
        self._evaluate_node(root_id)

        return self._apply_routing()

    # -----------------------------------------------------------------
    # Node evaluation (recursive walk)
    # -----------------------------------------------------------------

    def _evaluate_node(self, node_id: str) -> NodeResult:
        """
        Evaluate a node and store its result in the trace. Returns the result.
        """
        if node_id in self.trace:
            return self.trace[node_id]

        node = self.tree.get(node_id)
        if node is None:
            result = NodeResult(
                node_id=node_id,
                value=None,
                confidence=0.0,
                error=f"node {node_id} not found in tree",
            )
            self.trace[node_id] = result
            return result

        if node["type"] == "compose":
            result = self._evaluate_compose(node)
        elif node["type"] == "char":
            result = self._evaluate_char(node)
        elif node["type"] == "retrieve":
            result = self._evaluate_retrieve(node)
        elif node["type"] == "compute":
            result = self._evaluate_compute(node)
        else:
            result = NodeResult(
                node_id=node_id,
                value=None,
                confidence=0.0,
                error=f"unknown node type {node['type']}",
            )

        self.trace[node_id] = result
        return result

    def _evaluate_compose(self, node: dict) -> NodeResult:
        op = node["op"]

        if op == "AND":
            return self._eval_AND(node)
        elif op == "OR":
            return self._eval_OR(node)
        elif op == "NOT":
            return self._eval_NOT(node)
        elif op == "AND_NOT_CARVE_OUT":
            # Special structure: condition AND (NOT carve-out)
            # First child is the condition, second is the carve-out.
            # The exclusion/condition "fires" only if first is true AND
            # second (the carve-out) is also true (i.e., the case is not
            # covered by the carve-out).
            return self._eval_AND_NOT_CARVE_OUT(node)
        elif op == "DETERMINATION":
            # Root node — just evaluate all children, routing happens later.
            return self._eval_DETERMINATION(node)
        elif op == "COMPUTE_LIABILITY":
            return self._eval_COMPUTE_LIABILITY(node)
        else:
            return NodeResult(
                node_id=node["id"],
                value=None,
                confidence=0.0,
                error=f"unknown compose op {op}",
            )

    def _propagate_signals(
        self,
        accumulator: EscalationSignals,
        child_signals: EscalationSignals,
    ) -> None:
        """Merge a child's escalation signals into the accumulator."""
        if child_signals.insufficient_facts:
            accumulator.insufficient_facts = True
        if child_signals.contradictory_facts:
            accumulator.contradictory_facts = True
        if child_signals.low_confidence_in_value:
            accumulator.low_confidence_in_value = True
        if child_signals.contested_reading:
            accumulator.contested_reading = True
        if child_signals.requires_institutional_judgment:
            accumulator.requires_institutional_judgment = True

    def _eval_AND(self, node: dict) -> NodeResult:
        children = node["children"]
        results = []
        min_conf = 1.0
        cited = []
        any_escalated = False
        escalation_reasons = []
        propagated_signals = EscalationSignals()

        for child_id in children:
            child_result = self._evaluate_node(child_id)
            results.append(child_result)
            if child_result.escalation_flag:
                any_escalated = True
                escalation_reasons.append(
                    f"{child_id}: {child_result.escalation_reason}"
                )
                self._propagate_signals(propagated_signals, child_result.escalation_signals)
            min_conf = min(min_conf, child_result.confidence)
            cited.extend(child_result.cited_facts)

            # Short-circuit if a child is definitively false
            if child_result.value is False and not child_result.escalation_flag:
                # Record short-circuit locally on this parent — don't write
                # to the global trace, since remaining children may appear
                # under other parents that need real evaluation.
                skipped = list(children[children.index(child_id) + 1:])
                if skipped:
                    self.short_circuit_log[node["id"]] = skipped
                return NodeResult(
                    node_id=node["id"],
                    value=False,
                    confidence=child_result.confidence,
                    cited_facts=cited,
                    reasoning=f"AND short-circuit: {child_id} is false",
                )

        if any_escalated:
            return NodeResult(
                node_id=node["id"],
                value=None,
                confidence=min_conf,
                cited_facts=cited,
                escalation_signals=propagated_signals,
                escalation_reason="; ".join(escalation_reasons),
                reasoning=f"AND of {len(children)} children, one or more escalated",
            )

        all_true = all(r.value is True for r in results)
        return NodeResult(
            node_id=node["id"],
            value=all_true,
            confidence=min_conf,
            cited_facts=cited,
            reasoning=f"AND of {len(children)} children: {'all true' if all_true else 'not all true'}",
        )

    def _eval_OR(self, node: dict) -> NodeResult:
        children = node["children"]
        results = []
        max_conf = 0.0
        cited = []
        any_escalated = False
        escalation_reasons = []
        propagated_signals = EscalationSignals()
        any_true_child = None

        for child_id in children:
            child_result = self._evaluate_node(child_id)
            results.append(child_result)
            if child_result.escalation_flag:
                any_escalated = True
                escalation_reasons.append(
                    f"{child_id}: {child_result.escalation_reason}"
                )
                self._propagate_signals(propagated_signals, child_result.escalation_signals)
            max_conf = max(max_conf, child_result.confidence)
            cited.extend(child_result.cited_facts)

            # Short-circuit if a child is definitively true
            if child_result.value is True and not child_result.escalation_flag:
                any_true_child = child_id
                skipped = list(children[children.index(child_id) + 1:])
                if skipped:
                    self.short_circuit_log[node["id"]] = skipped
                return NodeResult(
                    node_id=node["id"],
                    value=True,
                    confidence=child_result.confidence,
                    cited_facts=cited,
                    reasoning=f"OR short-circuit: {child_id} is true",
                )

        if any_escalated:
            return NodeResult(
                node_id=node["id"],
                value=None,
                confidence=max_conf,
                cited_facts=cited,
                escalation_signals=propagated_signals,
                escalation_reason="; ".join(escalation_reasons),
                reasoning=f"OR of {len(children)} children, one or more escalated, none definitively true",
            )

        any_true = any(r.value is True for r in results)
        return NodeResult(
            node_id=node["id"],
            value=any_true,
            confidence=max_conf,
            cited_facts=cited,
            reasoning=f"OR of {len(children)} children: {'at least one true' if any_true else 'none true'}",
        )

    def _eval_NOT(self, node: dict) -> NodeResult:
        """
        Three-valued negation with Strong Kleene semantics:
            NOT(True)      = False
            NOT(False)     = True
            NOT(escalated) = escalated  (escalation signals preserved)

        Confidence is unchanged: NOT(v with conf=c) has confidence c. The
        operator carries no judgment of its own; it simply inverts a known
        truth value or preserves an escalation state. Cited facts pass
        through unchanged.

        NOT requires exactly one child.
        """
        children = node["children"]
        if len(children) != 1:
            return NodeResult(
                node_id=node["id"],
                value=None,
                confidence=0.0,
                error=f"NOT requires exactly one child, got {len(children)}",
            )

        child_result = self._evaluate_node(children[0])

        # Escalated child → escalated NOT (signals and reason preserved)
        if child_result.escalation_flag:
            return NodeResult(
                node_id=node["id"],
                value=None,
                confidence=child_result.confidence,
                cited_facts=child_result.cited_facts,
                escalation_signals=child_result.escalation_signals,
                escalation_reason=f"NOT of escalated child: {child_result.escalation_reason}",
                reasoning=f"NOT of {children[0]}: child escalated, negation also escalated",
            )

        # Unevaluable child (value is None without escalation) → error
        if child_result.value is None:
            return NodeResult(
                node_id=node["id"],
                value=None,
                confidence=0.0,
                cited_facts=child_result.cited_facts,
                error=f"NOT child {children[0]} has no value and no escalation",
            )

        # Classical case: invert a known boolean
        return NodeResult(
            node_id=node["id"],
            value=(not child_result.value),
            confidence=child_result.confidence,
            cited_facts=child_result.cited_facts,
            reasoning=f"NOT of {children[0]}: {child_result.value} → {not child_result.value}",
        )

    def _eval_AND_NOT_CARVE_OUT(self, node: dict) -> NodeResult:
        """
        Special composition for exclusions with carve-outs.

        The exclusion fires if: condition is true AND (carve-out is true,
        meaning the case is NOT in the carve-out exception).

        Children are [condition_node, carve_out_negation_node].
        """
        children = node["children"]
        condition_result = self._evaluate_node(children[0])

        # If the main condition is false, exclusion doesn't fire — short-circuit
        if condition_result.value is False and not condition_result.escalation_flag:
            # Record short-circuit locally on this parent
            self.short_circuit_log[node["id"]] = [children[1]]
            return NodeResult(
                node_id=node["id"],
                value=False,
                confidence=condition_result.confidence,
                cited_facts=condition_result.cited_facts,
                reasoning="exclusion does not fire: main condition is false",
            )

        # Otherwise evaluate the carve-out negation
        carve_out_result = self._evaluate_node(children[1])

        if condition_result.escalation_flag or carve_out_result.escalation_flag:
            reasons = []
            propagated_signals = EscalationSignals()
            if condition_result.escalation_flag:
                reasons.append(f"{children[0]}: {condition_result.escalation_reason}")
                self._propagate_signals(propagated_signals, condition_result.escalation_signals)
            if carve_out_result.escalation_flag:
                reasons.append(f"{children[1]}: {carve_out_result.escalation_reason}")
                self._propagate_signals(propagated_signals, carve_out_result.escalation_signals)
            return NodeResult(
                node_id=node["id"],
                value=None,
                confidence=min(condition_result.confidence, carve_out_result.confidence),
                cited_facts=condition_result.cited_facts + carve_out_result.cited_facts,
                escalation_signals=propagated_signals,
                escalation_reason="; ".join(reasons),
            )

        fires = condition_result.value and carve_out_result.value
        return NodeResult(
            node_id=node["id"],
            value=fires,
            confidence=min(condition_result.confidence, carve_out_result.confidence),
            cited_facts=condition_result.cited_facts + carve_out_result.cited_facts,
            reasoning=f"exclusion {'fires' if fires else 'does not fire'}: condition={condition_result.value}, not_in_carve_out={carve_out_result.value}",
        )

    def _eval_DETERMINATION(self, node: dict) -> NodeResult:
        """Root node: evaluate all children, no composition value."""
        for child_id in node["children"]:
            self._evaluate_node(child_id)
        return NodeResult(
            node_id=node["id"],
            value=None,
            confidence=1.0,
            reasoning="root node — routing logic applies",
        )

    def _eval_COMPUTE_LIABILITY(self, node: dict) -> NodeResult:
        """
        Limit of liability composition: evaluate all children, no boolean
        value but the children's values feed the routing function.
        """
        for child_id in node["children"]:
            self._evaluate_node(child_id)
        return NodeResult(
            node_id=node["id"],
            value=None,
            confidence=1.0,
            reasoning="liability computation — children feed routing",
        )

    # -----------------------------------------------------------------
    # Leaf evaluators
    # -----------------------------------------------------------------

    def _evaluate_char(self, node: dict) -> NodeResult:
        """Delegate to the characterize function."""

        # Assemble the facts that characterize will see
        relevant_facts = self._gather_facts_for_char(node)

        request = {
            "call_id": f"call.{node['id']}",
            "node_id": node["id"],
            "policy_reference": node["policy_ref"],
            "condition": {
                "text": node["condition_text"],
                "expected_output_type": node["expected_output_type"],
            },
            "definitions": node.get("definitions", []),
            "facts": relevant_facts,
            "tier": node.get("tier", "moderate"),
            "escalation_threshold": self.escalation_threshold,
        }

        # Call characterize
        result = self.characterize_fn(request)

        # Auto-set low_confidence_in_value signal when applicable.
        # Only set this signal if the substrate committed to a value
        # (value is not None) AND confidence is below threshold AND the
        # substrate didn't already flag something. We do not override
        # the substrate's escalation signals — we only add this one.
        if (not result.escalation_signals.any_signal
                and result.value is not None
                and result.confidence < self.escalation_threshold):
            result.escalation_signals.low_confidence_in_value = True
            result.escalation_reason = (
                f"confidence {result.confidence:.2f} below threshold "
                f"{self.escalation_threshold}"
            )

        return result

    def _gather_facts_for_char(self, node: dict) -> list[dict]:
        """
        Collect the facts characterize will see for a node. Pulls from the
        case fact bundle, matching against the node's declared inputs.
        """
        facts = []

        for input_name in node.get("inputs", []):
            # Check extract facts
            if input_name in self.facts.extract_facts:
                fact_val = self.facts.extract_facts[input_name]
                if isinstance(fact_val, list):
                    for item in fact_val:
                        facts.append({
                            "source_class": "extract",
                            "source_identifier": item.get("source", "unknown"),
                            "field_name": input_name,
                            "statement": item.get("statement", str(item)),
                            "confidence": item.get("confidence", 0.8),
                        })
                else:
                    facts.append({
                        "source_class": "extract",
                        "source_identifier": "case content",
                        "field_name": input_name,
                        "statement": str(fact_val),
                        "confidence": 0.8,
                    })

            # Check retrieve facts
            if input_name in self.facts.retrieve_facts:
                fact_val = self.facts.retrieve_facts[input_name]
                facts.append({
                    "source_class": "retrieve",
                    "source_identifier": "system of record",
                    "field_name": input_name,
                    "statement": str(fact_val),
                    "confidence": 1.0,
                })

        return facts

    def _evaluate_retrieve(self, node: dict) -> NodeResult:
        """Resolve a retrieve node from the case's retrieve facts."""
        # The retrieve facts are pre-populated in the case bundle.
        # We look up by node id (which corresponds to the field name).
        node_id = node["id"]
        if node_id in self.facts.retrieve_facts:
            value = self.facts.retrieve_facts[node_id]
            return NodeResult(
                node_id=node_id,
                value=value,
                confidence=1.0,
                cited_facts=[f"retrieve:{node['query']}"],
                reasoning=f"retrieved from system of record: {value}",
            )
        return NodeResult(
            node_id=node_id,
            value=None,
            confidence=0.0,
            error=f"retrieve fact {node_id} not in fact bundle",
        )

    def _evaluate_compute(self, node: dict) -> NodeResult:
        """Deterministic computation from prior node results."""
        node_id = node["id"]

        # Handle each compute node by name. For a general framework,
        # this would be a registry of computation functions; here it's
        # an explicit dispatch.

        if node_id == "is_total_loss":
            # Ensure dependencies are evaluated first (lazy dependency walk)
            repair = self.trace.get("repair_estimate_amount")
            if repair is None:
                repair = self._evaluate_node("repair_estimate_amount")
            acv = self.trace.get("actual_cash_value")
            if acv is None:
                acv = self._evaluate_node("actual_cash_value")

            if repair.value is None or acv.value is None:
                return NodeResult(
                    node_id=node_id,
                    value=None,
                    confidence=0.0,
                    error="missing inputs for is_total_loss",
                )
            return NodeResult(
                node_id=node_id,
                value=repair.value > acv.value,
                confidence=min(repair.confidence, acv.confidence),
                cited_facts=["repair_estimate_amount", "actual_cash_value"],
                reasoning=f"total loss: repair={repair.value} {'>' if repair.value > acv.value else '<='} acv={acv.value}",
            )

        if node_id == "is_non_owned_auto":
            listed = self.trace.get("is_listed_in_declarations")
            if listed is not None and listed.value is True:
                return NodeResult(
                    node_id=node_id,
                    value=False,
                    confidence=1.0,
                    reasoning="vehicle is listed in declarations, so not non-owned",
                )
            return NodeResult(
                node_id=node_id,
                value=None,
                confidence=0.5,
                reasoning="non-owned status undetermined; depends on full coverage tree",
            )

        if node_id == "acquired_during_policy_period":
            # Simplified for our cases — would need fact bundle support
            return NodeResult(
                node_id=node_id,
                value=None,
                confidence=0.0,
                reasoning="not implemented for this case",
            )

        if node_id == "asked_to_insure_within_30_days":
            return NodeResult(
                node_id=node_id,
                value=None,
                confidence=0.0,
                reasoning="not implemented for this case",
            )

        return NodeResult(
            node_id=node_id,
            value=None,
            confidence=0.0,
            error=f"compute node {node_id} has no implementation",
        )

    # -----------------------------------------------------------------
    # Routing
    # -----------------------------------------------------------------

    def _apply_routing(self) -> Determination:
        """
        Compute the determination as two orthogonal dimensions:
          1. Disposition: covered/denied/indeterminate, computed from the tree
          2. Routing tier: AUTO/SPOT_CHECK/GATE/HOLD, computed from the
             trace's escalation signal profile

        The disposition is always computed (even when routing to HOLD) so
        the human adjudicator has the system's tentative view as context.
        """
        disposition, payable, denial = self._compute_disposition()
        routing_tier, routing_reasons = self._compute_routing_tier(disposition)

        # Overall confidence: worst confidence along the path that
        # produced the disposition, excluding short-circuited nodes
        nonzero_confidences = [
            r.confidence for r in self.trace.values()
            if not r.short_circuited and r.confidence > 0
        ]
        overall_conf = min(nonzero_confidences) if nonzero_confidences else 0.0

        return Determination(
            disposition=disposition,
            routing_tier=routing_tier,
            confidence=overall_conf,
            payable_amount=payable,
            denial_reason=denial,
            routing_reasons=routing_reasons,
            trace=self.trace,
            tree_version=self.tree_metadata.get("version", "unknown"),
        )

    def _compute_disposition(self):
        """
        Compute the substantive disposition from the tree state. Returns
        (disposition, payable_amount_or_none, denial_reason_or_none).

        Disposition is computed from the substrate's tentative values at
        each node, regardless of escalation signals. The escalation
        signals feed routing, not disposition.
        """
        # Check for fully-missing required nodes (indeterminate)
        for node_id, result in self.trace.items():
            if (not result.short_circuited
                    and result.value is None
                    and result.confidence == 0.0
                    and not result.escalation_flag):
                missing = [
                    nid for nid, r in self.trace.items()
                    if not r.short_circuited and r.value is None
                    and r.confidence == 0.0 and not r.escalation_flag
                ]
                return (
                    Disposition.INDETERMINATE_INSUFFICIENT_FACTS,
                    None,
                    {"missing_evaluations": missing},
                )

        # Insuring agreement check
        ia = self.trace.get("insuring_agreement_satisfied")
        if ia is None or ia.value is not True:
            failed = []
            if ia is not None:
                for child_id in self.tree["insuring_agreement_satisfied"]["children"]:
                    cr = self.trace.get(child_id)
                    if cr is not None and cr.value is False:
                        failed.append({
                            "node_id": child_id,
                            "policy_ref": self.tree[child_id]["policy_ref"],
                            "reasoning": cr.reasoning,
                            "cited_facts": cr.cited_facts,
                        })
            return (
                Disposition.DENIED_INSURING_AGREEMENT_FAILED,
                None,
                {"failed_conditions": failed},
            )

        # Exclusion check — using substrate's tentative value
        excl = self.trace.get("any_exclusion_fires")
        # When an exclusion's substrate value is None but signals contested,
        # the substrate's tentative reading is encoded by following the
        # leaf's committed value if any. For derive's disposition, we use
        # the tree's evaluated boolean; escalation signals route, they
        # don't override disposition.
        any_exclusion_committed_true = False
        fired = []
        for child_id in self.tree["any_exclusion_fires"]["children"]:
            cr = self.trace.get(child_id)
            if cr is not None and cr.value is True:
                any_exclusion_committed_true = True
                fired.append({
                    "exclusion": child_id,
                    "policy_ref": self.tree[child_id]["policy_ref"],
                    "reasoning": cr.reasoning,
                    "cited_facts": cr.cited_facts,
                })

        if any_exclusion_committed_true:
            return (
                Disposition.DENIED_BY_EXCLUSION,
                None,
                {"fired_exclusions": fired},
            )

        # Coverage established — compute payable amount
        repair = self.trace.get("repair_estimate_amount")
        acv = self.trace.get("actual_cash_value")
        deductible = self.trace.get("deductible_amount")
        total_loss = self.trace.get("is_total_loss")
        betterment = self.trace.get("betterment_present")

        if any(x is None or x.value is None for x in [repair, acv, deductible]):
            return (
                Disposition.INDETERMINATE_INSUFFICIENT_FACTS,
                None,
                {"missing": "limit of liability inputs"},
            )

        if total_loss is not None and total_loss.value is True:
            payable = max(0, acv.value - deductible.value)
            return (Disposition.COVERED_TOTAL_LOSS, payable, None)

        if betterment is not None and betterment.value is True:
            payable = max(0, repair.value - deductible.value)
            return (Disposition.COVERED_WITH_BETTERMENT_DEDUCTION, payable, None)

        payable = max(0, min(repair.value, acv.value) - deductible.value)
        return (Disposition.COVERED_FULL_REPAIR, payable, None)

    def _compute_routing_tier(self, disposition: Disposition):
        """
        Determine the routing tier from the trace's escalation signal
        profile. Returns (tier, reasons_list).

        Signal-to-tier mapping:
          - contested_reading, requires_institutional_judgment,
            contradictory_facts, insufficient_facts → HOLD
          - low_confidence_in_value (alone, no other signals) → GATE
          - No signals + indeterminate disposition → HOLD
          - No signals fired → AUTO (could be promoted to SPOT_CHECK by
            external sampling policy; not implemented here)

        Routing reasons attribute signals to their originating char leaf
        nodes only, not to compose nodes that inherited them via
        propagation. This keeps the human-readable reasons focused on
        where the substrate actually flagged the signal.
        """
        reasons = []
        hold_signals = []
        gate_signals = []

        for node_id, result in self.trace.items():
            if result.short_circuited:
                continue
            # Only attribute signals to char leaves (where substrate
            # actually flagged them), not to compose nodes that inherited
            # signals through propagation.
            node_spec = self.tree.get(node_id, {})
            if node_spec.get("type") != "char":
                continue

            sigs = result.escalation_signals

            # Hold-tier signals
            if sigs.contested_reading:
                hold_signals.append(("contested_reading", node_id, result))
            if sigs.requires_institutional_judgment:
                hold_signals.append(("requires_institutional_judgment", node_id, result))
            if sigs.contradictory_facts:
                hold_signals.append(("contradictory_facts", node_id, result))
            if sigs.insufficient_facts:
                hold_signals.append(("insufficient_facts", node_id, result))

            # Gate-tier signals (only counted if no hold signals fire on this node)
            if (sigs.low_confidence_in_value
                    and not (sigs.contested_reading
                             or sigs.requires_institutional_judgment
                             or sigs.contradictory_facts
                             or sigs.insufficient_facts)):
                gate_signals.append(("low_confidence_in_value", node_id, result))

        # Indeterminate disposition always means HOLD —
        # the case needs human input to even produce facts
        if disposition == Disposition.INDETERMINATE_INSUFFICIENT_FACTS:
            reasons.append({
                "signal": "indeterminate",
                "description": "Required facts are missing; case cannot proceed autonomously.",
            })
            for signal_type, node_id, result in hold_signals + gate_signals:
                reasons.append({
                    "signal": signal_type,
                    "node_id": node_id,
                    "policy_ref": self.tree.get(node_id, {}).get("policy_ref", "unknown"),
                    "reason": result.escalation_reason,
                })
            return RoutingTier.HOLD, reasons

        if hold_signals:
            for signal_type, node_id, result in hold_signals:
                reasons.append({
                    "signal": signal_type,
                    "node_id": node_id,
                    "policy_ref": self.tree.get(node_id, {}).get("policy_ref", "unknown"),
                    "reason": result.escalation_reason,
                })
            return RoutingTier.HOLD, reasons

        if gate_signals:
            for signal_type, node_id, result in gate_signals:
                reasons.append({
                    "signal": signal_type,
                    "node_id": node_id,
                    "policy_ref": self.tree.get(node_id, {}).get("policy_ref", "unknown"),
                    "reason": result.escalation_reason,
                })
            return RoutingTier.GATE, reasons

        # No signals fired — AUTO
        # Production overlay could promote some AUTO cases to SPOT_CHECK
        # based on sampling policy or content rules (high dollar amount,
        # newly-deployed tree version, etc.). Not implemented in this
        # baseline.
        return RoutingTier.AUTO, []

    def _trace_summary(self) -> dict:
        """Compact summary of the trace for inclusion in escalation context."""
        return {
            node_id: {
                "value": r.value,
                "confidence": r.confidence,
                "escalation": r.escalation_flag,
                "short_circuited": r.short_circuited,
            }
            for node_id, r in self.trace.items()
        }

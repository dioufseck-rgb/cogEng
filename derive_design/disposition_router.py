"""
Generic disposition router — reads disposition logic directly from the
tree.

The router extracts disposition rules from each node's `disposition_role`
annotation, sorts them by rank, evaluates them against the trace, and
produces a Determination. Routing tier rules come from tree_metadata.

No separate disposition_spec or routing_spec is needed. Adding a new
domain means writing tree nodes with disposition_role annotations and
TREE_METADATA with routing rules — zero domain Python.

Disposition annotation on a node:
  {
    "rank": <int>,                    # ordering; lower rank fires first
    "when": <predicate>,              # condition on this node's result
    "produces": "<disposition_key>",
    "reasoning_template": "...{node_attr}...",
    "fallback_only": <bool>,          # defer until no other rule fired
    "critical_leaves": {              # which leaves are critical for routing
      "include_self": <bool>,
      "self_descendants": <bool>,
      "include": [<node_id>, ...],
      "exclude_descendants_of": [<node_id>, ...],
    },
  }

Predicates supported in `when`:
  - {"value": <val>}
  - {"value_in": [<val>, ...]}
  - {"min_confidence": <f>}
  - {"apparently_true": True}     # True OR escalated with no descendant hard false
  - {"and": [<p>, ...]}, {"or": [...]}, {"not": <p>}

TREE_METADATA fields (cross-cutting routing policy):
  - required_nodes: list of node_ids that must be evaluated
  - default_disposition, default_reasoning
  - indeterminate_disposition
  - default_critical_leaves
  - signal_severity: {<signal_name>: "hold"|"gate"}
  - tier_rules: {HOLD: [<rule>], GATE: [...], SPOT_CHECK: [...]}
  - default_tier
"""

from dataclasses import dataclass, field
from enum import Enum


class RoutingTier(Enum):
    AUTO = "auto"
    SPOT_CHECK = "spot_check"
    GATE = "gate"
    HOLD = "hold"


@dataclass
class Determination:
    disposition: str
    routing_tier: RoutingTier
    confidence: float = 1.0
    secondary_grounds: list = field(default_factory=list)
    primary_reasoning: str = ""
    routing_reasons: list = field(default_factory=list)
    trace: dict = field(default_factory=dict)
    tree_version: str = ""

    @property
    def is_tentative(self) -> bool:
        return self.routing_tier in (RoutingTier.GATE, RoutingTier.HOLD)


# =============================================================================
# Predicate evaluation
# =============================================================================

def evaluate_predicate(predicate, node_id, trace, tree):
    """Evaluate a `when` predicate against the trace. The predicate
    applies to the node whose disposition_role contains it.

    Same-level keys are conjunctive — all must match. Use explicit
    `and:`/`or:` for more complex compositions.
    """
    if not isinstance(predicate, dict):
        return False
    if "and" in predicate:
        return all(evaluate_predicate(p, node_id, trace, tree)
                   for p in predicate["and"])
    if "or" in predicate:
        return any(evaluate_predicate(p, node_id, trace, tree)
                   for p in predicate["or"])
    if "not" in predicate:
        return not evaluate_predicate(predicate["not"], node_id, trace, tree)

    result = trace.get(node_id)
    if result is None:
        return False

    # All keys at this level must match (conjunctive).
    checks = []
    if "apparently_true" in predicate and predicate["apparently_true"]:
        checks.append(_apparently_true(node_id, trace, tree))
    if "value" in predicate:
        checks.append(result.value == predicate["value"])
    if "value_in" in predicate:
        checks.append(result.value in predicate["value_in"])
    if "min_confidence" in predicate:
        checks.append(result.confidence >= predicate["min_confidence"])
    if "max_confidence" in predicate:
        checks.append(result.confidence <= predicate["max_confidence"])
    if "escalated" in predicate:
        checks.append(result.escalation_flag == predicate["escalated"])
    if "short_circuited" in predicate:
        checks.append(result.short_circuited == predicate["short_circuited"])
    if not checks:
        return False
    return all(checks)


def _apparently_true(node_id, trace, tree):
    """True if node.value is True OR escalated (None) with no descendant
    hard False. Captures 'apparently met pending interpretive judgment'."""
    result = trace.get(node_id)
    if result is None:
        return False
    if result.value is True:
        return True
    if result.value is False:
        return False
    node = tree.get(node_id, {})
    for child_id in node.get("children", []):
        child_result = trace.get(child_id)
        if child_result is None or child_result.short_circuited:
            continue
        if child_result.value is False and not child_result.escalation_flag:
            return False
        child_node = tree.get(child_id, {})
        if (child_node.get("type") == "compose"
                and child_result.value is None):
            if not _apparently_true(child_id, trace, tree):
                return False
    return True


def render_reasoning(template, node_result):
    if not template:
        return ""
    text = template
    if node_result is not None:
        text = text.replace("{reasoning}",
                            str(getattr(node_result, "reasoning", "")))
        text = text.replace("{value}",
                            str(getattr(node_result, "value", "")))
        text = text.replace("{confidence}",
                            f"{getattr(node_result, 'confidence', 0):.2f}")
    return text


# =============================================================================
# Critical-leaf resolution
# =============================================================================

def _descendant_char_leaves(root_id, tree):
    node = tree.get(root_id, {})
    if node.get("type") == "char":
        yield root_id
        return
    for child_id in node.get("children", []):
        yield from _descendant_char_leaves(child_id, tree)


def resolve_critical_leaves(spec, node_id, tree):
    if spec is None:
        return set()
    critical = set()
    if spec.get("include_self"):
        critical.add(node_id)
    if spec.get("self_descendants"):
        critical.update(_descendant_char_leaves(node_id, tree))
    for nid in spec.get("include", []):
        critical.update(_descendant_char_leaves(nid, tree))
    for nid in spec.get("exclude_descendants_of", []):
        critical -= set(_descendant_char_leaves(nid, tree))
    return critical


# =============================================================================
# Router
# =============================================================================

class DispositionRouter:
    """Reads disposition rules from tree node annotations and routing
    rules from tree_metadata."""

    def __init__(self, tree, tree_metadata):
        self.tree = tree
        self.tree_metadata = tree_metadata

    def derive_determination(self, trace, tree_version=""):
        missing = self._required_evaluations_missing(trace)
        if missing:
            return Determination(
                disposition=self.tree_metadata.get(
                    "indeterminate_disposition", "indeterminate"),
                routing_tier=RoutingTier.HOLD,
                confidence=0.0,
                primary_reasoning=(
                    f"Required evaluations could not be completed: "
                    f"{', '.join(missing)}"
                ),
                routing_reasons=[{
                    "signal": "indeterminate",
                    "description": "Required evaluations missing",
                }],
                trace=trace,
                tree_version=tree_version,
            )

        primary, secondary, reasoning, winning_node_id = (
            self._apply_disposition_rules(trace))

        routing_tier, routing_reasons = self._apply_routing_rules(
            trace, primary, winning_node_id)

        nonzero = [r.confidence for r in trace.values()
                   if not r.short_circuited and r.confidence > 0]
        overall_conf = min(nonzero) if nonzero else 0.0

        return Determination(
            disposition=primary,
            routing_tier=routing_tier,
            confidence=overall_conf,
            secondary_grounds=secondary,
            primary_reasoning=reasoning,
            routing_reasons=routing_reasons,
            trace=trace,
            tree_version=tree_version,
        )

    def _required_evaluations_missing(self, trace):
        required = self.tree_metadata.get("required_nodes", [])
        missing = []
        for node_id in required:
            r = trace.get(node_id)
            if r is None:
                missing.append(node_id)
            elif (r.value is None and not r.escalation_flag
                  and r.confidence == 0.0 and not r.short_circuited):
                missing.append(node_id)
        return missing

    def _collect_disposition_rules(self):
        rules = []
        for node_id, node in self.tree.items():
            role = node.get("disposition_role")
            if role:
                rules.append((node_id, role))
        rules.sort(key=lambda x: x[1].get("rank", 999))
        return rules

    def _apply_disposition_rules(self, trace):
        all_rules = self._collect_disposition_rules()
        fired_normal = []
        fired_fallback = []

        for node_id, role in all_rules:
            when = role.get("when", {})
            if not evaluate_predicate(when, node_id, trace, self.tree):
                continue
            reasoning = render_reasoning(
                role.get("reasoning_template", ""),
                trace.get(node_id),
            )
            entry = (node_id, role, reasoning)
            if role.get("fallback_only"):
                fired_fallback.append(entry)
            else:
                fired_normal.append(entry)

        if fired_normal:
            wid, role, rsn = fired_normal[0]
            primary = role["produces"]
            secondary = [e[1]["produces"] for e in fired_normal[1:]]
            for fb in fired_fallback:
                fbd = fb[1]["produces"]
                if fbd not in secondary and fbd != primary:
                    secondary.append(fbd)
            return primary, secondary, rsn, wid

        if fired_fallback:
            wid, role, rsn = fired_fallback[0]
            primary = role["produces"]
            secondary = [e[1]["produces"] for e in fired_fallback[1:]]
            return primary, secondary, rsn, wid

        default = self.tree_metadata.get("default_disposition", "uphold")
        default_rsn = self.tree_metadata.get("default_reasoning",
                                              "No overturn grounds apply.")
        return default, [], default_rsn, None

    def _apply_routing_rules(self, trace, disposition, winning_node_id):
        # Critical leaves
        if winning_node_id is not None:
            role = self.tree.get(winning_node_id, {}).get(
                "disposition_role", {})
            critical_leaves = resolve_critical_leaves(
                role.get("critical_leaves"),
                winning_node_id, self.tree)
        else:
            spec = self.tree_metadata.get("default_critical_leaves")
            critical_leaves = (resolve_critical_leaves(spec, "", self.tree)
                               if spec else set())

        sig_severity = self.tree_metadata.get("signal_severity", {})

        hc, hp, gc, gp = [], [], [], []

        for node_id, result in trace.items():
            if result.short_circuited:
                continue
            node_spec = self.tree.get(node_id, {})
            if node_spec.get("type") != "char":
                continue
            is_crit = node_id in critical_leaves
            sigs = result.escalation_signals

            for sig_name in ["contradictory_facts",
                             "requires_institutional_judgment",
                             "insufficient_facts", "contested_reading",
                             "low_confidence_in_value"]:
                if not getattr(sigs, sig_name, False):
                    continue
                override = f"{sig_name}_on_critical"
                severity = (sig_severity.get(override)
                            if is_crit and override in sig_severity
                            else sig_severity.get(sig_name, "gate"))
                entry = (sig_name, node_id, result)
                if severity == "hold":
                    (hc if is_crit else hp).append(entry)
                elif severity == "gate":
                    (gc if is_crit else gp).append(entry)

        ctx = {
            "hold_on_critical": len(hc),
            "hold_on_peripheral": len(hp),
            "hold_total": len(hc) + len(hp),
            "gate_on_critical": len(gc),
            "gate_on_peripheral": len(gp),
            "gate_total": len(gc) + len(gp),
        }
        tier_rules = self.tree_metadata.get("tier_rules", {})

        def to_reason(e):
            sig, node_id, result = e
            return {
                "signal": sig,
                "node_id": node_id,
                "policy_ref": self.tree.get(node_id, {}).get(
                    "policy_ref", "unknown"),
                "reason": result.escalation_reason or "",
            }

        for tier_name in ["HOLD", "GATE", "SPOT_CHECK"]:
            for rule in tier_rules.get(tier_name, []):
                if self._eval_tier_rule(rule, ctx):
                    if tier_name == "HOLD":
                        entries = hc + hp
                    elif tier_name == "GATE":
                        entries = hp + gc + gp
                    else:
                        entries = gp
                    return RoutingTier[tier_name], [to_reason(e) for e in entries]

        return RoutingTier[self.tree_metadata.get("default_tier", "AUTO")], []

    def _eval_tier_rule(self, rule, ctx):
        if "and" in rule:
            return all(self._eval_tier_rule(r, ctx) for r in rule["and"])
        if "or" in rule:
            return any(self._eval_tier_rule(r, ctx) for r in rule["or"])
        f = rule.get("field")
        op = rule.get("op", ">=")
        t = rule.get("value", 1)
        if f not in ctx:
            return False
        v = ctx[f]
        if op == ">=": return v >= t
        if op == ">":  return v > t
        if op == "==": return v == t
        if op == "<=": return v <= t
        if op == "<":  return v < t
        return False

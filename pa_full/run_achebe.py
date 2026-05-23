"""
Live end-to-end run of the Bernard Achebe PA appeal case through the
PA framework.

Compares against Cognitive Core's output on the same case:
  - Cognitive Core disposition: UPHOLD, routing: GATE
  - Cognitive Core latency: 703.9 seconds
  - Cognitive Core trajectory: 18 primitives

This run produces:
  - PaDisposition (one of seven dispositions)
  - RoutingTier (AUTO/SPOT_CHECK/GATE/HOLD)
  - End-to-end latency
  - Full trace of leaf evaluations
"""

import os
import sys
import json
import time
from pathlib import Path

# Resolve paths relative to this script's location, so the bundle
# works wherever it's unzipped.
_HERE = Path(__file__).resolve().parent  # pa_full/
_REPO_ROOT = _HERE.parent                # parent of pa_full/
_DERIVE = _REPO_ROOT / "derive_design"

sys.path.insert(0, str(_DERIVE))
sys.path.insert(0, str(_HERE))

from characterize_impl import CharacterizeImpl, DEFAULT_MODEL
from case_loader import load_tree, load_case_facts
from generic_orchestrator import GenericOrchestrator

# Load tree and case from JSON
PA_APPEAL_TREE, TREE_METADATA = load_tree(_HERE / "pa_appeal_tree.json")
BERNARD_ACHEBE_FACTS = load_case_facts(_HERE / "cases" / "achebe.json")


def render_determination(det):
    """Format the PA determination output for human review."""
    print("=" * 78)
    print("PA APPEAL DETERMINATION")
    print("=" * 78)
    print(f"Disposition:        {det.disposition}")
    if det.is_tentative:
        print(f"                    (TENTATIVE — pending human review)")
    print(f"Routing tier:       {det.routing_tier.value}")
    print(f"Tree version:       {det.tree_version}")
    print(f"Overall confidence: {det.confidence:.3f}")
    print()
    print("Primary reasoning:")
    print(f"  {det.primary_reasoning}")
    if det.secondary_grounds:
        print()
        print("Secondary grounds for overturn (also apply):")
        for g in det.secondary_grounds:
            print(f"  - {g}")
    if det.routing_reasons:
        print()
        print(f"Routing triggered by {len(det.routing_reasons)} signal(s):")
        for r in det.routing_reasons:
            signal = r.get("signal", "?")
            node = r.get("node_id", "?")
            ref = r.get("policy_ref", "?")
            reason = r.get("reason", "")
            print(f"  [{signal}] {node} ({ref})")
            if reason:
                print(f"    {reason[:160]}{'...' if len(reason) > 160 else ''}")


_NODE_DEPTH_CACHE = {}

def _depth_of(node_id):
    if node_id in _NODE_DEPTH_CACHE:
        return _NODE_DEPTH_CACHE[node_id]
    if node_id == "root.acdf_appeal":
        _NODE_DEPTH_CACHE[node_id] = 0
        return 0
    for parent_id, node in PA_APPEAL_TREE.items():
        if node.get("type") == "compose":
            if node_id in node.get("children", []):
                depth = _depth_of(parent_id) + 1
                _NODE_DEPTH_CACHE[node_id] = depth
                return depth
    _NODE_DEPTH_CACHE[node_id] = 0
    return 0


def render_trace(det):
    print("=" * 78)
    print("TRACE")
    print("=" * 78)

    visited = set()
    order = []

    def walk(node_id):
        if node_id in visited:
            return
        visited.add(node_id)
        order.append(node_id)
        node = PA_APPEAL_TREE.get(node_id)
        if node and node.get("type") == "compose":
            for child_id in node.get("children", []):
                walk(child_id)

    walk("root.acdf_appeal")

    for node_id in order:
        if node_id not in det.trace:
            continue
        result = det.trace[node_id]
        prefix = "  " * _depth_of(node_id)

        if result.escalation_flag:
            marker = "↑"
        elif result.value is True:
            marker = "✓"
        elif result.value is False:
            marker = "✗"
        elif result.short_circuited:
            marker = "—"
        elif result.value is None:
            marker = "?"
        else:
            marker = "→"  # enumerated values

        line = f"{prefix}{marker} {node_id}"
        if result.value is not None:
            if isinstance(result.value, float):
                line += f" → {result.value:,.2f}"
            else:
                line += f" → {result.value}"
        if result.escalation_flag:
            line += " [ESCALATE]"
        if result.short_circuited:
            line += " [short-circuit]"
        if result.confidence > 0 and not result.short_circuited:
            line += f" (conf={result.confidence:.2f})"
        print(line)
        if result.reasoning and not result.short_circuited:
            r = result.reasoning[:140]
            if len(result.reasoning) > 140:
                r += "..."
            print(f"{prefix}   {r}")


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL

    print("=" * 78)
    print("BERNARD ACHEBE PA APPEAL — Full Pipeline")
    print("=" * 78)
    print(f"Case ID:    {BERNARD_ACHEBE_FACTS.case_id}")
    print(f"Procedure:  ACDF C5-C6 (CPT 22551)")
    print(f"Tree:       {TREE_METADATA['tree_id']} v{TREE_METADATA['version']}")
    print(f"Substrate:  {model}")
    print()
    print(f"Cognitive Core baseline: UPHOLD + GATE in 703.9 seconds")
    print(f"Expected ground truth:   GATE (FM-2 authority sycophancy test)")
    print()

    characterize = CharacterizeImpl(model=model)
    orchestrator = GenericOrchestrator(
        tree=PA_APPEAL_TREE,
        tree_metadata=TREE_METADATA,
        characterize_fn=characterize,
        escalation_threshold=0.7,
    )

    start = time.time()
    determination = orchestrator.derive(BERNARD_ACHEBE_FACTS)
    elapsed = time.time() - start

    render_determination(determination)
    print()
    render_trace(determination)
    print()
    print("=" * 78)
    print("RUN STATISTICS")
    print("=" * 78)
    summary = characterize.summary()
    print(f"Total wall-clock time:  {elapsed:.1f}s")
    print(f"Substrate calls:        {summary['total_calls']}")
    print(f"Total substrate time:   {summary['total_latency_ms'] / 1000:.1f}s")
    print(f"Avg latency per call:   {summary['avg_latency_ms']:.0f}ms")
    print(f"Errors:                 {summary['errors']}")
    print(f"Escalations:            {summary['escalations']}")
    print()
    print(f"Cost comparison vs Cognitive Core (703.9s):")
    print(f"  Speedup: {703.9 / elapsed:.1f}x")
    if elapsed < 100:
        print(f"  Result: well under Cognitive Core baseline")


if __name__ == "__main__":
    main()

"""
Inspect the latest kamau run artifact in detail.

Compares against the prior kamau trace shape (the one with 16-17 substrate
calls and gate tier) to identify what changed structurally — which leaves
were evaluated, which were escalated, which short-circuited, which had
clean values.

Usage: python3 inspect_kamau.py
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_RUNS = _HERE / "runs"


def main():
    # Find the latest kamau artifact
    kamau_files = sorted(_RUNS.glob("*kamau*.json"))
    if not kamau_files:
        print("No kamau artifacts found in runs/")
        sys.exit(1)

    latest = kamau_files[-1]
    print(f"Inspecting: {latest.name}")
    print("=" * 78)

    data = json.loads(latest.read_text())
    det = data["determination"]

    print(f"Disposition:      {det['disposition']}")
    print(f"Routing tier:     {det['routing_tier']}")
    print(f"Confidence:       {det['confidence']}")
    print(f"Tree version:     {data['tree_version']}")
    print(f"Substrate calls:  {data['run_stats']['substrate_calls']}")
    print(f"Wall clock:       {data['run_stats']['wall_clock_seconds']:.1f}s")
    print(f"Escalations:      {data['run_stats']['escalations']}")
    print()
    print("Primary reasoning:")
    print(f"  {det['primary_reasoning']}")
    print()
    if det["secondary_grounds"]:
        print("Secondary grounds:")
        for g in det["secondary_grounds"]:
            print(f"  - {g}")
        print()
    print("Routing signals:")
    if not det["routing_reasons"]:
        print("  (none)")
    else:
        for r in det["routing_reasons"]:
            print(f"  [{r.get('signal', '?')}] node={r.get('node_id', '?')} tier={r.get('tier', '?')} critical={r.get('critical', '?')}")
            if r.get("description"):
                print(f"     {r['description']}")
    print()

    # Walk the trace in tree order (root first, then children)
    # For inspection: just dump every trace entry with its full info
    print("=" * 78)
    print("FULL TRACE — every node the engine touched")
    print("=" * 78)
    print()

    # Categorize trace entries
    evaluated = []          # had a real value or escalation
    short_circuited = []    # marked sc=True
    other = []

    for nid, r in det["trace"].items():
        if r["short_circuited"]:
            short_circuited.append((nid, r))
        elif r["value"] is not None or r["escalation_flag"]:
            evaluated.append((nid, r))
        else:
            other.append((nid, r))

    print(f"Trace size: {len(det['trace'])} nodes total")
    print(f"  Evaluated (real value or escalation): {len(evaluated)}")
    print(f"  Short-circuited: {len(short_circuited)}")
    print(f"  Other: {len(other)}")
    print()

    # Show every evaluated node with its full reasoning
    print("--- EVALUATED NODES (in trace insertion order) ---")
    print()
    for nid, r in evaluated:
        if r["escalation_flag"]:
            marker = "↑ ESCALATED"
        elif r["value"] is True:
            marker = "✓ TRUE"
        elif r["value"] is False:
            marker = "✗ FALSE"
        elif isinstance(r["value"], str):
            marker = f"→ {r['value']}"
        else:
            marker = f"? {r['value']}"

        print(f"  {marker}   {nid}   (conf {r['confidence']:.2f})")
        if r.get("escalation_signals"):
            sigs = [k for k, v in r["escalation_signals"].items() if v]
            if sigs:
                print(f"    signals: {sigs}")
        if r.get("escalation_reason"):
            print(f"    escalation_reason: {r['escalation_reason']}")
        # Truncate long reasoning to keep output manageable
        reasoning = r.get("reasoning", "")
        if len(reasoning) > 300:
            reasoning = reasoning[:300] + "..."
        print(f"    reasoning: {reasoning}")
        if r.get("cited_facts"):
            cited = r["cited_facts"]
            if len(cited) > 5:
                cited = cited[:5] + [f"... +{len(r['cited_facts']) - 5} more"]
            print(f"    cited: {cited}")
        print()

    # Show short-circuited
    if short_circuited:
        print("--- SHORT-CIRCUITED NODES ---")
        print()
        for nid, r in short_circuited:
            print(f"  — {nid}: {r.get('reasoning', '')}")
        print()

    # Show "other" — typically the root and intermediate nodes whose value
    # is None without escalation (i.e. the root marker, or composes returning
    # via a special path)
    if other:
        print("--- OTHER NODES (no value, no escalation, not short-circuited) ---")
        print()
        for nid, r in other:
            print(f"  ? {nid}: value={r['value']}, conf={r['confidence']}")
            if r.get("reasoning"):
                print(f"    reasoning: {r['reasoning'][:200]}")
        print()


if __name__ == "__main__":
    main()

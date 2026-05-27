"""
run_connected_clusterer.py - apply the connected-component clusterer to
cap_room's tagging output and inspect the results.

For each OBLIGATION, find all units connected via adjacency, explicit
references, or term references. Compare against the previous
adjacency-only clusterer to see how much the singleton-OBLIGATION
problem is resolved.

No LLM cost. Pure graph traversal.

Usage:
    python bin/run_connected_clusterer.py
    python bin/run_connected_clusterer.py --anchor 37
    python bin/run_connected_clusterer.py --min-connections 3
"""
import argparse
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.build.clusterer import units_from_tagging_output
from rulekit.build.connected_clusterer import (
    build_section_contexts,
    find_connected_cluster,
    find_all_obligation_clusters,
    ADJACENCY,
    EXPLICIT_REFERENCE,
    TERM_REFERENCE,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tagging",
                   default="audits/tagging_stability/tagging_run1_consolidated.json")
    p.add_argument("--out",
                   default="audits/connected_clusters/clusters.json")
    p.add_argument("--anchor", type=int, default=None,
                   help="If set, show only the cluster for this anchor sentence_id")
    p.add_argument("--min-connections", type=int, default=0,
                   help="Only show clusters with at least this many connections")
    p.add_argument("--show-all", action="store_true",
                   help="Show all matching clusters (default: first 20)")
    args = p.parse_args()

    print(f"Loading {args.tagging}...")
    with open(args.tagging, encoding="utf-8") as f:
        tag_records = json.load(f)
    units = units_from_tagging_output(tag_records)
    print(f"  Loaded {len(units)} tagged units")
    print()

    # If --anchor is set, just show that one cluster in detail
    if args.anchor is not None:
        section_contexts = build_section_contexts(units)
        anchor = next((u for u in units if u.sentence_id == args.anchor), None)
        if anchor is None:
            print(f"No unit with sentence_id={args.anchor}")
            sys.exit(1)
        if anchor.tag != "OBLIGATION":
            print(f"WARNING: sentence {args.anchor} has tag {anchor.tag}, "
                  f"not OBLIGATION. Showing connected cluster anyway.")
        c = find_connected_cluster(anchor, units, section_contexts)
        print_cluster_detail(c)
        return

    # Otherwise compute all OBLIGATION clusters
    clusters = find_all_obligation_clusters(units)

    # Summary
    sizes = [c.n_units for c in clusters]
    connection_counts = [len(c.connections) for c in clusters]
    by_kind = Counter()
    for c in clusters:
        for k, v in c.by_kind().items():
            by_kind[k] += v

    print("=" * 70)
    print("CONNECTED-CLUSTERING SUMMARY")
    print("=" * 70)
    print(f"  Total OBLIGATION clusters: {len(clusters)}")
    print(f"  Cluster size (anchor + connections):")
    print(f"    min={min(sizes)}, max={max(sizes)}, "
          f"mean={sum(sizes)/len(sizes):.1f}")
    print(f"  Connections per cluster:")
    print(f"    min={min(connection_counts)}, max={max(connection_counts)}, "
          f"mean={sum(connection_counts)/len(connection_counts):.1f}")
    print(f"  Total connections by kind:")
    for k, v in by_kind.most_common():
        print(f"    {k}: {v}")
    print()

    # Distribution of cluster sizes
    print("Cluster-size distribution:")
    size_dist = Counter(sizes)
    for s in sorted(size_dist.keys()):
        bar = "#" * min(size_dist[s], 50)
        print(f"    {s:>3} units: {size_dist[s]:>3} clusters  {bar}")
    print()

    # Compare to adjacency-only: how many clusters now have connections
    # beyond just adjacency?
    cross_section_clusters = [
        c for c in clusters
        if any(conn.kind == EXPLICIT_REFERENCE for conn in c.connections)
    ]
    term_using_clusters = [
        c for c in clusters
        if any(conn.kind == TERM_REFERENCE for conn in c.connections)
    ]
    singleton_clusters = [c for c in clusters if c.n_units == 1]
    print(f"Clusters with cross-section connections: "
          f"{len(cross_section_clusters)} / {len(clusters)}")
    print(f"Clusters with term-reference connections: "
          f"{len(term_using_clusters)} / {len(clusters)}")
    print(f"Singleton clusters (anchor only): {len(singleton_clusters)}")
    print()

    # Show some clusters
    print("=" * 70)
    print("CLUSTERS")
    print("=" * 70)
    print()
    shown = 0
    for c in clusters:
        if len(c.connections) < args.min_connections:
            continue
        first = c.anchor.sentence_id
        last = max((u.sentence_id for u in c.all_units), default=first)
        print(f"  Anchor sid={first}, {c.n_units} units, "
              f"{len(c.connections)} connections "
              f"(by kind: {c.by_kind()})")
        print(f"    [{first}] {c.anchor.text[:80]}")
        # Show first 5 connections
        for conn in c.connections[:5]:
            print(f"    [{conn.unit.sentence_id:>3}] {conn.kind:<22} "
                  f"{conn.unit.tag:<10} {conn.unit.text[:55]}")
        if len(c.connections) > 5:
            print(f"    ... and {len(c.connections)-5} more connections")
        print()
        shown += 1
        if not args.show_all and shown >= 20:
            print(f"  ... showing first 20 of {len(clusters)} clusters")
            break

    # Save
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    cluster_data = []
    for c in clusters:
        cluster_data.append({
            "anchor": {
                "sentence_id": c.anchor.sentence_id,
                "tag": c.anchor.tag,
                "text": c.anchor.text,
            },
            "n_units": c.n_units,
            "connections": [
                {
                    "sentence_id": conn.unit.sentence_id,
                    "tag": conn.unit.tag,
                    "text": conn.unit.text,
                    "kind": conn.kind,
                    "evidence": conn.evidence,
                }
                for conn in c.connections
            ],
        })
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total_clusters": len(clusters),
                "cross_section_clusters": len(cross_section_clusters),
                "singleton_clusters": len(singleton_clusters),
                "by_kind_total": dict(by_kind),
            },
            "clusters": cluster_data,
        }, f, indent=2)
    print()
    print(f"Details saved to {args.out}")


def print_cluster_detail(c):
    """Verbose print of a single cluster."""
    print("=" * 70)
    print(f"CLUSTER: anchor sentence_id = {c.anchor.sentence_id}")
    print("=" * 70)
    print()
    print(f"Anchor tag: {c.anchor.tag}")
    print(f"Anchor text: {c.anchor.text}")
    print()
    print(f"Total units: {c.n_units}")
    print(f"Connections by kind: {c.by_kind()}")
    print()
    print(f"All connections:")
    print()
    for conn in c.connections:
        print(f"  [{conn.unit.sentence_id:>3}] {conn.kind}")
        print(f"        evidence: {conn.evidence}")
        print(f"        tag: {conn.unit.tag}")
        print(f"        text: {conn.unit.text[:100]}")
        print()


if __name__ == "__main__":
    main()

"""
run_phase2_clusterer.py - apply the Phase 2 clusterer to a Phase 1
tagging output and inspect the resulting clusters.

No LLM cost. Analytical only.

Usage:
    python bin/run_phase2_clusterer.py
    python bin/run_phase2_clusterer.py --tagging audits/tagging_stability/tagging_run1_consolidated.json
    python bin/run_phase2_clusterer.py --show-all
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.build.clusterer import (
    cluster,
    cluster_summary,
    units_from_tagging_output,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tagging",
                   default="audits/tagging_stability/tagging_run1_consolidated.json")
    p.add_argument("--out",
                   default="audits/phase2_clusters/clusters.json")
    p.add_argument("--show-all", action="store_true",
                   help="Show all clusters, not just first 30")
    p.add_argument("--min-size", type=int, default=0,
                   help="Only show clusters with at least this many units")
    args = p.parse_args()

    print(f"Loading tagging output from {args.tagging}...")
    with open(args.tagging, encoding="utf-8") as f:
        tag_records = json.load(f)
    print(f"  Loaded {len(tag_records)} tagged sentences")
    print()

    units = units_from_tagging_output(tag_records)
    clusters = cluster(units)
    summary = cluster_summary(clusters)

    print("=" * 70)
    print("CLUSTERING SUMMARY")
    print("=" * 70)
    print(f"  Total clusters: {summary['total_clusters']}")
    print(f"  By anchor kind: {summary['by_kind']}")
    print(f"  Cluster size: min={summary['size_min']}, "
          f"max={summary['size_max']}, "
          f"mean={summary['size_mean']:.1f}")
    print(f"  Singleton clusters (anchor only): {summary['singletons']}")
    print()

    # Show clusters
    print("=" * 70)
    print("CLUSTERS")
    print("=" * 70)
    print()

    shown = 0
    for c in clusters:
        if len(c.all_units) < args.min_size:
            continue
        first, last = c.span
        print(f"  {c.cluster_id}  [sentences {first}-{last}]  "
              f"{c.kind}, {len(c.all_units)} units")
        if c.section_context:
            print(f"    Section: {c.section_context[:70]}")
        # Show the anchor
        print(f"    ANCHOR  [{c.anchor.sentence_id:>3}] {c.anchor.text[:75]}")
        # Show supporting units (first 5)
        for u in c.supporting[:5]:
            print(f"    {u.tag:<10} [{u.sentence_id:>3}] {u.text[:75]}")
        if len(c.supporting) > 5:
            print(f"    ... and {len(c.supporting)-5} more supporting units")
        print()
        shown += 1
        if not args.show_all and shown >= 30:
            print(f"  ... showing first 30 of {len(clusters)} clusters. "
                  f"Use --show-all to see all.")
            break

    # Save the clusters as JSON
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    cluster_data = []
    for c in clusters:
        first, last = c.span
        cluster_data.append({
            "cluster_id": c.cluster_id,
            "kind": c.kind,
            "span": [first, last],
            "n_units": len(c.all_units),
            "section_context": c.section_context,
            "anchor": {
                "sentence_id": c.anchor.sentence_id,
                "tag": c.anchor.tag,
                "text": c.anchor.text,
                "confidence": c.anchor.confidence,
            },
            "supporting": [{
                "sentence_id": u.sentence_id,
                "tag": u.tag,
                "text": u.text,
                "confidence": u.confidence,
            } for u in c.supporting],
        })
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "summary": summary,
            "clusters": cluster_data,
        }, f, indent=2)
    print()
    print(f"Cluster details saved to {args.out}")
    print()

    # Heuristic coherence check: look for anti-patterns
    print("=" * 70)
    print("ANTI-PATTERN CHECKS")
    print("=" * 70)
    print()
    anomalies = []

    # 1. Very large clusters (>15 units may be over-grouping)
    too_large = [c for c in clusters if len(c.all_units) > 15]
    if too_large:
        anomalies.append(f"  Large clusters (>15 units): {len(too_large)}")
        for c in too_large[:3]:
            print(f"    {c.cluster_id} has {len(c.all_units)} units "
                  f"(sentences {c.span[0]}-{c.span[1]})")

    # 2. Singleton OBLIGATION clusters (no supporting units)
    obl_singletons = [c for c in clusters
                      if c.kind == "OBLIGATION" and len(c.supporting) == 0]
    if obl_singletons:
        anomalies.append(
            f"  Singleton OBLIGATIONs (no supporting units): {len(obl_singletons)}"
        )
        # An obligation with no qualifiers might be a real standalone rule,
        # or might indicate a missing CONDITION/THRESHOLD nearby

    # 3. Very small clusters that are not just definitions
    tiny = [c for c in clusters
            if c.kind == "OBLIGATION" and 0 < len(c.supporting) <= 1]
    if tiny:
        print(f"  Tiny OBLIGATION clusters (1 supporting unit): {len(tiny)}")

    if not anomalies:
        print("  No obvious anti-patterns. Cluster shapes look reasonable.")
    else:
        for a in anomalies:
            print(a)
    print()


if __name__ == "__main__":
    main()

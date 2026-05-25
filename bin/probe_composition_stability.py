"""
probe_composition_stability.py — given a small cluster of tagged
sentences, does the LLM produce stable engine-node structure across
independent runs?

Phase 1 (tagging) is empirically stable (~93% three-way agreement).
This probe tests Phase 2 (composition): given typed tagged units, can
the LLM produce a stable logical structure (AndNode/OrNode/LeqNode/
PlusNode/Leaf composition) that captures the cluster's adjudication
logic?

If stable across runs: compositional approach has end-to-end viability.
If unstable: the variance just moved downstream from monolithic decompose.

Usage:
    python bin/probe_composition_stability.py
    python bin/probe_composition_stability.py --n 3

Cost: ~$1-3 for three composition passes on a small cluster.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


# The cluster we're testing: §6(b) Salary Cap basic rule + the 7 Section 6
# exceptions it references. This is a known structure that all three
# unguided Build runs of cap_room agreed on at the top level: an OR over
# [direct_cap_check, exception_1, ..., exception_7].
#
# Pre-tagged units (we're isolating Phase 2 from Phase 1):
TAGGED_CLUSTER = [
    {
        "id": "u1",
        "tag": "OBLIGATION",
        "text": "A Team's Team Salary may not exceed the Salary Cap at any "
                "time unless the Team is using an Exception under Article "
                "VII Section 6.",
    },
    {
        "id": "u2",
        "tag": "REFERENCE",
        "text": "Exception §6(d): Bi-annual Exception.",
    },
    {
        "id": "u3",
        "tag": "REFERENCE",
        "text": "Exception §6(e): Non-Taxpayer Mid-Level Salary Exception.",
    },
    {
        "id": "u4",
        "tag": "REFERENCE",
        "text": "Exception §6(f): Taxpayer Mid-Level Salary Exception.",
    },
    {
        "id": "u5",
        "tag": "REFERENCE",
        "text": "Exception §6(g): Mid-Level Salary Exception for Room Teams.",
    },
    {
        "id": "u6",
        "tag": "REFERENCE",
        "text": "Exception §6(b): Veteran Free Agent Exception (Qualifying, "
                "Early Qualifying, or Non-Qualifying variants).",
    },
    {
        "id": "u7",
        "tag": "REFERENCE",
        "text": "Exception §6(c): Minimum Player Salary Exception.",
    },
    {
        "id": "u8",
        "tag": "REFERENCE",
        "text": "Exception §6(j): Traded Player Exception.",
    },
    {
        "id": "u9",
        "tag": "THRESHOLD",
        "text": "Salary Cap value (named constant: salary_cap).",
    },
]

# Available engine vocabulary the composer can use:
ENGINE_VOCAB = """
Engine vocabulary (typed nodes you may use in composition):

Boolean operators:
  AndNode(children=[...])         - all children must be TRUE
  OrNode(children=[...])          - at least one child must be TRUE
  NotNode(child=...)              - logical negation
  Leaf(atom_id=...)               - opaque Boolean atom, bound from case data

Comparison operators (produce Boolean from numerics):
  LeqNode(left=numeric, right=numeric)   - left <= right
  GeqNode(left=numeric, right=numeric)   - left >= right
  LtNode(left=numeric, right=numeric)    - left < right
  GtNode(left=numeric, right=numeric)    - left > right
  EqNode(left=numeric, right=numeric)    - left == right

Numeric operators:
  PlusNode(left=numeric, right=numeric)        - addition
  MinusNode(left=numeric, right=numeric)       - subtraction
  SumNode(children=[...])                      - variadic sum
  MaxNode(children=[...])                      - variadic max
  MinNode(children=[...])                      - variadic min

Numeric leaves:
  NumericLeaf(atom_id=...)        - case-data numeric value
  Constant(label=...)             - named policy constant from registry
"""

COMPOSITION_PROMPT = """You are composing tagged policy units into an engine-node
structure that captures the adjudication logic of a single obligation.

The cluster below contains:
  - One OBLIGATION (the rule itself)
  - Several REFERENCEs (exceptions referenced by the obligation)
  - One THRESHOLD (the numeric limit named by the obligation)

Your task: produce a JSON structure representing the engine-node tree
that captures when this obligation is SATISFIED or VIOLATED.

{engine_vocab}

OUTPUT INSTRUCTIONS:
Return a JSON object representing the root engine node. Each node has:
  - "node_type": one of the engine node types above
  - "label": short descriptive label
  - "children": list of child nodes (for And/Or/Sum/Max/Min)
  - "left", "right": child nodes (for binary operators)
  - "child": single child (for NotNode)
  - "atom_id": for Leaf and NumericLeaf
  - "constant_label": for Constant

The structure should answer "is this obligation satisfied?" — TRUE means
satisfied (no violation), FALSE means violated.

Account for every unit in the cluster. The OBLIGATION's logic determines
the top-level structure. The REFERENCEs become alternative paths or
exception branches. The THRESHOLD is referenced by comparison nodes.

Output ONLY the JSON object, no preamble.

CLUSTER (tagged units):
{cluster_json}
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--out-dir", default="audits/composition_stability")
    p.add_argument("--model", default="claude-opus-4-7")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    from rulekit.build.decomposer import LLMCaller

    cluster_json = json.dumps(TAGGED_CLUSTER, indent=2)
    prompt = COMPOSITION_PROMPT.format(
        engine_vocab=ENGINE_VOCAB,
        cluster_json=cluster_json,
    )

    llm = LLMCaller(model=args.model)

    print(f"Composition probe: §6(b) Salary Cap cluster")
    print(f"Cluster size: {len(TAGGED_CLUSTER)} tagged units")
    print(f"Model: {args.model}, runs: {args.n}")
    print()

    runs = []
    for i in range(args.n):
        print(f"=== Composition Run {i+1}/{args.n} ===")
        t0 = time.time()
        response = llm.call(f"compose_run_{i+1}", prompt)
        elapsed = time.time() - t0

        raw_path = os.path.join(args.out_dir, f"composition_run{i+1}_raw.json")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response)

        # Parse
        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
                cleaned = re.sub(r"\n```\s*$", "", cleaned)
            structure = json.loads(cleaned)
        except json.JSONDecodeError as e:
            print(f"  PARSE ERROR: {e}")
            # Try to extract any JSON object
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                try:
                    structure = json.loads(match.group(0))
                except Exception:
                    structure = None
            else:
                structure = None

        if structure is None:
            print(f"  Could not parse structure for run {i+1}")
            runs.append({"run": i+1, "structure": None, "elapsed_s": elapsed})
            continue

        # Quick structural summary
        def walk(node, depth=0, sig=None):
            if sig is None:
                sig = []
            if not isinstance(node, dict):
                return sig
            ntype = node.get("node_type", "?")
            label = node.get("label", "")
            sig.append((depth, ntype, label[:60]))
            for k in ("children",):
                v = node.get(k)
                if isinstance(v, list):
                    for c in v:
                        walk(c, depth+1, sig)
            for k in ("left", "right", "child"):
                v = node.get(k)
                if isinstance(v, dict):
                    walk(v, depth+1, sig)
            return sig

        sig = walk(structure)
        ntypes = Counter(t for (_, t, _) in sig)
        max_depth = max((d for (d, _, _) in sig), default=0)

        print(f"  Wall time: {elapsed:.1f}s")
        print(f"  Total nodes: {len(sig)}")
        print(f"  Max depth: {max_depth}")
        print(f"  Node-type counts: {dict(ntypes)}")
        print(f"  Root type: {structure.get('node_type', '?')}")
        if structure.get("node_type") in ("AndNode", "OrNode"):
            children = structure.get("children", [])
            print(f"  Root children: {len(children)}")
            for j, c in enumerate(children):
                if isinstance(c, dict):
                    print(f"    [{j}] {c.get('node_type', '?')}: {c.get('label', '')[:60]}")
        print()

        runs.append({
            "run": i + 1,
            "structure": structure,
            "elapsed_s": elapsed,
            "n_nodes": len(sig),
            "max_depth": max_depth,
            "node_type_counts": dict(ntypes),
            "root_type": structure.get("node_type"),
        })

    # === Stability analysis ===
    print("=" * 70)
    print("COMPOSITION STABILITY ANALYSIS")
    print("=" * 70)
    print()

    # Filter to runs that parsed
    valid_runs = [r for r in runs if r.get("structure") is not None]
    if len(valid_runs) < 2:
        print("Not enough valid runs to compare.")
        sys.exit(1)

    # 1. Root structure
    print("Root structure across runs:")
    for r in valid_runs:
        root = r["structure"]
        rtype = root.get("node_type", "?")
        nch = len(root.get("children", [])) if rtype in ("AndNode", "OrNode") else "n/a"
        print(f"  Run {r['run']}: {rtype} with {nch} children")
    print()

    # 2. Node-count comparison
    print("Node counts:")
    for r in valid_runs:
        print(f"  Run {r['run']}: {r['n_nodes']} nodes, max depth {r['max_depth']}")
    print()

    # 3. Operator distribution
    print("Operator usage across runs:")
    all_types = sorted({t for r in valid_runs for t in r["node_type_counts"]})
    print(f"  {'Operator':<20} " + " ".join(f"Run{r['run']:>2}" for r in valid_runs))
    for op in all_types:
        counts = [r["node_type_counts"].get(op, 0) for r in valid_runs]
        consistency = "stable" if len(set(counts)) == 1 else "VARIES"
        row = f"  {op:<20} " + " ".join(f"{c:>4}" for c in counts) + f"   ({consistency})"
        print(row)
    print()

    # 4. Children-set comparison (do the OR's children represent the same exceptions?)
    print("Top-level children labels (do they identify the same branches?):")
    for r in valid_runs:
        root = r["structure"]
        labels = []
        for c in root.get("children", []):
            if isinstance(c, dict):
                labels.append(c.get("label", "?")[:50])
        print(f"  Run {r['run']}: ({len(labels)} children)")
        for lbl in labels:
            print(f"    - {lbl}")
        print()

    # Save summary
    summary = {
        "cluster": TAGGED_CLUSTER,
        "model": args.model,
        "n_runs": args.n,
        "runs": [{k: v for k, v in r.items() if k != "structure"} for r in runs],
    }
    summary_path = os.path.join(args.out_dir, "composition_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Summary: {summary_path}")
    print()

    # Interpretation
    print("=" * 70)
    print("INTERPRETATION")
    print("=" * 70)

    # Stability heuristic: do all runs have the same root type, similar
    # node counts, and similar children-set sizes?
    root_types = {r["root_type"] for r in valid_runs}
    node_counts = [r["n_nodes"] for r in valid_runs]
    counts_range = max(node_counts) - min(node_counts) if node_counts else 0
    counts_mean = sum(node_counts) / len(node_counts)

    if len(root_types) == 1 and counts_range <= counts_mean * 0.3:
        print("HIGH STABILITY in composition.")
        print(f"All runs agree on root type ({list(root_types)[0]}).")
        print(f"Node counts within tight range: {node_counts}")
        print("Compositional approach has end-to-end viability.")
        print("Next step: validate on a more complex cluster (multi-determination)")
        print("or scale up to compose tagged units across full cap_room.")
    elif len(root_types) == 1:
        print("MODERATE STABILITY in composition.")
        print(f"Root structure agrees, but node counts vary: {node_counts}")
        print("Surface variation in how exception branches are unpacked.")
        print("Adjudication semantics may still be equivalent — worth checking.")
    else:
        print("LOW STABILITY in composition.")
        print(f"Root types disagree: {root_types}")
        print("The variance moved downstream from monolithic decompose.")
        print("Compositional approach with current prompt design does not")
        print("escape the variance problem.")


if __name__ == "__main__":
    main()

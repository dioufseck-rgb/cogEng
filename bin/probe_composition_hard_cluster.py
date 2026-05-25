"""
probe_composition_hard_cluster.py - test Phase 3 composition stability
on a structurally non-trivial cluster.

The previous composition probe used the §6(b) Salary Cap basic rule — a
simple OR over a primary obligation and named exceptions. It produced
100% structural identity across 3 runs.

This probe tests Higher Max Criteria, which has:
  - An OBLIGATION/THRESHOLD specifying max salary computation
  - Multiple CONDITIONs that gate eligibility for higher brackets
  - A table of THRESHOLDs that defines bracket percentages
  - Internal logical structure: IF criteria met THEN bracketed_pct × cap

This is the kind of structural complexity that monolithic decompose
would handle stochastically. If Phase 3 composition handles it stably,
the tag vocabulary is sufficient. If it diverges, tags need enrichment.

Usage:
    python bin/probe_composition_hard_cluster.py
    python bin/probe_composition_hard_cluster.py --n 3
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


# Higher Max Criteria cluster from Article II §7(a). Tags come directly
# from the chunked tagging run's consolidated output.
TAGGED_CLUSTER = [
    {
        "id": "u1",
        "tag": "OBLIGATION",
        "text": "(a) Notwithstanding any other provision of this Agreement, "
                "no Player Contract entered into during the term of this "
                "Agreement may provide for a Salary in the first Salary Cap "
                "Year covered by the Contract in excess of the Maximum "
                "Annual Salary for the player.",
    },
    {
        "id": "u2",
        "tag": "THRESHOLD",
        "text": "(i) for any player who has completed fewer than seven (7) "
                "Years of Service, the greater of (x) twenty-five percent "
                "(25%) of the Salary Cap in effect at the time the Contract "
                "is executed, or (y) one hundred five percent (105%) of the "
                "Salary in the last Salary Cap Year of the player's prior "
                "Contract.",
    },
    {
        "id": "u3",
        "tag": "CONDITION",
        "text": "(A) the player was named to the All-NBA first, second, or "
                "third team, or was named NBA Defensive Player of the Year, "
                "in the immediately preceding Season or in two of the three "
                "preceding Seasons.",
    },
    {
        "id": "u4",
        "tag": "CONDITION",
        "text": "(B) the player was named NBA MVP during one of the "
                "immediately preceding three Seasons.",
    },
    {
        "id": "u5",
        "tag": "THRESHOLD",
        "text": "Higher Max Criteria table: 27% of Salary Cap if All-NBA "
                "Second Team, 28% if All-NBA First Team, 30% if NBA MVP.",
    },
    {
        "id": "u6",
        "tag": "THRESHOLD",
        "text": "(ii) for any player who has completed at least seven (7) "
                "but fewer than ten (10) Years of Service, the greater of "
                "(x) thirty percent (30%) of the Salary Cap in effect at "
                "the time the Contract is executed, or (y) one hundred "
                "five percent (105%) of the Salary in the last Salary Cap "
                "Year of the player's prior Contract.",
    },
    {
        "id": "u7",
        "tag": "THRESHOLD",
        "text": "(iii) for any player who has completed ten (10) or more "
                "Years of Service, the greater of (x) thirty-five percent "
                "(35%) of the Salary Cap in effect at the time the Contract "
                "is executed, or (y) one hundred five percent (105%) of "
                "the Salary in the last Salary Cap Year of the player's "
                "prior Contract.",
    },
]

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
  TimesConstNode(left=numeric, constant=...)   - multiply by named constant
  SumNode(children=[...])                      - variadic sum
  MaxNode(children=[...])                      - variadic max
  MinNode(children=[...])                      - variadic min

Numeric leaves:
  NumericLeaf(atom_id=...)        - case-data numeric value (e.g.,
                                    first_year_salary, prior_contract_last_year_salary)
  Constant(label=...)             - named policy constant from registry
                                    (e.g., salary_cap)

Conditional numeric (selecting one value based on a Boolean condition):
  ConditionalNumericNode(condition=BooleanNode, if_true=numeric, if_false=numeric)
"""

COMPOSITION_PROMPT = """You are composing tagged policy units into an engine-node
structure that captures the adjudication logic of a single obligation.

The cluster below contains:
  - An OBLIGATION (the rule: no contract may exceed maximum annual salary)
  - Multiple THRESHOLDs (the maximum annual salary computation, which varies
    by years of service and may be boosted by Higher Max Criteria)
  - Multiple CONDITIONs (the Higher Max Criteria that gate the boost)

Your task: produce a JSON structure representing the engine-node tree
that captures when this obligation is SATISFIED (TRUE = within max salary)
or VIOLATED (FALSE = exceeds max salary).

The obligation is: first_year_salary <= maximum_annual_salary.
The maximum_annual_salary depends on:
  - Player's Years of Service (which bracket: <7, 7-9, or 10+)
  - Whether the player meets Higher Max Criteria (which boosts <7 bracket)
  - The greater of (bracket percentage × Salary Cap) or (105% × prior salary)

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
  - "condition", "if_true", "if_false": for ConditionalNumericNode

The structure should answer "is this obligation satisfied?" — TRUE means
satisfied (no violation), FALSE means violated.

Account for every unit in the cluster. Express the logical structure
of how YOS-bracket selection, Higher Max Criteria gating, and the
greater-of computation compose.

Output ONLY the JSON object, no preamble.

CLUSTER (tagged units):
{cluster_json}
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--out-dir", default="audits/composition_hard")
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

    print(f"Composition probe: Higher Max Criteria cluster (structurally complex)")
    print(f"Cluster size: {len(TAGGED_CLUSTER)} tagged units")
    print(f"Model: {args.model}, runs: {args.n}")
    print()

    runs = []
    for i in range(args.n):
        print(f"=== Composition Run {i+1}/{args.n} ===")
        t0 = time.time()
        response = llm.call(f"compose_hard_run_{i+1}", prompt)
        elapsed = time.time() - t0

        raw_path = os.path.join(args.out_dir, f"composition_run{i+1}_raw.json")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response)

        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
                cleaned = re.sub(r"\n```\s*$", "", cleaned)
            structure = json.loads(cleaned)
        except json.JSONDecodeError as e:
            print(f"  PARSE ERROR: {e}")
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
            for k in ("left", "right", "child", "condition", "if_true", "if_false"):
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
    print("COMPOSITION STABILITY ANALYSIS (HARD CLUSTER)")
    print("=" * 70)
    print()

    valid_runs = [r for r in runs if r.get("structure") is not None]
    if len(valid_runs) < 2:
        print("Not enough valid runs to compare.")
        sys.exit(1)

    # Root structure
    print("Root structure:")
    for r in valid_runs:
        print(f"  Run {r['run']}: {r['root_type']}, "
              f"{r['n_nodes']} nodes, depth {r['max_depth']}")
    print()

    # Operator usage
    print("Operator usage across runs:")
    all_types = sorted({t for r in valid_runs for t in r["node_type_counts"]})
    print(f"  {'Operator':<28} " + " ".join(f"Run{r['run']:>2}" for r in valid_runs))
    for op in all_types:
        counts = [r["node_type_counts"].get(op, 0) for r in valid_runs]
        consistency = "stable" if len(set(counts)) == 1 else "VARIES"
        row = f"  {op:<28} " + " ".join(f"{c:>4}" for c in counts) + f"   ({consistency})"
        print(row)
    print()

    # Walk and show each run's structure briefly
    print("Top-level structure summary per run:")
    for r in valid_runs:
        root = r["structure"]
        print(f"\n  Run {r['run']}: {root.get('node_type')}: {root.get('label', '')[:70]}")
        # Show children at depth 1 and 2
        def show(node, depth=0, max_depth=3, prefix="    "):
            if depth > max_depth:
                return
            ntype = node.get("node_type", "?")
            label = node.get("label", "")[:60]
            print(f"{prefix}{'  '*depth}{ntype}: {label}")
            for k in ("children",):
                v = node.get(k)
                if isinstance(v, list):
                    for c in v[:6]:
                        if isinstance(c, dict):
                            show(c, depth+1, max_depth, prefix)
                    if len(v) > 6:
                        print(f"{prefix}{'  '*(depth+1)}... +{len(v)-6} more")
            for k in ("left", "right", "child", "condition", "if_true", "if_false"):
                v = node.get(k)
                if isinstance(v, dict):
                    print(f"{prefix}{'  '*(depth+1)}[{k}]:")
                    show(v, depth+1, max_depth, prefix)
        show(root)
    print()

    # Save
    summary_path = os.path.join(args.out_dir, "hard_composition_summary.json")
    with open(summary_path, "w") as f:
        json.dump({
            "cluster": TAGGED_CLUSTER,
            "model": args.model,
            "n_runs": args.n,
            "runs": [{k: v for k, v in r.items() if k != "structure"} for r in runs],
            "structures": [r.get("structure") for r in runs],
        }, f, indent=2, default=str)
    print(f"Summary: {summary_path}")
    print()

    # Interpretation
    print("=" * 70)
    print("INTERPRETATION")
    print("=" * 70)
    root_types = {r["root_type"] for r in valid_runs}
    node_counts = [r["n_nodes"] for r in valid_runs]
    counts_range = max(node_counts) - min(node_counts) if node_counts else 0
    counts_mean = sum(node_counts) / len(node_counts)

    if len(root_types) == 1 and counts_range <= counts_mean * 0.2:
        print("HIGH STABILITY on hard cluster.")
        print(f"All runs agree on root type ({list(root_types)[0]}).")
        print(f"Node counts within tight range: {node_counts}")
        print("Tag vocabulary is sufficient for structurally complex clusters.")
        print("The compositional architecture has strong end-to-end traction.")
    elif len(root_types) == 1 and counts_range <= counts_mean * 0.5:
        print("MODERATE STABILITY on hard cluster.")
        print(f"Root structure agrees, but node counts vary moderately: {node_counts}")
        print("Surface variance in how internal logical relations are unpacked.")
        print("Worth checking: are the runs semantically equivalent partial orders,")
        print("or are they encoding different adjudication semantics?")
    else:
        print("LOWER STABILITY on hard cluster.")
        print(f"Root types: {root_types}")
        print(f"Node counts: {node_counts} (range {counts_range}, mean {counts_mean:.0f})")
        print("Tag vocabulary appears insufficient to constrain composition on")
        print("non-trivial structural relations. Phase 3 falls back on")
        print("stochastic interpretation when tags don't fully specify connectives.")
        print("Refinement needed: enriched tag vocabulary or explicit structural")
        print("annotation phase between tagging and composition.")


if __name__ == "__main__":
    main()

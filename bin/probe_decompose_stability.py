"""
probe_decompose_stability.py — measure how stable the Build decomposer is
across repeated runs of the same determination with the same prompt.

The goal is foundational: how much does Build's output vary between runs?
The architecture has been treating Build as if its outputs are deterministic.
If decompose is highly stable, that assumption holds and single-Build artifacts
are meaningful. If decompose is unstable, we need to either (a) reduce variance
or (b) embrace ensembling.

Method:
  - Load the BuildSpec from domains/nba/cba.yaml
  - Restrict to a single determination (default: nba.sign_and_trade)
  - Run Build N times, each into a separate state_dir to ensure independence
  - For each run, dump the determination's tree to a text file
  - Compare trees: do operators match? do node counts match? do specific
    rules (e.g., First Apron threshold check) appear consistently?

Usage:
    python bin/probe_decompose_stability.py
    python bin/probe_decompose_stability.py --det nba.sign_and_trade --n 3
    python bin/probe_decompose_stability.py --det nba.cap_room --n 5

Cost: ~$2-5 per run × N runs. Default N=3 ≈ $6-15.
"""
import argparse
import os
import pickle
import shutil
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


def tree_signature(node, depth=0):
    """Walk a tree and return a list of (depth, node_type, label) tuples.
    Used to compare structural shape between runs."""
    sig = []
    name = type(node).__name__
    label = ""
    for attr in ("surface_label", "atom_id"):
        v = getattr(node, attr, None)
        if v:
            label = str(v)
            break
    sig.append((depth, name, label[:80]))
    if hasattr(node, "children") and isinstance(node.children, list):
        for c in node.children:
            sig.extend(tree_signature(c, depth + 1))
    for attr in ("left", "right", "child", "tree"):
        if hasattr(node, attr):
            child = getattr(node, attr)
            if child is not None and not isinstance(child, (str, int, float)):
                sig.extend(tree_signature(child, depth + 1))
    return sig


def operator_counts(node):
    """Count occurrences of each operator type in the tree."""
    counts = {}
    sig = tree_signature(node)
    for (_, name, _) in sig:
        counts[name] = counts.get(name, 0) + 1
    return counts


def find_phrases(node, phrases):
    """Find which target phrases appear anywhere in the tree's labels.
    Returns dict {phrase: [list of (node_type, label) where it appeared]}."""
    found = {p: [] for p in phrases}
    for (_, name, label) in tree_signature(node):
        for p in phrases:
            if p.lower() in label.lower():
                found[p].append((name, label))
    return found


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--det", default="nba.sign_and_trade",
                   help="Determination to probe stability of")
    p.add_argument("--n", type=int, default=3,
                   help="Number of independent Build runs")
    p.add_argument("--spec", default="domains/nba/cba.yaml")
    p.add_argument("--out-dir", default="audits/decompose_stability")
    p.add_argument("--model", default="claude-opus-4-7",
                   help="LLM model. Try 'claude-sonnet-4-6' for less-reflective comparison.")
    p.add_argument("--phrases", nargs="*",
                   default=["First Apron", "Second Apron", "hard cap",
                            "acquiring", "assignee", "post-signing",
                            "Bird", "Salary Cap"],
                   help="Phrases to search for across runs (case-insensitive)")
    args = p.parse_args()

    from rulekit.build.decomposer import (
        build_from_spec, load_spec_from_yaml, LLMCaller
    )
    from domains.voices import VOICES

    os.makedirs(args.out_dir, exist_ok=True)

    spec = load_spec_from_yaml(args.spec, voices_registry=VOICES)
    llm_caller = LLMCaller(model=args.model)

    # Restrict to one determination
    spec.determinations = [
        d for d in spec.determinations if d.id == args.det
    ]
    if not spec.determinations:
        print(f"ERROR: determination {args.det} not found in {args.spec}")
        sys.exit(1)

    print(f"Probing stability of {args.det} over {args.n} independent runs.")
    print(f"Model: {args.model}")
    print(f"Spec: {args.spec}")
    print(f"Output: {args.out_dir}")
    print()

    runs = []
    for i in range(args.n):
        run_label = f"run{i+1}"
        state_dir = os.path.join(args.out_dir, f"state_{run_label}")
        out_pkl = os.path.join(args.out_dir, f"built_{run_label}.pkl")

        # Ensure clean state for this run
        if os.path.exists(state_dir):
            shutil.rmtree(state_dir)

        print(f"=== Run {i+1}/{args.n} ===")
        t0 = time.time()
        result = build_from_spec(
            spec=spec,
            llm=llm_caller,
            refine=False,
            state_dir=state_dir,
        )
        t1 = time.time()
        det_tree = result.determinations[args.det]
        with open(out_pkl, "wb") as f:
            pickle.dump(result, f)

        elapsed = t1 - t0
        counts = operator_counts(det_tree)
        sig = tree_signature(det_tree)
        n_nodes = len(sig)
        n_atoms = len(result.atoms)
        phrases_found = find_phrases(det_tree, args.phrases)

        print(f"  Wall time: {elapsed:.1f}s")
        print(f"  Total nodes: {n_nodes}, total atoms: {n_atoms}")
        print(f"  Operator counts: {counts}")
        print(f"  Target phrase presence:")
        for ph, hits in phrases_found.items():
            print(f"    '{ph}': {len(hits)} hits")
        print()

        runs.append({
            "run": i + 1,
            "elapsed_s": elapsed,
            "n_nodes": n_nodes,
            "n_atoms": n_atoms,
            "operator_counts": counts,
            "tree_signature": sig,
            "phrases_found": {ph: hits for ph, hits in phrases_found.items()},
        })

    # === Comparison ===
    print("=" * 70)
    print("STABILITY ANALYSIS")
    print("=" * 70)
    print()
    print(f"Determination: {args.det}")
    print(f"Runs: {args.n}")
    print()

    print("Node counts across runs:")
    for r in runs:
        print(f"  Run {r['run']}: {r['n_nodes']} nodes, {r['n_atoms']} atoms")
    print()

    print("Operator usage across runs:")
    all_ops = sorted({op for r in runs for op in r["operator_counts"]})
    print(f"  {'Operator':<20} " + " ".join(f"Run{r['run']:>2}" for r in runs))
    for op in all_ops:
        counts_per_run = [r["operator_counts"].get(op, 0) for r in runs]
        # Only print rows where there's variance OR the operator is one of
        # the new arithmetic ones we care about
        new_ops = {"PlusNode", "MinusNode", "MulNode", "SumNode",
                   "MaxNode", "MinNode", "LeqNode", "GeqNode"}
        if op in new_ops or len(set(counts_per_run)) > 1:
            row = f"  {op:<20} " + " ".join(f"{c:>4}" for c in counts_per_run)
            print(row)
    print()

    print("Phrase presence across runs (target rule indicators):")
    for ph in args.phrases:
        presence = [len(r["phrases_found"][ph]) > 0 for r in runs]
        bits = " ".join("YES" if p else " .  " for p in presence)
        consistency = "stable" if len(set(presence)) == 1 else "VARIES"
        print(f"  {ph:<25} {bits}    ({consistency})")
    print()

    # Tree-shape comparison
    print("Tree-shape similarity:")
    sigs = [tuple(r["tree_signature"]) for r in runs]
    unique = set(sigs)
    print(f"  Unique tree shapes: {len(unique)} / {len(runs)}")
    if len(unique) == 1:
        print("  -> All runs produced structurally identical trees.")
    else:
        print("  -> Tree shape varies across runs.")
        # Show where they diverge - just the operator-only signature
        for i, sig in enumerate(sigs):
            ops_only = [name for (_, name, _) in sig
                        if name not in ("Leaf", "NumericLeaf", "Constant")]
            print(f"  Run {i+1} operator sequence: {' '.join(ops_only)[:120]}")

    # Save summary JSON
    import json
    summary_path = os.path.join(args.out_dir, "stability_summary.json")
    with open(summary_path, "w") as f:
        # Strip tree_signature for JSON brevity (it's huge); keep counts and phrases
        serializable = []
        for r in runs:
            r_copy = {k: v for k, v in r.items() if k != "tree_signature"}
            r_copy["unique_node_types"] = sorted(
                {name for (_, name, _) in r["tree_signature"]}
            )
            serializable.append(r_copy)
        json.dump({
            "determination": args.det,
            "n_runs": args.n,
            "runs": serializable,
            "unique_tree_shapes": len(unique),
        }, f, indent=2, default=str)
    print()
    print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    main()

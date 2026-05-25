"""
probe_translation_framing.py - test whether reframing decompose as
translation reduces variance.

Method:
  - Monkey-patch the DECOMPOSE_PROMPT to add a translation-framing
    preamble that emphasizes fidelity to the source policy
  - Run cap_room three times with the new prompt
  - Compare to baseline variance (Opus 4.7 runs we already have)

The translation framing makes three things explicit:
  1. The operation is translation, not decomposition
  2. The fidelity standard is preservation of all operative claims
  3. The decomposer should refuse to add OR drop content silently

Usage:
    python bin/probe_translation_framing.py
    python bin/probe_translation_framing.py --det nba.sign_and_trade --n 3

Cost: ~$10-15 for cap_room x 3 runs.
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


# Translation-framing preamble. This will be prepended to the existing
# DECOMPOSE_PROMPT, and it explicitly reframes the operation.
TRANSLATION_PREAMBLE = """TRANSLATION FRAMING (READ FIRST)
================================

You are performing a TRANSLATION task. The source language is the English
of the policy writer. The target language is a typed expression tree
(AndNode, OrNode, NotNode, AtLeastNode over claim leaves).

Treat this as legal translation, not as creative summarization. Apply
these fidelity standards:

1. PRESERVE every operative claim in the source policy text. If the
   source states a threshold, condition, exception, or numeric limit,
   your translation must include it. If the source enumerates branches,
   your translation must enumerate them.

2. RENDER ONLY what the source states. Do not infer claims the source
   does not make. Do not add operative content from domain knowledge.
   Do not skip operative content because it seems redundant or implicit.

3. MARK ambiguity faithfully. If the source supports multiple readings,
   produce multiple branches rather than collapsing to one. Translation
   should preserve the source's ambiguity structure.

4. RENDER logical connectives explicitly. "And", "or", "unless", "except",
   "provided that", "subject to" — each maps to specific target-language
   structure. Render them, don't paraphrase them away.

5. WHEN you encounter a cross-reference or named exception, treat it as
   an opaque leaf unless the referenced content is in the visible policy
   text. Do not silently expand or skip cross-references.

A translation is incomplete if it omits operative content from the
source. A translation is incorrect if it adds content not in the source.

Now proceed with the decomposition task as described below, applying
these translation standards throughout.

================================
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--det", default="nba.cap_room")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--spec", default="domains/nba/cba.yaml")
    p.add_argument("--out-dir", default="audits/translation_framing")
    p.add_argument("--model", default="claude-opus-4-7")
    p.add_argument("--phrases", nargs="*",
                   default=["First Apron", "Second Apron", "hard cap",
                            "acquiring", "assignee", "post-signing",
                            "Bird", "Salary Cap"])
    args = p.parse_args()

    # Monkey-patch the DECOMPOSE_PROMPT before importing build_from_spec
    from rulekit.build import decomposer
    original_prompt = decomposer.DECOMPOSE_PROMPT
    decomposer.DECOMPOSE_PROMPT = TRANSLATION_PREAMBLE + original_prompt
    print("Monkey-patched DECOMPOSE_PROMPT with translation preamble.")
    print(f"Prompt length: {len(original_prompt)} -> {len(decomposer.DECOMPOSE_PROMPT)}")
    print()

    from rulekit.build.decomposer import (
        build_from_spec, load_spec_from_yaml, LLMCaller
    )
    from domains.voices import VOICES

    os.makedirs(args.out_dir, exist_ok=True)

    spec = load_spec_from_yaml(args.spec, voices_registry=VOICES)
    spec.determinations = [d for d in spec.determinations if d.id == args.det]
    if not spec.determinations:
        print(f"ERROR: determination {args.det} not found")
        sys.exit(1)

    llm_caller = LLMCaller(model=args.model)

    print(f"Probing translation-framed decompose of {args.det}")
    print(f"Model: {args.model}, runs: {args.n}")
    print()

    # Walk function for analysis
    def tree_signature(node, depth=0):
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
        counts = {}
        for (_, name, _) in tree_signature(node):
            counts[name] = counts.get(name, 0) + 1
        return counts

    def find_phrases(node, phrases):
        found = {p: [] for p in phrases}
        for (_, name, label) in tree_signature(node):
            for p in phrases:
                if p.lower() in label.lower():
                    found[p].append((name, label))
        return found

    runs = []
    for i in range(args.n):
        run_label = f"run{i+1}"
        state_dir = os.path.join(args.out_dir, f"state_{run_label}")
        out_pkl = os.path.join(args.out_dir, f"built_{run_label}.pkl")
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

        counts = operator_counts(det_tree)
        sig = tree_signature(det_tree)
        n_nodes = len(sig)
        n_atoms = len(result.atoms)
        phrases_found = find_phrases(det_tree, args.phrases)

        print(f"  Wall time: {t1-t0:.1f}s")
        print(f"  Total nodes: {n_nodes}, atoms: {n_atoms}")
        print(f"  Operator counts: {counts}")
        print(f"  Target phrase presence:")
        for ph, hits in phrases_found.items():
            print(f"    '{ph}': {len(hits)} hits")
        print()

        runs.append({
            "run": i + 1,
            "elapsed_s": t1 - t0,
            "n_nodes": n_nodes,
            "n_atoms": n_atoms,
            "operator_counts": counts,
            "tree_signature": sig,
            "phrases_found": {ph: hits for ph, hits in phrases_found.items()},
        })

    print("=" * 70)
    print("TRANSLATION-FRAMING STABILITY ANALYSIS")
    print("=" * 70)
    print(f"\nDetermination: {args.det}\nModel: {args.model}\nRuns: {args.n}")
    print()
    print("Node counts:")
    for r in runs:
        print(f"  Run {r['run']}: {r['n_nodes']} nodes, {r['n_atoms']} atoms, {r['elapsed_s']:.0f}s")
    print()
    print("Operator usage across runs:")
    all_ops = sorted({op for r in runs for op in r["operator_counts"]})
    print(f"  {'Operator':<20} " + " ".join(f"Run{r['run']:>2}" for r in runs))
    for op in all_ops:
        counts_per_run = [r["operator_counts"].get(op, 0) for r in runs]
        if len(set(counts_per_run)) > 1 or op in {
            "PlusNode", "MinusNode", "MulNode", "SumNode",
            "MaxNode", "MinNode", "LeqNode", "GeqNode"
        }:
            row = f"  {op:<20} " + " ".join(f"{c:>4}" for c in counts_per_run)
            print(row)
    print()
    print("Phrase presence (target rule indicators):")
    for ph in args.phrases:
        presence = [len(r["phrases_found"][ph]) > 0 for r in runs]
        bits = " ".join("YES" if p else " .  " for p in presence)
        consistency = "stable" if len(set(presence)) == 1 else "VARIES"
        print(f"  {ph:<25} {bits}    ({consistency})")
    print()
    sigs = [tuple(r["tree_signature"]) for r in runs]
    unique = set(sigs)
    print(f"Unique tree shapes: {len(unique)} / {len(runs)}")
    if len(unique) == 1:
        print("  -> All runs produced structurally identical trees.")
    else:
        print("  -> Tree shape varies across runs.")

    # Comparison to baseline (if available)
    baseline_path = "audits/decompose_stability/stability_summary.json"
    if os.path.exists(baseline_path):
        import json
        with open(baseline_path) as f:
            baseline = json.load(f)
        if baseline.get("determination") == args.det:
            print()
            print("=" * 70)
            print(f"COMPARISON TO BASELINE (no translation framing)")
            print("=" * 70)
            print(f"Baseline runs: {baseline['n_runs']}, unique shapes: {baseline['unique_tree_shapes']}")
            print(f"Baseline node counts:")
            for r in baseline.get("runs", []):
                print(f"  Run {r['run']}: {r['n_nodes']} nodes, {r['n_atoms']} atoms")
            print(f"Translation-framed unique shapes: {len(unique)}")
            print(f"Translation-framed node counts:")
            for r in runs:
                print(f"  Run {r['run']}: {r['n_nodes']} nodes, {r['n_atoms']} atoms")

    # Save summary
    import json
    summary_path = os.path.join(args.out_dir, "translation_summary.json")
    with open(summary_path, "w") as f:
        serializable = []
        for r in runs:
            r_copy = {k: v for k, v in r.items() if k != "tree_signature"}
            r_copy["unique_node_types"] = sorted(
                {name for (_, name, _) in r["tree_signature"]}
            )
            serializable.append(r_copy)
        json.dump({
            "determination": args.det,
            "model": args.model,
            "framing": "translation_preamble",
            "n_runs": args.n,
            "runs": serializable,
            "unique_tree_shapes": len(unique),
        }, f, indent=2, default=str)
    print(f"\nSummary: {summary_path}")


if __name__ == "__main__":
    main()

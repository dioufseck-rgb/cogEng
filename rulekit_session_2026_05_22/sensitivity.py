"""
sensitivity.py — degradation curve analysis.

Given a Level 0 bundle (every atom assigned a concrete TRUE or FALSE that
produces the expected determination), this tool systematically probes:
which individual atoms, when dropped to UNDETERMINED, change the
determination's outcome?

This identifies the load-bearing atoms — the ones the institution must
reliably collect evidence for, vs. atoms that are robustness margin.

Two modes:

  single — drop each atom individually, see which moves the outcome
  cumulative — drop atoms in order of "least impactful first," tracking
               how many atoms can go UNDETERMINED before the outcome
               degrades

Usage:
    python sensitivity.py BUILD_PKL BUNDLE_JSON [--determination ID] [--mode single]
"""

import sys
import os
import json
import pickle
import argparse
from collections import OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rulekit.engine import Kleene, FactBundle
from eval_bundle import parse_kleene, load_bundle_file, construct_fact_bundle


def evaluate(build, det_id, bundle):
    det = build.determinations[det_id]
    outcome, _trace = det.evaluate(bundle)
    return outcome


def single_atom_sensitivity(build, det_id, baseline_bundle: FactBundle,
                            baseline_outcome: Kleene) -> dict:
    """
    For each atom, drop its value to UNDETERMINED and re-evaluate.
    Returns a dict mapping atom_id → outcome with that atom undetermined.
    Atoms whose outcome differs from baseline are load-bearing for this det.
    """
    results = {}
    for atom_id in sorted(baseline_bundle.values.keys()):
        original = baseline_bundle.values[atom_id]
        if original == Kleene.UNDETERMINED:
            results[atom_id] = {
                "original": str(original),
                "outcome_with_undetermined": str(baseline_outcome),
                "changed": False,
                "skipped": "already undetermined in baseline",
            }
            continue

        # Probe: set this atom to UNDETERMINED, re-eval
        new_values = dict(baseline_bundle.values)
        new_values[atom_id] = Kleene.UNDETERMINED
        probe_bundle = FactBundle(values=new_values)
        new_outcome = evaluate(build, det_id, probe_bundle)
        changed = (new_outcome != baseline_outcome)
        results[atom_id] = {
            "original": str(original),
            "outcome_with_undetermined": str(new_outcome),
            "changed": changed,
        }
    return results


def cumulative_sensitivity(build, det_id, baseline_bundle: FactBundle,
                           baseline_outcome: Kleene, single_results: dict) -> list:
    """
    Drop atoms one by one in order of "non-load-bearing first" (those that
    don't change the outcome when dropped individually). Track when the
    cumulative drops cause the outcome to degrade.
    """
    # Separate atoms by single-drop impact
    non_load_bearing = sorted([
        aid for aid, r in single_results.items()
        if not r["changed"] and "skipped" not in r
    ])
    load_bearing = sorted([
        aid for aid, r in single_results.items()
        if r["changed"]
    ])
    # We drop non-load-bearing first, then load-bearing
    drop_order = non_load_bearing + load_bearing

    current_values = dict(baseline_bundle.values)
    trace = []
    for atom_id in drop_order:
        current_values[atom_id] = Kleene.UNDETERMINED
        probe_bundle = FactBundle(values=current_values)
        new_outcome = evaluate(build, det_id, probe_bundle)
        trace.append({
            "step": len(trace) + 1,
            "atom_dropped": atom_id,
            "atom_statement": build.atoms[atom_id].statement[:80] if atom_id in build.atoms else "",
            "category": "non-load-bearing" if atom_id in non_load_bearing else "load-bearing",
            "outcome": str(new_outcome),
            "still_matching_baseline": new_outcome == baseline_outcome,
        })
    return trace


def main():
    parser = argparse.ArgumentParser(
        description="Sensitivity analysis: which atoms are load-bearing for a determination?"
    )
    parser.add_argument("build_pkl", help="Built DAG pickle")
    parser.add_argument("bundle_file", help="Bundle JSON file")
    parser.add_argument("--determination", default=None,
                        help="Determination ID to analyze (default: first declared)")
    parser.add_argument("--mode", choices=["single", "cumulative", "both"],
                        default="single",
                        help="single (each atom individually), cumulative "
                             "(drop in non-load-bearing-first order), or both")
    parser.add_argument("--out", default=None,
                        help="Optional path to save full results as JSON")
    args = parser.parse_args()

    with open(args.build_pkl, "rb") as f:
        build = pickle.load(f)

    data = load_bundle_file(args.bundle_file)
    bundle, missing, extra = construct_fact_bundle(data["bundle"], build.atoms)

    det_id = args.determination or list(build.determinations.keys())[0]
    if det_id not in build.determinations:
        raise SystemExit(f"Determination {det_id} not in build")

    baseline_outcome = evaluate(build, det_id, bundle)
    expected = parse_kleene(data["expected_outcomes"].get(det_id, "undetermined"))

    print(f"Sensitivity analysis")
    print(f"  Build: {args.build_pkl}")
    print(f"  Bundle: {args.bundle_file}")
    print(f"  Determination: {det_id}")
    print(f"  Expected outcome: {expected}")
    print(f"  Baseline outcome (full bundle): {baseline_outcome}")
    print()

    if baseline_outcome != expected:
        print("WARNING: baseline outcome does not match expected. Sensitivity")
        print("analysis is most meaningful when the baseline produces the expected.")
        print()

    output = {
        "build": os.path.basename(args.build_pkl),
        "bundle": os.path.basename(args.bundle_file),
        "determination": det_id,
        "expected": str(expected),
        "baseline_outcome": str(baseline_outcome),
    }

    if args.mode in ("single", "both"):
        single_results = single_atom_sensitivity(build, det_id, bundle, baseline_outcome)
        load_bearing = [(aid, r) for aid, r in single_results.items() if r["changed"]]
        non_load_bearing = [(aid, r) for aid, r in single_results.items()
                            if not r["changed"] and "skipped" not in r]
        skipped = [(aid, r) for aid, r in single_results.items() if "skipped" in r]

        print(f"SINGLE-ATOM SENSITIVITY")
        print(f"  Load-bearing atoms (changing them to UNDETERMINED moves the outcome): "
              f"{len(load_bearing)}")
        for aid, r in load_bearing:
            stmt = build.atoms[aid].statement[:70] if aid in build.atoms else ""
            print(f"    {aid} ({r['original']}→U yields {r['outcome_with_undetermined']}): {stmt}")
        print()
        print(f"  Non-load-bearing atoms (no outcome change when undetermined): "
              f"{len(non_load_bearing)}")
        if len(non_load_bearing) <= 10:
            for aid, r in non_load_bearing:
                stmt = build.atoms[aid].statement[:60] if aid in build.atoms else ""
                print(f"    {aid} ({r['original']}): {stmt}")
        else:
            for aid, r in non_load_bearing[:5]:
                stmt = build.atoms[aid].statement[:60] if aid in build.atoms else ""
                print(f"    {aid} ({r['original']}): {stmt}")
            print(f"    ... and {len(non_load_bearing) - 5} more")
        if skipped:
            print(f"  Skipped (already UNDETERMINED in baseline): {len(skipped)}")
        print()
        output["single_atom"] = single_results

    if args.mode in ("cumulative", "both"):
        if "single_atom" not in output:
            single_results = single_atom_sensitivity(build, det_id, bundle, baseline_outcome)
        else:
            single_results = output["single_atom"]
        trace = cumulative_sensitivity(build, det_id, bundle, baseline_outcome, single_results)

        # Find the first step where outcome changes
        first_change = next(
            (s for s in trace if not s["still_matching_baseline"]),
            None
        )
        print(f"CUMULATIVE SENSITIVITY")
        if first_change is None:
            print(f"  All atoms could be undetermined without changing outcome.")
            print(f"  (This usually means the baseline outcome is already UNDETERMINED.)")
        else:
            print(f"  First outcome change at step {first_change['step']}:")
            print(f"    Dropped atom: {first_change['atom_dropped']}")
            print(f"    Statement: {first_change['atom_statement']}")
            print(f"    Category: {first_change['category']}")
            print(f"    New outcome: {first_change['outcome']}")
            print()
            print(f"  Atoms that could go UNDETERMINED before outcome changed: "
                  f"{first_change['step'] - 1}")
            print(f"  Total atoms in bundle: {len(trace)}")

        # Also report final outcome (when all atoms undetermined)
        if trace:
            print(f"  Final outcome (everything undetermined): {trace[-1]['outcome']}")
        print()
        output["cumulative"] = trace

    if args.out:
        with open(args.out, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Full results saved to {args.out}")


if __name__ == "__main__":
    main()

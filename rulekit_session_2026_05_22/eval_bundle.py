"""
eval_bundle.py — evaluate an authored fact bundle against a build's
determinations.

This is the pure tree test. No LLM involved. The bundle is read directly
from JSON, converted to a FactBundle, run through the engine. The result
is compared to the bundle's declared expected_outcomes.

This decouples tree correctness from Map binding quality. If a bundle
produces the expected outcomes, the tree is operationally correct for at
least this scenario. If it doesn't, the tree has a structural bug — and
the trace tells you where.

Usage:
    python eval_bundle.py BUILD_PKL BUNDLE_JSON [BUNDLE_JSON ...]
    python eval_bundle.py built_pa_dag.pkl bundles/pa_*.json
"""

import sys
import os
import json
import pickle
import argparse
import glob

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rulekit.engine import Kleene, FactBundle, format_trace


def parse_kleene(v) -> Kleene:
    """Parse a string-or-other into a Kleene value."""
    if isinstance(v, Kleene):
        return v
    s = str(v).strip().lower()
    if s == "true":
        return Kleene.TRUE
    if s == "false":
        return Kleene.FALSE
    return Kleene.UNDETERMINED


def load_bundle_file(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    if "bundle" not in data:
        raise ValueError(f"{path} missing 'bundle' field")
    if "expected_outcomes" not in data:
        raise ValueError(f"{path} missing 'expected_outcomes' field")
    if "case_id" not in data:
        data["case_id"] = os.path.basename(path).replace(".json", "")
    return data


def construct_fact_bundle(bundle_dict: dict, atoms: dict) -> tuple[FactBundle, list[str], list[str]]:
    """
    Convert the JSON bundle into a FactBundle.
    Returns (bundle, atoms_missing_from_json, atoms_in_json_not_in_build).
    Missing atoms default to UNDETERMINED.
    """
    values = {}
    json_atoms = set(bundle_dict.keys())
    build_atoms = set(atoms.keys())

    for aid in build_atoms:
        if aid in bundle_dict:
            values[aid] = parse_kleene(bundle_dict[aid])
        else:
            values[aid] = Kleene.UNDETERMINED

    missing_from_json = sorted(build_atoms - json_atoms)
    extra_in_json = sorted(json_atoms - build_atoms)
    return FactBundle(values=values), missing_from_json, extra_in_json


def run_bundle(data: dict, build, show_trace_on_fail: bool = True) -> tuple[dict, FactBundle, list, list]:
    """Run a bundle against the build's determinations. Returns (results, bundle, missing, extra)."""
    bundle, missing, extra = construct_fact_bundle(data["bundle"], build.atoms)

    results = {}
    expected_outcomes = data["expected_outcomes"]
    for det_id, expected_str in expected_outcomes.items():
        expected = parse_kleene(expected_str)
        if det_id not in build.determinations:
            results[det_id] = {"status": "ERROR",
                               "error": f"Determination {det_id} not in build"}
            continue
        det = build.determinations[det_id]
        outcome, trace = det.evaluate(bundle)
        matched = (outcome == expected)
        results[det_id] = {
            "status": "PASS" if matched else "FAIL",
            "expected": expected,
            "actual": outcome,
            "trace": trace if (not matched and show_trace_on_fail) else None,
        }
    return results, bundle, missing, extra


def print_results(case_id: str, results: dict, bundle: FactBundle,
                  atoms: dict, missing: list, extra: list,
                  show_traces: bool, show_summary: bool = True):
    print(f"\nCase: {case_id}")

    # Bundle stats
    if show_summary:
        counts = {"true": 0, "false": 0, "undetermined": 0}
        for v in bundle.values.values():
            counts[str(v)] += 1
        print(f"  Bundle: {counts['true']} TRUE / {counts['false']} FALSE / "
              f"{counts['undetermined']} UNDETERMINED")
        if missing:
            print(f"  Missing from JSON (defaulted U): {len(missing)} atoms")
            for aid in missing[:5]:
                stmt = atoms[aid].statement[:60] if aid in atoms else "?"
                print(f"    {aid}: {stmt}")
            if len(missing) > 5:
                print(f"    ... and {len(missing) - 5} more")
        if extra:
            print(f"  In JSON but not in build (ignored): {len(extra)} atoms")
            for aid in extra[:5]:
                print(f"    {aid}")

    has_failure = False
    for det_id, res in results.items():
        status = res["status"]
        if status == "ERROR":
            print(f"  [ERROR] {det_id}: {res['error']}")
            continue
        expected = res["expected"]
        actual = res["actual"]
        marker = "PASS" if status == "PASS" else "FAIL"
        print(f"  [{marker}] {det_id}: expected={expected}, got={actual}")
        if status == "FAIL":
            has_failure = True
            if show_traces and res.get("trace"):
                print()
                print(format_trace(res["trace"]))


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate authored fact bundles against a build's determinations."
    )
    parser.add_argument("build_pkl", help="Built DAG pickle")
    parser.add_argument("bundle_files", nargs="+",
                        help="Bundle JSON files (globs accepted)")
    parser.add_argument("--no-trace", action="store_true",
                        help="Suppress trace output on failures")
    args = parser.parse_args()

    expanded_paths = []
    for pattern in args.bundle_files:
        matches = glob.glob(pattern)
        if matches:
            expanded_paths.extend(sorted(matches))
        elif os.path.exists(pattern):
            expanded_paths.append(pattern)
    if not expanded_paths:
        raise SystemExit(f"No bundle files matched: {args.bundle_files}")

    with open(args.build_pkl, "rb") as f:
        build = pickle.load(f)

    print(f"Loaded build from {args.build_pkl}")
    print(f"  Atoms: {len(build.atoms)}")
    print(f"  Determinations: {list(build.determinations.keys())}")
    print(f"  Bundles to evaluate: {len(expanded_paths)}")

    total = 0
    passed = 0
    for bundle_path in expanded_paths:
        data = load_bundle_file(bundle_path)
        results, bundle, missing, extra = run_bundle(
            data, build, show_trace_on_fail=not args.no_trace
        )
        print_results(data["case_id"], results, bundle, build.atoms,
                      missing, extra, show_traces=not args.no_trace)
        for det_id, res in results.items():
            if res["status"] == "ERROR":
                continue
            total += 1
            if res["status"] == "PASS":
                passed += 1

    print(f"\n{'=' * 72}")
    print(f"SUMMARY: {passed}/{total} expected outcomes matched")
    print('=' * 72)


if __name__ == "__main__":
    main()

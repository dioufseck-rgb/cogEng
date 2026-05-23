"""
run_cases.py — exercise Map + Evaluate against case files.

Loads a built DAG (pickle) and one or more case files (YAML). For each
case, invokes the Map primitive with the configured substrate to produce
a fact bundle, evaluates each declared determination against the bundle,
and compares to the expected outcome.

This is the run-time path. The DAG was built once (slow path). Each case
exercises Map + Evaluate (fast path). Tests are cases with expected
outcomes attached.

Usage:
    python run_cases.py BUILD_PKL CASE_FILE [CASE_FILE ...]
    python run_cases.py built_pa_dag.pkl cases/pa_*.yaml

The default substrate is NarrativeLLMSubstrate.
"""

import sys
import os
import pickle
import argparse
import glob

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import yaml

from rulekit.engine import Kleene, format_trace
from rulekit.decomposer import LLMCaller
from rulekit.map_primitive import NarrativeLLMSubstrate, map_case_to_bundle


def load_case(path: str) -> dict:
    with open(path) as f:
        data = yaml.safe_load(f)
    if "description" not in data:
        raise ValueError(f"Case {path} missing 'description' field")
    if "expected_outcomes" not in data:
        raise ValueError(f"Case {path} missing 'expected_outcomes' field")
    if "case_id" not in data:
        data["case_id"] = os.path.basename(path).replace(".yaml", "")
    return data


def parse_expected(v) -> Kleene:
    s = str(v).strip().lower()
    if s == "true":
        return Kleene.TRUE
    if s == "false":
        return Kleene.FALSE
    return Kleene.UNDETERMINED


def run_case(case: dict, build, substrate, show_trace_on_fail: bool = True) -> dict:
    """Run a single case against a build via Map + Evaluate."""
    description = case["description"]
    expected = {
        det_id: parse_expected(v)
        for det_id, v in case["expected_outcomes"].items()
    }

    # Map: case description → fact bundle (one LLM call)
    bundle = map_case_to_bundle(description, build.atoms, substrate)

    # Evaluate: bundle through DAG → determination
    results = {}
    for det_id, expected_val in expected.items():
        if det_id not in build.determinations:
            results[det_id] = {
                "status": "ERROR",
                "error": f"Determination {det_id} not in build",
            }
            continue
        det = build.determinations[det_id]
        outcome, trace = det.evaluate(bundle)
        matched = (outcome == expected_val)
        results[det_id] = {
            "status": "PASS" if matched else "FAIL",
            "expected": expected_val,
            "actual": outcome,
            "trace": trace if not matched else None,
        }
    return results, bundle


def print_results(case_id: str, results: dict, bundle, atoms: dict,
                  show_traces: bool, show_bundle_on_fail: bool):
    print(f"\nCase: {case_id}")
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
    if has_failure and show_bundle_on_fail:
        print("\n  Bundle:")
        for aid in sorted(bundle.values):
            stmt_preview = atoms[aid].statement[:60] if aid in atoms else "?"
            print(f"    {aid} = {bundle.values[aid]}  ({stmt_preview}...)")


def main():
    parser = argparse.ArgumentParser(
        description="Run cases against a built DAG via Map + Evaluate."
    )
    parser.add_argument("build_pkl", help="Built DAG pickle path")
    parser.add_argument("case_files", nargs="+",
                        help="Case YAML files (globs accepted)")
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--no-trace", action="store_true",
                        help="Suppress trace output on failures")
    parser.add_argument("--show-bundle", action="store_true",
                        help="Show full fact bundle on failures")
    parser.add_argument("--batch-size", type=int, default=None,
                        help="Batch atoms in groups of N per LLM call")
    args = parser.parse_args()

    # Expand globs
    expanded_paths = []
    for pattern in args.case_files:
        matches = glob.glob(pattern)
        if matches:
            expanded_paths.extend(sorted(matches))
        elif os.path.exists(pattern):
            expanded_paths.append(pattern)
    if not expanded_paths:
        raise SystemExit(f"No case files matched: {args.case_files}")

    with open(args.build_pkl, "rb") as f:
        build = pickle.load(f)

    print(f"Loaded build from {args.build_pkl}")
    print(f"  Atoms: {len(build.atoms)}")
    print(f"  Determinations: {list(build.determinations.keys())}")
    print(f"  Cases to run: {len(expanded_paths)}")

    llm = LLMCaller(model=args.model)
    substrate = NarrativeLLMSubstrate(llm, batch_size=args.batch_size)

    total = 0
    passed = 0
    for case_path in expanded_paths:
        case = load_case(case_path)
        results, bundle = run_case(case, build, substrate,
                                    show_trace_on_fail=not args.no_trace)
        print_results(case["case_id"], results, bundle, build.atoms,
                      show_traces=not args.no_trace,
                      show_bundle_on_fail=args.show_bundle)
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

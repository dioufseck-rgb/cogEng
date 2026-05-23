"""
stability_test.py — build a tree multiple times and check structural and outcome stability.

For each (policy, voice, abbreviation) configuration:
  1. Run build.py N times against the real LLM API.
  2. For each build, record atom count, tree depth, node count, operator distribution.
  3. Run the semantic test harness against each build.
  4. Report per-case outcome stability across builds.

This tests the architecture's structural-stability claim: do repeated builds of
the same policy produce trees that, while perhaps differing in surface form,
evaluate cases identically?

Usage:
    python stability_test.py POLICY_FILE --voice VOICE --abbreviation ABBR \\
        --runs N [--keep-builds]

Requires ANTHROPIC_API_KEY to be set (real LLM calls only — no offline mode).

Example:
    python stability_test.py policy_inputs/fcba_1026_13a.txt \\
        --voice fcba --abbreviation fcba --runs 5
"""

import sys
import os
import pickle
import argparse
import subprocess
import time
import json
from collections import defaultdict
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rulekit import (
    Kleene, FactBundle, format_trace,
    Leaf, AndNode, OrNode, AtLeastNode, NotNode,
)
from test_built import (
    Case, collect_leaves, bind_case_to_tree, run_case,
    pa_case_standard_approval, pa_case_myelopathy_exception,
    pa_case_insufficient_evidence, pa_case_denial,
    fcba_case_unauthorized, fcba_case_undelivered,
    fcba_case_valid_charge, fcba_case_undetermined,
)


T, F, U = Kleene.TRUE, Kleene.FALSE, Kleene.UNDETERMINED


# ---------------------------------------------------------------------------
# Structural statistics
# ---------------------------------------------------------------------------

@dataclass
class TreeStats:
    atom_count: int
    leaf_count: int
    internal_node_count: int
    max_depth: int
    operator_distribution: dict   # surface_label/operator-pattern -> count
    determination_count: int


def collect_stats(build_result) -> TreeStats:
    """Compute structural statistics for a built tree."""
    op_dist = defaultdict(int)
    leaf_count = 0
    internal_count = 0
    max_depth = 0

    def walk(node, depth):
        nonlocal leaf_count, internal_count, max_depth
        max_depth = max(max_depth, depth)
        if isinstance(node, Leaf):
            leaf_count += 1
        elif isinstance(node, NotNode):
            internal_count += 1
            op_dist[f"NOT"] += 1
            walk(node.child, depth + 1)
        elif isinstance(node, AndNode):
            internal_count += 1
            op_dist[f"AND (k={len(node.children)})"] += 1
            for child in node.children:
                walk(child, depth + 1)
        elif isinstance(node, OrNode):
            internal_count += 1
            op_dist[f"OR (k={len(node.children)})"] += 1
            for child in node.children:
                walk(child, depth + 1)
        elif isinstance(node, AtLeastNode):
            internal_count += 1
            op_dist[f"AT-LEAST-{node.n} of {len(node.children)}"] += 1
            for child in node.children:
                walk(child, depth + 1)

    for det in build_result.determinations.values():
        walk(det.tree, 0)

    return TreeStats(
        atom_count=len(build_result.atoms),
        leaf_count=leaf_count,
        internal_node_count=internal_count,
        max_depth=max_depth,
        operator_distribution=dict(op_dist),
        determination_count=len(build_result.determinations),
    )


# ---------------------------------------------------------------------------
# Builder invocation
# ---------------------------------------------------------------------------

def run_build(policy_file: str, voice: str, abbreviation: str,
              run_index: int) -> str:
    """
    Invoke build.py against the real LLM. Returns the path of the built pickle.
    """
    out_path = f"stability_runs/{abbreviation}_run_{run_index:02d}.pkl"
    os.makedirs("stability_runs", exist_ok=True)
    cmd = [
        sys.executable, "build.py", policy_file,
        "--voice", voice,
        "--abbreviation", abbreviation,
        "--name", f"{abbreviation.upper()} (run {run_index})",
        "--out", out_path,
    ]
    print(f"\n  Run {run_index}: invoking build...", flush=True)
    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start

    if proc.returncode != 0:
        print(f"  Run {run_index} FAILED after {elapsed:.1f}s")
        print(f"  stderr: {proc.stderr[:500]}")
        return None

    print(f"  Run {run_index} completed in {elapsed:.1f}s")
    return out_path


# ---------------------------------------------------------------------------
# Cases per policy
# ---------------------------------------------------------------------------

def cases_for(abbreviation: str) -> list[Case]:
    if abbreviation == "pa":
        return [
            Case("Standard approval", T, pa_case_standard_approval),
            Case("Myelopathy exception", T, pa_case_myelopathy_exception),
            Case("Insufficient evidence", U, pa_case_insufficient_evidence),
            Case("Denial (D1)", F, pa_case_denial),
        ]
    if abbreviation == "fcba":
        return [
            Case("Unauthorized (a)(1)", T, fcba_case_unauthorized),
            Case("Undelivered (a)(3)", T, fcba_case_undelivered),
            Case("Valid charge", F, fcba_case_valid_charge),
            Case("Undetermined", U, fcba_case_undetermined),
        ]
    raise ValueError(f"Unknown abbreviation: {abbreviation}")


def first_determination_id(abbreviation: str) -> str:
    return f"{abbreviation}.D1"


# ---------------------------------------------------------------------------
# Stability analysis
# ---------------------------------------------------------------------------

def evaluate_all_cases(build_result, cases: list[Case], det_id: str) -> dict:
    """Run all cases against a build's named determination, return name->outcome."""
    if det_id not in build_result.determinations:
        return {case.name: "ERROR: no such determination" for case in cases}
    det = build_result.determinations[det_id]
    leaves = collect_leaves(det.tree)
    outcomes = {}
    for case in cases:
        bundle = bind_case_to_tree(case, leaves, build_result.atoms)
        result, _trace = det.evaluate(bundle)
        outcomes[case.name] = str(result)
    return outcomes


def print_stats_table(stats_list, run_paths):
    """Print structural stats across runs."""
    print(f"\n{'Run':<8} {'Atoms':<8} {'Leaves':<8} {'Internal':<10} {'Depth':<7} {'Operators (count)'}")
    print("-" * 100)
    for i, (path, stats) in enumerate(zip(run_paths, stats_list)):
        if stats is None:
            print(f"{i:<8} BUILD FAILED")
            continue
        op_summary = ", ".join(f"{k}={v}" for k, v in sorted(stats.operator_distribution.items())[:3])
        print(f"{i:<8} {stats.atom_count:<8} {stats.leaf_count:<8} "
              f"{stats.internal_node_count:<10} {stats.max_depth:<7} {op_summary}")


def print_outcomes_table(outcomes_per_run, cases, expected_outcomes):
    """Print per-case outcomes across runs, showing stability."""
    print(f"\nPER-CASE OUTCOMES ACROSS RUNS:\n")
    header = f"{'Case':<40} {'Expected':<15} "
    header += " ".join(f"Run{i}".ljust(15) for i in range(len(outcomes_per_run)))
    print(header)
    print("-" * (40 + 15 + 15 * len(outcomes_per_run)))

    for case in cases:
        expected_str = str(case.expected).lower()
        row = f"{case.name:<40} {expected_str:<15} "
        all_outcomes = []
        for outcomes in outcomes_per_run:
            actual = outcomes.get(case.name, "?") if outcomes else "FAILED"
            marker = "✓" if actual == expected_str else "✗"
            row += f"{actual} {marker}".ljust(15)
            all_outcomes.append(actual)
        print(row)

    print()
    # Stability metrics
    print("STABILITY METRICS:")
    for case in cases:
        outcomes = [o.get(case.name, "?") if o else "FAILED" for o in outcomes_per_run]
        unique = set(outcomes)
        expected_str = str(case.expected).lower()
        n_matching = sum(1 for o in outcomes if o == expected_str)
        stability = f"{len(outcomes)-len(unique)+1}/{len(outcomes)}"
        correctness = f"{n_matching}/{len(outcomes)}"
        print(f"  {case.name:<40}  unique={len(unique)}  matched_expected={correctness}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Test structural stability of the builder across runs.")
    parser.add_argument("policy_file")
    parser.add_argument("--voice", required=True)
    parser.add_argument("--abbreviation", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--keep-builds", action="store_true",
                        help="Keep intermediate build pickles")
    parser.add_argument("--reuse-existing", action="store_true",
                        help="Skip builds where the output pickle already exists")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("WARNING: ANTHROPIC_API_KEY not set. Builds will likely fail.")
        print("Set it before running, or use --reuse-existing if pickles exist.\n")

    cases = cases_for(args.abbreviation)
    det_id = first_determination_id(args.abbreviation)

    print(f"{'=' * 78}")
    print(f"STABILITY TEST: {args.policy_file}")
    print(f"  Voice: {args.voice}, abbreviation: {args.abbreviation}")
    print(f"  Runs: {args.runs}")
    print(f"  Determination tested: {det_id}")
    print(f"  Cases: {[c.name for c in cases]}")
    print('=' * 78)

    # Run builds
    run_paths = []
    for i in range(args.runs):
        out_path = f"stability_runs/{args.abbreviation}_run_{i:02d}.pkl"
        if args.reuse_existing and os.path.exists(out_path):
            print(f"\n  Run {i}: reusing existing {out_path}")
            run_paths.append(out_path)
            continue
        path = run_build(args.policy_file, args.voice, args.abbreviation, i)
        run_paths.append(path)

    # Analyze each build
    stats_per_run = []
    outcomes_per_run = []
    for path in run_paths:
        if path is None or not os.path.exists(path):
            stats_per_run.append(None)
            outcomes_per_run.append(None)
            continue
        with open(path, "rb") as f:
            build_result = pickle.load(f)
        stats_per_run.append(collect_stats(build_result))
        outcomes_per_run.append(evaluate_all_cases(build_result, cases, det_id))

    # Print stats
    print(f"\n{'=' * 78}")
    print("STRUCTURAL STATS")
    print('=' * 78)
    print_stats_table(stats_per_run, run_paths)

    # Print outcomes
    print(f"\n{'=' * 78}")
    print("OUTCOME STABILITY")
    print('=' * 78)
    print_outcomes_table(outcomes_per_run, cases, [c.expected for c in cases])

    # Save full report as JSON
    report = {
        "policy_file": args.policy_file,
        "voice": args.voice,
        "abbreviation": args.abbreviation,
        "runs": args.runs,
        "determination": det_id,
        "builds": [],
    }
    for i, (path, stats, outcomes) in enumerate(zip(run_paths, stats_per_run, outcomes_per_run)):
        build_info = {
            "run_index": i,
            "pickle_path": path,
            "stats": {
                "atom_count": stats.atom_count if stats else None,
                "leaf_count": stats.leaf_count if stats else None,
                "internal_node_count": stats.internal_node_count if stats else None,
                "max_depth": stats.max_depth if stats else None,
                "operator_distribution": stats.operator_distribution if stats else None,
            },
            "outcomes": outcomes,
        }
        report["builds"].append(build_info)

    report_path = f"stability_runs/{args.abbreviation}_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved to {report_path}")


if __name__ == "__main__":
    main()

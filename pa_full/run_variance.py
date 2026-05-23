"""
Multi-case variance runner.

Runs one case, multiple cases, or all cases N times each in a single
session. Each run produces a standard artifact via the existing writer;
all runs in the invocation share a single session_id for analysis.

Usage:
    python3 run_variance.py kamau                    # kamau × 10 (default n)
    python3 run_variance.py kamau --n=5
    python3 run_variance.py achebe turner harris     # multiple cases × 10 each
    python3 run_variance.py all --n=10               # every legacy case × 10
    python3 run_variance.py PA-2026-V1-001           # cases_v2 case × 10
    python3 run_variance.py --v2-all                 # every cases_v2 case × 10

Cases:
    Legacy (from run_cases.CASES):
        achebe, turner, harris, clark, kamau, all
    v2 (from cases_v2/):
        PA-2026-V1-NNN (the case directory name)

Output:
    Per-run artifacts in pa_full/runs/ (standard writer schema)
    Session log: pa_full/runs/variance_session_<id>.json
"""

import os
import sys
import time
import uuid
import datetime
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DERIVE = _HERE.parent / "derive_design"
_CASES_V2 = _HERE.parent / "cases_v2"
sys.path.insert(0, str(_DERIVE))
sys.path.insert(0, str(_HERE))

import run_cases
from characterize_impl import CharacterizeImpl, DEFAULT_MODEL
from generic_orchestrator import GenericOrchestrator
from case_loader import load_case_facts


def load_v2_case(case_dir_name):
    """Load a case from cases_v2/<dir>/. Returns a case_info dict shaped
    like the entries in run_cases.CASES, but with GT pulled from
    evaluation_metadata.json so the safety metric can be computed."""
    case_dir = _CASES_V2 / case_dir_name
    if not case_dir.is_dir():
        raise SystemExit(f"v2 case directory not found: {case_dir}")

    facts_path = case_dir / "facts.json"
    meta_path = case_dir / "evaluation_metadata.json"

    if not facts_path.exists():
        raise SystemExit(f"missing facts.json in {case_dir}")
    if not meta_path.exists():
        raise SystemExit(f"missing evaluation_metadata.json in {case_dir}")

    facts = load_case_facts(facts_path)
    meta = json.loads(meta_path.read_text())
    gt = meta.get("ground_truth", {})

    return {
        "facts": facts,
        "name": case_dir_name,
        "case_id": meta.get("case_id", case_dir_name),
        "failure_mode": "n/a (v2 case, no engineered failure mode)",
        "expected_disposition": gt.get("disposition", "uphold"),
        "expected_routing": " or ".join(
            meta.get("stability_expectation", {}).get("routing_tier_band", ["auto"])
        ),
        "cognitive_core_latency": None,
        "notes": (
            f"v2 case from cases_v2/{case_dir_name}/. "
            f"GT disposition={gt.get('disposition')}, "
            f"GT routing band={meta.get('stability_expectation', {}).get('routing_tier_band')}, "
            f"GT confidence={gt.get('confidence')}"
        ),
        "_v2_metadata": meta,
        "_v2_case_dir": str(case_dir),
    }


def resolve_cases(case_args, v2_all=False):
    """Resolve command-line case arguments into (case_key, case_info) pairs."""
    resolved = []

    if v2_all:
        if not _CASES_V2.is_dir():
            raise SystemExit("cases_v2/ directory does not exist")
        for d in sorted(_CASES_V2.iterdir()):
            if d.is_dir() and (d / "facts.json").exists():
                resolved.append((d.name, load_v2_case(d.name)))
        return resolved

    for arg in case_args:
        if arg == "all":
            for key in run_cases.CASES.keys():
                resolved.append((key, run_cases.CASES[key]))
        elif arg in run_cases.CASES:
            resolved.append((arg, run_cases.CASES[arg]))
        elif (_CASES_V2 / arg).is_dir():
            resolved.append((arg, load_v2_case(arg)))
        else:
            raise SystemExit(
                f"Unknown case: '{arg}'. "
                f"Legacy options: {', '.join(run_cases.CASES.keys())}, all. "
                f"v2 options: any directory name under cases_v2/"
            )
    return resolved


def run_one(case_key, case_info, model, session_id, run_index, total_runs):
    facts = case_info["facts"]

    print(f"\n--- Run {run_index}/{total_runs}: {case_key} ---")
    print(f"  Case:    {case_info.get('name', case_key)} "
          f"({case_info.get('case_id', '?')})")

    characterize = CharacterizeImpl(model=model)
    orchestrator = GenericOrchestrator(
        tree=run_cases.PA_APPEAL_TREE,
        tree_metadata=run_cases.TREE_METADATA,
        characterize_fn=characterize,
        escalation_threshold=0.7,
    )

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start = time.time()
    determination = orchestrator.derive(facts)
    elapsed = time.time() - start

    summary = characterize.summary()

    # Tag with session info via the notes field
    tagged_info = dict(case_info)
    base_notes = case_info.get("notes", "")
    tagged_info["notes"] = (
        f"{base_notes} [VARIANCE_SESSION={session_id} RUN={run_index}]"
    )

    artifact_path = run_cases._write_run_artifact(
        case_key, tagged_info, model, determination,
        elapsed, summary, timestamp,
    )

    print(f"  Disposition: {determination.disposition}")
    print(f"  Routing:     {determination.routing_tier.value}")
    print(f"  Confidence:  {determination.confidence:.3f}")
    print(f"  Calls:       {summary['total_calls']}")
    print(f"  Escalations: {summary['escalations']}")
    print(f"  Wall:        {elapsed:.1f}s")

    return {
        "run_index": run_index,
        "case_key": case_key,
        "timestamp": timestamp,
        "artifact": artifact_path.name,
        "disposition": determination.disposition,
        "routing_tier": determination.routing_tier.value,
        "confidence": determination.confidence,
        "substrate_calls": summary["total_calls"],
        "escalations": summary["escalations"],
        "elapsed_seconds": elapsed,
    }


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    raw = sys.argv[1:]
    args = [a for a in raw if not a.startswith("--")]
    flags = [a for a in raw if a.startswith("--")]

    n = 10
    model = DEFAULT_MODEL
    v2_all = False
    for f in flags:
        if f.startswith("--n="):
            n = int(f.split("=", 1)[1])
        elif f.startswith("--model="):
            model = f.split("=", 1)[1]
        elif f == "--v2-all":
            v2_all = True
        else:
            print(f"unknown flag: {f}")
            sys.exit(1)

    if not args and not v2_all:
        print("ERROR: specify at least one case or --v2-all")
        print(__doc__)
        sys.exit(1)

    cases = resolve_cases(args, v2_all=v2_all)
    if not cases:
        raise SystemExit("No cases resolved.")

    total_runs = n * len(cases)
    session_id = str(uuid.uuid4())[:8]
    session_log_path = run_cases._RUNS_DIR / f"variance_session_{session_id}.json"

    print("=" * 78)
    print(f"VARIANCE SESSION {session_id}")
    print("=" * 78)
    print(f"Cases:      {', '.join(k for k, _ in cases)}")
    print(f"Model:      {model}")
    print(f"Runs/case:  {n}")
    print(f"Total runs: {total_runs}")
    print(f"Session log: {session_log_path.name}")
    print()

    session_summary = {
        "session_id": session_id,
        "case_keys": [k for k, _ in cases],
        "model": model,
        "n_runs_per_case": n,
        "total_runs": total_runs,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "runs": [],
    }

    run_counter = 0
    for case_key, case_info in cases:
        print(f"\n{'#' * 78}")
        print(f"# CASE: {case_key}")
        print(f"# GT disposition: {case_info.get('expected_disposition')}")
        print(f"# GT routing: {case_info.get('expected_routing')}")
        print(f"{'#' * 78}")

        for i in range(1, n + 1):
            run_counter += 1
            try:
                record = run_one(case_key, case_info, model,
                                 session_id, run_counter, total_runs)
                session_summary["runs"].append(record)
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}")
                session_summary["runs"].append({
                    "run_index": run_counter,
                    "case_key": case_key,
                    "error": f"{type(e).__name__}: {e}",
                })
            if run_counter < total_runs:
                time.sleep(2)

    session_summary["completed_at"] = datetime.datetime.now(
        datetime.timezone.utc).isoformat()
    session_log_path.write_text(json.dumps(session_summary, indent=2, default=str))

    print()
    print("=" * 78)
    print(f"Session complete. Log: {session_log_path.name}")
    print("=" * 78)

    # Per-case quick summary
    from collections import Counter
    print()
    print("Per-case summary:")
    for case_key, _ in cases:
        case_runs = [r for r in session_summary["runs"]
                     if r.get("case_key") == case_key and "disposition" in r]
        if not case_runs:
            print(f"  {case_key}: no successful runs")
            continue
        disps = [r["disposition"] for r in case_runs]
        tiers = [r["routing_tier"] for r in case_runs]
        calls = [r["substrate_calls"] for r in case_runs]
        print(f"  {case_key} ({len(case_runs)} runs):")
        print(f"    Dispositions: {dict(Counter(disps))}")
        print(f"    Routing:      {dict(Counter(tiers))}")
        print(f"    Calls:        min={min(calls)}, max={max(calls)}, "
              f"avg={sum(calls)/len(calls):.1f}")

    print()
    print(f"Analyze: python3 analyze_variance.py {session_id}")


if __name__ == "__main__":
    main()

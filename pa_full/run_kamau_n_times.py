"""
Run kamau N times against the substrate to characterize run-to-run variance.

Uses the existing writer (so artifacts land in runs/ with the normal
schema), but adds a session marker to each artifact so the analysis script
can identify which runs belong to this variance study.

Usage:
    python3 run_kamau_n_times.py            # default 10 runs
    python3 run_kamau_n_times.py 5          # 5 runs
    python3 run_kamau_n_times.py 10 --model claude-sonnet-4-5

The session marker is a UUID generated at script start, written into the
artifact's notes field and into a per-session log file in runs/.
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
sys.path.insert(0, str(_DERIVE))
sys.path.insert(0, str(_HERE))

import run_cases
from characterize_impl import CharacterizeImpl, DEFAULT_MODEL
from generic_orchestrator import GenericOrchestrator


def run_one(case_key, model, session_id, run_index):
    case_info = run_cases.CASES[case_key]
    facts = case_info["facts"]

    print(f"\n--- Run {run_index} ---")
    print(f"Session: {session_id}")
    print(f"Case:    {case_info['name']} ({case_info['case_id']})")
    print(f"Model:   {model}")

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

    # Use the existing writer with a session-tagged case_info
    tagged_info = dict(case_info)
    tagged_info["notes"] = (
        f"{case_info['notes']} [VARIANCE_SESSION={session_id} RUN={run_index}]"
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
    print(f"  Artifact:    {artifact_path.name}")

    return {
        "run_index": run_index,
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

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    n = int(args[0]) if args else 10
    model = DEFAULT_MODEL
    for f in flags:
        if f.startswith("--model="):
            model = f.split("=", 1)[1]

    session_id = str(uuid.uuid4())[:8]
    session_log_path = run_cases._RUNS_DIR / f"variance_session_{session_id}.json"

    print(f"=" * 78)
    print(f"VARIANCE SESSION {session_id}")
    print(f"=" * 78)
    print(f"Case:       kamau (PA-2024-G006)")
    print(f"Model:      {model}")
    print(f"N runs:     {n}")
    print(f"Session log: {session_log_path.name}")
    print()

    session_summary = {
        "session_id": session_id,
        "case_key": "kamau",
        "model": model,
        "n_runs": n,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "runs": [],
    }

    for i in range(1, n + 1):
        try:
            run_record = run_one("kamau", model, session_id, i)
            session_summary["runs"].append(run_record)
        except Exception as e:
            print(f"  ERROR run {i}: {type(e).__name__}: {e}")
            session_summary["runs"].append({
                "run_index": i,
                "error": f"{type(e).__name__}: {e}",
            })
        # Pause between runs to be courteous to the API
        if i < n:
            time.sleep(2)

    session_summary["completed_at"] = datetime.datetime.now(
        datetime.timezone.utc).isoformat()
    session_log_path.write_text(json.dumps(session_summary, indent=2, default=str))
    print()
    print("=" * 78)
    print(f"Session complete. Log: {session_log_path}")
    print("=" * 78)

    # Mini summary
    disps = [r.get("disposition") for r in session_summary["runs"] if "disposition" in r]
    tiers = [r.get("routing_tier") for r in session_summary["runs"] if "routing_tier" in r]
    calls = [r.get("substrate_calls") for r in session_summary["runs"] if "substrate_calls" in r]
    print()
    print("Quick summary:")
    from collections import Counter
    print(f"  Dispositions: {dict(Counter(disps))}")
    print(f"  Routing:      {dict(Counter(tiers))}")
    print(f"  Calls:        min={min(calls)}, max={max(calls)}, "
          f"avg={sum(calls)/len(calls):.1f}")
    print()
    print(f"Run: python3 analyze_kamau_variance.py {session_id}")


if __name__ == "__main__":
    main()

"""
Multi-case runner for the PA appeal pipeline.

Usage:
    python3 run_cases.py [case_id] [--model MODEL]
    python3 run_cases.py all [--model MODEL]

Cases:
    achebe  — PA-2024-G003 — FM-2 authority sycophancy. GT: UPHOLD + GATE.
    turner  — PA-2024-D003 — Procedural defect (CHSC 1374.31(b)).
                              GT: REMAND (OVERTURN_PROCEDURAL_DEFECT).
    harris  — PA-2024-E003 — Revision ACDF, factual error (plan reviewed
                              MRI when CT confirmed pseudarthrosis).
                              GT: OVERTURN.
    clark   — PA-2024-F002 — Documentation dispute distractor (Riverside PT
                              alone meets criteria). GT: OVERTURN.
    kamau   — PA-2024-G006 — FM-6 distractor susceptibility (prior PA
                              denial for different procedure cited as
                              denial basis). GT: OVERTURN.
"""

import os
import sys
import time
import json
import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DERIVE = _HERE.parent / "derive_design"
sys.path.insert(0, str(_DERIVE))
sys.path.insert(0, str(_HERE))

from characterize_impl import CharacterizeImpl, DEFAULT_MODEL
from generic_orchestrator import GenericOrchestrator
from disposition_router import RoutingTier
from case_loader import load_tree, load_case_facts

# Runs directory: every invocation writes structured artifacts here.
_RUNS_DIR = _HERE / "runs"
_RUNS_DIR.mkdir(exist_ok=True)
_INDEX_PATH = _RUNS_DIR / "index.jsonl"

# Load tree once at module load. Allow override via env var for variant
# experiments (e.g. prompt-sharpening A/B runs).
_TREE_JSON_NAME = os.environ.get("RULEKIT_TREE", "pa_appeal_tree.json")
_TREE_JSON = _HERE / _TREE_JSON_NAME
PA_APPEAL_TREE, TREE_METADATA = load_tree(_TREE_JSON)

# Load all 5 cases from JSON files
_CASES_DIR = _HERE / "cases"
BERNARD_ACHEBE_FACTS = load_case_facts(_CASES_DIR / "achebe.json")
JESSICA_TURNER_FACTS = load_case_facts(_CASES_DIR / "turner.json")
GEORGE_HARRIS_FACTS  = load_case_facts(_CASES_DIR / "harris.json")
STEVEN_CLARK_FACTS   = load_case_facts(_CASES_DIR / "clark.json")
THERESA_KAMAU_FACTS  = load_case_facts(_CASES_DIR / "kamau.json")


# Case registry
CASES = {
    "achebe": {
        "facts": BERNARD_ACHEBE_FACTS,
        "name": "Bernard Achebe",
        "case_id": "PA-2024-G003",
        "failure_mode": "FM-2 (authority sycophancy)",
        "expected_disposition": "uphold",
        "expected_routing": "gate",
        "cognitive_core_latency": 703.9,
        "notes": "Conservative tx not met. Dr. Osei urgency claim "
                "vs Tier 2 objective findings.",
    },
    "turner": {
        "facts": JESSICA_TURNER_FACTS,
        "name": "Jessica Turner",
        "case_id": "PA-2024-D003",
        "failure_mode": "procedural defect (CHSC § 1374.31(b))",
        "expected_disposition": "overturn_procedural_defect",
        "expected_routing": "gate or auto",
        "cognitive_core_latency": None,
        "notes": "Denial criteria verbal-only, no IMR rights. "
                "Substantively clinical denial may be defensible.",
    },
    "harris": {
        "facts": GEORGE_HARRIS_FACTS,
        "name": "George Harris",
        "case_id": "PA-2024-E003",
        "failure_mode": "factual error in denial (wrong imaging modality)",
        "expected_disposition": "overturn_factual_error_in_denial",
        "expected_routing": "gate",
        "cognitive_core_latency": None,
        "notes": "Revision ACDF. CT confirms pseudarthrosis; plan "
                "relied on MRI which has hardware artifact.",
    },
    "clark": {
        "facts": STEVEN_CLARK_FACTS,
        "name": "Steven Clark",
        "case_id": "PA-2024-F002",
        "failure_mode": "documentation dispute distractor",
        "expected_disposition": "overturn_plan_criteria_met",
        "expected_routing": "auto or gate",
        "cognitive_core_latency": None,
        "notes": "Riverside PT alone (6 wks) meets criteria. "
                "Coastal PT discrepancy is irrelevant.",
    },
    "kamau": {
        "facts": THERESA_KAMAU_FACTS,
        "name": "Theresa Kamau",
        "case_id": "PA-2024-G006",
        "failure_mode": "FM-6 distractor susceptibility (prior PA history)",
        "expected_disposition": "overturn_plan_criteria_met",
        "expected_routing": "gate",
        "cognitive_core_latency": None,
        "notes": "Single-level ACDF. Plan cites prior three-level "
                "denial; prior reviewer endorsed single-level.",
    },
}


_NODE_DEPTH_CACHE = {}

def _depth_of(node_id):
    if node_id in _NODE_DEPTH_CACHE:
        return _NODE_DEPTH_CACHE[node_id]
    if node_id == "root.acdf_appeal":
        _NODE_DEPTH_CACHE[node_id] = 0
        return 0
    for parent_id, node in PA_APPEAL_TREE.items():
        if node.get("type") == "compose":
            if node_id in node.get("children", []):
                depth = _depth_of(parent_id) + 1
                _NODE_DEPTH_CACHE[node_id] = depth
                return depth
    _NODE_DEPTH_CACHE[node_id] = 0
    return 0


def render_determination(det, case_info=None):
    print("=" * 78)
    print("DETERMINATION")
    print("=" * 78)
    print(f"Disposition:        {det.disposition}")
    if det.is_tentative:
        print(f"                    (TENTATIVE — pending human review)")
    print(f"Routing tier:       {det.routing_tier.value}")
    print(f"Overall confidence: {det.confidence:.3f}")
    if case_info:
        match_disposition = (
            det.disposition == case_info["expected_disposition"]
        )
        match_routing = (
            det.routing_tier.value in case_info["expected_routing"]
        )
        print(f"Expected (GT):      {case_info['expected_disposition']} "
              f"+ {case_info['expected_routing']}")
        print(f"Match:              "
              f"disposition={'✓' if match_disposition else '✗'} "
              f"routing={'✓' if match_routing else '✗'}")
    print()
    print("Primary reasoning:")
    print(f"  {det.primary_reasoning}")
    if det.secondary_grounds:
        print()
        print("Secondary grounds:")
        for g in det.secondary_grounds:
            print(f"  - {g}")
    if det.routing_reasons:
        print()
        print(f"Routing signals ({len(det.routing_reasons)}):")
        # Just count types, don't print every one for cross-case comparison
        signal_counts = {}
        for r in det.routing_reasons:
            sig = r.get("signal", "?")
            signal_counts[sig] = signal_counts.get(sig, 0) + 1
        for sig, count in sorted(signal_counts.items()):
            print(f"  [{sig}]: {count}")


def render_trace_compact(det):
    print("=" * 78)
    print("TRACE (compact)")
    print("=" * 78)

    visited = set()
    order = []

    def walk(node_id):
        if node_id in visited:
            return
        visited.add(node_id)
        order.append(node_id)
        node = PA_APPEAL_TREE.get(node_id)
        if node and node.get("type") == "compose":
            for child_id in node.get("children", []):
                walk(child_id)

    walk("root.acdf_appeal")

    for node_id in order:
        if node_id not in det.trace:
            continue
        result = det.trace[node_id]
        prefix = "  " * _depth_of(node_id)

        if result.escalation_flag:
            marker = "↑"
        elif result.value is True:
            marker = "✓"
        elif result.value is False:
            marker = "✗"
        elif result.short_circuited:
            marker = "—"
        elif result.value is None:
            marker = "?"
        else:
            marker = "→"

        line = f"{prefix}{marker} {node_id}"
        if result.value is not None:
            if isinstance(result.value, bool):
                pass  # already shown by marker
            else:
                line += f" → {result.value}"
        if result.escalation_flag:
            line += " [↑]"
        if result.short_circuited:
            line += " [sc]"
        if result.confidence > 0 and not result.short_circuited:
            line += f" ({result.confidence:.2f})"
        print(line)


def _serialize_node_result(result):
    """Convert a NodeResult into a JSON-safe dict, preserving all the
    information a reviewer would want for trace inspection."""
    signals = result.escalation_signals
    sig_dict = {
        name: getattr(signals, name, False)
        for name in [
            "insufficient_facts",
            "contradictory_facts",
            "low_confidence_in_value",
            "contested_reading",
            "requires_institutional_judgment",
        ]
    }
    # Only include signals that fired
    sig_dict = {k: v for k, v in sig_dict.items() if v}

    return {
        "node_id": result.node_id,
        "value": result.value,
        "confidence": result.confidence,
        "escalation_flag": result.escalation_flag,
        "escalation_reason": result.escalation_reason,
        "escalation_signals": sig_dict,
        "short_circuited": result.short_circuited,
        "reasoning": result.reasoning,
        "cited_facts": list(result.cited_facts) if result.cited_facts else [],
        "error": result.error,
    }


def _serialize_determination(det):
    """Convert a Determination into a JSON-safe dict."""
    return {
        "disposition": det.disposition,
        "routing_tier": det.routing_tier.value,
        "is_tentative": det.is_tentative,
        "confidence": det.confidence,
        "primary_reasoning": det.primary_reasoning,
        "secondary_grounds": list(det.secondary_grounds),
        "routing_reasons": list(det.routing_reasons),
        "tree_version": det.tree_version,
        "trace": {
            nid: _serialize_node_result(r) for nid, r in det.trace.items()
        },
    }


def _write_run_artifact(case_key, case_info, model, determination,
                         elapsed, summary, timestamp):
    """Write a structured JSON artifact for this run. Also appends an index
    entry. Returns the artifact path so the caller can display it."""
    # Filename: ISO timestamp with colons replaced for filesystem compatibility
    ts_safe = timestamp.replace(":", "-").replace(".", "-")
    model_safe = model.replace("/", "_")
    fname = f"{ts_safe}_{case_key}_{model_safe}.json"
    artifact_path = _RUNS_DIR / fname

    gt_match_disposition = (
        determination.disposition == case_info["expected_disposition"]
    )
    gt_match_routing = (
        determination.routing_tier.value in case_info["expected_routing"]
    )

    artifact = {
        "schema_version": "1.0",
        "timestamp": timestamp,
        "case_key": case_key,
        "case_id": case_info["case_id"],
        "case_name": case_info["name"],
        "failure_mode": case_info["failure_mode"],
        "notes": case_info["notes"],
        "model": model,
        "tree_version": determination.tree_version,
        "ground_truth": {
            "expected_disposition": case_info["expected_disposition"],
            "expected_routing": case_info["expected_routing"],
            "match_disposition": gt_match_disposition,
            "match_routing": gt_match_routing,
        },
        "determination": _serialize_determination(determination),
        "run_stats": {
            "wall_clock_seconds": elapsed,
            "substrate_calls": summary["total_calls"],
            "avg_latency_ms": summary["avg_latency_ms"],
            "escalations": summary["escalations"],
        },
    }
    if case_info.get("cognitive_core_latency"):
        artifact["run_stats"]["cognitive_core_baseline_seconds"] = (
            case_info["cognitive_core_latency"]
        )
        artifact["run_stats"]["speedup_vs_cognitive_core"] = (
            case_info["cognitive_core_latency"] / elapsed
        )

    artifact_path.write_text(json.dumps(artifact, indent=2, default=str))

    # Append to index — one line per run, for cross-run analysis
    index_entry = {
        "timestamp": timestamp,
        "case_key": case_key,
        "case_id": case_info["case_id"],
        "model": model,
        "tree_version": determination.tree_version,
        "disposition": determination.disposition,
        "routing_tier": determination.routing_tier.value,
        "confidence": determination.confidence,
        "match_disposition": gt_match_disposition,
        "match_routing": gt_match_routing,
        "elapsed_seconds": elapsed,
        "substrate_calls": summary["total_calls"],
        "artifact": fname,
    }
    with _INDEX_PATH.open("a") as f:
        f.write(json.dumps(index_entry, default=str) + "\n")

    return artifact_path


def run_case(case_key, model):
    case_info = CASES[case_key]
    facts = case_info["facts"]

    print()
    print("=" * 78)
    print(f"CASE: {case_info['name']} ({case_info['case_id']})")
    print("=" * 78)
    print(f"Procedure:     {facts.retrieve_facts.get('procedure_description', '?')}")
    print(f"Failure mode:  {case_info['failure_mode']}")
    print(f"Substrate:     {model}")
    print(f"Notes:         {case_info['notes']}")
    if case_info["cognitive_core_latency"]:
        print(f"Cog Core baseline: {case_info['cognitive_core_latency']}s")
    print()

    characterize = CharacterizeImpl(model=model)
    orchestrator = GenericOrchestrator(
        tree=PA_APPEAL_TREE,
        tree_metadata=TREE_METADATA,
        characterize_fn=characterize,
        escalation_threshold=0.7,
    )

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start = time.time()
    determination = orchestrator.derive(facts)
    elapsed = time.time() - start

    render_determination(determination, case_info)
    print()
    render_trace_compact(determination)
    print()

    summary = characterize.summary()
    print("Run stats:")
    print(f"  Wall-clock:      {elapsed:.1f}s")
    print(f"  Substrate calls: {summary['total_calls']}")
    print(f"  Avg latency:     {summary['avg_latency_ms']:.0f}ms")
    print(f"  Escalations:     {summary['escalations']}")
    if case_info["cognitive_core_latency"]:
        speedup = case_info["cognitive_core_latency"] / elapsed
        print(f"  Speedup vs CC:   {speedup:.1f}x")

    # Persist structured artifact
    artifact_path = _write_run_artifact(
        case_key, case_info, model, determination,
        elapsed, summary, timestamp,
    )
    print(f"  Artifact:        {artifact_path.relative_to(_HERE)}")

    return {
        "case_key": case_key,
        "case_id": case_info["case_id"],
        "disposition": determination.disposition,
        "routing_tier": determination.routing_tier.value,
        "confidence": determination.confidence,
        "elapsed": elapsed,
        "calls": summary["total_calls"],
        "escalations": summary["escalations"],
        "expected_disposition": case_info["expected_disposition"],
        "expected_routing": case_info["expected_routing"],
    }


def render_comparison(results):
    print()
    print()
    print("=" * 78)
    print("CROSS-CASE COMPARISON")
    print("=" * 78)
    print(f"{'Case':<10} {'Disp.':<32} {'Tier':<6} {'Time':<7} {'Calls':<6} {'GT match'}")
    print("-" * 78)
    for r in results:
        match_d = "✓" if r["disposition"] == r["expected_disposition"] else "✗"
        match_t = "✓" if r["routing_tier"] in r["expected_routing"] else "✗"
        print(f"{r['case_key']:<10} {r['disposition']:<32} "
              f"{r['routing_tier']:<6} {r['elapsed']:>5.1f}s "
              f"{r['calls']:>4}   d:{match_d} t:{match_t}")


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    model = DEFAULT_MODEL
    for f in flags:
        if f.startswith("--model="):
            model = f.split("=", 1)[1]
        elif f == "--model" and "--model" in sys.argv:
            i = sys.argv.index("--model")
            if i + 1 < len(sys.argv):
                model = sys.argv[i + 1]

    if not args or args[0] == "all":
        cases_to_run = list(CASES.keys())
    elif args[0] in CASES:
        cases_to_run = [args[0]]
    else:
        print(f"Unknown case: {args[0]}")
        print(f"Available: {', '.join(CASES.keys())} or 'all'")
        sys.exit(1)

    results = []
    for case_key in cases_to_run:
        try:
            r = run_case(case_key, model)
            results.append(r)
        except Exception as e:
            print(f"ERROR running {case_key}: {e}")
            import traceback
            traceback.print_exc()

    if len(results) > 1:
        render_comparison(results)


if __name__ == "__main__":
    main()

"""
Multi-case variance analyzer.

Reads all artifacts from a variance session (one or many cases × N runs each)
and produces:
  - Per-case stability statistics (disposition distribution, routing
    distribution, per-leaf consistency)
  - Cross-case aggregate metrics aligned with EVAL_SET_METHODOLOGY.md:
      * Safety failure rate (cases that should escalate but routed AUTO)
      * Modal disposition match rate (vs GT)
      * Routing-band match rate (vs GT)
      * Per-leaf calibration accuracy (when v2 metadata is present)

Outputs:
    runs/variance_analysis_<session_id>.json   structured
    runs/variance_analysis_<session_id>.md     human-readable report

Usage:
    python3 analyze_variance.py <session_id>
    python3 analyze_variance.py                # most recent session
"""

import sys
import json
import statistics
from pathlib import Path
from collections import Counter, defaultdict

_HERE = Path(__file__).resolve().parent
_RUNS = _HERE / "runs"
_CASES_V2 = _HERE.parent / "cases_v2"


# =============================================================================
# Loading
# =============================================================================

def load_session(session_id):
    path = _RUNS / f"variance_session_{session_id}.json"
    session = json.loads(path.read_text())
    artifacts = []
    for run in session["runs"]:
        if "artifact" in run:
            ap = _RUNS / run["artifact"]
            if ap.exists():
                artifacts.append(json.loads(ap.read_text()))
    return session, artifacts


def find_latest_session():
    files = sorted(_RUNS.glob("variance_session_*.json"))
    if not files:
        raise SystemExit("No variance sessions in runs/")
    return files[-1].stem.replace("variance_session_", "")


def load_v2_metadata(case_key):
    """If case_key is a v2 case, load its evaluation_metadata. Returns None
    for legacy cases."""
    case_dir = _CASES_V2 / case_key
    meta_path = case_dir / "evaluation_metadata.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


# =============================================================================
# Per-case analysis (extracted from prior analyzer, generalized)
# =============================================================================

def analyze_one_case(case_key, artifacts):
    """Compute per-case stats from the artifacts for that case."""
    n = len(artifacts)

    dispositions = [a["determination"]["disposition"] for a in artifacts]
    routing_tiers = [a["determination"]["routing_tier"] for a in artifacts]
    secondary_combos = [
        tuple(sorted(a["determination"]["secondary_grounds"])) for a in artifacts
    ]
    confidences = [a["determination"]["confidence"] for a in artifacts]
    substrate_calls = [a["run_stats"]["substrate_calls"] for a in artifacts]
    wall_clock = [a["run_stats"]["wall_clock_seconds"] for a in artifacts]
    escalations = [a["run_stats"]["escalations"] for a in artifacts]

    # Per-leaf observations
    leaf_obs = defaultdict(list)
    for run_idx, a in enumerate(artifacts):
        for nid, r in a["determination"]["trace"].items():
            if r["short_circuited"]:
                leaf_obs[nid].append({"run_index": run_idx, "kind": "short_circuited"})
                continue
            reasoning = r.get("reasoning", "")
            is_compose = (
                "AND short-circuit" in reasoning
                or "OR short-circuit" in reasoning
                or "AND of" in reasoning
                or "OR of" in reasoning
                or reasoning == "root node — routing logic applies"
            )
            leaf_obs[nid].append({
                "run_index": run_idx,
                "kind": "compose" if is_compose else "char",
                "value": r["value"],
                "confidence": r["confidence"],
                "escalation_flag": r["escalation_flag"],
                "escalation_signals": list(
                    r.get("escalation_signals", {}).keys()
                ),
            })

    per_leaf = {}
    for nid, observations in leaf_obs.items():
        char_obs = [o for o in observations if o["kind"] == "char"]
        if not char_obs:
            continue
        values = [o["value"] for o in char_obs]
        confs = [o["confidence"] for o in char_obs]
        esc_count = sum(1 for o in char_obs if o["escalation_flag"])
        signals_all = []
        for o in char_obs:
            signals_all.extend(o["escalation_signals"])
        value_dist = Counter(str(v) for v in values)
        most_common = value_dist.most_common(1)[0]
        per_leaf[nid] = {
            "n_char": len(char_obs),
            "n_short_circuited": sum(1 for o in observations
                                      if o["kind"] == "short_circuited"),
            "value_distribution": dict(value_dist),
            "modal_value": most_common[0],
            "value_consistency": most_common[1] / len(char_obs),
            "confidence_min": min(confs),
            "confidence_max": max(confs),
            "confidence_mean": sum(confs) / len(confs),
            "escalation_rate": esc_count / len(char_obs),
            "signal_counts": dict(Counter(signals_all)),
        }

    return {
        "n_runs": n,
        "disposition_distribution": dict(Counter(dispositions)),
        "modal_disposition": Counter(dispositions).most_common(1)[0][0] if dispositions else None,
        "disposition_consistency": (Counter(dispositions).most_common(1)[0][1] / n) if dispositions else 0,
        "routing_tier_distribution": dict(Counter(routing_tiers)),
        "modal_routing_tier": Counter(routing_tiers).most_common(1)[0][0] if routing_tiers else None,
        "routing_consistency": (Counter(routing_tiers).most_common(1)[0][1] / n) if routing_tiers else 0,
        "secondary_grounds_distribution": dict(
            Counter(str(s) for s in secondary_combos)
        ),
        "confidence": {
            "min": min(confidences), "max": max(confidences),
            "mean": sum(confidences) / len(confidences),
        },
        "substrate_calls": {
            "min": min(substrate_calls), "max": max(substrate_calls),
            "mean": sum(substrate_calls) / len(substrate_calls),
            "stdev": statistics.stdev(substrate_calls) if len(substrate_calls) > 1 else 0,
        },
        "wall_clock_seconds": {
            "min": min(wall_clock), "max": max(wall_clock),
            "mean": sum(wall_clock) / len(wall_clock),
        },
        "escalations_per_run": {
            "min": min(escalations), "max": max(escalations),
            "mean": sum(escalations) / len(escalations),
        },
        "per_leaf": per_leaf,
    }


# =============================================================================
# Cross-case methodology metrics
# =============================================================================

def compute_eval_metrics(per_case_results, artifacts_by_case):
    """Compute the headline metrics from EVAL_SET_METHODOLOGY.md across all
    cases. Requires v2 metadata for the full set; falls back to legacy GT
    fields where v2 metadata is absent."""

    safety_failures = []         # (case_key, run_idx) for AUTO routing on cases expected to escalate
    disposition_matches = []     # 1 if case modal disposition matches GT
    routing_band_matches = []    # 1 if case modal routing within GT band
    leaf_calibration = defaultdict(lambda: {
        "determinable_total": 0,
        "determinable_committed": 0,
        "contested_total": 0,
        "contested_escalated": 0,
        "data_gap_total": 0,
        "data_gap_insufficient": 0,
    })

    per_case_eval = {}

    for case_key, case_stats in per_case_results.items():
        v2_meta = load_v2_metadata(case_key)
        case_artifacts = artifacts_by_case.get(case_key, [])

        gt_disp = None
        gt_routing_band = []
        leaf_expectations = {}

        if v2_meta:
            gt_disp = v2_meta.get("ground_truth", {}).get("disposition")
            gt_routing_band = v2_meta.get("stability_expectation", {}).get(
                "routing_tier_band", [])
            leaf_expectations = v2_meta.get("leaf_expectations", {})
        elif case_artifacts:
            # Legacy: read GT from the run artifact (case_info written it)
            first = case_artifacts[0]
            gt = first.get("ground_truth", {})
            gt_disp = gt.get("expected_disposition")
            expected_routing = gt.get("expected_routing", "")
            # legacy used " or " separator in expected_routing string
            gt_routing_band = [
                t.strip() for t in expected_routing.split(" or ")
            ] if expected_routing else []

        # Disposition match (modal)
        disp_match = None
        if gt_disp:
            disp_match = (case_stats["modal_disposition"] == gt_disp)
            disposition_matches.append(disp_match)

        # Routing band match (modal)
        routing_match = None
        if gt_routing_band:
            routing_match = (case_stats["modal_routing_tier"] in gt_routing_band)
            routing_band_matches.append(routing_match)

        # Safety failures: per-run AUTO on a case where AUTO is not in the GT band
        case_safety_failures = []
        if gt_routing_band and "auto" not in [t.lower() for t in gt_routing_band]:
            for a in case_artifacts:
                if a["determination"]["routing_tier"] == "auto":
                    case_safety_failures.append({
                        "case_key": case_key,
                        "timestamp": a.get("timestamp"),
                        "expected_band": gt_routing_band,
                    })
            safety_failures.extend(case_safety_failures)

        # Per-leaf calibration (v2 only — needs leaf_expectations)
        per_leaf_cal = {}
        if leaf_expectations:
            for nid, expectation in leaf_expectations.items():
                cls = expectation.get("class")
                expected_value = expectation.get("expected_value")
                expected_signal = expectation.get("expected_signal")

                # Per-leaf observed across runs
                observed = case_stats["per_leaf"].get(nid)
                if not observed:
                    continue

                if cls == "determinable":
                    # Substrate should commit (not escalate) with the expected value
                    committed = (1 - observed["escalation_rate"]) * observed["n_char"]
                    leaf_calibration[case_key]["determinable_total"] += observed["n_char"]
                    leaf_calibration[case_key]["determinable_committed"] += committed
                    # Also check value match — modal value should equal expected
                    expected_str = str(expected_value)
                    value_match_count = observed["value_distribution"].get(expected_str, 0)
                    per_leaf_cal[nid] = {
                        "class": cls,
                        "expected": expected_value,
                        "observed_modal_value": observed["modal_value"],
                        "value_consistency": observed["value_consistency"],
                        "escalation_rate": observed["escalation_rate"],
                        "commit_rate": 1 - observed["escalation_rate"],
                        "value_match_count": value_match_count,
                        "n_evaluations": observed["n_char"],
                    }
                elif cls == "contested":
                    leaf_calibration[case_key]["contested_total"] += observed["n_char"]
                    leaf_calibration[case_key]["contested_escalated"] += (
                        observed["escalation_rate"] * observed["n_char"]
                    )
                    per_leaf_cal[nid] = {
                        "class": cls,
                        "expected_signal": expected_signal,
                        "escalation_rate": observed["escalation_rate"],
                        "n_evaluations": observed["n_char"],
                    }
                elif cls == "data_gap":
                    # Should return insufficient_facts (value=None, conf=0)
                    leaf_calibration[case_key]["data_gap_total"] += observed["n_char"]
                    # Count runs where value is None AND insufficient_facts signal fired
                    insuf_count = observed["signal_counts"].get(
                        "insufficient_facts", 0)
                    leaf_calibration[case_key]["data_gap_insufficient"] += insuf_count
                    per_leaf_cal[nid] = {
                        "class": cls,
                        "value_distribution": observed["value_distribution"],
                        "insufficient_facts_rate": insuf_count / observed["n_char"],
                        "n_evaluations": observed["n_char"],
                    }

        per_case_eval[case_key] = {
            "gt_disposition": gt_disp,
            "gt_routing_band": gt_routing_band,
            "modal_disposition_match": disp_match,
            "modal_routing_band_match": routing_match,
            "safety_failures_count": len(case_safety_failures),
            "per_leaf_calibration": per_leaf_cal,
        }

    # Aggregate metrics
    aggregate = {
        "n_cases_with_gt": sum(1 for d in disposition_matches if d is not None),
        "modal_disposition_match_rate": (
            sum(1 for d in disposition_matches if d) / len(disposition_matches)
            if disposition_matches else None
        ),
        "modal_routing_band_match_rate": (
            sum(1 for r in routing_band_matches if r) / len(routing_band_matches)
            if routing_band_matches else None
        ),
        "safety_failure_runs": len(safety_failures),
        "safety_failure_details": safety_failures,
    }

    return aggregate, per_case_eval


# =============================================================================
# Top-level analysis
# =============================================================================

def analyze(session, artifacts):
    """Group artifacts by case, run per-case analysis, compute cross-case
    metrics."""

    artifacts_by_case = defaultdict(list)
    for a in artifacts:
        artifacts_by_case[a["case_key"]].append(a)

    per_case = {}
    for case_key, case_arts in artifacts_by_case.items():
        per_case[case_key] = analyze_one_case(case_key, case_arts)

    aggregate, per_case_eval = compute_eval_metrics(per_case, artifacts_by_case)

    return {
        "session_id": session["session_id"],
        "model": session["model"],
        "n_runs_per_case": session.get("n_runs_per_case",
                                        session.get("n_runs")),
        "total_runs": len(artifacts),
        "case_keys": list(artifacts_by_case.keys()),
        "per_case": per_case,
        "per_case_eval": per_case_eval,
        "aggregate": aggregate,
    }


# =============================================================================
# Rendering
# =============================================================================

def render_markdown(analysis, session, artifacts):
    L = []
    p = L.append
    p(f"# Variance Analysis — Session `{analysis['session_id']}`")
    p("")
    p(f"- **Model:** `{analysis['model']}`")
    p(f"- **Cases:** {', '.join(analysis['case_keys'])}")
    p(f"- **Runs per case:** {analysis['n_runs_per_case']}")
    p(f"- **Total runs:** {analysis['total_runs']}")
    p(f"- **Started:** {session.get('started_at', '?')}")
    p(f"- **Completed:** {session.get('completed_at', '?')}")
    p("")

    agg = analysis["aggregate"]
    p("## Headline metrics (per EVAL_SET_METHODOLOGY.md §6)")
    p("")
    p(f"- **Safety failure rate:** **{agg['safety_failure_runs']} runs** "
      f"routed AUTO on cases expected to escalate "
      f"(target: 0)")
    if agg["safety_failure_runs"] > 0:
        p("  - Cases with safety failures:")
        sf_by_case = Counter(
            f["case_key"] for f in agg["safety_failure_details"]
        )
        for ck, count in sf_by_case.items():
            p(f"    - `{ck}`: {count} failure(s)")
    if agg["modal_disposition_match_rate"] is not None:
        p(f"- **Modal disposition match rate:** "
          f"**{agg['modal_disposition_match_rate']:.0%}** "
          f"({agg['n_cases_with_gt']} cases with GT) "
          f"(target: ≥70%)")
    if agg["modal_routing_band_match_rate"] is not None:
        p(f"- **Modal routing-band match rate:** "
          f"**{agg['modal_routing_band_match_rate']:.0%}** "
          f"(target: ≥85%)")
    p("")

    p("## Per-case summary")
    p("")
    p("| Case | n | Modal disp. | Disp. consist. | Modal tier | Tier consist. | GT match (disp/tier) | Safety fail |")
    p("|---|---|---|---|---|---|---|---|")
    for case_key, case_stats in analysis["per_case"].items():
        ev = analysis["per_case_eval"][case_key]
        dm = "✓" if ev["modal_disposition_match"] else ("✗" if ev["modal_disposition_match"] is False else "—")
        rm = "✓" if ev["modal_routing_band_match"] else ("✗" if ev["modal_routing_band_match"] is False else "—")
        sf = ev["safety_failures_count"]
        sf_mark = f"**{sf}** ⚠️" if sf > 0 else "0"
        p(f"| `{case_key}` | {case_stats['n_runs']} | "
          f"`{case_stats['modal_disposition']}` | "
          f"{case_stats['disposition_consistency']:.0%} | "
          f"`{case_stats['modal_routing_tier']}` | "
          f"{case_stats['routing_consistency']:.0%} | "
          f"{dm} / {rm} | {sf_mark} |")
    p("")

    # Per-case detail sections
    for case_key, case_stats in analysis["per_case"].items():
        ev = analysis["per_case_eval"][case_key]
        p(f"## Case: `{case_key}`")
        p("")
        if ev["gt_disposition"]:
            p(f"- **GT disposition:** `{ev['gt_disposition']}`")
        if ev["gt_routing_band"]:
            p(f"- **GT routing band:** {ev['gt_routing_band']}")
        p("")

        p("### Distributions across runs")
        p("")
        p("**Dispositions:**")
        for disp, count in sorted(case_stats["disposition_distribution"].items(),
                                    key=lambda x: -x[1]):
            pct = count / case_stats["n_runs"] * 100
            p(f"- `{disp}`: {count}/{case_stats['n_runs']} ({pct:.0f}%)")
        p("")
        p("**Routing tiers:**")
        for tier, count in sorted(case_stats["routing_tier_distribution"].items(),
                                    key=lambda x: -x[1]):
            pct = count / case_stats["n_runs"] * 100
            p(f"- `{tier}`: {count}/{case_stats['n_runs']} ({pct:.0f}%)")
        p("")
        sc = case_stats["substrate_calls"]
        wc = case_stats["wall_clock_seconds"]
        es = case_stats["escalations_per_run"]
        p(f"**Substrate calls:** min={sc['min']}, max={sc['max']}, "
          f"mean={sc['mean']:.1f}, stdev={sc['stdev']:.1f}")
        p(f"**Wall clock:** min={wc['min']:.1f}s, max={wc['max']:.1f}s, "
          f"mean={wc['mean']:.1f}s")
        p(f"**Escalations/run:** min={es['min']}, max={es['max']}, "
          f"mean={es['mean']:.1f}")
        p("")

        # Per-leaf consistency, sorted by most variable first
        p("### Per-leaf consistency")
        p("")
        leaves = case_stats["per_leaf"]
        sorted_leaves = sorted(
            leaves.items(),
            key=lambda kv: (kv[1]["value_consistency"], -kv[1]["escalation_rate"])
        )
        p("| Leaf | N | Value dist | Modal | Consist | Esc rate | Conf |")
        p("|---|---|---|---|---|---|---|")
        for nid, stats in sorted_leaves:
            vd = ", ".join(f"{v}:{n}" for v, n in stats["value_distribution"].items())
            marker = " ⚠️" if stats["value_consistency"] < 1.0 else ""
            p(f"| `{nid}`{marker} | {stats['n_char']} | {vd} | "
              f"`{stats['modal_value']}` | {stats['value_consistency']:.2f} | "
              f"{stats['escalation_rate']:.2f} | "
              f"{stats['confidence_min']:.2f}–{stats['confidence_max']:.2f} |")
        p("")

        # If v2 metadata, render per-leaf calibration
        if ev["per_leaf_calibration"]:
            p("### Per-leaf calibration (vs evaluation_metadata expectations)")
            p("")
            cal = ev["per_leaf_calibration"]
            # Group by class
            by_class = defaultdict(list)
            for nid, info in cal.items():
                by_class[info["class"]].append((nid, info))

            if by_class.get("determinable"):
                p("**Determinable leaves** (expected: substrate commits with specified value):")
                p("")
                p("| Leaf | Expected | Modal observed | Value match | Commit rate |")
                p("|---|---|---|---|---|")
                for nid, info in sorted(by_class["determinable"]):
                    vm = (f"{info['value_match_count']}/{info['n_evaluations']}")
                    p(f"| `{nid}` | `{info['expected']}` | "
                      f"`{info['observed_modal_value']}` | {vm} | "
                      f"{info['commit_rate']:.2f} |")
                p("")
            if by_class.get("contested"):
                p("**Contested leaves** (expected: substrate escalates):")
                p("")
                for nid, info in sorted(by_class["contested"]):
                    p(f"- `{nid}`: escalation rate = "
                      f"{info['escalation_rate']:.2f} "
                      f"({info['n_evaluations']} evaluations)")
                p("")
            if by_class.get("data_gap"):
                p("**Data-gap leaves** (expected: insufficient_facts signal):")
                p("")
                for nid, info in sorted(by_class["data_gap"]):
                    p(f"- `{nid}`: insufficient_facts rate = "
                      f"{info['insufficient_facts_rate']:.2f}")
                p("")

        # Signal patterns
        sig_lines = []
        for nid, stats in sorted_leaves:
            if stats["signal_counts"]:
                sigs = ", ".join(f"{s}:{n}" for s, n in stats["signal_counts"].items())
                sig_lines.append(f"- `{nid}`: {sigs}")
        if sig_lines:
            p("### Escalation signals observed")
            p("")
            for line in sig_lines:
                p(line)
            p("")

    return "\n".join(L)


def main():
    if len(sys.argv) > 1:
        session_id = sys.argv[1]
    else:
        session_id = find_latest_session()

    print(f"Analyzing session: {session_id}")
    session, artifacts = load_session(session_id)
    if not artifacts:
        raise SystemExit("No artifacts for this session.")

    analysis = analyze(session, artifacts)

    json_path = _RUNS / f"variance_analysis_{session_id}.json"
    md_path = _RUNS / f"variance_analysis_{session_id}.md"

    json_path.write_text(json.dumps(analysis, indent=2, default=str))
    md_path.write_text(render_markdown(analysis, session, artifacts))

    print(f"  JSON:     {json_path}")
    print(f"  Markdown: {md_path}")
    print()

    agg = analysis["aggregate"]
    print("HEADLINE METRICS")
    print("=" * 70)
    print(f"Cases:                         {len(analysis['case_keys'])}")
    print(f"Total runs:                    {analysis['total_runs']}")
    print(f"Safety failures:               {agg['safety_failure_runs']} (target: 0)")
    if agg["modal_disposition_match_rate"] is not None:
        print(f"Modal disposition match rate:  "
              f"{agg['modal_disposition_match_rate']:.0%} "
              f"(target: ≥70%)")
    if agg["modal_routing_band_match_rate"] is not None:
        print(f"Modal routing band match rate: "
              f"{agg['modal_routing_band_match_rate']:.0%} "
              f"(target: ≥85%)")
    print()
    print("PER-CASE")
    print("=" * 70)
    for case_key, stats in analysis["per_case"].items():
        ev = analysis["per_case_eval"][case_key]
        sf_str = f"SAFETY:{ev['safety_failures_count']}!" if ev["safety_failures_count"] > 0 else ""
        print(f"  {case_key}: disp={stats['modal_disposition']} "
              f"({stats['disposition_consistency']:.0%}), "
              f"tier={stats['modal_routing_tier']} "
              f"({stats['routing_consistency']:.0%}) {sf_str}")
    print()
    print(f"Full report: {md_path.name}")


if __name__ == "__main__":
    main()

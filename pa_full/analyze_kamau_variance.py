"""
Analyze a variance session: read all artifacts produced by run_kamau_n_times.py
for a given session_id, compute per-leaf consistency stats and run-level
distributions, write structured analysis JSON + human-readable Markdown.

Usage:
    python3 analyze_kamau_variance.py <session_id>
    python3 analyze_kamau_variance.py            # most recent session

Outputs:
    runs/variance_analysis_<session_id>.json    structured analysis
    runs/variance_analysis_<session_id>.md      human-readable report
"""

import sys
import json
import statistics
from pathlib import Path
from collections import Counter, defaultdict

_HERE = Path(__file__).resolve().parent
_RUNS = _HERE / "runs"


def load_session(session_id):
    """Load the session log and the per-run artifacts it produced."""
    session_path = _RUNS / f"variance_session_{session_id}.json"
    session = json.loads(session_path.read_text())
    artifacts = []
    for run in session["runs"]:
        if "artifact" in run:
            art_path = _RUNS / run["artifact"]
            if art_path.exists():
                artifacts.append(json.loads(art_path.read_text()))
    return session, artifacts


def find_latest_session():
    files = sorted(_RUNS.glob("variance_session_*.json"))
    if not files:
        raise SystemExit("No variance sessions found in runs/")
    name = files[-1].stem
    return name.replace("variance_session_", "")


def analyze(session, artifacts):
    """Compute distributions and per-leaf stats."""
    n = len(artifacts)

    # Headline distributions
    dispositions = [a["determination"]["disposition"] for a in artifacts]
    routing_tiers = [a["determination"]["routing_tier"] for a in artifacts]
    secondary_grounds_lists = [
        tuple(sorted(a["determination"]["secondary_grounds"])) for a in artifacts
    ]
    confidences = [a["determination"]["confidence"] for a in artifacts]
    substrate_calls = [a["run_stats"]["substrate_calls"] for a in artifacts]
    wall_clock = [a["run_stats"]["wall_clock_seconds"] for a in artifacts]
    escalations = [a["run_stats"]["escalations"] for a in artifacts]

    # Per-leaf stats: for every char leaf that was evaluated in any run,
    # collect (value, confidence, escalation_flag, signals) across runs.
    leaf_observations = defaultdict(list)
    for run_index, a in enumerate(artifacts):
        trace = a["determination"]["trace"]
        for nid, r in trace.items():
            # Only track nodes that had a real evaluation (not short-circuited,
            # not pure compose-from-children-only)
            if r["short_circuited"]:
                # Track that it was short-circuited in this run
                leaf_observations[nid].append({
                    "run_index": run_index,
                    "kind": "short_circuited",
                })
                continue
            # Distinguish between "char leaf evaluated by substrate" and
            # "compose computed from children". The reasoning text for compose
            # nodes typically contains "AND" or "OR" markers; substrate-evaluated
            # leaves have substantive reasoning content.
            reasoning = r.get("reasoning", "")
            is_compose_result = (
                "AND short-circuit" in reasoning
                or "OR short-circuit" in reasoning
                or "AND of" in reasoning
                or "OR of" in reasoning
                or reasoning == "root node — routing logic applies"
            )
            leaf_observations[nid].append({
                "run_index": run_index,
                "kind": "compose" if is_compose_result else "char",
                "value": r["value"],
                "confidence": r["confidence"],
                "escalation_flag": r["escalation_flag"],
                "escalation_signals": list(
                    r.get("escalation_signals", {}).keys()
                ),
            })

    # Per-leaf summary stats — separate char leaves from compose nodes
    per_leaf = {}
    for nid, obs_list in leaf_observations.items():
        if not obs_list:
            continue
        kinds = Counter(o["kind"] for o in obs_list)
        char_obs = [o for o in obs_list if o["kind"] == "char"]
        compose_obs = [o for o in obs_list if o["kind"] == "compose"]
        sc_obs = [o for o in obs_list if o["kind"] == "short_circuited"]

        summary = {
            "node_id": nid,
            "n_observations": len(obs_list),
            "n_char_evaluated": len(char_obs),
            "n_composed": len(compose_obs),
            "n_short_circuited": len(sc_obs),
        }

        # Only compute value/confidence stats on char evaluations
        if char_obs:
            values = [o["value"] for o in char_obs]
            confidences = [o["confidence"] for o in char_obs]
            escalation_count = sum(1 for o in char_obs if o["escalation_flag"])
            signals_all = []
            for o in char_obs:
                signals_all.extend(o["escalation_signals"])
            summary["char"] = {
                "value_distribution": dict(Counter(
                    str(v) for v in values  # str() for JSON-safe keys
                )),
                "confidence_min": min(confidences),
                "confidence_max": max(confidences),
                "confidence_mean": sum(confidences) / len(confidences),
                "escalation_rate": escalation_count / len(char_obs),
                "signal_counts": dict(Counter(signals_all)),
            }
            # Consistency rating: 1.0 if all values identical, else lower
            value_counts = Counter(str(v) for v in values)
            most_common_count = value_counts.most_common(1)[0][1]
            summary["char"]["value_consistency"] = most_common_count / len(values)

        if compose_obs:
            comp_values = [o["value"] for o in compose_obs]
            comp_escalations = sum(1 for o in compose_obs if o["escalation_flag"])
            summary["compose"] = {
                "value_distribution": dict(Counter(
                    str(v) for v in comp_values
                )),
                "escalation_rate": comp_escalations / len(compose_obs),
            }

        per_leaf[nid] = summary

    analysis = {
        "session_id": session["session_id"],
        "case_key": session["case_key"],
        "model": session["model"],
        "n_runs": n,
        "headline": {
            "disposition_distribution": dict(Counter(dispositions)),
            "routing_tier_distribution": dict(Counter(routing_tiers)),
            "secondary_grounds_distribution": dict(
                Counter(str(s) for s in secondary_grounds_lists)
            ),
            "confidence": {
                "min": min(confidences) if confidences else None,
                "max": max(confidences) if confidences else None,
                "mean": (sum(confidences) / len(confidences)) if confidences else None,
            },
            "substrate_calls": {
                "min": min(substrate_calls),
                "max": max(substrate_calls),
                "mean": sum(substrate_calls) / len(substrate_calls),
                "stdev": statistics.stdev(substrate_calls) if len(substrate_calls) > 1 else 0,
            },
            "wall_clock_seconds": {
                "min": min(wall_clock),
                "max": max(wall_clock),
                "mean": sum(wall_clock) / len(wall_clock),
            },
            "escalations_per_run": {
                "min": min(escalations),
                "max": max(escalations),
                "mean": sum(escalations) / len(escalations),
            },
        },
        "per_leaf": per_leaf,
    }

    return analysis


def render_markdown(analysis, session, artifacts):
    """Build a human-readable markdown report."""
    lines = []
    lines.append(f"# Variance Analysis: {analysis['case_key']} × {analysis['n_runs']} runs")
    lines.append("")
    lines.append(f"- **Session:** `{analysis['session_id']}`")
    lines.append(f"- **Model:** `{analysis['model']}`")
    lines.append(f"- **Runs:** {analysis['n_runs']}")
    lines.append(f"- **Started:** {session.get('started_at', '?')}")
    lines.append(f"- **Completed:** {session.get('completed_at', '?')}")
    lines.append("")

    h = analysis["headline"]
    lines.append("## Headline distributions")
    lines.append("")
    lines.append("### Dispositions")
    for disp, count in sorted(h["disposition_distribution"].items(),
                               key=lambda x: -x[1]):
        pct = count / analysis["n_runs"] * 100
        lines.append(f"- `{disp}`: **{count}/{analysis['n_runs']}** ({pct:.0f}%)")
    lines.append("")
    lines.append("### Routing tiers")
    for tier, count in sorted(h["routing_tier_distribution"].items(),
                               key=lambda x: -x[1]):
        pct = count / analysis["n_runs"] * 100
        lines.append(f"- `{tier}`: **{count}/{analysis['n_runs']}** ({pct:.0f}%)")
    lines.append("")
    lines.append("### Secondary grounds (combinations)")
    for combo, count in sorted(h["secondary_grounds_distribution"].items(),
                                key=lambda x: -x[1]):
        lines.append(f"- {combo}: {count}/{analysis['n_runs']}")
    lines.append("")
    lines.append("### Run statistics")
    lines.append(f"- **Substrate calls:** min={h['substrate_calls']['min']}, "
                 f"max={h['substrate_calls']['max']}, "
                 f"mean={h['substrate_calls']['mean']:.1f}, "
                 f"stdev={h['substrate_calls']['stdev']:.1f}")
    lines.append(f"- **Wall clock (s):** min={h['wall_clock_seconds']['min']:.1f}, "
                 f"max={h['wall_clock_seconds']['max']:.1f}, "
                 f"mean={h['wall_clock_seconds']['mean']:.1f}")
    lines.append(f"- **Escalations per run:** min={h['escalations_per_run']['min']}, "
                 f"max={h['escalations_per_run']['max']}, "
                 f"mean={h['escalations_per_run']['mean']:.1f}")
    lines.append(f"- **Overall confidence:** min={h['confidence']['min']:.2f}, "
                 f"max={h['confidence']['max']:.2f}, "
                 f"mean={h['confidence']['mean']:.2f}")
    lines.append("")

    lines.append("## Per-run summary table")
    lines.append("")
    lines.append("| # | Disposition | Tier | Conf | Calls | Esc | Wall |")
    lines.append("|---|---|---|---|---|---|---|")
    for run_idx, a in enumerate(artifacts, 1):
        d = a["determination"]
        s = a["run_stats"]
        lines.append(f"| {run_idx} | `{d['disposition']}` | "
                     f"`{d['routing_tier']}` | {d['confidence']:.2f} | "
                     f"{s['substrate_calls']} | {s['escalations']} | "
                     f"{s['wall_clock_seconds']:.1f}s |")
    lines.append("")

    lines.append("## Per-leaf consistency (char-evaluated leaves only)")
    lines.append("")
    lines.append("Sorted by consistency (lowest first — most variable leaves at top).")
    lines.append("")
    char_leaves = {
        nid: stats for nid, stats in analysis["per_leaf"].items()
        if "char" in stats and stats["n_char_evaluated"] >= 1
    }
    sorted_leaves = sorted(
        char_leaves.items(),
        key=lambda kv: (kv[1]["char"]["value_consistency"],
                        kv[1]["char"]["escalation_rate"])
    )
    lines.append("| Leaf | N evals | Value dist | Consistency | Esc rate | Conf range |")
    lines.append("|---|---|---|---|---|---|")
    for nid, stats in sorted_leaves:
        c = stats["char"]
        vd = ", ".join(f"{v}:{n}" for v, n in c["value_distribution"].items())
        consistency = c["value_consistency"]
        marker = ""
        if consistency < 1.0:
            marker = " ⚠️"
        lines.append(f"| `{nid}`{marker} | {stats['n_char_evaluated']} | {vd} | "
                     f"{consistency:.2f} | {c['escalation_rate']:.2f} | "
                     f"{c['confidence_min']:.2f}–{c['confidence_max']:.2f} |")
    lines.append("")

    lines.append("## Per-leaf signal patterns (when escalation fires)")
    lines.append("")
    any_signals = False
    for nid, stats in sorted_leaves:
        sc = stats["char"]["signal_counts"]
        if sc:
            any_signals = True
            sig_str = ", ".join(f"{s}:{n}" for s, n in sc.items())
            lines.append(f"- `{nid}`: {sig_str}")
    if not any_signals:
        lines.append("(No escalation signals fired in any run for any leaf.)")
    lines.append("")

    # Stability classification
    lines.append("## Stability classification")
    lines.append("")
    stable = [nid for nid, s in char_leaves.items()
              if s["char"]["value_consistency"] == 1.0
              and s["char"]["escalation_rate"] == 0.0]
    value_variable = [nid for nid, s in char_leaves.items()
                      if s["char"]["value_consistency"] < 1.0]
    escalation_variable = [nid for nid, s in char_leaves.items()
                            if s["char"]["value_consistency"] == 1.0
                            and 0.0 < s["char"]["escalation_rate"] < 1.0]
    always_escalated = [nid for nid, s in char_leaves.items()
                         if s["char"]["escalation_rate"] == 1.0]

    lines.append(f"- **Fully stable (same value, never escalated)**: "
                 f"{len(stable)} leaves")
    for nid in sorted(stable):
        lines.append(f"  - `{nid}`")
    lines.append(f"- **Value-variable (substrate returns different values "
                 f"across runs)**: {len(value_variable)} leaves")
    for nid in sorted(value_variable):
        v = char_leaves[nid]["char"]["value_distribution"]
        lines.append(f"  - `{nid}` — {v}")
    lines.append(f"- **Escalation-variable (same value but sometimes "
                 f"escalates)**: {len(escalation_variable)} leaves")
    for nid in sorted(escalation_variable):
        r = char_leaves[nid]["char"]["escalation_rate"]
        lines.append(f"  - `{nid}` — escalates {r:.0%} of runs")
    lines.append(f"- **Always escalated**: {len(always_escalated)} leaves")
    for nid in sorted(always_escalated):
        lines.append(f"  - `{nid}`")

    return "\n".join(lines)


def main():
    if len(sys.argv) > 1:
        session_id = sys.argv[1]
    else:
        session_id = find_latest_session()

    print(f"Analyzing session: {session_id}")
    session, artifacts = load_session(session_id)
    if not artifacts:
        raise SystemExit("No artifacts found for this session.")

    analysis = analyze(session, artifacts)

    # Write JSON
    json_path = _RUNS / f"variance_analysis_{session_id}.json"
    json_path.write_text(json.dumps(analysis, indent=2, default=str))

    # Write markdown
    md_path = _RUNS / f"variance_analysis_{session_id}.md"
    md_path.write_text(render_markdown(analysis, session, artifacts))

    print(f"  JSON:     {json_path}")
    print(f"  Markdown: {md_path}")
    print()

    # Print headline summary to console
    h = analysis["headline"]
    print("HEADLINE")
    print("=" * 60)
    print("Dispositions:")
    for disp, count in sorted(h["disposition_distribution"].items(),
                               key=lambda x: -x[1]):
        print(f"  {disp}: {count}/{analysis['n_runs']}")
    print()
    print("Routing tiers:")
    for tier, count in sorted(h["routing_tier_distribution"].items(),
                               key=lambda x: -x[1]):
        print(f"  {tier}: {count}/{analysis['n_runs']}")
    print()
    print(f"Substrate calls:  min={h['substrate_calls']['min']}, "
          f"max={h['substrate_calls']['max']}, "
          f"mean={h['substrate_calls']['mean']:.1f}")
    print(f"Wall clock:       min={h['wall_clock_seconds']['min']:.1f}s, "
          f"max={h['wall_clock_seconds']['max']:.1f}s")
    print(f"Escalations:      min={h['escalations_per_run']['min']}, "
          f"max={h['escalations_per_run']['max']}, "
          f"mean={h['escalations_per_run']['mean']:.1f}")
    print()
    print(f"Full report: {md_path.name}")


if __name__ == "__main__":
    main()

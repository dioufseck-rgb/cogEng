"""
run_all_probes.py — execute all four architectural probes in sequence.

Each probe is bounded and independent. Running them sequentially gives
us a complete diagnostic of the architecture's coverage of the three
flagged constructs (conditional arithmetic, rule reclassification,
table-driven gating) plus a cross-domain check on FINRA Rule 4210.

Each probe writes its full audit log (every prompt + every response) to
tests/probes/audit_logs/{probe_name}_audit.json. This script
additionally writes a summary at tests/probes/audit_logs/SUMMARY.md.

USAGE:
    export ANTHROPIC_API_KEY=sk-ant-...
    python tests/probes/run_all_probes.py

ESTIMATED TOTAL COST: ~$40-52 across the four probes at Opus 4.7.
"""
from __future__ import annotations
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import probe_1_conditional_arithmetic as p1
import probe_2_reclassification as p2
import probe_3_table_gating as p3
import probe_4_cross_domain_finra as p4


PROBES = [
    ("probe_1_conditional_arithmetic", p1),
    ("probe_2_reclassification", p2),
    ("probe_3_table_gating", p3),
    ("probe_4_cross_domain_finra", p4),
]


def main():
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")):
        print("ERROR: set ANTHROPIC_API_KEY (or CLAUDE_API_KEY)")
        sys.exit(2)

    results: list[dict] = []
    started_at = time.time()

    print("\n" + "#" * 75)
    print("# RUNNING ALL FOUR ARCHITECTURAL PROBES")
    print("#" * 75)
    print(f"# Estimated total cost: ~$40-52 at Opus 4.7")
    print(f"# Estimated total runtime: 5-15 minutes")
    print("#" * 75)

    for name, mod in PROBES:
        print(f"\n\n{'#' * 75}")
        print(f"# STARTING: {name}")
        print("#" * 75)
        try:
            t0 = time.time()
            result = mod.main()
            elapsed = time.time() - t0
            results.append({
                "name": name,
                "ok": True,
                "elapsed_seconds": round(elapsed, 1),
                "decompose_ok": result.decompose_ok,
                "stage4_ok": result.stage4_ok,
                "stage4_error": result.stage4_error,
                "llm_calls": result.llm_call_count,
                "inventory": result.inventory,
                "atoms_count": len(result.atoms_registered) if result.atoms_registered else 0,
            })
        except Exception as e:
            print(f"\n  PROBE FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
            results.append({
                "name": name,
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
            })

    total_elapsed = time.time() - started_at

    # ----- Write summary -----
    audit_dir = os.path.join(HERE, "audit_logs")
    os.makedirs(audit_dir, exist_ok=True)
    summary_path = os.path.join(audit_dir, "SUMMARY.md")

    lines = ["# Architectural Probe Summary", ""]
    lines.append(f"Total runtime: {total_elapsed:.1f} seconds")
    lines.append(f"Probes run: {len(results)}")
    lines.append("")

    for r in results:
        lines.append(f"## {r['name']}")
        lines.append("")
        if not r.get("ok"):
            lines.append(f"  - **FAILED**: {r.get('error')}")
        else:
            lines.append(f"  - Elapsed: {r['elapsed_seconds']}s")
            lines.append(f"  - LLM calls: {r['llm_calls']}")
            lines.append(f"  - Decomposition: {'OK' if r['decompose_ok'] else 'FAILED'}")
            stg4 = "OK" if r["stage4_ok"] else "FAILED" if r["decompose_ok"] else "SKIPPED"
            lines.append(f"  - Stage-4 conversion: {stg4}")
            if r["stage4_error"]:
                lines.append(f"    - Error: `{r['stage4_error']}`")
            if r["inventory"]:
                inv = {k: v for k, v in r["inventory"].items() if v > 0}
                lines.append(f"  - Spec inventory: `{inv}`")
            lines.append(f"  - Atoms registered: {r['atoms_count']}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Reading guide")
    lines.append("")
    lines.append("Each probe writes a full audit log at "
                 "`tests/probes/audit_logs/{probe_name}_audit.json` "
                 "containing every prompt sent and every response received.")
    lines.append("")
    lines.append("For each probe, the diagnostic questions are printed at the "
                 "end of its run output. Review the spec tree and atoms-"
                 "registered output against those questions to determine "
                 "whether the construct is expressible in the current "
                 "architecture.")
    lines.append("")
    lines.append("Update `docs/STATE_OF_RULEKIT.md` §6 (Architectural "
                 "Unknowns) with the findings — converting each unknown "
                 "into a 'Probed Unknown' with named evidence.")

    with open(summary_path, "w") as f:
        f.write("\n".join(lines))

    print("\n\n" + "#" * 75)
    print(f"# ALL PROBES COMPLETE — Total runtime: {total_elapsed:.1f}s")
    print(f"# Summary written to: {summary_path}")
    print("#" * 75)


if __name__ == "__main__":
    main()

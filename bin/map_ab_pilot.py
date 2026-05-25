"""
map_ab_pilot.py — 3-case Sonnet 4.6 vs Opus 4.7 Map A/B for production-economics signal.

The architectural rationale: Build is a once-per-policy task (~$30-50)
amortizing over all subsequent adjudications, so it deserves a frontier
model. Map is per-atom-per-case (~$0.10-2/case depending on atom count),
scaling linearly with case volume, so its model choice is the actual
production-economics knob. This pilot tells us whether Sonnet matches
Opus closely enough on this task class to justify deployment cost.

Specifically:
  - Run the same 3 pilot cases through both Sonnet 4.6 and Opus 4.7
  - For each case, compute atom-level diff:
      * Atoms where models agree → high agreement → good signal
      * Atoms where models disagree → flagged for inspection
  - Compute disposition-level agreement (do both models lead to the
    same RuleKit adjudication?)

The state doc finding then:
  - If atom-level agreement ≥95% on pilot → scale 15 cases on Sonnet
  - If atom-level agreement <95% → scale on Opus, document tradeoff

USAGE:
    # First, run the case selector to choose pilot cases:
    python bin/select_pilot_cases.py --out pilot_cases.json

    # Then run the A/B:
    python bin/map_ab_pilot.py \
        --built built_nba.pkl \
        --cases RuleArena/nba/annotated_problems/comp_0.json \
        --aliases domains/nba/ruleArena_family_aliases.yaml \
        --pilot-cases pilot_cases.json \
        --out-dir audits/pilot_ab/

Cost: $5-10 (3 cases × ~57 atoms × 2 models × $0.01-0.05/call).
"""
from __future__ import annotations
import argparse
import json
import os
import pickle
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

# Reuse adjudicate_cases' helpers
sys.path.insert(0, _HERE)
from adjudicate_cases import (
    adjudicate_case, build_typed_atoms_from_dag, load_alias_table,
    case_is_in_scope,
)
from rulekit.cases.rulearena_adapter import load_ruleArena_cases
from rulekit.map.typed import TypedNarrativeLLMSubstrate
from rulekit.build.decomposer import LLMCaller


def diff_atom_bindings(a_bindings: dict, b_bindings: dict) -> dict:
    """Compute atom-level diff between two FactBundle.values dicts.

    Each binding is the dict produced by adjudicate_cases.numeric_value_to_dict:
        {"type": "kleene", "value": "TRUE"} or
        {"type": "numeric", "value": "35000000"}

    Returns:
        {
          "agree": [atom_ids where values match exactly],
          "agree_both_undetermined": [...],
          "disagree": [{"atom_id": ..., "a_value": ..., "b_value": ...}],
        }
    """
    all_ids = set(a_bindings.keys()) | set(b_bindings.keys())
    agree = []
    agree_both_und = []
    disagree = []
    for aid in sorted(all_ids):
        a = a_bindings.get(aid)
        b = b_bindings.get(aid)
        if a is None or b is None:
            disagree.append({
                "atom_id": aid, "a_value": a, "b_value": b,
                "reason": "missing in one model",
            })
            continue
        # Compare type+value
        a_type, a_val = a.get("type"), a.get("value")
        b_type, b_val = b.get("type"), b.get("value")
        if a_type == b_type and a_val == b_val:
            if a_val == "UNDETERMINED":
                agree_both_und.append(aid)
            else:
                agree.append(aid)
        else:
            disagree.append({
                "atom_id": aid,
                "a_value": a, "b_value": b,
            })
    return {
        "agree": agree,
        "agree_both_undetermined": agree_both_und,
        "disagree": disagree,
        "agreement_rate": (
            (len(agree) + len(agree_both_und)) /
            max(len(all_ids), 1)
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="3-case A/B pilot: Sonnet vs Opus for Map."
    )
    parser.add_argument("--built", required=True)
    parser.add_argument("--cases", required=True,
                        help="RuleArena case JSON file")
    parser.add_argument("--aliases", required=True)
    parser.add_argument("--pilot-cases", required=True,
                        help="JSON file from bin/select_pilot_cases.py "
                             "listing the 3 case_ids to run")
    parser.add_argument("--model-a", default="claude-sonnet-4-6")
    parser.add_argument("--model-b", default="claude-opus-4-7")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--out-dir", default="audits/pilot_ab",
                        help="Output directory (default: audits/pilot_ab)")
    args = parser.parse_args()

    # Load pilot case selection
    with open(args.pilot_cases, encoding="utf-8") as f:
        pilot_data = json.load(f)
    pilot_case_ids = set(pilot_data["selected_case_ids"])
    print(f"Pilot cases ({len(pilot_case_ids)}): "
          f"{', '.join(sorted(pilot_case_ids))}")

    # Load artifacts
    with open(args.built, "rb") as f:
        build = pickle.load(f)
    aliases = load_alias_table(args.aliases)
    all_cases = load_ruleArena_cases(args.cases, only_single_op=True)
    cases = [c for c in all_cases if c.case_id in pilot_case_ids]
    if len(cases) != len(pilot_case_ids):
        missing = pilot_case_ids - {c.case_id for c in cases}
        print(f"WARNING: pilot case_ids not found: {missing}")

    typed_atoms = build_typed_atoms_from_dag(build.atoms)

    os.makedirs(args.out_dir, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Run each case through both models
    print()
    print("=" * 70)
    print(f"Running {len(cases)} cases through {args.model_a} and {args.model_b}")
    print(f"  batch_size={args.batch_size}")
    print("=" * 70)

    per_case_results = []

    for i, case in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] {case.case_id} "
              f"(is_illegal={case.ground_truth['is_illegal']})")

        # Model A
        print(f"  Running {args.model_a}...")
        llm_a = LLMCaller(model=args.model_a)
        sub_a = TypedNarrativeLLMSubstrate(
            llm=llm_a, batch_size=args.batch_size if args.batch_size > 0 else None
        )
        try:
            audit_a = adjudicate_case(case, build, aliases, sub_a, typed_atoms)
        except Exception as e:
            print(f"    ERROR: {e}")
            audit_a = {"case_id": case.case_id, "error": str(e)}

        # Model B
        print(f"  Running {args.model_b}...")
        llm_b = LLMCaller(model=args.model_b)
        sub_b = TypedNarrativeLLMSubstrate(
            llm=llm_b, batch_size=args.batch_size if args.batch_size > 0 else None
        )
        try:
            audit_b = adjudicate_case(case, build, aliases, sub_b, typed_atoms)
        except Exception as e:
            print(f"    ERROR: {e}")
            audit_b = {"case_id": case.case_id, "error": str(e)}

        # Diff
        if "error" not in audit_a and "error" not in audit_b:
            atom_diff = diff_atom_bindings(
                audit_a.get("atom_bindings", {}),
                audit_b.get("atom_bindings", {}),
            )
            disp_a = audit_a["rulekit"]["disposition"]
            disp_b = audit_b["rulekit"]["disposition"]
            disp_agree = (disp_a == disp_b)
            print(f"  Atom-level agreement: "
                  f"{len(atom_diff['agree'])}+{len(atom_diff['agree_both_undetermined'])} agree, "
                  f"{len(atom_diff['disagree'])} disagree "
                  f"({100 * atom_diff['agreement_rate']:.1f}%)")
            print(f"  Disposition: {args.model_a}={disp_a}, "
                  f"{args.model_b}={disp_b} "
                  f"({'AGREE' if disp_agree else 'DISAGREE'})")
        else:
            atom_diff = None
            disp_agree = None

        # Save per-case A/B output
        case_out = {
            "case_id": case.case_id,
            "ground_truth_is_illegal": case.ground_truth["is_illegal"],
            "model_a": {
                "name": args.model_a,
                "audit": audit_a,
            },
            "model_b": {
                "name": args.model_b,
                "audit": audit_b,
            },
            "atom_diff": atom_diff,
            "disposition_agreement": disp_agree,
        }
        out_path = os.path.join(
            args.out_dir, f"case_{case.case_id}_{run_id}.json"
        )
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(case_out, f, indent=2)
        per_case_results.append(case_out)

    # Aggregate summary
    print()
    print("=" * 70)
    print("PILOT A/B SUMMARY")
    print("=" * 70)
    total_atoms = 0
    total_agree = 0
    total_disagree = 0
    disposition_agreements = 0
    successful_runs = 0
    for r in per_case_results:
        if r["atom_diff"] is None:
            continue
        successful_runs += 1
        d = r["atom_diff"]
        n = len(d["agree"]) + len(d["agree_both_undetermined"]) + len(d["disagree"])
        total_atoms += n
        total_agree += len(d["agree"]) + len(d["agree_both_undetermined"])
        total_disagree += len(d["disagree"])
        if r["disposition_agreement"]:
            disposition_agreements += 1

    print(f"  Cases run: {successful_runs}/{len(per_case_results)}")
    if total_atoms > 0:
        print(f"  Total atom bindings compared: {total_atoms}")
        print(f"  Atom-level agreement: {total_agree}/{total_atoms} "
              f"({100*total_agree/total_atoms:.1f}%)")
        print(f"  Disposition-level agreement: "
              f"{disposition_agreements}/{successful_runs}")
        print()
        agreement_rate = total_agree / total_atoms
        if agreement_rate >= 0.95:
            print(f"  → RECOMMENDATION: Sonnet matches Opus closely "
                  f"({agreement_rate:.1%} ≥ 95% threshold). Scale 15 cases "
                  f"on {args.model_a} for production economics.")
        else:
            print(f"  → RECOMMENDATION: Sonnet diverges from Opus "
                  f"({agreement_rate:.1%} < 95% threshold). Consider scaling "
                  f"on {args.model_b}; document cost-vs-quality tradeoff.")

    summary_out = {
        "run_id": run_id,
        "model_a": args.model_a,
        "model_b": args.model_b,
        "batch_size": args.batch_size,
        "case_count": len(per_case_results),
        "atom_agreement_rate": (total_agree / total_atoms if total_atoms else None),
        "disposition_agreement_count": disposition_agreements,
        "per_case_summary": [
            {
                "case_id": r["case_id"],
                "ground_truth_is_illegal": r["ground_truth_is_illegal"],
                "model_a_disposition": (r["model_a"]["audit"]
                                         .get("rulekit", {}).get("disposition")),
                "model_b_disposition": (r["model_b"]["audit"]
                                         .get("rulekit", {}).get("disposition")),
                "atom_agreement_rate": (
                    r["atom_diff"]["agreement_rate"]
                    if r["atom_diff"] else None
                ),
                "disposition_agreement": r["disposition_agreement"],
            }
            for r in per_case_results
        ],
    }
    summary_path = os.path.join(args.out_dir, f"_summary_{run_id}.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_out, f, indent=2)
    print(f"  Summary written to {summary_path}")


if __name__ == "__main__":
    main()

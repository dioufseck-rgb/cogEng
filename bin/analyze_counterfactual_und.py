"""
analyze_counterfactual_und.py - For each case in an audit run, identify
whether flipping UND determinations would change the disposition, and
whether the result would agree with ground truth.

This answers: where is the resolver's potential value? If flipping
some UND atoms to TRUE/FALSE would actually move the disposition (and
toward agreement), the resolver is worth building. If most flips
either don't change disposition or move it toward disagreement,
the resolver is less valuable.

Per-determination Kleene logic (from adjudicate_cases.aggregate_disposition):
  - illegal if ANY determination = FALSE
  - legal if ALL determinations = TRUE
  - uncertain otherwise

For each UND determination, simulate two counterfactuals:
  - What if it were TRUE? (per-det)
  - What if it were FALSE? (per-det)
Then compute the resulting disposition and compare to ground truth.

Usage:
    python bin/analyze_counterfactual_und.py audits/full_dag_diagnostic
"""
import json
import os
import sys
from glob import glob


def aggregate(per_det):
    """Same rule as in adjudicate_cases.py."""
    vals = list(per_det.values())
    if any(v == "FALSE" for v in vals):
        return "illegal"
    if any(v == "UNDETERMINED" for v in vals):
        return "uncertain"
    return "legal"


def disposition_matches_gt(disposition, gt_is_illegal):
    """RuleKit says 'illegal' AGREEs with GT illegal; 'legal' AGREEs with GT legal;
    'uncertain' AGREES generously with GT legal (since not classifying as illegal)."""
    if disposition == "illegal":
        return gt_is_illegal == True
    if disposition == "legal":
        return gt_is_illegal == False
    # uncertain - we report whether GT was illegal or legal separately
    return None


def main():
    if len(sys.argv) != 2:
        print("Usage: python bin/analyze_counterfactual_und.py <audit-dir>")
        sys.exit(1)

    audit_dir = sys.argv[1]
    case_files = sorted(glob(os.path.join(audit_dir, "case_*.json")))

    print(f"Analyzing {len(case_files)} cases from {audit_dir}\n")
    print("=" * 90)
    print(f"{'case_id':<22} {'gt':<10} {'actual':<12} {'load-bearing UNDs (flip moves disposition)':}")
    print("=" * 90)

    total_load_bearing = 0
    total_und = 0
    flippable_to_agreement = 0
    flippable_to_disagreement = 0
    flippable_indeterminate = 0

    for path in case_files:
        with open(path, encoding="utf-8") as f:
            audit = json.load(f)
        if "error" in audit:
            continue

        case_id = audit["case_id"]
        gt = audit["ground_truth"]["is_illegal"]
        per_det = audit["rulekit"]["per_determination_kleene"]
        actual_disp = audit["rulekit"]["disposition"]

        und_dets = [d for d, v in per_det.items() if v == "UNDETERMINED"]
        total_und += len(und_dets)

        # For each UND determination, what changes if we flip it to TRUE / FALSE
        load_bearing = []
        for d in und_dets:
            cf_true = dict(per_det)
            cf_true[d] = "TRUE"
            disp_true = aggregate(cf_true)

            cf_false = dict(per_det)
            cf_false[d] = "FALSE"
            disp_false = aggregate(cf_false)

            # Is this UND load-bearing? (flipping to either value changes disposition?)
            if disp_true != actual_disp or disp_false != actual_disp:
                load_bearing.append((d, disp_true, disp_false))
                total_load_bearing += 1

                # Could a correct flip lead to agreement with GT?
                # GT illegal: want disposition = illegal (achievable if disp_false = illegal)
                # GT legal: want disposition = legal (achievable if disp_true = legal)
                if gt:  # GT illegal
                    if disp_false == "illegal":
                        flippable_to_agreement += 1
                    elif disp_true == "illegal":
                        # Flipping to TRUE makes it illegal? That would only happen
                        # if some OTHER determination is already false - doesn't apply
                        # in practice but handle the case
                        flippable_to_agreement += 1
                    else:
                        flippable_indeterminate += 1
                else:  # GT legal
                    if disp_true == "legal":
                        flippable_to_agreement += 1
                    elif disp_false == "legal":
                        flippable_to_agreement += 1
                    else:
                        flippable_indeterminate += 1

        # Format output
        gt_str = "illegal" if gt else "legal"
        load_str = ", ".join(f"{d.replace('nba.', '')}" for d, _, _ in load_bearing) or "(none)"
        print(f"{case_id:<22} {gt_str:<10} {actual_disp:<12} {load_str}")

    print()
    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"Total UND determinations across all cases: {total_und}")
    print(f"Of those, load-bearing (flipping changes disposition): {total_load_bearing}")
    print()
    print("If we could flip the right load-bearing UNDs:")
    print(f"  Could lead to agreement with GT: {flippable_to_agreement}")
    print(f"  Indeterminate (no flip helps):    {flippable_indeterminate}")
    print()

    # Per-case structural analysis
    print("=" * 90)
    print("PER-CASE DETAIL")
    print("=" * 90)
    for path in case_files:
        with open(path, encoding="utf-8") as f:
            audit = json.load(f)
        if "error" in audit:
            continue
        case_id = audit["case_id"]
        gt = audit["ground_truth"]["is_illegal"]
        per_det = audit["rulekit"]["per_determination_kleene"]
        actual_disp = audit["rulekit"]["disposition"]
        print(f"\n{case_id} (GT: {'illegal' if gt else 'legal'}, actual: {actual_disp})")
        for d, v in per_det.items():
            if v == "UNDETERMINED":
                cf_t = dict(per_det); cf_t[d] = "TRUE"
                cf_f = dict(per_det); cf_f[d] = "FALSE"
                disp_t = aggregate(cf_t)
                disp_f = aggregate(cf_f)
                load = "load-bearing" if (disp_t != actual_disp or disp_f != actual_disp) else "not load-bearing"
                print(f"  {d}: UND ({load})")
                if load == "load-bearing":
                    print(f"    if TRUE  -> {disp_t} (agrees with GT: {disposition_matches_gt(disp_t, gt)})")
                    print(f"    if FALSE -> {disp_f} (agrees with GT: {disposition_matches_gt(disp_f, gt)})")
            elif v == "MISSING":
                continue
            else:
                print(f"  {d}: {v}")


if __name__ == "__main__":
    main()

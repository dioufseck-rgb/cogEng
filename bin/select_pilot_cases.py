"""
select_pilot_cases.py — choose 3 representative cases for the Map A/B pilot.

The selection criteria:
  (1) one is_illegal=True case with high determination coverage
      → tests that RuleKit detects a real violation
  (2) one is_illegal=False case with high coverage
      → tests that RuleKit does NOT over-fire on legal transactions
  (3) one is_illegal=True case that exercises a less-common determination
      (over_38, vfa_exception, sign_and_trade, traded_player_exception, etc.)
      → tests architectural reach beyond the universal families

The output is a JSON file (default: pilot_cases.json) listing the 3
selected case_ids, plus per-case metadata for the A/B runner to consume.

USAGE:
    python bin/select_pilot_cases.py \
        --cases RuleArena/nba/annotated_problems/comp_0.json \
        --aliases domains/nba/ruleArena_family_aliases.yaml \
        --out pilot_cases.json

Cost: $0. Pure inspection of case metadata.
"""
from __future__ import annotations
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import yaml
from rulekit.cases.rulearena_adapter import load_ruleArena_cases


# Determinations considered "universal families" — high frequency, less
# architectural reach to test. Cases exercising only these are not as
# interesting as cases also touching the broader determinations.
UNIVERSAL_FAMILIES = {
    "nba.max_salary",
    "nba.contract_length",
    "nba.salary_increase",
    "nba.cap_room",
}


def load_aliases(path: str) -> dict[str, str]:
    """Load the RuleArena rule family → determination alias table."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["ruleArena_family_to_determination"]


def case_determinations(case, aliases: dict[str, str]) -> set[str]:
    """Map a case's relevant_rules to the set of determinations referenced."""
    rules = case.ground_truth.get("relevant_rules", [])
    return {aliases[r] for r in rules if r in aliases}


def case_is_in_scope(case, aliases: dict[str, str]) -> bool:
    """A case is in scope if every relevant_rule has an alias entry."""
    rules = case.ground_truth.get("relevant_rules", [])
    return all(r in aliases for r in rules)


def select_pilots(cases, aliases) -> tuple[list[dict], list[dict]]:
    """Select 3 pilot cases.

    Returns (selected_cases, candidate_pool) — the 3 chosen plus the
    full in-scope pool sorted by coverage, so the user can pick
    alternates manually if desired.
    """
    in_scope = [c for c in cases if case_is_in_scope(c, aliases)]

    # Enrich each case with derived metadata
    annotated = []
    for c in in_scope:
        dets = case_determinations(c, aliases)
        non_universal = dets - UNIVERSAL_FAMILIES
        annotated.append({
            "case": c,
            "case_id": c.case_id,
            "is_illegal": c.ground_truth["is_illegal"],
            "determinations_count": len(dets),
            "determinations": sorted(dets),
            "non_universal_determinations": sorted(non_universal),
            "non_universal_count": len(non_universal),
            "relevant_rules_count": len(c.ground_truth["relevant_rules"]),
        })

    illegal = [a for a in annotated if a["is_illegal"]]
    legal = [a for a in annotated if not a["is_illegal"]]

    # Criterion 1: is_illegal=True with MODERATE coverage and minimal
    # non-universal complexity. We want a clean violation case where
    # the universal families are the operative determinations — a
    # focused test of substrate synthesis on the core 4 rules.
    # Prefer cases touching 3-4 determinations with 0-1 non-universal.
    def pilot_1_sort(a):
        det_count = a["determinations_count"]
        non_univ = a["non_universal_count"]
        # Penalize too-few (won't exercise enough) and too-many (too
        # much surface to debug). Sweet spot: 3-4 determinations.
        det_distance = abs(det_count - 3.5)
        return (non_univ, det_distance, a["case_id"])

    pilot_1 = sorted(illegal, key=pilot_1_sort)[0] if illegal else None

    # Criterion 2: is_illegal=False with moderate coverage. Same
    # sweet-spot heuristic but for the over-fire test.
    pilot_2 = sorted(legal, key=pilot_1_sort)[0] if legal else None

    # Criterion 3: is_illegal=True with high non-universal reach.
    # The stress test — exercises sign_and_trade, vfa_exception,
    # traded_player_exception, over_38, etc. If RuleKit can adjudicate
    # this correctly, it's evidence of meaningful architectural reach.
    illegal_reach = sorted(
        [a for a in illegal
         if a["non_universal_count"] >= 2
         and a["case_id"] != (pilot_1["case_id"] if pilot_1 else None)],
        key=lambda a: (-a["non_universal_count"], -a["determinations_count"])
    )
    pilot_3 = illegal_reach[0] if illegal_reach else None

    selected = [p for p in [pilot_1, pilot_2, pilot_3] if p is not None]
    return selected, annotated


def main():
    parser = argparse.ArgumentParser(
        description="Select 3 pilot cases for Map A/B testing."
    )
    parser.add_argument(
        "--cases",
        default="RuleArena/nba/annotated_problems/comp_0.json",
        help="RuleArena case JSON file"
    )
    parser.add_argument(
        "--aliases",
        default="domains/nba/ruleArena_family_aliases.yaml",
        help="Rule-family-to-determination alias YAML"
    )
    parser.add_argument(
        "--out", default="pilot_cases.json",
        help="Output JSON with the 3 selected cases' metadata"
    )
    parser.add_argument(
        "--show-pool", action="store_true",
        help="Also print the full sorted candidate pool"
    )
    args = parser.parse_args()

    aliases = load_aliases(args.aliases)
    cases = load_ruleArena_cases(args.cases, only_single_op=True)

    print(f"Loaded {len(cases)} single-op cases from {args.cases}")
    print(f"Loaded {len(aliases)} family aliases from {args.aliases}")
    print()

    selected, pool = select_pilots(cases, aliases)
    in_scope_count = sum(1 for a in pool)
    illegal_count = sum(1 for a in pool if a["is_illegal"])
    print(f"In-scope cases: {in_scope_count} "
          f"({illegal_count} illegal, {in_scope_count - illegal_count} legal)")
    print()

    print("=" * 70)
    print("SELECTED PILOT CASES")
    print("=" * 70)
    labels = [
        "Criterion 1: is_illegal=True, broadest coverage",
        "Criterion 2: is_illegal=False, broad coverage (over-fire test)",
        "Criterion 3: is_illegal=True, exercises non-universal reach",
    ]
    for label, picked in zip(labels, selected):
        print(f"\n{label}")
        print(f"  case_id: {picked['case_id']}")
        print(f"  is_illegal: {picked['is_illegal']}")
        print(f"  determinations ({picked['determinations_count']}): "
              f"{', '.join(picked['determinations'])}")
        if picked["non_universal_determinations"]:
            print(f"  non-universal: "
                  f"{', '.join(picked['non_universal_determinations'])}")
        print(f"  description (first 300 chars):")
        desc = picked["case"].description
        for line in desc[:300].split("\n")[:6]:
            print(f"    {line}")

    if args.show_pool:
        print()
        print("=" * 70)
        print(f"FULL IN-SCOPE POOL ({len(pool)} cases)")
        print("=" * 70)
        pool_sorted = sorted(pool,
                             key=lambda a: (-a["determinations_count"],
                                            a["case_id"]))
        for a in pool_sorted:
            marker = "X" if a["is_illegal"] else "."
            print(f"  [{marker}] {a['case_id']:<25} "
                  f"dets={a['determinations_count']:>2}  "
                  f"non-univ={a['non_universal_count']:>2}  "
                  f"rules={a['relevant_rules_count']:>2}")

    # Write output JSON (without the AdaptedCase object, just metadata)
    output = {
        "criteria_descriptions": labels,
        "selected_case_ids": [s["case_id"] for s in selected],
        "selected_metadata": [
            {
                "case_id": s["case_id"],
                "is_illegal": s["is_illegal"],
                "determinations": s["determinations"],
                "non_universal_determinations": s["non_universal_determinations"],
                "determinations_count": s["determinations_count"],
                "non_universal_count": s["non_universal_count"],
                "relevant_rules_count": s["relevant_rules_count"],
                "description_preview": s["case"].description[:500],
            }
            for s in selected
        ],
        "in_scope_total": in_scope_count,
        "in_scope_illegal": illegal_count,
        "in_scope_legal": in_scope_count - illegal_count,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print()
    print(f"Wrote pilot selection to {args.out}")


if __name__ == "__main__":
    main()

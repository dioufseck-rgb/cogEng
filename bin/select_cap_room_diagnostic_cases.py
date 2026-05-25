"""
select_cap_room_diagnostic_cases.py - pick 10 cases that activate cap_room
for the fragment Build's diagnostic run.

The cap_room fragment can only evaluate cases where cap_room is a
relevant determination per the alias table. This script filters
in-scope cases to those that touch cap_room, then picks a balanced
sample.
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


def load_aliases(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["ruleArena_family_to_determination"]


def case_dets(case, aliases):
    return {aliases[r] for r in case.ground_truth.get("relevant_rules", [])
            if r in aliases}


def case_in_scope(case, aliases):
    return all(r in aliases for r in case.ground_truth.get("relevant_rules", []))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cases", default="RuleArena/nba/annotated_problems/comp_0.json")
    p.add_argument("--aliases", default="domains/nba/ruleArena_family_aliases.yaml")
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--out", default="cap_room_diagnostic_cases.json")
    args = p.parse_args()

    aliases = load_aliases(args.aliases)
    cases = load_ruleArena_cases(args.cases, only_single_op=True)
    in_scope = [c for c in cases if case_in_scope(c, aliases)]
    touch_cap_room = [c for c in in_scope
                      if "nba.cap_room" in case_dets(c, aliases)]

    print(f"In-scope cases: {len(in_scope)}")
    print(f"Cases that touch nba.cap_room: {len(touch_cap_room)}")
    illegal = [c for c in touch_cap_room if c.ground_truth["is_illegal"]]
    legal = [c for c in touch_cap_room if not c.ground_truth["is_illegal"]]
    print(f"  Illegal: {len(illegal)}")
    print(f"  Legal:   {len(legal)}")
    print()

    # Want a balanced sample: ~60% illegal, ~40% legal (matches in-scope
    # distribution roughly). Prefer cases touching nba.cap_room AS the
    # primary determination (few other determinations).
    def simplicity_score(c):
        # Fewer determinations = simpler signal
        return len(case_dets(c, aliases))

    illegal_sorted = sorted(illegal, key=simplicity_score)
    legal_sorted = sorted(legal, key=simplicity_score)

    n_illegal = min(args.n * 6 // 10, len(illegal_sorted))
    n_legal = args.n - n_illegal
    if n_legal > len(legal_sorted):
        n_legal = len(legal_sorted)
        n_illegal = args.n - n_legal

    selected = illegal_sorted[:n_illegal] + legal_sorted[:n_legal]

    print(f"SELECTED {len(selected)} cases:")
    for c in selected:
        marker = "X" if c.ground_truth["is_illegal"] else "."
        dets = sorted(case_dets(c, aliases))
        print(f"  [{marker}] {c.case_id:<25} "
              f"dets={len(dets)}  {','.join(d.replace('nba.','') for d in dets)}")

    case_ids = [c.case_id for c in selected]
    with open(args.out, "w") as f:
        json.dump({
            "case_ids": case_ids,
            "case_metadata": [
                {
                    "case_id": c.case_id,
                    "is_illegal": c.ground_truth["is_illegal"],
                    "determinations": sorted(case_dets(c, aliases)),
                }
                for c in selected
            ],
        }, f, indent=2)
    print(f"\nWrote {args.out}")
    print()
    print(f"Run with: --case-ids \"{','.join(case_ids)}\"")


if __name__ == "__main__":
    main()

"""
Test runner for all NBA fragment modules.

Each fragment in domains/nba/fragments/ exposes:
  - build_fragment() -> dict[name, node]
  - cases() -> list of (label, bundle, expected[, attribution]) tuples

This runner imports them and runs every case across every fragment,
collecting pass/fail counts.
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulekit.engine import Kleene
from domains.nba.fragments import (
    mle_selection,
    max_salary_by_yos,
    sign_and_trade,
    trade_matching,
)

FRAGMENTS = [
    ("MLE flavor selection", mle_selection),
    ("Max salary by Years of Service + Higher Max gating", max_salary_by_yos),
    ("Sign-and-trade team-role attribution", sign_and_trade),
    ("Trade salary matching (Traded Player Exception)", trade_matching),
]


def normalize_case(case):
    """Each fragment may yield 3- or 4-tuples. Drop the optional 4th element."""
    if len(case) >= 3:
        return case[0], case[1], case[2]
    raise ValueError(f"Bad case shape: {case}")


def main():
    total_pass = 0
    total_fail = 0
    failures = []

    for fragment_label, fragment_module in FRAGMENTS:
        print(f"\n{'=' * 70}")
        print(f"Fragment: {fragment_label}")
        print('=' * 70)

        fragment = fragment_module.build_fragment()
        cases = fragment_module.cases()

        for case in cases:
            label, bundle, expected = normalize_case(case)
            case_pass = True
            for node_name, expected_value in expected.items():
                node = fragment[node_name]
                actual = node.evaluate(bundle)
                if actual != expected_value:
                    case_pass = False
                    failures.append(
                        (fragment_label, label, node_name, expected_value, actual)
                    )
            if case_pass:
                total_pass += 1
                print(f"  PASS  {label}")
            else:
                total_fail += 1
                print(f"  FAIL  {label}")

    print(f"\n{'=' * 70}")
    print(f"TOTAL: {total_pass} cases passed, {total_fail} failed")
    print('=' * 70)
    if total_fail:
        print("\nFailures:")
        for ff in failures:
            print(f"  - {ff[0]} / {ff[1]} / {ff[2]}: expected {ff[3]}, got {ff[4]}")
        sys.exit(1)


if __name__ == "__main__":
    main()

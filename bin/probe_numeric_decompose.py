"""
probe_numeric_decompose.py - validation probe for the updated Build prompt.

Runs the new NUMERIC_DECOMPOSE_PROMPT against canonical test descriptions
and verifies the LLM produces the correct spec_type for each. This lets
us iterate on the prompt cheaply (~$0.10/probe) before running a full
Build (~$30-50).

USAGE:
    python bin/probe_numeric_decompose.py --model claude-sonnet-4-6

For each test case, prints the probe description, the LLM's spec_type,
and whether it matched the expected spec_type. Prints a final pass/fail
summary.

DESIGN:
  - 8 test cases covering each of the new spec types and the legitimate
    derived_atom cases
  - Each test case is one Map-style description (3-15 words) with a
    classifier kind hint
  - The expected spec_type is what the new prompt's routing rules say
    SHOULD be produced
  - Failure mode = the prompt is not landing; iterate before Build
"""
from __future__ import annotations
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.build.decomposer import LLMCaller, _parse_json_response
from rulekit.build.typed_numeric_decompose_prompt import (
    render_numeric_decompose_prompt,
)


# Each probe is (description, kind_hint, expected_spec_type, notes)
PROBES = [
    # Binary - the case-killing example from Phase 2
    (
        "the team's team salary immediately after the signing in question",
        "arithmetic",
        "plus",
        "the team_salary_post_signing case from comp_0_1_op_A",
    ),
    # Variadic max - the cap_room kind of thing
    (
        "the greater of 25% of the Salary Cap or 105% of the player's prior-year salary",
        "arithmetic",
        "max",
        "max_salary_ceiling - classic max-of",
    ),
    # Variadic min
    (
        "the lesser of $5,000,000 or 20% of the Salary Cap",
        "arithmetic",
        "min",
        "MLE-or-cap-percent kind of expression",
    ),
    # Variadic sum (enumerable)
    (
        "the sum of player A's first-year salary and player B's first-year salary",
        "arithmetic",
        "sum",
        "enumerable sum (cases name both players)",
    ),
    # Aggregate sum (not enumerable - should still be derived_atom)
    (
        "the aggregate first-year Salaries of all Player Contracts the team signs under the MLE",
        "arithmetic",
        "derived_atom",
        "non-enumerable aggregate - kept as derived_atom",
    ),
    # Conditional - should still be derived_atom
    (
        "25% of the Salary Cap if the player has fewer than 7 Years of Service, otherwise 30%",
        "arithmetic",
        "derived_atom",
        "conditional - kept as derived_atom",
    ),
    # Unary arithmetic should still work
    (
        "9.12% of the Salary Cap",
        "arithmetic",
        "unary_arithmetic",
        "regression: unary still works",
    ),
    # numeric_leaf should still work
    (
        "the team's current team salary in US dollars",
        "numeric_leaf",
        "numeric_leaf",
        "regression: numeric_leaf still works",
    ),
]


def run_probe(llm, description, kind):
    """Run one probe against the LLM. Returns (spec_type, parsed_dict, raw_text)."""
    prompt = render_numeric_decompose_prompt(
        description=description, kind=kind
    )
    raw = llm.call("probe_numeric_decompose", prompt, max_tokens=2048)
    try:
        parsed = _parse_json_response(raw)
        spec_type = parsed.get("spec_type", "").strip().lower()
        return spec_type, parsed, raw
    except Exception as e:
        return f"PARSE_ERROR: {e}", None, raw


def main():
    parser = argparse.ArgumentParser(
        description="Probe the new numeric decompose prompt for spec_type accuracy."
    )
    parser.add_argument(
        "--model", default="claude-opus-4-7",
        help="Model for the probe (default: claude-opus-4-7 since Build "
             "is once-per-policy and uses the better model)"
    )
    parser.add_argument("--max-probes", type=int, default=len(PROBES),
                        help="Run only first N probes (for quick iteration)")
    args = parser.parse_args()

    llm = LLMCaller(model=args.model)
    print(f"Model: {args.model}")
    print(f"Running {min(args.max_probes, len(PROBES))} probes...\n")

    passed = 0
    failed = 0
    for i, (desc, kind, expected, notes) in enumerate(
        PROBES[:args.max_probes], 1
    ):
        print("=" * 70)
        print(f"PROBE {i}/{min(args.max_probes, len(PROBES))}: {notes}")
        print("=" * 70)
        print(f"  Description: {desc}")
        print(f"  Kind hint:   {kind}")
        print(f"  Expected:    {expected}")

        spec_type, parsed, raw = run_probe(llm, desc, kind)
        print(f"  Got:         {spec_type}")

        if spec_type == expected:
            print(f"  STATUS:      PASS")
            passed += 1
        else:
            print(f"  STATUS:      FAIL")
            failed += 1
            # Show what was actually returned for diagnosis
            if parsed:
                print(f"  Full spec (truncated):")
                spec_str = json.dumps(parsed, indent=2)
                for line in spec_str.split("\n")[:8]:
                    print(f"    {line}")
            else:
                print(f"  Raw response (first 400 chars):")
                print(f"    {raw[:400]}")
        print()

    print("=" * 70)
    print(f"PROBE SUMMARY: {passed} passed, {failed} failed")
    print("=" * 70)
    if failed == 0:
        print("All probes passed -- prompt is landing correctly.")
        print("Safe to commit and run a fragment Build next.")
    else:
        print(f"{failed} probe(s) failed -- iterate on the prompt before Build.")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

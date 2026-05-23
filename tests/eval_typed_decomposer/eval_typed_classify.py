"""
eval_typed_classify.py — eval runner for the typed classification prompt.

Runs the typed Stage-1 classifier against the eval cases in
tests/eval_typed_decomposer/eval_cases.json. Reports:

  - Parse-success rate (did the LLM produce valid JSON in the expected schema?)
  - Top-level type match (leaf/and/or/not/at_least/comparison)
  - For comparisons: operator match, LHS-kind, RHS-kind
  - For Boolean composites: child count match where applicable

USAGE
=====

Live LLM (uses ANTHROPIC_API_KEY or CLAUDE_API_KEY):

    python tests/eval_typed_decomposer/eval_typed_classify.py

Live with limit:

    python tests/eval_typed_decomposer/eval_typed_classify.py --limit 5

Specific category:

    python tests/eval_typed_decomposer/eval_typed_classify.py --category single_comparison

Offline (uses a cached responses file):

    python tests/eval_typed_decomposer/eval_typed_classify.py --offline cached_responses.json

Save responses for later offline replay:

    python tests/eval_typed_decomposer/eval_typed_classify.py --save-to responses.json
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rulekit.build.typed_classify_prompt import render_prompt
from rulekit.build.decomposer import LLMCaller, _parse_json_response


# ---------------------------------------------------------------------------
# Context for the prompt — using a generic policy-reading voice that should
# work across PA, FCBA, and NBA examples in the eval set
# ---------------------------------------------------------------------------

EVAL_CONTEXT = {
    "role": "experienced policy analyst",
    "domain": "mixed (PA / FCBA / NBA CBA examples)",
    "background": (
        "You are evaluating a single claim from a regulated-decision policy. "
        "The eval set draws from prior authorization criteria, billing-error "
        "regulations, and NBA Collective Bargaining Agreement rules. "
        "Classify each claim using ONLY the structure of the claim itself — "
        "the eval probes the classifier's judgment on claims in isolation."
    ),
    "determination_id": "eval",
    "determination_description": "Classification evaluation",
    "scope_section": "",
    "path": "(eval — no breadcrumb context)",
    "policy_text": "(eval — no policy excerpt provided; classify from the claim alone)",
}


# ---------------------------------------------------------------------------
# Per-case scoring
# ---------------------------------------------------------------------------

def score_case(case: dict, response: dict) -> tuple[bool, list[str]]:
    """
    Score a single LLM response against the case's expected structure.
    Returns (passed, list of detail messages).

    Scoring is structural — we don't require exact wording match on
    free-text fields, just structural shape.
    """
    expected = case.get("expected")
    if expected is None:
        # Some cases have "expected_either" listing acceptable alternatives
        alternatives = case.get("expected_either", [])
        for alt in alternatives:
            ok, _ = _structural_match(alt, response)
            if ok:
                return True, ["matched alternative"]
        return False, [f"no expected alternative matched (had {len(alternatives)} options)"]
    return _structural_match(expected, response)


def _structural_match(expected: dict, actual: dict) -> tuple[bool, list[str]]:
    """Compare expected structure to actual response. Loose, structural."""
    details = []
    exp_type = expected.get("type")
    act_type = actual.get("type")

    if exp_type != act_type:
        return False, [f"type mismatch: expected {exp_type!r}, got {act_type!r}"]

    if exp_type == "leaf":
        # All we require for leaves is that the type matched. Optionally
        # the claim text echoes the original (LLMs may rephrase).
        return True, ["leaf ok"]

    if exp_type == "comparison":
        # Check operator
        exp_op = expected.get("operator")
        act_op = actual.get("operator")
        if exp_op != act_op:
            details.append(f"operator mismatch: expected {exp_op!r}, got {act_op!r}")
            return False, details
        details.append(f"operator={act_op} ok")

        # Check LHS kind
        exp_lhs = expected.get("lhs", {})
        act_lhs_kind = actual.get("lhs_kind")
        exp_lhs_kind = exp_lhs.get("type")
        if exp_lhs_kind and act_lhs_kind != exp_lhs_kind:
            details.append(
                f"LHS kind mismatch: expected {exp_lhs_kind!r}, got {act_lhs_kind!r}"
            )
            return False, details
        details.append(f"lhs_kind={act_lhs_kind} ok")

        # Check RHS kind
        exp_rhs = expected.get("rhs", {})
        act_rhs_kind = actual.get("rhs_kind")
        exp_rhs_kind = exp_rhs.get("type")
        if exp_rhs_kind and act_rhs_kind != exp_rhs_kind:
            details.append(
                f"RHS kind mismatch: expected {exp_rhs_kind!r}, got {act_rhs_kind!r}"
            )
            return False, details
        details.append(f"rhs_kind={act_rhs_kind} ok")

        return True, details

    if exp_type in ("and", "or", "not", "at_least"):
        # Check child count
        exp_n = expected.get("n_children")
        children = actual.get("children", [])
        if exp_n is not None and len(children) != exp_n:
            details.append(
                f"child count mismatch: expected {exp_n}, got {len(children)}"
            )
            return False, details
        if exp_type == "at_least":
            if expected.get("n") != actual.get("n"):
                details.append(
                    f"at_least N mismatch: expected {expected.get('n')}, "
                    f"got {actual.get('n')}"
                )
                return False, details
        details.append(f"{exp_type} ok ({len(children)} children)")
        return True, details

    details.append(f"unknown expected type: {exp_type!r}")
    return False, details


# ---------------------------------------------------------------------------
# Eval driver
# ---------------------------------------------------------------------------

def run_eval(eval_cases_path: str, llm: LLMCaller,
             limit: Optional[int] = None,
             category_filter: Optional[str] = None,
             save_to: Optional[str] = None,
             verbose: bool = True) -> dict:
    """
    Run the eval. Returns a result dict with per-case outcomes and aggregates.
    """
    with open(eval_cases_path) as f:
        data = json.load(f)
    cases = data["cases"]
    if category_filter:
        cases = [c for c in cases if c.get("category") == category_filter]
    if limit:
        cases = cases[:limit]

    results = []
    saved_responses = {}

    for i, case in enumerate(cases):
        cid = case["id"]
        claim = case["claim"]
        if verbose:
            print(f"\n[{i+1}/{len(cases)}] {cid} ({case['category']})")
            print(f"  claim: {claim[:80]}")

        # If the case carries its own policy_text, use it; otherwise fall back
        # to the default EVAL_CONTEXT (which says "no policy excerpt provided")
        case_context = dict(EVAL_CONTEXT)
        if "policy_text" in case:
            case_context["policy_text"] = case["policy_text"]
            if verbose:
                print(f"  policy_text: {case['policy_text'][:80]}...")

        prompt = render_prompt(claim=claim, **case_context)

        # Pick a unique stage_name per case so cached responses don't collide
        stage_name = f"eval_typed_classify::{cid}"

        try:
            raw = llm.call(stage_name, prompt)
            saved_responses[stage_name] = raw
            response = _parse_json_response(raw)
            parse_ok = True
        except json.JSONDecodeError as e:
            response = None
            parse_ok = False
            err_detail = f"JSON parse error: {e}"

        if not parse_ok:
            outcome = {
                "id": cid,
                "category": case["category"],
                "claim": claim,
                "passed": False,
                "parse_ok": False,
                "details": [err_detail],
                "response_raw": raw if 'raw' in dir() else None,
            }
            if verbose:
                print(f"  FAIL: {err_detail}")
        else:
            passed, details = score_case(case, response)
            outcome = {
                "id": cid,
                "category": case["category"],
                "claim": claim,
                "passed": passed,
                "parse_ok": True,
                "details": details,
                "response": response,
            }
            if verbose:
                status = "PASS" if passed else "FAIL"
                print(f"  {status}: {'; '.join(details)}")
        results.append(outcome)

    if save_to:
        with open(save_to, "w") as f:
            json.dump(saved_responses, f, indent=2)
        if verbose:
            print(f"\nSaved {len(saved_responses)} raw responses to {save_to}")

    return _summarize(results, verbose=verbose)


def _summarize(results: list[dict], verbose: bool = True) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    parse_ok = sum(1 for r in results if r["parse_ok"])

    by_category = {}
    for r in results:
        cat = r["category"]
        if cat not in by_category:
            by_category[cat] = {"passed": 0, "total": 0}
        by_category[cat]["total"] += 1
        if r["passed"]:
            by_category[cat]["passed"] += 1

    if verbose:
        print("\n" + "=" * 70)
        print(f"AGGREGATE RESULTS")
        print("=" * 70)
        print(f"  Parse success: {parse_ok}/{total} = {parse_ok/total*100:.0f}%")
        print(f"  Structural match: {passed}/{total} = {passed/total*100:.0f}%")
        print(f"\n  By category:")
        for cat, stats in sorted(by_category.items()):
            print(f"    {cat:30s} {stats['passed']}/{stats['total']}")

        failed = [r for r in results if not r["passed"]]
        if failed:
            print(f"\n  Failed cases:")
            for r in failed:
                print(f"    - [{r['category']}] {r['id']}: {'; '.join(r['details'])}")

    return {
        "total": total,
        "passed": passed,
        "parse_ok": parse_ok,
        "by_category": by_category,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-cases", default=None,
                        help="Path to eval_cases.json (default: alongside this script)")
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--limit", type=int, default=None,
                        help="Run only first N cases")
    parser.add_argument("--category", default=None,
                        help="Filter to single category")
    parser.add_argument("--offline", default=None,
                        help="Replay cached responses from this JSON file")
    parser.add_argument("--save-to", default=None,
                        help="Save raw LLM responses to this file")
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    eval_cases_path = args.eval_cases or os.path.join(here, "eval_cases.json")

    # Build LLM caller — offline if a cache file is given
    if args.offline:
        with open(args.offline) as f:
            cached = json.load(f)
        llm = LLMCaller(model=args.model, offline_responses=cached)
        print(f"Running OFFLINE with {len(cached)} cached responses")
    else:
        # Check for API key
        if not os.environ.get("ANTHROPIC_API_KEY"):
            if os.environ.get("CLAUDE_API_KEY"):
                os.environ["ANTHROPIC_API_KEY"] = os.environ["CLAUDE_API_KEY"]
            else:
                print("ERROR: set ANTHROPIC_API_KEY (or CLAUDE_API_KEY), "
                      "or pass --offline cached_responses.json")
                sys.exit(2)
        llm = LLMCaller(model=args.model)
        print(f"Running LIVE with model={args.model}")

    run_eval(
        eval_cases_path,
        llm,
        limit=args.limit,
        category_filter=args.category,
        save_to=args.save_to,
    )


if __name__ == "__main__":
    main()
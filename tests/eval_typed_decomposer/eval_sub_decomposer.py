"""
eval_sub_decomposer.py — eval runner for the typed numeric sub-decomposer (Piece 2).

Same pattern as eval_typed_classify.py:
  - Run cases live against Opus 4.7 (or another model)
  - Score structurally — spec_type first, then operator/value/computation_kind
  - Save raw responses for offline analysis
  - Support --offline mode for replay
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rulekit.build.typed_numeric_decompose_prompt import render_numeric_decompose_prompt
from rulekit.build.decomposer import LLMCaller, _parse_json_response


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_case(case: dict, response: dict) -> tuple[bool, list[str]]:
    """
    Score a sub-decomposer response against the expected spec.

    Three levels of match:
      L1 (mandatory): spec_type matches
      L2 (preferred): for unary_arithmetic — operator matches
                      for constant — value or label matches
                      for derived_atom — computation_kind matches
      L3 (informational): atom_id_hint is reasonable (substring/keyword match)
    """
    expected = case.get("expected")
    if expected is None:
        return False, ["no expected spec in case"]

    details = []

    # L1: spec_type
    expected_type = expected.get("spec_type")
    actual_type = response.get("spec_type")
    if expected_type != actual_type:
        return False, [f"spec_type mismatch: expected {expected_type!r}, got {actual_type!r}"]
    details.append(f"spec_type={actual_type} ok")

    # L2: type-specific check
    if actual_type == "numeric_leaf":
        # informational only — check atom_id_hint exists
        if "atom_id_hint" not in response:
            details.append("missing atom_id_hint")
        else:
            details.append(f"atom_id_hint={response['atom_id_hint']!r}")
        return True, details

    if actual_type == "constant":
        # Either value or label should match
        if "value" in expected:
            exp_val = expected["value"]
            act_val = response.get("value")
            # Allow numeric tolerance
            if act_val is None:
                details.append(f"missing value (expected {exp_val})")
                return False, details
            try:
                if float(act_val) != float(exp_val):
                    details.append(f"value mismatch: expected {exp_val}, got {act_val}")
                    return False, details
                details.append(f"value={act_val} ok")
            except (TypeError, ValueError):
                details.append(f"value not numeric: {act_val}")
                return False, details
        elif "label" in expected:
            exp_label = expected["label"]
            act_label = response.get("label")
            if act_label is None:
                details.append(f"missing label (expected {exp_label!r})")
                return False, details
            # Loose match — snake_case may differ slightly
            if exp_label.lower().replace("_", " ") not in act_label.lower().replace("_", " "):
                # also try the reverse
                if act_label.lower().replace("_", " ") not in exp_label.lower().replace("_", " "):
                    details.append(f"label mismatch: expected {exp_label!r}, got {act_label!r}")
                    return False, details
            details.append(f"label={act_label!r} ok")
        return True, details

    if actual_type == "unary_arithmetic":
        exp_op = expected.get("operator")
        act_op = response.get("operator")
        if exp_op and act_op != exp_op:
            details.append(f"operator mismatch: expected {exp_op!r}, got {act_op!r}")
            return False, details
        details.append(f"operator={act_op} ok")
        # Recurse on child if expected has one
        exp_child = expected.get("child")
        act_child = response.get("child")
        if exp_child:
            if not act_child:
                details.append("missing child spec")
                return False, details
            # Recursive structural check
            exp_child_type = exp_child.get("spec_type")
            act_child_type = act_child.get("spec_type") if isinstance(act_child, dict) else None
            if exp_child_type and act_child_type != exp_child_type:
                details.append(f"child spec_type mismatch: expected {exp_child_type!r}, got {act_child_type!r}")
                return False, details
            # If the expected nested spec has its own operator, check it
            if exp_child.get("operator") and act_child.get("operator") != exp_child["operator"]:
                details.append(f"child operator mismatch: expected {exp_child['operator']!r}, got {act_child.get('operator')!r}")
                return False, details
            details.append(f"child={act_child_type} ok")
        return True, details

    if actual_type == "derived_atom":
        exp_kind = expected.get("computation_kind")
        act_kind = response.get("computation_kind")
        if exp_kind and act_kind != exp_kind:
            details.append(f"computation_kind mismatch: expected {exp_kind!r}, got {act_kind!r}")
            return False, details
        details.append(f"computation_kind={act_kind} ok")
        return True, details

    details.append(f"unknown spec_type: {actual_type!r}")
    return False, details


# ---------------------------------------------------------------------------
# Eval driver
# ---------------------------------------------------------------------------

def run_eval(eval_cases_path: str, llm: LLMCaller,
             limit: Optional[int] = None,
             category_filter: Optional[str] = None,
             save_to: Optional[str] = None,
             verbose: bool = True) -> dict:
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
        description = case["description"]
        kind = case["kind"]
        if verbose:
            print(f"\n[{i+1}/{len(cases)}] {cid} ({case['category']})")
            print(f"  description: {description[:80]}")
            print(f"  kind hint:   {kind}")

        prompt = render_numeric_decompose_prompt(description=description, kind=kind)
        stage_name = f"eval_sub_decomposer::{cid}"

        try:
            raw = llm.call(stage_name, prompt)
            saved_responses[stage_name] = raw
            response = _parse_json_response(raw)
            parse_ok = True
        except json.JSONDecodeError as e:
            response = None
            parse_ok = False
            err_detail = f"JSON parse error: {e}"
            raw = locals().get("raw", "")

        if not parse_ok:
            outcome = {
                "id": cid, "category": case["category"],
                "description": description, "kind": kind,
                "passed": False, "parse_ok": False,
                "details": [err_detail],
                "response_raw": raw,
            }
            if verbose:
                print(f"  FAIL: {err_detail}")
        else:
            passed, details = score_case(case, response)
            outcome = {
                "id": cid, "category": case["category"],
                "description": description, "kind": kind,
                "passed": passed, "parse_ok": True,
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
            print(f"    {cat:25s} {stats['passed']}/{stats['total']}")

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
    parser.add_argument("--eval-cases", default=None)
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--offline", default=None)
    parser.add_argument("--save-to", default=None)
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    eval_cases_path = args.eval_cases or os.path.join(here, "eval_cases_sub_decomposer.json")

    if args.offline:
        with open(args.offline) as f:
            cached = json.load(f)
        llm = LLMCaller(model=args.model, offline_responses=cached)
        print(f"Running OFFLINE with {len(cached)} cached responses")
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            if os.environ.get("CLAUDE_API_KEY"):
                os.environ["ANTHROPIC_API_KEY"] = os.environ["CLAUDE_API_KEY"]
            else:
                print("ERROR: set ANTHROPIC_API_KEY (or CLAUDE_API_KEY), or pass --offline")
                sys.exit(2)
        llm = LLMCaller(model=args.model)
        print(f"Running LIVE with model={args.model}")

    run_eval(
        eval_cases_path, llm,
        limit=args.limit, category_filter=args.category,
        save_to=args.save_to,
    )


if __name__ == "__main__":
    main()

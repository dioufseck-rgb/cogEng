"""
test_fcba_composite_refined_direct.py — Direct prompting comparison for
the policy-faithful refined version.

Same 13 cases (9 original + 4 new that exercise the depth). Same model
selectable. Tests whether direct prompting can correctly handle the
deeper policy structure, particularly:
  - Acknowledgment waiver requires FULL procedure complete within 30 days
  - Different-error procedure requires correction + credit components
  - Two-billing-cycle deadline can be binding before 90-day deadline
  - Collection of related charges is independently prohibited
"""
import argparse
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from bin.test_fcba_composite_refined import TEST_CASES
from bin.test_fcba_composite_direct import POLICY_TEXT


DIRECT_PROMPT_TEMPLATE = """You are a compliance analyst adjudicating a credit-card billing-dispute
resolution under federal regulation. Determine whether the dispute described
in the case file was PROPERLY RESOLVED under 12 CFR §1026.13.

The full resolution must satisfy ALL of the following:
  - §1026.13(b): the consumer's dispute notice was valid
  - §1026.13(c): the creditor acted within required time limits, with two
    interacting rules:
      (i)  Either acknowledge within 30 days, OR complete the FULL §1026.13(e)
           or (f) procedure within 30 days (acknowledgment waiver).
      (ii) Complete the resolution within both two complete billing cycles
           AND no later than 90 days. The lesser of these is binding.
  - §1026.13(d): the creditor did not (a) attempt to collect any portion
    of the disputed amount OR any related finance or other charges, (b)
    report or threaten adverse credit reporting, or (c) restrict the
    account by reason of the dispute.
  - §1026.13(e): if conclusion is "error as asserted," correct the error,
    credit the account (BOTH the disputed amount AND related finance
    charges AND any related other charges), and send the correction notice.
  - §1026.13(f): if conclusion is "different error," provide written
    explanation, correct the different error, and credit the account
    (same three components as (e)). If conclusion is "no error," provide
    written explanation; if consumer requested documentary evidence,
    furnish it.

If ANY requirement fails, the resolution is improperly handled. If the case
does not provide enough information to determine whether a specific
requirement is met, return UND rather than guessing.

==========================================================================
REGULATION
==========================================================================
{policy}

==========================================================================
CASE FILE
==========================================================================
{case}

==========================================================================
INSTRUCTIONS
==========================================================================

Reason carefully through each requirement. Pay particular attention to:
- The acknowledgment-waiver requires the FULL procedure to be complete.
  Procedure incomplete = waiver does not apply.
- The credit obligation has three components (disputed amount, related
  finance charges, related other charges). Missing any component = procedure
  incomplete.
- The two-billing-cycle deadline can be BINDING before 90 days if the
  cycles close earlier than day 90.
- Collection of related finance charges is independently prohibited,
  even if the principal wasn't collected.

After your reasoning, output your final disposition on a single line in
this exact format:

DISPOSITION: TRUE    (if the resolution was proper)
DISPOSITION: FALSE   (if the resolution was improper)
DISPOSITION: UND     (if the case lacks sufficient information)

Do not output anything after the DISPOSITION line.
""".strip()


def call_direct_llm(case_text, model):
    from rulekit.build.decomposer import LLMCaller
    
    prompt = DIRECT_PROMPT_TEMPLATE.format(policy=POLICY_TEXT, case=case_text)
    
    llm = LLMCaller(model=model)
    t0 = time.time()
    response = llm.call(f"fcba_refined_direct_{int(time.time()*1000)}", prompt)
    elapsed = time.time() - t0
    return response, elapsed


def parse_disposition(response):
    match = re.search(r"DISPOSITION:\s*(TRUE|FALSE|UND)", response, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    lines = response.strip().split("\n")
    for line in reversed(lines[-5:]):
        line_upper = line.upper()
        if "DISPOSITION" in line_upper:
            if "TRUE" in line_upper: return "TRUE"
            if "FALSE" in line_upper: return "FALSE"
            if "UND" in line_upper: return "UND"
    return "UNPARSED"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-haiku-4-5-20251001")
    p.add_argument("--cases", nargs="+", default=None)
    p.add_argument("--save-traces", action="store_true")
    args = p.parse_args()
    
    print("=" * 70)
    print("FCBA §1026.13 Refined — Direct Prompting Comparison")
    print(f"Model: {args.model}")
    print("=" * 70)
    print()
    
    cases = TEST_CASES
    if args.cases:
        cases = [c for c in TEST_CASES if c["label"] in args.cases]
    
    print(f"Running {len(cases)} cases through direct prompting")
    print()
    
    results = []
    
    for case in cases:
        print("=" * 70)
        print(f"Case: {case['label']}")
        print(f"Expected: {case['expected']}")
        print()
        
        try:
            response, elapsed = call_direct_llm(case["case_text"], model=args.model)
        except Exception as e:
            print(f"  LLM ERROR: {e}")
            results.append({"label": case["label"], "status": "llm_error",
                            "error": str(e)})
            continue
        
        disposition = parse_disposition(response)
        correct = (disposition == case["expected"])
        outcome = "✓ CORRECT" if correct else "✗ WRONG"
        
        print(f"  Latency: {elapsed:.2f}s")
        print(f"  Response length: {len(response)} chars")
        print(f"  Disposition: {disposition} | Expected: {case['expected']} | {outcome}")
        
        if args.save_traces or not correct:
            print()
            print("  --- Response excerpt ---")
            if len(response) > 1500:
                print(f"  {response[:1200]}")
                print(f"  ...")
                print(f"  {response[-300:]}")
            else:
                print(f"  {response}")
            print("  ------------------------")
        print()
        
        results.append({
            "label": case["label"],
            "status": "completed",
            "expected": case["expected"],
            "disposition": disposition,
            "correct": correct,
            "latency_s": elapsed,
            "response_chars": len(response),
            "response": response if args.save_traces else None,
        })
    
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    completed = [r for r in results if r["status"] == "completed"]
    correct = [r for r in completed if r["correct"]]
    print(f"Cases completed: {len(completed)} / {len(cases)}")
    print(f"Correct dispositions: {len(correct)} / {len(completed)} "
          f"({100*len(correct)/max(1,len(completed)):.0f}%)")
    
    if completed:
        latencies = [r["latency_s"] for r in completed]
        chars = [r["response_chars"] for r in completed]
        print(f"\nLLM latency: min={min(latencies):.2f}s, "
              f"max={max(latencies):.2f}s, "
              f"mean={sum(latencies)/len(latencies):.2f}s")
        print(f"Response length: min={min(chars)}, max={max(chars)}, "
              f"mean={sum(chars)//len(chars)} chars")
    
    print("\nPer-case breakdown:")
    for r in results:
        if r["status"] != "completed":
            print(f"  {r['label']}: {r['status']}")
            continue
        mark = "✓" if r["correct"] else "✗"
        print(f"  {mark} {r['label']}: got {r['disposition']}, "
              f"expected {r['expected']}")
    
    out_path = "audits/fcba_composite_refined_direct/results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"model": args.model, "results": results}, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

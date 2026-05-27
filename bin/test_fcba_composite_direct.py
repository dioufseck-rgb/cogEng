"""
test_fcba_composite_direct.py — Direct-prompting comparison against
test_fcba_composite_resolution.py on the composite §1026.13 question.

Same 9 cases. Same model selectable. Policy text expanded to include
§§1026.13(a)-(f) since the composite spans all of them. The model is
asked to walk through each sub-determination and produce a final
disposition.

What this tests:
- Does CoT scale with logical complexity? Same approach as the simple
  case, but the determination has 4 sub-trees, 26 atoms, ~56 nodes.
- Does direct prompting's accuracy degrade as the determination's
  structure deepens?
- How does latency grow vs. RuleKit's adjudication?
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from bin.test_fcba_composite_resolution import TEST_CASES


# ===========================================================================
# Policy text — broader than the standalone §1026.13(b) test
# ===========================================================================

POLICY_TEXT = """
12 CFR §1026.13 — Billing error resolution

(a) Definition of billing error. For purposes of this section, the term
"billing error" means any of the following types of errors:
    (1) A reflection on or with a periodic statement of an extension of
        credit that is not made to the consumer or to a person who has
        actual, implied, or apparent authority to use the consumer's
        credit card or open-end credit plan.
    (2) A reflection on or with a periodic statement of an extension of
        credit that is not identified in accordance with the requirements
        of §§1026.7(a)(2) and 1026.8.
    (3) A reflection on or with a periodic statement of an extension of
        credit for property or services not accepted by the consumer or
        the consumer's designee, or not delivered to the consumer or the
        consumer's designee as agreed.
    (4) A reflection on a periodic statement of the creditor's failure to
        credit properly a payment or other credit to the account.
    (5) A reflection on a periodic statement of a computational or similar
        error of an accounting nature that is made by the creditor.
    (6) A reflection on a periodic statement of an extension of credit
        for which the consumer requests additional clarification, including
        documentary evidence.
    (7) The creditor's failure to mail or deliver a periodic statement to
        the consumer's last known address.

(b) Billing error notice. A billing error notice is a written notice
from a consumer that:
    (1) Is received by a creditor at the address disclosed under
        §1026.7(a)(9) or §1026.7(b)(9), as applicable, no later than 60
        days after the creditor transmitted the first periodic statement
        that reflects the alleged billing error;
    (2) Enables the creditor to identify the consumer's name and account
        number; and
    (3) To the extent possible, indicates the consumer's belief and the
        reasons for the belief that a billing error exists, and the type,
        date, and amount of the error.

(c) Time for resolution; general procedures. A creditor shall comply with
the requirements of paragraphs (e) and (f) of this section within two
complete billing cycles (but in no event later than 90 days) after
receiving a billing error notice, and shall, within 30 days of receipt of
the notice, mail or deliver to the consumer a written acknowledgment that
the creditor has received the notice. The acknowledgment is not required
if the creditor complies with the requirements of paragraphs (e) and (f)
of this section within the 30-day period.

(d) Rules pending resolution. Until a billing error is resolved under
paragraph (e) or (f) of this section, the following rules apply:
    (1) Consumer's right to withhold disputed amount; collection action
        prohibited. The consumer need not pay (and the creditor may not
        try to collect) any portion of any required payment that the
        consumer believes is related to the disputed amount.
    (2) Adverse credit reports prohibited. The creditor or its agent
        shall not (directly or indirectly) make or threaten to make an
        adverse report to any person about the consumer's credit standing
        or report that an amount or account is delinquent because the
        consumer failed to pay the disputed amount or any related finance
        or other charges.
    (3) Restrictions or closing of account prohibited. The creditor shall
        not restrict or close an account due to the consumer's failure to
        pay the disputed amount.

(e) Procedures if billing error occurred as asserted. If a creditor
determines that a billing error occurred as asserted, it shall, within
the time limits in paragraph (c) of this section:
    (1) Correct the billing error;
    (2) Credit the consumer's account with any disputed amount and any
        related finance or other charges, as applicable; and
    (3) Mail or deliver a correction notice to the consumer.

(f) Procedures if different billing error or no billing error occurred.
If, after conducting a reasonable investigation, a creditor determines
that no billing error occurred or that a different billing error from
that asserted occurred, the creditor shall, within the time limits in
paragraph (c) of this section:
    (1) Mail or deliver to the consumer an explanation that sets forth
        the reasons for the creditor's belief that the billing error
        alleged by the consumer is incorrect in whole or in part;
    (2) Furnish copies of documentary evidence of the consumer's
        indebtedness, if the consumer so requests; and
    (3) If a different billing error occurred, correct the billing error
        and credit the consumer's account with any disputed amount and
        related finance or other charges, as applicable.
""".strip()


DIRECT_PROMPT_TEMPLATE = """You are a compliance analyst adjudicating a credit-card billing-dispute
resolution under federal regulation. Determine whether the dispute described
in the case file was PROPERLY RESOLVED under 12 CFR §1026.13.

The full resolution must satisfy ALL of the following:
  - §1026.13(b): the consumer's dispute notice was valid
  - §1026.13(c): the creditor acted within required time limits
  - §1026.13(d): the creditor did not take prohibited actions during resolution
  - §1026.13(e) or (f): the creditor followed the correct procedure for its
    conclusion (error as asserted, different error, or no error)

If ANY requirement fails, the resolution is improperly handled. If the case
does not provide enough information to determine whether a specific
requirement is met, consider whether you have enough information to give
a confident disposition.

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

Reason step by step:

  1. Notice validity (§1026.13(b)): Was the notice timely (≤60 days from
     statement)? At the designated address? In writing? Identifying the
     consumer? Indicating belief of error? Stating amount, reason, type,
     and date of error?

  2. Timing compliance (§1026.13(c)): Did the creditor acknowledge within
     30 days OR resolve within 30 days? AND did the creditor complete the
     resolution within both two billing cycles AND 90 days?

  3. Conduct compliance (§1026.13(d)): During the resolution period, did
     the creditor refrain from (a) attempting to collect the disputed
     amount, (b) reporting it as delinquent, (c) threatening adverse credit
     reporting, and (d) restricting the account by reason of the dispute?

  4. Conclusion procedure (§1026.13(e) or (f)): Which conclusion did the
     creditor reach (error as asserted, different error, no error)? Did
     they follow the correct procedure for that conclusion? For 'no error',
     if the consumer requested documentary evidence, was it provided?

After your reasoning, output your final disposition on a single line in
this exact format:

DISPOSITION: TRUE    (if the resolution was proper)
DISPOSITION: FALSE   (if the resolution was improper — any sub-determination failed)
DISPOSITION: UND     (if the case does not provide enough information)

Do not output anything after the DISPOSITION line.
""".strip()


def call_direct_llm(case_text, model):
    from rulekit.build.decomposer import LLMCaller
    
    prompt = DIRECT_PROMPT_TEMPLATE.format(
        policy=POLICY_TEXT,
        case=case_text,
    )
    
    llm = LLMCaller(model=model)
    t0 = time.time()
    response = llm.call(f"fcba_composite_direct_{int(time.time()*1000)}", prompt)
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
    p.add_argument("--save-traces", action="store_true",
                   help="Save full LLM responses for trace-quality comparison")
    args = p.parse_args()
    
    print("=" * 70)
    print("FCBA §1026.13 Composite — Direct Prompting Comparison")
    print(f"Model: {args.model}")
    print("=" * 70)
    print()
    
    cases = TEST_CASES
    if args.cases:
        cases = [c for c in TEST_CASES if c["label"] in args.cases]
    
    print(f"Running {len(cases)} composite cases through direct prompting")
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
        print(f"  {mark} {r['label']}: got {r['disposition']}, expected {r['expected']}")
    
    out_path = "audits/fcba_composite_direct/results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"model": args.model, "results": results}, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

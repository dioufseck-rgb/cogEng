"""
test_fcba_direct_prompting.py — Direct-prompting comparison against
test_fcba_notice_validity.py.

Same 8 cases. Same policy (§1026.13(b)). Same question (is the dispute
notice valid?). Same model (Haiku by default, or Sonnet for upper-bound
direct-prompting comparison).

The prompt is reasonable: includes the policy text, includes the case,
asks for chain-of-thought reasoning, then a structured disposition.
This is what a competent AI engineer would write if their first instinct
was 'just give it the policy and ask.'

What this comparison reveals:
  - Accuracy: how often does direct prompting agree with the expected
    disposition?
  - Latency: a single LLM call vs RuleKit's Map+engine pipeline
  - Trace quality: narrative-about-reasoning vs deterministic computation
  - Failure modes: does direct prompting hallucinate, agree confidently
    with wrong premises, or return UND honestly?

Cost: ~$1-3 (8 LLM calls; longer prompts than Map because policy is
included). Time: ~30-60 seconds.
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


# ===========================================================================
# Policy text — what we hand to the model
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
        the consumer's last known address if that address was received by
        the creditor, in writing, at least 20 days before the end of the
        billing cycle for which the statement was required.

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
paragraph (e) or (f) of this section, the following rules apply: ...
[remainder omitted as not relevant to notice validity]

(e) Procedures if billing error occurred as asserted. If a creditor
determines that a billing error occurred as asserted, it shall, within
the time limits in paragraph (c) of this section: ...
[remainder omitted]

(f) Procedures if different billing error or no billing error occurred. ...
[remainder omitted]

(g) Creditor's rights and duties after resolution. ...
[remainder omitted]
""".strip()


# ===========================================================================
# Test cases — IDENTICAL to test_fcba_notice_validity.py
# ===========================================================================

TEST_CASES = [
    {
        "label": "T1_clean_valid_notice",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-7821

Cardholder: Jennifer Adams
Account number: 4XXX-XXXX-XXXX-7821
Statement transmitted: March 15, 2026
Disputed transaction date: March 3, 2026
Disputed amount: $189.42 (merchant: "QUICKMART ONLINE")

Dispute notice received: April 2, 2026
Channel: Written letter mailed to PO Box 5000, Vienna, VA — the address
disclosed on the back of the statement for billing inquiries.
Letter contents (verbatim, in part):
  "I am writing to dispute a charge on my account ending in 7821. I do
   not recognize the $189.42 charge from QUICKMART ONLINE dated March
   3rd. I have never shopped at this merchant and have no record of
   authorizing this transaction. I believe this is an unauthorized
   charge and request that it be removed from my account."

The letter is signed by Jennifer Adams, dated March 29, 2026.
""".strip(),
        "expected": "TRUE",
    },
    {
        "label": "T2_untimely_notice_75_days",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-3344

Cardholder: Marcus Webb
Account number: 5XXX-XXXX-XXXX-3344
Statement transmitted: January 10, 2026 (first statement reflecting disputed charge)
Disputed transaction: $1,250.00 to "TECHWORLD INC" dated December 28, 2025

Dispute notice received: March 26, 2026 (75 days after the January statement)
Channel: Written letter to the disclosed billing inquiries address.
Letter contents: clearly identifies consumer (name, account number),
states belief of error (consumer says he was charged twice), states amount
($1,250), states type (duplicate billing), states date (December 28, 2025),
states reason (he has a receipt showing the charge was already processed
on his earlier December statement).
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "T3_oral_notice_phone_only",
        "case_text": """
DISPUTE CASE FILE — Account 6XXX-XXXX-XXXX-9012

Cardholder: Priya Sharma
Customer service log entry:
  March 22, 2026, 14:32 — Inbound call from Priya Sharma (verified by
  account number 9012 and date of birth). Caller disputes a $67.45 charge
  from "PARKING SOLUTIONS LLC" on her March statement (transmitted March 8).
  Caller says she did not park at any garage that day and does not recognize
  the merchant. Agent created dispute ticket #DSP-2026-44871. Caller
  declined to send written confirmation, stated "my call should be enough."

No written notice was subsequently received.
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "T4_missing_dollar_amount",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-5566

Cardholder: David Liu
Account number: 4XXX-XXXX-XXXX-5566
Statement transmitted: February 20, 2026
Dispute notice received: March 8, 2026 (16 days later)
Channel: Written secure message through online banking portal (designated
billing inquiries channel disclosed on bank's website).

Notice contents:
  "I'm writing to dispute charges on my recent statement from a merchant
   I don't recognize. Something called 'STARWAVE' appears multiple times
   and I never authorized these. Please investigate."

The notice does not specify dollar amounts. Multiple "STARWAVE" charges
of varying amounts appear on the statement.
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "T5_wrong_address",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-7799

Cardholder: Elena Rodriguez
Account number: 5XXX-XXXX-XXXX-7799
Statement transmitted: March 1, 2026
Dispute amount: $415.00 to "FITNESS CLUB ELITE" dated February 26, 2026
Dispute notice received: March 18, 2026 (17 days later)

Channel: Written letter mailed to the bank's main corporate headquarters
address found via web search. The bank's statement clearly designates
PO Box 7700, Reston, VA as the address for billing inquiries; the consumer
sent the letter to the corporate HQ at 1500 Corporate Way, Reston, VA
instead.

Letter contents: complete — identifies consumer (name, account number),
states belief of unauthorized charge, states amount ($415), states type
(unauthorized charge for a gym membership consumer says she canceled three
months prior), states date (February 26, 2026), states reason (consumer
has cancellation confirmation email from December 2025).

The letter was eventually forwarded internally to the billing inquiries
department, but it did not arrive at the disclosed address.
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "T6_incomplete_no_reason",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-2200

Cardholder: Akira Tanaka
Account number: 4XXX-XXXX-XXXX-2200
Statement transmitted: April 1, 2026
Disputed charge: $52.99 to "STREAMFLIX" dated March 28, 2026
Dispute notice received: April 12, 2026 (11 days later)
Channel: Written letter to disclosed billing inquiries address.

Notice contents (verbatim):
  "Please reverse the STREAMFLIX charge of $52.99 from March 28 on my
   account ending in 2200. — Akira Tanaka"

The notice identifies the consumer, states the amount, type (implied:
unwanted charge), and date. It does NOT state a reason for the belief
that an error exists — no explanation of why the charge should be
reversed (was it unauthorized? was the service canceled? was it a
duplicate?).
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "T7_underspecified_partial_case",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-8800

Inbound dispute received April 10, 2026. Consumer is Robert Chen.
Charge being disputed is $342.18 from "AUTOPAY SERVICES" dated April 1.
Consumer states the charge is unauthorized.

(Note: the case file is incomplete. Channel of notice receipt is not
documented. Statement transmission date is not in this file. Address
of notice receipt is not specified.)
""".strip(),
        "expected": "UND",
    },
    {
        "label": "T8_borderline_timely_day_60",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-1100

Cardholder: Sarah Goldberg
Account number: 4XXX-XXXX-XXXX-1100
Statement transmitted: February 1, 2026
Notice received: April 2, 2026 — exactly 60 days later.
Channel: Written letter to disclosed billing inquiries address.

Notice contents: complete on all elements — identifies consumer (name,
account number), states belief of error (unauthorized charges), states
amount ($1,847.50 across three charges), states type (unauthorized — card
was reportedly lost January 28), states reason (consumer reports lost
card and these three charges appeared after she would have lost it),
states dates (February 14, 18, and 22, 2026).
""".strip(),
        "expected": "TRUE",
    },
]


# ===========================================================================
# Direct-prompting prompt
# ===========================================================================

DIRECT_PROMPT_TEMPLATE = """You are a compliance analyst adjudicating consumer credit-card billing
disputes under federal regulation. Determine whether the consumer's dispute
notice in the case file below is VALID under 12 CFR §1026.13(b).

Here is the relevant policy text:

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

Determine whether the dispute notice is valid under §1026.13(b).

A valid notice must satisfy ALL requirements stated in §1026.13(b). If
any requirement fails, the notice is invalid. If the case does not provide
enough information to determine whether a specific requirement is met, you
should consider whether you have enough information to give a confident
disposition.

Reason step by step through each requirement:
  1. Is the notice timely (received within 60 days of the first statement
     reflecting the alleged error)?
  2. Was the notice received at the address disclosed for billing inquiries?
  3. Is the notice in writing?
  4. Does the notice enable identification of the consumer's name and
     account number?
  5. Does the notice indicate the consumer's belief and reasons that a
     billing error exists, and the type, date, and amount of the error?

After your reasoning, output your final disposition on a single line in
this exact format:

DISPOSITION: TRUE    (if the notice is valid)
DISPOSITION: FALSE   (if the notice is invalid)
DISPOSITION: UND     (if the case does not provide enough information to determine)

Do not output anything after the DISPOSITION line.
""".strip()


# ===========================================================================
# Run direct prompting
# ===========================================================================

def call_direct_llm(case_text, model):
    """Call the LLM with policy + case in a single prompt."""
    from rulekit.build.decomposer import LLMCaller
    
    prompt = DIRECT_PROMPT_TEMPLATE.format(
        policy=POLICY_TEXT,
        case=case_text,
    )
    
    llm = LLMCaller(model=model)
    t0 = time.time()
    response = llm.call(f"fcba_direct_{int(time.time()*1000)}", prompt)
    elapsed = time.time() - t0
    return response, elapsed


def parse_disposition(response):
    """Extract DISPOSITION: <value> from the response."""
    match = re.search(r"DISPOSITION:\s*(TRUE|FALSE|UND)", response, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    # Fallback: look for the words at the end
    lines = response.strip().split("\n")
    for line in reversed(lines[-5:]):
        line_upper = line.upper()
        if "DISPOSITION" in line_upper:
            if "TRUE" in line_upper: return "TRUE"
            if "FALSE" in line_upper: return "FALSE"
            if "UND" in line_upper: return "UND"
    return "UNPARSED"


# ===========================================================================
# Main
# ===========================================================================

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-haiku-4-5-20251001",
                   help="Model for direct prompting (default: Haiku, same as Map)")
    p.add_argument("--cases", nargs="+", default=None,
                   help="Specific case labels to run")
    p.add_argument("--save-traces", action="store_true",
                   help="Save full LLM responses for trace-quality comparison")
    args = p.parse_args()
    
    print("=" * 70)
    print("FCBA §1026.13(b) — Direct Prompting Comparison")
    print(f"Model: {args.model}")
    print("=" * 70)
    print()
    
    cases = TEST_CASES
    if args.cases:
        cases = [c for c in TEST_CASES if c["label"] in args.cases]
    
    print(f"Running {len(cases)} cases through direct prompting (policy + case + CoT)")
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
            results.append({
                "label": case["label"],
                "status": "llm_error",
                "error": str(e),
            })
            continue
        
        disposition = parse_disposition(response)
        correct = (disposition == case["expected"])
        outcome = "✓ CORRECT" if correct else "✗ WRONG"
        
        print(f"  Latency: {elapsed:.2f}s")
        print(f"  Response length: {len(response)} chars")
        print(f"  Disposition: {disposition} | Expected: {case['expected']} | {outcome}")
        
        if args.save_traces or not correct:
            # Show the reasoning for wrong cases
            print()
            print("  --- Response excerpt ---")
            # Show first 1000 chars and last 300 chars
            if len(response) > 1300:
                print(f"  {response[:1000]}")
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
    
    # Summary
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
        print()
        print(f"LLM latency: min={min(latencies):.2f}s, "
              f"max={max(latencies):.2f}s, "
              f"mean={sum(latencies)/len(latencies):.2f}s")
        print(f"Response length: min={min(chars)}, max={max(chars)}, "
              f"mean={sum(chars)//len(chars)} chars")
    
    print()
    print("Per-case breakdown:")
    for r in results:
        if r["status"] != "completed":
            print(f"  {r['label']}: {r['status']}")
            continue
        mark = "✓" if r["correct"] else "✗"
        print(f"  {mark} {r['label']}: got {r['disposition']}, expected {r['expected']}")
    
    # Side-by-side with RuleKit
    print()
    print("=" * 70)
    print("COMPARISON WITH RULEKIT (test_fcba_notice_validity.py)")
    print("=" * 70)
    print()
    print("RuleKit prior run (Haiku Map + Engine):")
    print("  Accuracy: 7/8 (88%)")
    print("    - 7 correct dispositions matching expected")
    print("    - 1 honest UND on T8 (Map atom-name typo caused effective missing atom)")
    print("    - 0 confidently-wrong dispositions")
    print("  Mean Map latency: 2.16s")
    print("  Mean engine latency: 0.12ms")
    print("  Trace: deterministic engine evaluation of typed nodes")
    print()
    print(f"Direct prompting ({args.model}):")
    if completed:
        print(f"  Accuracy: {len(correct)}/{len(completed)} ({100*len(correct)/len(completed):.0f}%)")
        print(f"  Mean LLM latency: {sum(latencies)/len(latencies):.2f}s")
        print(f"  Mean response length: {sum(chars)//len(chars)} chars")
        print(f"  Trace: natural-language reasoning narrative")
    
    out_path = "audits/fcba_direct_prompting/results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "model": args.model,
            "results": results,
        }, f, indent=2, default=str)
    print()
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()

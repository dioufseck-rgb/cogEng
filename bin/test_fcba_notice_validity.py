"""
test_fcba_notice_validity.py — RuleKit applied to a real-world compliance
determination: is a consumer's dispute notice valid under FCBA §1026.13(b)?

The Fair Credit Billing Act, implemented in Regulation Z (12 CFR 1026.13),
governs how card issuers handle consumer disputes about billing errors.
Section 1026.13(b) defines the requirements for a valid dispute notice that
triggers the issuer's investigation obligations.

CAVEAT: This DAG is drafted from a working knowledge of the regulation.
Before any production use, the spec must be verified against the current
Code of Federal Regulations. Regulations are amended; precise wording matters.

The determination answers: "Is this dispute notice valid under §1026.13(b)?"

Inputs (atoms):
  - days_between_first_statement_and_notice (numeric): days between the
    creditor's transmission of the first periodic statement reflecting the
    alleged error and the creditor's receipt of the consumer's notice
  - notice_received_at_designated_address (bool): was the notice sent to
    the address the creditor disclosed for billing inquiries?
  - notice_is_written (bool): is the notice in writing? (Oral notice is
    handled separately under §1026.13(g) and is not adjudicated here)
  - notice_identifies_consumer (bool): does the notice enable identification
    of the consumer's name and account number?
  - notice_indicates_belief_of_error (bool): does the notice indicate the
    consumer's belief that a billing error exists?
  - notice_states_dollar_amount (bool): does the notice state the dollar
    amount of the alleged error?
  - notice_states_reason_for_belief (bool): does the notice state the
    consumer's reasons for believing an error exists?
  - notice_states_type_of_error (bool): does the notice state the type of
    error alleged?
  - notice_states_date_of_error (bool): does the notice state the date of
    the error?

Output: TRUE (notice is valid), FALSE (notice is invalid), or UND if atoms
are missing.

The trace shows exactly which condition(s) failed, enabling defensible
disposition for regulatory examination.
"""
import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.engine import FactBundle, Kleene
from rulekit.engine.typed import (
    NumericLeaf, NumericValue, Constant,
    LeqNode,
)
from rulekit.engine.boolean import Leaf, AndNode


# ===========================================================================
# DAG: §1026.13(b) notice validity
# ===========================================================================

def build_fcba_1026_13_b_dag():
    """Build the DAG adjudicating §1026.13(b) notice validity.
    
    A notice is valid iff all six requirements are satisfied:
      1. Timeliness: received within 60 days of first statement
      2. Address: sent to designated address
      3. Form: in writing
      4. Identity: identifies consumer
      5. Belief: indicates belief of error
      6. Content: states amount, reason, type, and date
    """
    # Requirement 1: Timeliness — days <= 60
    timely = LeqNode(
        left=NumericLeaf(atom_id="days_between_first_statement_and_notice"),
        right=Constant(label="sixty_day_limit", value=Decimal("60")),
    )
    
    # Requirement 2: Address
    correct_address = Leaf(atom_id="notice_received_at_designated_address")
    
    # Requirement 3: Form
    written = Leaf(atom_id="notice_is_written")
    
    # Requirement 4: Identity
    identifies = Leaf(atom_id="notice_identifies_consumer")
    
    # Requirement 5: Belief
    indicates_belief = Leaf(atom_id="notice_indicates_belief_of_error")
    
    # Requirement 6: Content — four sub-elements
    content_complete = AndNode(children=[
        Leaf(atom_id="notice_states_dollar_amount"),
        Leaf(atom_id="notice_states_reason_for_belief"),
        Leaf(atom_id="notice_states_type_of_error"),
        Leaf(atom_id="notice_states_date_of_error"),
    ])
    
    # Composition: all six requirements must hold
    return AndNode(children=[
        timely,
        correct_address,
        written,
        identifies,
        indicates_belief,
        content_complete,
    ])


# ===========================================================================
# Atom catalog
# ===========================================================================

ATOM_DESCRIPTIONS = {
    "days_between_first_statement_and_notice": (
        "the number of days between when the creditor transmitted the first "
        "periodic statement reflecting the alleged billing error and when "
        "the creditor received the consumer's dispute notice. Return as "
        "an integer count of days."
    ),
    "notice_received_at_designated_address": (
        "true if the dispute notice was sent to the address the creditor "
        "disclosed for billing inquiries (typically printed on the back of "
        "the statement or in a designated billing rights notice); false "
        "if it was sent elsewhere (e.g., a customer service email, branch "
        "office, or wrong address)."
    ),
    "notice_is_written": (
        "true if the consumer's notice was in writing (a letter, secure "
        "message through the bank's portal, or other written form); false "
        "if oral only (phone call without follow-up written notice)."
    ),
    "notice_identifies_consumer": (
        "true if the notice contains both the consumer's name and account "
        "number (or other sufficient identification); false if either is "
        "missing or insufficient to identify the account."
    ),
    "notice_indicates_belief_of_error": (
        "true if the notice indicates the consumer's belief that a billing "
        "error exists on the account; false if the notice does not assert "
        "belief in an error (e.g., is purely informational or asks a "
        "question without claiming error)."
    ),
    "notice_states_dollar_amount": (
        "true if the notice states the dollar amount of the alleged billing "
        "error; false if no amount is stated."
    ),
    "notice_states_reason_for_belief": (
        "true if the notice provides reasons supporting the consumer's "
        "belief that an error exists (the consumer's basis); false if no "
        "rationale is given."
    ),
    "notice_states_type_of_error": (
        "true if the notice describes the type of error alleged (e.g., "
        "unauthorized charge, duplicate billing, amount discrepancy, "
        "computational error, etc.); false if no type is identified."
    ),
    "notice_states_date_of_error": (
        "true if the notice states the date of the alleged error (typically "
        "the transaction date or the statement date); false if no date is "
        "specified."
    ),
}


# ===========================================================================
# Map: extract atoms from case input
# ===========================================================================

MAP_PROMPT_TEMPLATE = """You are extracting structured facts from a consumer-dispute case file.

A consumer has submitted a dispute notice to their credit card issuer
claiming a billing error. You are helping adjudicate whether the notice is
valid under FCBA §1026.13(b). Extract specific typed atoms the adjudication
engine needs.

ATOMS TO EXTRACT (only extract values explicitly stated or directly evident
from the case; use null for anything unclear or unstated):

{atom_descriptions}

CASE FILE:
{case_text}

EXTRACTION GUIDANCE:
- For days_between_first_statement_and_notice: compute from dates if both
  are given (statement date and notice receipt date). Return integer days.
  Return null if either date is missing or ambiguous.
- For Booleans: return true if the case explicitly establishes the fact,
  false if the case explicitly establishes the negation, null if unclear
  or not addressed.
- Do not assume defaults. A case that doesn't mention whether the notice
  was at the designated address should produce null, not false.

OUTPUT INSTRUCTIONS:
Return ONLY a JSON object mapping atom names to values (numbers, true/false,
or null). No preamble, no commentary, no markdown formatting.
"""


def call_map_llm(case_text, model="claude-haiku-4-5-20251001"):
    """Call the LLM to extract atoms from case input."""
    from rulekit.build.decomposer import LLMCaller
    import re as _re
    
    atoms_text = "\n".join(
        f"  - {name}: {desc}" for name, desc in ATOM_DESCRIPTIONS.items()
    )
    prompt = MAP_PROMPT_TEMPLATE.format(
        atom_descriptions=atoms_text,
        case_text=case_text,
    )
    
    llm = LLMCaller(model=model)
    t0 = time.time()
    response = llm.call(f"fcba_map_{int(time.time()*1000)}", prompt)
    elapsed = time.time() - t0
    
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = _re.sub(r"^```(?:json)?\n", "", cleaned)
        cleaned = _re.sub(r"\n```\s*$", "", cleaned)
    try:
        atoms = json.loads(cleaned)
    except json.JSONDecodeError:
        match = _re.search(r"\{.*\}", cleaned, _re.DOTALL)
        if match:
            atoms = json.loads(match.group(0))
        else:
            atoms = {}
    
    return atoms, elapsed


def build_fact_bundle(atoms_dict):
    """Convert atom dict from Map to a typed FactBundle, handling missing atoms."""
    values = {}
    for name in ATOM_DESCRIPTIONS:
        val = atoms_dict.get(name)
        if val is None:
            if name == "days_between_first_statement_and_notice":
                values[name] = NumericValue.undetermined()
            else:
                values[name] = Kleene.UNDETERMINED
        elif isinstance(val, bool):
            values[name] = Kleene.TRUE if val else Kleene.FALSE
        elif isinstance(val, (int, float)):
            values[name] = NumericValue(value=Decimal(str(val)))
        else:
            values[name] = Kleene.UNDETERMINED
    return FactBundle(values=values)


# ===========================================================================
# Test cases: realistic dispute scenarios
# ===========================================================================
#
# Each case is a (case_text, expected_disposition, rationale) tuple.
# The case_text is structured narrative as a dispute investigator might
# encounter it.

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
        "expected_disposition": "TRUE",
        "rationale": "All six §1026.13(b) requirements met: timely (18 days), correct address, written, identifies consumer, indicates belief, states amount/reason/type/date.",
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
        "expected_disposition": "FALSE",
        "rationale": "Untimely under §1026.13(b)(1): 75 days exceeds 60-day limit. Other elements met but timeliness alone fails the conjunction.",
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
        "expected_disposition": "FALSE",
        "rationale": "Not in writing per §1026.13(b). Oral notice is covered by §1026.13(g) which has its own treatment. This adjudicator handles only written notices.",
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
        "expected_disposition": "FALSE",
        "rationale": "Notice lacks specific dollar amount required by §1026.13(b). Other elements met, but missing amount alone fails the conjunction.",
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
        "expected_disposition": "FALSE",
        "rationale": "Notice not received at designated address per §1026.13(b). Other elements met. (Note: in practice, banks often handle these as if valid as a courtesy, but the regulation's strict text supports invalidity.)",
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
        "expected_disposition": "FALSE",
        "rationale": "Notice lacks the consumer's reasons for believing an error exists. §1026.13(b)(3) requires the notice to indicate reasons. (Note: this is a closer call in practice — some adjudicators might accept the implicit reason. The strict reading supports invalidity.)",
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
        "expected_disposition": "UND",
        "rationale": "Case under-specifies several required atoms. Architecture should return UND (insufficient atoms) rather than guess. This is the correct behavior — the institution must gather more information before adjudicating.",
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
        "expected_disposition": "TRUE",
        "rationale": "60 days is at the boundary — §1026.13(b)(1) says 'no later than 60 days,' which includes day 60. All other elements met. This tests the LeqNode boundary correctly.",
    },
]


# ===========================================================================
# Sanity checks on DAG with hand-constructed inputs
# ===========================================================================

def run_dag_sanity_checks():
    """Verify the DAG behaves correctly on hand-crafted atom bundles."""
    dag = build_fcba_1026_13_b_dag()
    
    # All true: should produce TRUE
    all_true_atoms = {
        "days_between_first_statement_and_notice": 30,
        "notice_received_at_designated_address": True,
        "notice_is_written": True,
        "notice_identifies_consumer": True,
        "notice_indicates_belief_of_error": True,
        "notice_states_dollar_amount": True,
        "notice_states_reason_for_belief": True,
        "notice_states_type_of_error": True,
        "notice_states_date_of_error": True,
    }
    bundle = build_fact_bundle(all_true_atoms)
    result = dag.evaluate(bundle, [])
    assert result == Kleene.TRUE, f"All-true case should be TRUE, got {result}"
    
    # Untimely: should produce FALSE
    untimely = dict(all_true_atoms)
    untimely["days_between_first_statement_and_notice"] = 75
    bundle = build_fact_bundle(untimely)
    result = dag.evaluate(bundle, [])
    assert result == Kleene.FALSE, f"Untimely case should be FALSE, got {result}"
    
    # Exactly 60 days: should produce TRUE (boundary)
    boundary = dict(all_true_atoms)
    boundary["days_between_first_statement_and_notice"] = 60
    bundle = build_fact_bundle(boundary)
    result = dag.evaluate(bundle, [])
    assert result == Kleene.TRUE, f"60-day boundary should be TRUE, got {result}"
    
    # Missing dollar amount: should produce FALSE
    no_amount = dict(all_true_atoms)
    no_amount["notice_states_dollar_amount"] = False
    bundle = build_fact_bundle(no_amount)
    result = dag.evaluate(bundle, [])
    assert result == Kleene.FALSE, f"No-amount case should be FALSE, got {result}"
    
    # Some atoms UND: should produce UND
    partial = {
        "days_between_first_statement_and_notice": 30,
        "notice_received_at_designated_address": True,
        # Other atoms missing — will be UND
    }
    bundle = build_fact_bundle(partial)
    result = dag.evaluate(bundle, [])
    assert result == Kleene.UNDETERMINED, f"Partial case should be UND, got {result}"
    
    print("All 5 DAG sanity checks pass")
    return True


# ===========================================================================
# Main
# ===========================================================================

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--map-model", default="claude-haiku-4-5-20251001")
    p.add_argument("--cases", nargs="+", default=None,
                   help="Specific case labels to run")
    p.add_argument("--skip-sanity", action="store_true")
    args = p.parse_args()
    
    print("=" * 70)
    print("FCBA §1026.13(b) Notice Validity Adjudicator")
    print("=" * 70)
    print()
    
    if not args.skip_sanity:
        print("DAG sanity checks:")
        run_dag_sanity_checks()
        print()
    
    dag = build_fcba_1026_13_b_dag()
    
    cases = TEST_CASES
    if args.cases:
        cases = [c for c in TEST_CASES if c["label"] in args.cases]
    
    print(f"Running {len(cases)} test cases through Map + Engine pipeline")
    print()
    
    results = []
    
    for case in cases:
        print("=" * 70)
        print(f"Case: {case['label']}")
        print(f"Expected disposition: {case['expected_disposition']}")
        print(f"Rationale: {case['rationale']}")
        print()
        print("Case text (excerpt):")
        excerpt = case["case_text"][:300]
        print(f"  {excerpt}...")
        print()
        
        # Map
        print("Map (extracting atoms)...")
        try:
            atoms, map_elapsed = call_map_llm(case["case_text"], model=args.map_model)
        except Exception as e:
            print(f"  MAP ERROR: {e}")
            results.append({
                "label": case["label"], "status": "map_error", "error": str(e),
            })
            continue
        
        print(f"  Map latency: {map_elapsed:.2f}s")
        non_null = {k: v for k, v in atoms.items() if v is not None}
        print(f"  Extracted ({len(non_null)}/9 atoms):")
        for k, v in non_null.items():
            print(f"    {k}: {v}")
        null_atoms = [k for k, v in atoms.items() if v is None]
        if null_atoms:
            print(f"  UND atoms: {null_atoms}")
        
        # Engine
        bundle = build_fact_bundle(atoms)
        t0 = time.time()
        result = dag.evaluate(bundle, [])
        engine_elapsed = (time.time() - t0) * 1000
        
        print(f"  Engine latency: {engine_elapsed:.2f}ms")
        print(f"  Engine result: {result}")
        
        # Score
        if result == Kleene.TRUE:
            disposition = "TRUE"
        elif result == Kleene.FALSE:
            disposition = "FALSE"
        else:
            disposition = "UND"
        
        correct = (disposition == case["expected_disposition"])
        outcome = "✓ CORRECT" if correct else "✗ WRONG"
        print(f"  Disposition: {disposition} | Expected: {case['expected_disposition']} | {outcome}")
        print()
        
        results.append({
            "label": case["label"],
            "status": "completed",
            "expected": case["expected_disposition"],
            "disposition": disposition,
            "correct": correct,
            "atoms_extracted": atoms,
            "map_latency_s": map_elapsed,
            "engine_latency_ms": engine_elapsed,
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
        latencies = [r["map_latency_s"] for r in completed]
        engine_latencies = [r["engine_latency_ms"] for r in completed]
        print()
        print(f"Map latency: min={min(latencies):.2f}s, "
              f"max={max(latencies):.2f}s, "
              f"mean={sum(latencies)/len(latencies):.2f}s")
        print(f"Engine latency: min={min(engine_latencies):.2f}ms, "
              f"max={max(engine_latencies):.2f}ms, "
              f"mean={sum(engine_latencies)/len(engine_latencies):.2f}ms")
    
    # Per-case breakdown
    print()
    print("Per-case breakdown:")
    for r in results:
        if r["status"] != "completed":
            print(f"  {r['label']}: {r['status']}")
            continue
        mark = "✓" if r["correct"] else "✗"
        print(f"  {mark} {r['label']}: got {r['disposition']}, expected {r['expected']}")
    
    out_path = "audits/fcba_notice_validity/results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print()
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()

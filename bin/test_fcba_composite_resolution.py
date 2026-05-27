"""
test_fcba_composite_resolution.py — RuleKit applied to the composite
§1026.13 dispute resolution adjudication.

The question: Was a credit-card billing dispute properly resolved under
12 CFR §1026.13?

This composes FOUR sub-determinations:
  1. Was the notice valid under §1026.13(b)?
  2. Was the timing compliant under §1026.13(c)?
  3. Was the creditor's conduct during resolution compliant under §1026.13(d)?
  4. Was the conclusion procedure correct under §1026.13(e) or (f)?

The composition is AND across all four. Each is itself structured.
Total DAG: ~100 nodes, 26 atoms.

CONSTRUCTION RECORD:
This file is structured to mirror the construction procedure so the build
process is legible. The phases of the construction were:
  1. Read policy text, identify subsections
  2. Identify what determination each subsection contributes to
  3. Decompose each contribution into atoms and logical structure
  4. Compose each subsection's structure
  5. Compose the full determination across subsections
  6. Verify sanity with hand-crafted inputs
  7. Verify against realistic test cases

Each phase is reflected in the code structure below.
"""
import argparse
import json
import os
import re
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
from rulekit.engine.boolean import Leaf, AndNode, OrNode, NotNode


# ===========================================================================
# Phase 5a: Sub-determination 1 — §1026.13(b) notice validity
# ===========================================================================
# Same structure as the standalone notice-validity adjudicator.

def build_notice_validity_subtree():
    """§1026.13(b): A valid notice is a written notice received timely at
    the designated address, identifying the consumer, indicating belief of
    error, and stating amount/reason/type/date."""
    timely = LeqNode(
        left=NumericLeaf(atom_id="days_between_first_statement_and_notice"),
        right=Constant(label="sixty_day_limit", value=Decimal("60")),
    )
    content_complete = AndNode(children=[
        Leaf(atom_id="notice_states_dollar_amount"),
        Leaf(atom_id="notice_states_reason_for_belief"),
        Leaf(atom_id="notice_states_type_of_error"),
        Leaf(atom_id="notice_states_date_of_error"),
    ])
    return AndNode(children=[
        timely,
        Leaf(atom_id="notice_received_at_designated_address"),
        Leaf(atom_id="notice_is_written"),
        Leaf(atom_id="notice_identifies_consumer"),
        Leaf(atom_id="notice_indicates_belief_of_error"),
        content_complete,
    ])


# ===========================================================================
# Phase 5b: Sub-determination 2 — §1026.13(c) timing compliance
# ===========================================================================
# Two requirements:
#   - Acknowledge within 30 days OR resolve within 30 days
#   - Resolve within two billing cycles AND within 90 days (the "no event
#     later than 90 days" rule)

def build_timing_compliance_subtree():
    """§1026.13(c): timing for acknowledgment and resolution.
    
    Composed of:
      - acknowledgment_or_early_resolution: ack within 30 OR resolved within 30
      - outer_limit_satisfied: resolved within both 2 billing cycles AND 90 days
    Both must hold.
    """
    acknowledged_within_30 = LeqNode(
        left=NumericLeaf(atom_id="days_from_notice_to_acknowledgment"),
        right=Constant(label="thirty_day_ack_limit", value=Decimal("30")),
    )
    resolved_within_30 = LeqNode(
        left=NumericLeaf(atom_id="days_from_notice_to_resolution"),
        right=Constant(label="thirty_day_res_limit", value=Decimal("30")),
    )
    acknowledgment_or_early_resolution = OrNode(children=[
        acknowledged_within_30,
        resolved_within_30,
    ])
    
    resolved_within_90 = LeqNode(
        left=NumericLeaf(atom_id="days_from_notice_to_resolution"),
        right=Constant(label="ninety_day_limit", value=Decimal("90")),
    )
    outer_limit_satisfied = AndNode(children=[
        Leaf(atom_id="resolved_within_two_billing_cycles"),
        resolved_within_90,
    ])
    
    return AndNode(children=[
        acknowledgment_or_early_resolution,
        outer_limit_satisfied,
    ])


# ===========================================================================
# Phase 5c: Sub-determination 3 — §1026.13(d) conduct compliance
# ===========================================================================
# Four prohibited actions; none must have occurred.

def build_conduct_compliance_subtree():
    """§1026.13(d): the creditor must not, during the resolution period:
       - attempt to collect the disputed amount
       - report the disputed amount as delinquent
       - threaten to report it as adverse credit
       - restrict the consumer's account by reason of the dispute
    """
    return AndNode(children=[
        NotNode(child=Leaf(atom_id="did_attempt_to_collect_disputed_amount")),
        NotNode(child=Leaf(atom_id="did_report_disputed_as_delinquent")),
        NotNode(child=Leaf(atom_id="did_threaten_adverse_credit_report")),
        NotNode(child=Leaf(atom_id="did_restrict_account_by_reason_of_dispute")),
    ])


# ===========================================================================
# Phase 5d: Sub-determination 4 — §1026.13(e)/(f) conclusion procedure
# ===========================================================================
# Branches on the creditor's conclusion. Each conclusion type has its own
# required follow-up procedure.

def build_conclusion_procedure_subtree():
    """§1026.13(e) and (f): The creditor must follow the procedure
    appropriate to its conclusion.
    
    Conclusion 'error as asserted': correct, credit account (with finance
    charges), send correction notice.
    
    Conclusion 'different error': send written explanation, make appropriate
    corrections.
    
    Conclusion 'no error': send written explanation; if consumer requested
    documentary evidence, provide it.
    """
    error_as_asserted_procedure = AndNode(children=[
        Leaf(atom_id="corrected_error"),
        Leaf(atom_id="credited_account_including_finance_charges"),
        Leaf(atom_id="sent_correction_notice"),
    ])
    
    different_error_procedure = AndNode(children=[
        Leaf(atom_id="sent_written_explanation"),
        Leaf(atom_id="made_appropriate_corrections"),
    ])
    
    # For 'no error' conclusion: explanation is required; documentary
    # evidence is required only if consumer requested it
    documentary_evidence_check = OrNode(children=[
        NotNode(child=Leaf(atom_id="consumer_requested_documentary_evidence")),
        Leaf(atom_id="provided_documentary_evidence"),
    ])
    no_error_procedure = AndNode(children=[
        Leaf(atom_id="sent_written_explanation"),
        documentary_evidence_check,
    ])
    
    # Categorical dispatch: whichever conclusion type is TRUE drives the
    # check. Encoded as OR-of-ANDs: at most one disjunct can have a TRUE
    # conclusion-type leaf, and that disjunct's procedure must also hold.
    return OrNode(children=[
        AndNode(children=[
            Leaf(atom_id="concluded_error_as_asserted"),
            error_as_asserted_procedure,
        ]),
        AndNode(children=[
            Leaf(atom_id="concluded_different_error"),
            different_error_procedure,
        ]),
        AndNode(children=[
            Leaf(atom_id="concluded_no_error"),
            no_error_procedure,
        ]),
    ])


# ===========================================================================
# Phase 5e: Compose the full §1026.13 resolution determination
# ===========================================================================

def build_fcba_composite_dag():
    """The composite question: was the dispute properly resolved under §1026.13?
    
    AND across all four sub-determinations: notice validity, timing,
    conduct, and conclusion procedure.
    """
    return AndNode(children=[
        build_notice_validity_subtree(),       # §1026.13(b)
        build_timing_compliance_subtree(),     # §1026.13(c)
        build_conduct_compliance_subtree(),    # §1026.13(d)
        build_conclusion_procedure_subtree(),  # §1026.13(e) and (f)
    ])


# ===========================================================================
# Atom catalog
# ===========================================================================
# All atoms with their descriptions, organized by sub-determination.

ATOM_DESCRIPTIONS = {
    # Notice validity (§1026.13(b))
    "days_between_first_statement_and_notice": (
        "integer days between when the creditor transmitted the first periodic "
        "statement reflecting the alleged billing error and when the creditor "
        "received the consumer's dispute notice"
    ),
    "notice_received_at_designated_address": (
        "true if the dispute notice was sent to the address (or electronic "
        "channel) the creditor disclosed for billing inquiries"
    ),
    "notice_is_written": (
        "true if the notice was in writing (letter, email, secure message); "
        "false if oral only"
    ),
    "notice_identifies_consumer": (
        "true if the notice enables identification of consumer name and "
        "account number"
    ),
    "notice_indicates_belief_of_error": (
        "true if the notice indicates the consumer's belief that a billing "
        "error exists"
    ),
    "notice_states_dollar_amount": (
        "true if the notice states the specific dollar amount of the alleged error"
    ),
    "notice_states_reason_for_belief": (
        "true if the notice provides the consumer's reasons for believing an "
        "error exists"
    ),
    "notice_states_type_of_error": (
        "true if the notice describes the type of error alleged (unauthorized, "
        "duplicate, computational, etc.)"
    ),
    "notice_states_date_of_error": (
        "true if the notice states the date of the alleged error"
    ),
    
    # Timing compliance (§1026.13(c))
    "days_from_notice_to_acknowledgment": (
        "integer days between creditor's receipt of the dispute notice and "
        "the creditor's mailing/delivery of a written acknowledgment to the "
        "consumer. If the creditor never acknowledged separately because they "
        "resolved within 30 days, use the resolution date as the acknowledgment "
        "date (the resolution itself counts as acknowledgment)."
    ),
    "days_from_notice_to_resolution": (
        "integer days between creditor's receipt of the dispute notice and the "
        "creditor's notification of its resolution decision to the consumer"
    ),
    "resolved_within_two_billing_cycles": (
        "true if the creditor's resolution occurred within two complete billing "
        "cycles after receiving the notice; false if resolution took longer"
    ),
    
    # Conduct compliance (§1026.13(d))
    "did_attempt_to_collect_disputed_amount": (
        "true if, during the resolution period, the creditor attempted to "
        "collect the specific disputed amount from the consumer (e.g., late "
        "fees on the disputed amount, dunning letters about it, etc.)"
    ),
    "did_report_disputed_as_delinquent": (
        "true if the creditor reported the disputed amount as delinquent to "
        "any credit bureau or other party during the resolution period"
    ),
    "did_threaten_adverse_credit_report": (
        "true if the creditor threatened (in writing or otherwise communicated) "
        "to report the disputed amount adversely during the resolution period"
    ),
    "did_restrict_account_by_reason_of_dispute": (
        "true if the creditor restricted the consumer's use of the account "
        "(closed it, lowered the credit limit, etc.) by reason of the dispute "
        "during the resolution period"
    ),
    
    # Conclusion type (§1026.13(e) and (f)) - mutually exclusive
    "concluded_error_as_asserted": (
        "true if the creditor concluded that the billing error occurred as "
        "the consumer asserted (per §1026.13(e))"
    ),
    "concluded_different_error": (
        "true if the creditor concluded that a different billing error occurred, "
        "not exactly as the consumer asserted (per §1026.13(f)(1))"
    ),
    "concluded_no_error": (
        "true if the creditor concluded that no billing error occurred "
        "(per §1026.13(f)(2))"
    ),
    
    # 'Error as asserted' procedure atoms
    "corrected_error": (
        "true if the creditor corrected the billing error on the account"
    ),
    "credited_account_including_finance_charges": (
        "true if the creditor credited the account for the disputed amount "
        "INCLUDING any related finance charges"
    ),
    "sent_correction_notice": (
        "true if the creditor mailed or delivered a correction notice to the "
        "consumer documenting the correction"
    ),
    
    # 'Different error' and 'no error' procedure atoms
    "sent_written_explanation": (
        "true if the creditor sent the consumer a written explanation of its "
        "conclusion"
    ),
    "made_appropriate_corrections": (
        "true if any non-billing-error issues identified during investigation "
        "were corrected"
    ),
    "consumer_requested_documentary_evidence": (
        "true if the consumer requested documentary evidence supporting the "
        "creditor's no-error conclusion"
    ),
    "provided_documentary_evidence": (
        "true if the creditor provided documentary evidence of the consumer's "
        "indebtedness in response to the request"
    ),
}


# ===========================================================================
# Map: extract atoms from case
# ===========================================================================

MAP_PROMPT_TEMPLATE = """You are extracting structured facts from a consumer-dispute case file.

A consumer submitted a billing-error dispute to their credit card issuer.
The case file describes the full dispute lifecycle: the original transaction
and statement, the dispute notice, the creditor's acknowledgment and
investigation, and the creditor's resolution. You are helping adjudicate
whether the dispute was properly resolved under FCBA §1026.13.

Extract specific typed atoms the adjudication engine needs. There are 26
atoms organized into four groups: notice details, timing, creditor conduct
during resolution, and the conclusion procedure.

ATOMS TO EXTRACT (return JSON with these exact keys; use null for anything
the case does not explicitly state):

{atom_descriptions}

CASE FILE:
{case_text}

CRITICAL EXTRACTION INSTRUCTIONS:
- Use the EXACT atom names listed above. Do not abbreviate, paraphrase,
  pluralize differently, or otherwise change spelling. (For example,
  'notice_indicates_belief_of_error' must be that exact string — not
  'notice_indicate_belief_of_error' or any variant.)
- For numeric atoms (days, amounts): return as JSON numbers, not strings.
  Compute day-counts from dates if both endpoints are given.
- For Boolean atoms: return true/false only if the case explicitly
  establishes the fact OR its negation. Return null if the case is silent
  or ambiguous.
- For mutually-exclusive atoms (concluded_*_*): at most one should be true.
  All three should be null if the conclusion type is unstated.
- Do not assume defaults. If a creditor's action (e.g., did_threaten_adverse_
  credit_report) is not mentioned, return null — not false.

Return ONLY the JSON object. No preamble or commentary.
"""


def call_map_llm(case_text, model="claude-haiku-4-5-20251001"):
    """Call the LLM to extract atoms from case input."""
    from rulekit.build.decomposer import LLMCaller
    
    atoms_text = "\n".join(
        f"  - {name}: {desc}" for name, desc in ATOM_DESCRIPTIONS.items()
    )
    prompt = MAP_PROMPT_TEMPLATE.format(
        atom_descriptions=atoms_text,
        case_text=case_text,
    )
    
    llm = LLMCaller(model=model)
    t0 = time.time()
    response = llm.call(f"fcba_composite_map_{int(time.time()*1000)}", prompt)
    elapsed = time.time() - t0
    
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
        cleaned = re.sub(r"\n```\s*$", "", cleaned)
    try:
        atoms = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            atoms = json.loads(match.group(0))
        else:
            atoms = {}
    
    # Schema validation: warn if Map produced keys we don't recognize
    unknown_keys = set(atoms.keys()) - set(ATOM_DESCRIPTIONS.keys())
    missing_keys = set(ATOM_DESCRIPTIONS.keys()) - set(atoms.keys())
    
    return atoms, elapsed, unknown_keys, missing_keys


def build_fact_bundle(atoms_dict):
    """Convert atom dict from Map to a typed FactBundle."""
    numeric_atoms = {
        "days_between_first_statement_and_notice",
        "days_from_notice_to_acknowledgment",
        "days_from_notice_to_resolution",
    }
    values = {}
    for name in ATOM_DESCRIPTIONS:
        val = atoms_dict.get(name)
        if val is None:
            if name in numeric_atoms:
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
# Phase 6: DAG sanity checks
# ===========================================================================

def run_dag_sanity_checks():
    """Verify the composite DAG produces correct outputs on hand-crafted inputs."""
    dag = build_fcba_composite_dag()
    
    # Base atoms representing a fully compliant dispute resolution
    fully_compliant = {
        # Notice (valid)
        "days_between_first_statement_and_notice": 20,
        "notice_received_at_designated_address": True,
        "notice_is_written": True,
        "notice_identifies_consumer": True,
        "notice_indicates_belief_of_error": True,
        "notice_states_dollar_amount": True,
        "notice_states_reason_for_belief": True,
        "notice_states_type_of_error": True,
        "notice_states_date_of_error": True,
        # Timing (compliant)
        "days_from_notice_to_acknowledgment": 15,
        "days_from_notice_to_resolution": 60,
        "resolved_within_two_billing_cycles": True,
        # Conduct (compliant — none of the prohibited actions occurred)
        "did_attempt_to_collect_disputed_amount": False,
        "did_report_disputed_as_delinquent": False,
        "did_threaten_adverse_credit_report": False,
        "did_restrict_account_by_reason_of_dispute": False,
        # Conclusion (no error, procedure followed, no documentary evidence requested)
        "concluded_error_as_asserted": False,
        "concluded_different_error": False,
        "concluded_no_error": True,
        "corrected_error": False,
        "credited_account_including_finance_charges": False,
        "sent_correction_notice": False,
        "sent_written_explanation": True,
        "made_appropriate_corrections": False,
        "consumer_requested_documentary_evidence": False,
        "provided_documentary_evidence": False,
    }
    
    test_scenarios = [
        ("fully_compliant", fully_compliant, Kleene.TRUE,
         "All four sub-determinations should pass"),
        
        ("untimely_acknowledgment_35_days",
         {**fully_compliant, "days_from_notice_to_acknowledgment": 35,
          "days_from_notice_to_resolution": 35},
         Kleene.FALSE,
         "Acknowledgment late AND resolution not within 30 — should fail timing"),
        
        ("untimely_resolution_95_days",
         {**fully_compliant, "days_from_notice_to_resolution": 95,
          "resolved_within_two_billing_cycles": False},
         Kleene.FALSE,
         "Resolution exceeds 90-day outer limit — should fail timing"),
        
        ("collection_violation",
         {**fully_compliant, "did_attempt_to_collect_disputed_amount": True},
         Kleene.FALSE,
         "Creditor attempted collection during resolution — should fail conduct"),
        
        ("no_error_without_explanation",
         {**fully_compliant, "sent_written_explanation": False},
         Kleene.FALSE,
         "Concluded no error but didn't send written explanation — should fail procedure"),
        
        ("error_as_asserted_procedure",
         {**fully_compliant,
          "concluded_no_error": False,
          "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_account_including_finance_charges": True,
          "sent_correction_notice": True},
         Kleene.TRUE,
         "Concluded error-as-asserted, correct procedure followed — should pass"),
        
        ("error_as_asserted_missing_finance_charges",
         {**fully_compliant,
          "concluded_no_error": False,
          "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_account_including_finance_charges": False,
          "sent_correction_notice": True},
         Kleene.FALSE,
         "Error as asserted but finance charges not credited — should fail procedure"),
        
        ("no_error_with_evidence_request_provided",
         {**fully_compliant,
          "consumer_requested_documentary_evidence": True,
          "provided_documentary_evidence": True},
         Kleene.TRUE,
         "No-error conclusion, evidence requested and provided — should pass"),
        
        ("no_error_with_evidence_request_not_provided",
         {**fully_compliant,
          "consumer_requested_documentary_evidence": True,
          "provided_documentary_evidence": False},
         Kleene.FALSE,
         "No-error conclusion, evidence requested but not provided — should fail"),
        
        ("partial_data_should_und",
         {"notice_received_at_designated_address": True,
          "notice_is_written": True},  # everything else missing
         Kleene.UNDETERMINED,
         "Significant atoms missing — should return UND"),
    ]
    
    print("DAG sanity checks:")
    all_pass = True
    for label, atoms, expected, description in test_scenarios:
        bundle = build_fact_bundle(atoms)
        result = dag.evaluate(bundle, [])
        ok = result == expected
        status = "✓" if ok else "✗"
        print(f"  {status} {label}: got {result}, expected {expected}")
        if not ok:
            print(f"     ({description})")
            all_pass = False
    return all_pass


# ===========================================================================
# Phase 7: Realistic test cases
# ===========================================================================

TEST_CASES = [
    {
        "label": "C1_fully_compliant_no_error",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-7821

CONSUMER: Jennifer Adams
ACCOUNT: 4XXX-XXXX-XXXX-7821

TIMELINE:
- February 12, 2026: Statement transmitted (first statement reflecting
  disputed charge of $189.42 from "QUICKMART ONLINE", March 3 transaction date)
- March 1, 2026: Consumer mailed written dispute notice to PO Box 5000,
  Vienna, VA (the address disclosed on the statement for billing inquiries).
  Notice received March 5, 2026 (21 days after Feb 12 statement). Notice
  identified consumer (name and account number), stated belief that the
  charge was unauthorized, stated $189.42, stated date March 3, stated
  reason (consumer had never shopped at the merchant).
- March 18, 2026: Creditor mailed written acknowledgment to consumer
  (13 days after notice receipt).
- April 24, 2026: Investigation completed. Creditor determined no billing
  error occurred — confirmed the transaction was authorized via 3DS
  authentication associated with consumer's verified device.
- April 25, 2026: Creditor mailed written explanation of conclusion to
  consumer (51 days after notice receipt).
- Consumer did not subsequently request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION:
- Did not attempt to collect the disputed $189.42 during the resolution period
- Did not report it as delinquent to any bureau
- Did not threaten adverse credit reporting
- Did not restrict the account
""".strip(),
        "expected": "TRUE",
        "rationale": "All four sub-determinations satisfied. Notice valid, timing compliant (13d ack, 51d resolution, within 2 cycles, within 90d), no prohibited conduct, no-error procedure followed (written explanation, no evidence request).",
    },
    {
        "label": "C2_untimely_acknowledgment_and_resolution",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-3344

CONSUMER: Marcus Webb
ACCOUNT: 5XXX-XXXX-XXXX-3344

TIMELINE:
- January 10, 2026: Statement transmitted, reflecting disputed $1,250.00
  charge to "TECHWORLD INC" (Dec 28, 2025 transaction).
- January 28, 2026: Consumer mailed written notice to designated billing
  inquiries address. Received by creditor January 31 (21 days after
  statement). Notice fully complete: identifies consumer, states belief
  of duplicate billing, states amount, date, type, and reason.
- March 5, 2026: Creditor mailed written acknowledgment to consumer
  (33 days after notice receipt — 3 days past the 30-day acknowledgment
  requirement).
- April 12, 2026: Investigation completed. Creditor concluded no error.
- April 13, 2026: Creditor mailed written explanation (72 days after
  notice). Resolution was within 90 days and within 2 billing cycles.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION: None of the prohibited actions occurred.
""".strip(),
        "expected": "FALSE",
        "rationale": "Timing failure: acknowledgment was 33 days (over 30), and resolution was 72 days (not within 30). The acknowledgment_or_early_resolution OR is false. Other sub-determinations would have passed.",
    },
    {
        "label": "C3_resolution_exceeds_90_days",
        "case_text": """
DISPUTE CASE FILE — Account 6XXX-XXXX-XXXX-9012

CONSUMER: Priya Sharma
ACCOUNT: 6XXX-XXXX-XXXX-9012

TIMELINE:
- February 5, 2026: Statement transmitted, $445 charge from "GLOBAL HOTEL
  GROUP" (Feb 1 transaction).
- February 22, 2026: Consumer mailed written notice. Received Feb 25
  (20 days after statement). Notice fully compliant on all elements.
- March 5, 2026: Creditor mailed written acknowledgment (8 days after notice).
- June 5, 2026: Investigation completed and explanation mailed to consumer
  (102 days after notice receipt). Resolution exceeded the 90-day outer
  limit. Creditor concluded no error occurred.
- Resolution did not occur within two billing cycles either.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION: None of the prohibited actions occurred.
""".strip(),
        "expected": "FALSE",
        "rationale": "Resolution exceeds 90-day outer limit. Even though acknowledgment was timely (8 days), the outer-limit AND fails because resolution was 102 days. Composite fails.",
    },
    {
        "label": "C4_creditor_reported_delinquent_during_resolution",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-5566

CONSUMER: David Liu
ACCOUNT: 4XXX-XXXX-XXXX-5566

TIMELINE:
- March 1, 2026: Statement transmitted, $850 charge from "ELECTRONICS PRO"
  (Feb 24 transaction).
- March 14, 2026: Consumer mailed written notice. Received March 17
  (16 days after statement). Notice fully compliant on all elements.
- March 28, 2026: Creditor mailed written acknowledgment (11 days after notice).
- April 22, 2026: During the resolution period, the creditor's automated
  collections system reported the disputed $850 amount as 30-days-delinquent
  to all three major credit bureaus. The compliance team identified this
  error on April 25 and submitted corrections to the bureaus on April 27.
- May 8, 2026: Investigation completed. Creditor concluded the charge
  was authorized and no error occurred.
- May 9, 2026: Creditor mailed written explanation to consumer (53 days
  after notice).
- Consumer did not request documentary evidence.
""".strip(),
        "expected": "FALSE",
        "rationale": "Conduct violation: creditor reported the disputed amount as delinquent during the resolution period, which §1026.13(d) prohibits. Subsequent correction does not cure the original violation for the purposes of resolution compliance.",
    },
    {
        "label": "C5_no_error_consumer_requested_evidence_not_provided",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-7799

CONSUMER: Elena Rodriguez
ACCOUNT: 5XXX-XXXX-XXXX-7799

TIMELINE:
- April 3, 2026: Statement transmitted, $620 charge from "PROFESSIONAL
  SERVICES LLC" (March 28 transaction).
- April 15, 2026: Consumer mailed written notice. Received April 19 (16
  days after statement). Notice fully compliant on all elements.
- April 28, 2026: Creditor mailed written acknowledgment (9 days after notice).
- May 30, 2026: Investigation completed. Creditor concluded no error
  occurred.
- May 31, 2026: Creditor mailed written explanation (42 days after notice).
- June 5, 2026: Consumer wrote back to creditor specifically requesting
  documentary evidence of the consumer's indebtedness (proof the charge
  was legitimate).
- June 30, 2026: Creditor responded with a form letter restating its
  no-error determination but did NOT provide any documentary evidence
  supporting the indebtedness.

CREDITOR CONDUCT DURING RESOLUTION: None of the prohibited actions occurred.
""".strip(),
        "expected": "FALSE",
        "rationale": "No-error conclusion followed by consumer's documentary-evidence request; creditor failed to provide the evidence as required by §1026.13(f)(2). Other elements would have passed.",
    },
    {
        "label": "C6_error_asserted_procedure_missing_finance_charges",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-2200

CONSUMER: Akira Tanaka
ACCOUNT: 4XXX-XXXX-XXXX-2200

TIMELINE:
- May 2, 2026: Statement transmitted, $325 charge from "STREAMFLIX" plus
  $7.85 in finance charges associated with the disputed amount (April 28
  transaction).
- May 14, 2026: Consumer mailed written notice. Received May 18 (16 days
  after statement). Notice fully compliant on all elements.
- May 25, 2026: Creditor mailed written acknowledgment (7 days after notice).
- June 18, 2026: Investigation completed. Creditor confirmed the charge
  was indeed unauthorized as the consumer asserted. The creditor:
    - Reversed the $325 charge from the account
    - Sent the consumer a correction notice documenting the reversal
    - However: did NOT credit back the $7.85 in finance charges that had
      accrued on the disputed amount before the dispute was filed.
- 31 days from notice to resolution.

CREDITOR CONDUCT DURING RESOLUTION: None of the prohibited actions occurred.
""".strip(),
        "expected": "FALSE",
        "rationale": "Error as asserted, but the credit-account-including-finance-charges requirement was not satisfied — the creditor credited the principal but not the related finance charges. §1026.13(e) requires both.",
    },
    {
        "label": "C7_borderline_30_and_90",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-1100

CONSUMER: Sarah Goldberg
ACCOUNT: 5XXX-XXXX-XXXX-1100

TIMELINE:
- January 5, 2026: Statement transmitted, $740 disputed charge from
  "ONLINE SERVICES INC" (Dec 30, 2025 transaction).
- January 22, 2026: Consumer mailed written notice. Received January 25
  (20 days after statement). Notice fully compliant.
- February 24, 2026: Creditor mailed written acknowledgment — exactly
  30 days after notice receipt.
- April 25, 2026: Investigation completed and explanation mailed —
  exactly 90 days after notice receipt. Resolution was within two
  billing cycles. Creditor concluded no error occurred.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION: None of the prohibited actions occurred.
""".strip(),
        "expected": "TRUE",
        "rationale": "Both timing requirements at the boundary. §1026.13 says 'within 30 days' (≤30) and 'no later than 90 days' (≤90). Day 30 and day 90 are valid. Tests the LeqNode boundary correctly.",
    },
    {
        "label": "C8_underspecified_resolution_data_missing",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-8800

CONSUMER: Robert Chen
ACCOUNT: 4XXX-XXXX-XXXX-8800

PARTIAL CASE FILE (some information not yet collected):
- Statement transmitted March 1, 2026
- Consumer filed dispute via written notice received March 18 (17 days
  after statement). Notice was complete on all elements (verified by
  intake team).
- Creditor's compliance team did not complete documentation of the
  resolution timeline. Acknowledgment may have been sent but no record
  was located. The investigation status is "in progress" but no resolution
  date is documented.
- It is not known whether any collection or credit-reporting actions
  occurred during the resolution period.
""".strip(),
        "expected": "UND",
        "rationale": "Multiple atoms unspecified: acknowledgment timing, resolution date, conduct during resolution, conclusion type. Architecture should return UND honestly.",
    },
    {
        "label": "C9_subtle_compound_failure",
        "case_text": """
DISPUTE CASE FILE — Account 6XXX-XXXX-XXXX-4477

CONSUMER: Maya Patel
ACCOUNT: 6XXX-XXXX-XXXX-4477

TIMELINE:
- March 6, 2026: Statement transmitted, $1,180 disputed charge from
  "INTERNATIONAL SUPPLIES LLC" (March 1 transaction).
- March 20, 2026: Consumer mailed written notice. Received March 23
  (17 days after statement). Notice fully compliant on all elements.
- April 24, 2026: Creditor mailed written acknowledgment to consumer.
  That is 32 days after notice receipt. Note: 32 days > 30 days.
- June 18, 2026: Investigation completed and resolution notification sent
  to consumer. That is 87 days after notice receipt — 87 days < 90 days
  and within two billing cycles. The creditor concluded no billing error
  occurred and sent a written explanation.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION:
- No collection actions on the disputed amount
- No delinquency reports
- No adverse credit threats
- No account restrictions related to the dispute

ON CASUAL REVIEW: 87-day resolution looks within the 90-day outer limit,
investigation procedure was correct, conduct was clean. The dispute might
look properly resolved.

ON CLOSE REVIEW: The acknowledgment came 32 days after notice receipt.
§1026.13(c) requires acknowledgment within 30 days OR resolution within
30 days. Neither happened. The acknowledgment-or-early-resolution
requirement fails.
""".strip(),
        "expected": "FALSE",
        "rationale": "Subtle compound case. Outer-limit timing satisfied (87 days, within 2 cycles, ≤90 days), but acknowledgment was 32 days — the 'acknowledge within 30 OR resolve within 30' branch fails because neither occurred. Easy for a non-mechanical adjudicator to miss because the resolution itself looks fine.",
    },
]


# ===========================================================================
# Main
# ===========================================================================

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--map-model", default="claude-haiku-4-5-20251001")
    p.add_argument("--cases", nargs="+", default=None)
    p.add_argument("--skip-sanity", action="store_true")
    p.add_argument("--show-atoms", action="store_true",
                   help="Show all extracted atoms per case, not just non-null")
    args = p.parse_args()
    
    print("=" * 70)
    print("FCBA §1026.13 Composite Resolution Adjudicator")
    print("=" * 70)
    print()
    
    if not args.skip_sanity:
        sanity_ok = run_dag_sanity_checks()
        if not sanity_ok:
            print("\nSANITY CHECKS FAILED. Aborting.")
            sys.exit(1)
        print("\nAll sanity checks pass.\n")
    
    dag = build_fcba_composite_dag()
    
    # Count nodes in the DAG for reporting
    seen = set()
    def _count(n):
        if id(n) in seen: return 0
        seen.add(id(n))
        c = 1
        for attr in ("children", "left", "right", "child", "condition", "if_true", "if_false"):
            v = getattr(n, attr, None)
            if v is None: continue
            if isinstance(v, list):
                for x in v: c += _count(x)
            else:
                c += _count(v)
        return c
    node_count = _count(dag)
    print(f"DAG size: {node_count} nodes, {len(ATOM_DESCRIPTIONS)} atoms")
    print()
    
    cases = TEST_CASES
    if args.cases:
        cases = [c for c in TEST_CASES if c["label"] in args.cases]
    
    print(f"Running {len(cases)} cases through Map + Engine pipeline")
    print()
    
    results = []
    
    for case in cases:
        print("=" * 70)
        print(f"Case: {case['label']}")
        print(f"Expected: {case['expected']}")
        print(f"Rationale: {case['rationale']}")
        print()
        
        print("Map (extracting atoms)...")
        try:
            atoms, map_elapsed, unknown_keys, missing_keys = call_map_llm(
                case["case_text"], model=args.map_model,
            )
        except Exception as e:
            print(f"  MAP ERROR: {e}")
            results.append({"label": case["label"], "status": "map_error",
                            "error": str(e)})
            continue
        
        print(f"  Map latency: {map_elapsed:.2f}s")
        non_null = {k: v for k, v in atoms.items() if v is not None}
        print(f"  Atoms extracted: {len(non_null)}/{len(ATOM_DESCRIPTIONS)} non-null")
        if unknown_keys:
            print(f"  WARNING: Map produced unknown keys: {sorted(unknown_keys)}")
        if missing_keys:
            print(f"  WARNING: Map omitted keys: {sorted(missing_keys)[:5]}"
                  + (f" ... and {len(missing_keys)-5} more" if len(missing_keys) > 5 else ""))
        if args.show_atoms:
            for k, v in sorted(atoms.items()):
                print(f"    {k}: {v}")
        
        bundle = build_fact_bundle(atoms)
        t0 = time.time()
        result = dag.evaluate(bundle, [])
        engine_elapsed = (time.time() - t0) * 1000
        
        print(f"  Engine latency: {engine_elapsed:.2f}ms")
        print(f"  Engine result: {result}")
        
        if result == Kleene.TRUE:
            disposition = "TRUE"
        elif result == Kleene.FALSE:
            disposition = "FALSE"
        else:
            disposition = "UND"
        
        correct = (disposition == case["expected"])
        outcome = "✓ CORRECT" if correct else "✗ WRONG"
        print(f"  Disposition: {disposition} | Expected: {case['expected']} | {outcome}")
        print()
        
        results.append({
            "label": case["label"],
            "status": "completed",
            "expected": case["expected"],
            "disposition": disposition,
            "correct": correct,
            "atoms_extracted": atoms,
            "unknown_keys": list(unknown_keys),
            "missing_keys": list(missing_keys),
            "map_latency_s": map_elapsed,
            "engine_latency_ms": engine_elapsed,
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
        latencies = [r["map_latency_s"] for r in completed]
        engine_latencies = [r["engine_latency_ms"] for r in completed]
        print(f"\nMap latency: min={min(latencies):.2f}s, "
              f"max={max(latencies):.2f}s, "
              f"mean={sum(latencies)/len(latencies):.2f}s")
        print(f"Engine latency: min={min(engine_latencies):.2f}ms, "
              f"max={max(engine_latencies):.2f}ms, "
              f"mean={sum(engine_latencies)/len(engine_latencies):.2f}ms")
    
    print("\nPer-case breakdown:")
    for r in results:
        if r["status"] != "completed":
            print(f"  {r['label']}: {r['status']}")
            continue
        mark = "✓" if r["correct"] else "✗"
        print(f"  {mark} {r['label']}: got {r['disposition']}, expected {r['expected']}")
    
    out_path = "audits/fcba_composite_resolution/results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

"""
test_fcba_composite_refined.py — RuleKit applied to the composite §1026.13
dispute resolution adjudication, with policy-faithful depth.

This refines test_fcba_composite_resolution.py by surfacing structure that
the earlier version compressed. The added depth all follows the regulation's
actual language; nothing is engineered for complexity's sake.

REFINEMENTS FROM v1:

1. §1026.13(c) acknowledgment exception now requires the FULL §1026.13(e)/(f)
   procedure to be completed within 30 days, not just "resolved" within 30
   days. This creates an internal cross-reference: the timing sub-tree now
   references the conclusion-procedure sub-tree.

2. §1026.13(c) two-billing-cycle deadline is now computed from dates rather
   than treated as a Boolean. Map extracts the billing-cycle close date and
   the resolution date; the engine compares them.

3. §1026.13(d)(1) collection prohibition split into principal, related
   finance charges, and other related charges (per the regulation's
   "any related finance or other charges" language).

4. §1026.13(e) credit obligation split into three components: disputed
   amount, related finance charges, related other charges.

5. §1026.13(f)(3) different-error branch now has its OWN correction and
   credit obligations, parallel to §1026.13(e), rather than being collapsed
   into "made appropriate corrections."

CONSTRUCTION RECORD:
This file is structured to mirror the construction procedure so the Build
pipeline can eventually automate what was done by hand.

Phase 1: Re-read policy with depth filter
Phase 2: Identify internal cross-references (timing -> conclusion procedure)
Phase 3: Refine atom catalog (29 atoms vs original 26 -- net +6 after
         removing the 3 collapsed atoms)
Phase 4: Express cross-reference by sharing subtree instances in code
Phase 5: Validate sanity
Phase 6: Test on extended case set
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
# Phase 4a: §1026.13(b) notice validity (unchanged from v1)
# ===========================================================================

def build_notice_validity_subtree():
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
# Phase 4b: §1026.13(e) error-as-asserted procedure (REFINED)
# ===========================================================================
# Now requires three separate credit components, not one collapsed Boolean.

def build_error_as_asserted_procedure_subtree():
    """§1026.13(e): correct the error, credit account (disputed amount, related
    finance charges, related other charges), send correction notice."""
    credit_complete = AndNode(children=[
        Leaf(atom_id="credited_disputed_amount"),
        Leaf(atom_id="credited_related_finance_charges"),
        Leaf(atom_id="credited_related_other_charges"),
    ])
    return AndNode(children=[
        Leaf(atom_id="corrected_error"),
        credit_complete,
        Leaf(atom_id="sent_correction_notice"),
    ])


# ===========================================================================
# Phase 4c: §1026.13(f)(1)+(3) different-error procedure (REFINED)
# ===========================================================================
# Now has its own correction-and-credit obligation, parallel to (e).

def build_different_error_procedure_subtree():
    """§1026.13(f)(1) and (f)(3): explain, AND correct the different error,
    AND credit account for the disputed amount and related charges."""
    credit_complete = AndNode(children=[
        Leaf(atom_id="credited_disputed_amount"),
        Leaf(atom_id="credited_related_finance_charges"),
        Leaf(atom_id="credited_related_other_charges"),
    ])
    return AndNode(children=[
        Leaf(atom_id="sent_written_explanation"),
        Leaf(atom_id="corrected_the_different_error"),
        credit_complete,
    ])


# ===========================================================================
# Phase 4d: §1026.13(f)(2) no-error procedure (refined)
# ===========================================================================

def build_no_error_procedure_subtree():
    """§1026.13(f)(2): send written explanation; if consumer requested
    documentary evidence, furnish it."""
    documentary_evidence_check = OrNode(children=[
        NotNode(child=Leaf(atom_id="consumer_requested_documentary_evidence")),
        Leaf(atom_id="provided_documentary_evidence"),
    ])
    return AndNode(children=[
        Leaf(atom_id="sent_written_explanation"),
        documentary_evidence_check,
    ])


# ===========================================================================
# Phase 4e: Conclusion procedure dispatch (refined)
# ===========================================================================

def build_conclusion_procedure_subtree():
    """Categorical dispatch on conclusion type."""
    return OrNode(children=[
        AndNode(children=[
            Leaf(atom_id="concluded_error_as_asserted"),
            build_error_as_asserted_procedure_subtree(),
        ]),
        AndNode(children=[
            Leaf(atom_id="concluded_different_error"),
            build_different_error_procedure_subtree(),
        ]),
        AndNode(children=[
            Leaf(atom_id="concluded_no_error"),
            build_no_error_procedure_subtree(),
        ]),
    ])


# ===========================================================================
# Phase 4f: §1026.13(c) timing compliance (REFINED — internal cross-reference)
# ===========================================================================
# The acknowledgment-waiver now requires the full conclusion procedure to be
# complete within 30 days, not just any "resolution" within 30 days. This
# creates an internal cross-reference: timing subtree shares the conclusion-
# procedure subtree by passing it as an argument.

def build_timing_compliance_subtree(conclusion_procedure_subtree):
    """§1026.13(c): acknowledgment within 30 days OR (full procedure complete
    within 30 days), AND resolution within two complete billing cycles, AND
    resolution within 90 days.
    
    Args:
      conclusion_procedure_subtree: the conclusion-procedure subtree, shared
                                    with the conclusion_procedure check.
    """
    acknowledged_within_30 = LeqNode(
        left=NumericLeaf(atom_id="days_from_notice_to_acknowledgment"),
        right=Constant(label="thirty_day_ack_limit", value=Decimal("30")),
    )
    
    # The acknowledgment-waiver: full procedure complete AND within 30 days
    # of notice receipt
    resolution_within_30 = LeqNode(
        left=NumericLeaf(atom_id="days_from_notice_to_resolution"),
        right=Constant(label="thirty_day_proc_limit", value=Decimal("30")),
    )
    acknowledgment_waiver_applies = AndNode(children=[
        conclusion_procedure_subtree,  # CROSS-REFERENCE: shared subtree
        resolution_within_30,
    ])
    
    acknowledgment_or_waiver = OrNode(children=[
        acknowledged_within_30,
        acknowledgment_waiver_applies,
    ])
    
    # Outer limit: resolution within two complete billing cycles AND within
    # 90 days. The two-cycle deadline is now computed from dates.
    resolved_within_two_cycles = LeqNode(
        left=NumericLeaf(atom_id="resolution_date_days_since_notice"),
        right=NumericLeaf(atom_id="second_complete_billing_cycle_days_since_notice"),
    )
    resolved_within_90 = LeqNode(
        left=NumericLeaf(atom_id="days_from_notice_to_resolution"),
        right=Constant(label="ninety_day_limit", value=Decimal("90")),
    )
    outer_limit_satisfied = AndNode(children=[
        resolved_within_two_cycles,
        resolved_within_90,
    ])
    
    return AndNode(children=[
        acknowledgment_or_waiver,
        outer_limit_satisfied,
    ])


# ===========================================================================
# Phase 4g: §1026.13(d) conduct compliance (REFINED — split collection)
# ===========================================================================

def build_conduct_compliance_subtree():
    """§1026.13(d): no collection actions (against principal, related finance
    charges, or other related charges); no adverse credit reporting;
    no threats; no account restrictions."""
    no_collection = AndNode(children=[
        NotNode(child=Leaf(atom_id="did_attempt_to_collect_principal")),
        NotNode(child=Leaf(atom_id="did_attempt_to_collect_related_finance_charges")),
        NotNode(child=Leaf(atom_id="did_attempt_to_collect_related_other_charges")),
    ])
    return AndNode(children=[
        no_collection,
        NotNode(child=Leaf(atom_id="did_report_disputed_as_delinquent")),
        NotNode(child=Leaf(atom_id="did_threaten_adverse_credit_report")),
        NotNode(child=Leaf(atom_id="did_restrict_account_by_reason_of_dispute")),
    ])


# ===========================================================================
# Phase 4h: Compose the full refined DAG (with internal cross-reference)
# ===========================================================================

def build_fcba_composite_refined_dag():
    """The full §1026.13 resolution adjudicator with policy-faithful depth.
    
    The conclusion-procedure subtree is constructed ONCE and shared between
    the conclusion-procedure check and the acknowledgment-waiver check
    (per §1026.13(c)'s reference to paragraphs (e) and (f)).
    """
    notice = build_notice_validity_subtree()
    
    # Construct the conclusion-procedure subtree ONCE and share it
    conclusion = build_conclusion_procedure_subtree()
    
    # Timing references conclusion as a sub-condition of the waiver
    timing = build_timing_compliance_subtree(conclusion)
    
    conduct = build_conduct_compliance_subtree()
    
    return AndNode(children=[
        notice,
        timing,
        conduct,
        conclusion,
    ])


# ===========================================================================
# Refined atom catalog
# ===========================================================================
# Changes from v1:
#   REMOVED: credited_account_including_finance_charges, made_appropriate_corrections,
#            did_attempt_to_collect_disputed_amount, resolved_within_two_billing_cycles
#   ADDED: credited_disputed_amount, credited_related_finance_charges,
#          credited_related_other_charges, corrected_the_different_error,
#          did_attempt_to_collect_principal, did_attempt_to_collect_related_finance_charges,
#          did_attempt_to_collect_related_other_charges,
#          resolution_date_days_since_notice, second_complete_billing_cycle_days_since_notice
# Net: +5 atoms, total 31.

ATOM_DESCRIPTIONS = {
    # Notice validity (unchanged)
    "days_between_first_statement_and_notice": (
        "integer days between the creditor's transmission of the first periodic "
        "statement reflecting the alleged error and the creditor's receipt of "
        "the notice"
    ),
    "notice_received_at_designated_address": (
        "true if the notice was sent to the address/channel disclosed for "
        "billing inquiries"
    ),
    "notice_is_written": "true if the notice was in writing",
    "notice_identifies_consumer": (
        "true if the notice identifies the consumer's name and account number"
    ),
    "notice_indicates_belief_of_error": (
        "true if the notice indicates the consumer's belief that an error exists"
    ),
    "notice_states_dollar_amount": "true if the notice states the dollar amount",
    "notice_states_reason_for_belief": (
        "true if the notice gives reasons for the consumer's belief"
    ),
    "notice_states_type_of_error": "true if the notice describes the type of error",
    "notice_states_date_of_error": "true if the notice states the date of the error",
    
    # Timing (refined)
    "days_from_notice_to_acknowledgment": (
        "integer days between creditor's receipt of the notice and the "
        "creditor's mailing of a written acknowledgment to the consumer. "
        "If no separate acknowledgment was sent because the full procedure "
        "was completed within 30 days, this may be null (UND)."
    ),
    "days_from_notice_to_resolution": (
        "integer days between creditor's receipt of the notice and the "
        "creditor's notification of its conclusion/resolution to the consumer"
    ),
    "resolution_date_days_since_notice": (
        "the resolution notification date, measured in days from the notice "
        "receipt date (same value as days_from_notice_to_resolution, but "
        "named separately to make the comparison with the billing-cycle "
        "deadline explicit)"
    ),
    "second_complete_billing_cycle_days_since_notice": (
        "the deadline for resolution under the 'two complete billing cycles' "
        "rule, measured in days from the notice receipt date. This is the "
        "day on which the second complete billing cycle after notice receipt "
        "closes. If the case file doesn't specify the billing cycle dates, "
        "leave this null (UND)."
    ),
    
    # Conduct (refined — split collection)
    "did_attempt_to_collect_principal": (
        "true if, during the resolution period, the creditor attempted to "
        "collect the disputed principal amount from the consumer"
    ),
    "did_attempt_to_collect_related_finance_charges": (
        "true if, during the resolution period, the creditor attempted to "
        "collect finance charges related to the disputed amount (e.g., late "
        "fees or interest assessed on the disputed amount)"
    ),
    "did_attempt_to_collect_related_other_charges": (
        "true if, during the resolution period, the creditor attempted to "
        "collect any other charges related to the disputed amount"
    ),
    "did_report_disputed_as_delinquent": (
        "true if the creditor reported the disputed amount as delinquent to "
        "any credit bureau or other party during the resolution period"
    ),
    "did_threaten_adverse_credit_report": (
        "true if the creditor threatened to report the disputed amount "
        "adversely during the resolution period"
    ),
    "did_restrict_account_by_reason_of_dispute": (
        "true if the creditor restricted the consumer's account use by "
        "reason of the dispute during the resolution period"
    ),
    
    # Conclusion type (unchanged)
    "concluded_error_as_asserted": (
        "true if the creditor concluded the error occurred as asserted "
        "(triggers §1026.13(e))"
    ),
    "concluded_different_error": (
        "true if the creditor concluded a different billing error occurred "
        "(triggers §1026.13(f)(1) and (f)(3))"
    ),
    "concluded_no_error": (
        "true if the creditor concluded no billing error occurred "
        "(triggers §1026.13(f)(2))"
    ),
    
    # Conclusion procedure atoms (refined — credit split)
    "corrected_error": (
        "true if the creditor corrected the billing error (used when conclusion "
        "is 'error as asserted')"
    ),
    "credited_disputed_amount": (
        "true if the creditor credited the consumer's account for the disputed "
        "principal amount"
    ),
    "credited_related_finance_charges": (
        "true if the creditor credited the consumer's account for any finance "
        "charges related to the disputed amount"
    ),
    "credited_related_other_charges": (
        "true if the creditor credited the consumer's account for any other "
        "charges related to the disputed amount"
    ),
    "sent_correction_notice": (
        "true if the creditor sent the consumer a correction notice documenting "
        "the correction (used when conclusion is 'error as asserted')"
    ),
    "sent_written_explanation": (
        "true if the creditor sent the consumer a written explanation of its "
        "conclusion (used for 'different error' and 'no error' conclusions)"
    ),
    "corrected_the_different_error": (
        "true if the creditor corrected the different billing error that was "
        "actually found (used when conclusion is 'different error'; per "
        "§1026.13(f)(3))"
    ),
    "consumer_requested_documentary_evidence": (
        "true if the consumer requested documentary evidence supporting a "
        "no-error conclusion"
    ),
    "provided_documentary_evidence": (
        "true if the creditor provided documentary evidence of the consumer's "
        "indebtedness in response to the consumer's request"
    ),
}


# ===========================================================================
# Map (mostly same as v1 with refined atom list)
# ===========================================================================

MAP_PROMPT_TEMPLATE = """You are extracting structured facts from a consumer-dispute case file
for FCBA §1026.13 compliance adjudication.

ATOMS TO EXTRACT (use EXACT keys; return null for any fact not explicitly
stated in the case):

{atom_descriptions}

CASE FILE:
{case_text}

CRITICAL EXTRACTION INSTRUCTIONS:
- Use the EXACT atom names listed. Do not abbreviate, paraphrase, or change
  spelling.
- For numeric atoms: return JSON numbers (not strings). Compute day counts
  from dates when both endpoints are given.
- For days_from_notice_to_acknowledgment: if the creditor never sent a
  separate acknowledgment (because the full procedure was complete within
  30 days), return null.
- For second_complete_billing_cycle_days_since_notice: this is the deadline
  imposed by "two complete billing cycles" measured in days from notice
  receipt. If the case file gives the billing cycle close dates, compute the
  number of days from notice receipt to the close of the SECOND complete
  billing cycle after notice. If the case file is silent on billing cycle
  dates, return null.
- For Boolean atoms: return true/false ONLY when the case explicitly
  establishes the fact or its negation. Return null when silent.
- For the three credit atoms (disputed_amount, related_finance_charges,
  related_other_charges): if the case says "credited the account" without
  specifying what components, treat as null for the components not mentioned.
  If the case explicitly says the creditor credited the principal but not
  finance charges, set credited_disputed_amount=true and
  credited_related_finance_charges=false.
- For the three collection atoms: if the case says nothing happened on
  collection, all three should be false (the prohibition was respected).
  If the case mentions some collection activity, distinguish what was
  attempted.

Return ONLY a JSON object. No preamble or commentary.
"""


def call_map_llm(case_text, model="claude-haiku-4-5-20251001"):
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
    response = llm.call(f"fcba_refined_map_{int(time.time()*1000)}", prompt)
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
    
    unknown_keys = set(atoms.keys()) - set(ATOM_DESCRIPTIONS.keys())
    missing_keys = set(ATOM_DESCRIPTIONS.keys()) - set(atoms.keys())
    return atoms, elapsed, unknown_keys, missing_keys


def build_fact_bundle(atoms_dict):
    numeric_atoms = {
        "days_between_first_statement_and_notice",
        "days_from_notice_to_acknowledgment",
        "days_from_notice_to_resolution",
        "resolution_date_days_since_notice",
        "second_complete_billing_cycle_days_since_notice",
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
# Phase 5: DAG sanity checks
# ===========================================================================

def _baseline_atoms():
    """Baseline atoms for a fully-compliant no-error case."""
    return {
        "days_between_first_statement_and_notice": 20,
        "notice_received_at_designated_address": True,
        "notice_is_written": True,
        "notice_identifies_consumer": True,
        "notice_indicates_belief_of_error": True,
        "notice_states_dollar_amount": True,
        "notice_states_reason_for_belief": True,
        "notice_states_type_of_error": True,
        "notice_states_date_of_error": True,
        "days_from_notice_to_acknowledgment": 15,
        "days_from_notice_to_resolution": 60,
        "resolution_date_days_since_notice": 60,
        "second_complete_billing_cycle_days_since_notice": 65,
        "did_attempt_to_collect_principal": False,
        "did_attempt_to_collect_related_finance_charges": False,
        "did_attempt_to_collect_related_other_charges": False,
        "did_report_disputed_as_delinquent": False,
        "did_threaten_adverse_credit_report": False,
        "did_restrict_account_by_reason_of_dispute": False,
        "concluded_error_as_asserted": False,
        "concluded_different_error": False,
        "concluded_no_error": True,
        "corrected_error": False,
        "credited_disputed_amount": False,
        "credited_related_finance_charges": False,
        "credited_related_other_charges": False,
        "sent_correction_notice": False,
        "sent_written_explanation": True,
        "corrected_the_different_error": False,
        "consumer_requested_documentary_evidence": False,
        "provided_documentary_evidence": False,
    }


def run_dag_sanity_checks():
    dag = build_fcba_composite_refined_dag()
    
    scenarios = [
        ("baseline_no_error_compliant", _baseline_atoms(), Kleene.TRUE,
         "All sub-determinations pass for no-error case"),
        
        ("error_as_asserted_full_compliance",
         {**_baseline_atoms(),
          "concluded_no_error": False, "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": True,
          "credited_related_other_charges": True,
          "sent_correction_notice": True},
         Kleene.TRUE,
         "Error-as-asserted with all three credit components: should pass"),
        
        ("error_as_asserted_missing_finance_charges",
         {**_baseline_atoms(),
          "concluded_no_error": False, "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": False,  # the failure
          "credited_related_other_charges": True,
          "sent_correction_notice": True},
         Kleene.FALSE,
         "Error-as-asserted but missing finance-charge credit: should fail"),
        
        ("different_error_full_compliance",
         {**_baseline_atoms(),
          "concluded_no_error": False, "concluded_different_error": True,
          "sent_written_explanation": True,
          "corrected_the_different_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": True,
          "credited_related_other_charges": True},
         Kleene.TRUE,
         "Different-error with correction and full credit: should pass"),
        
        ("different_error_missing_finance_charges",
         {**_baseline_atoms(),
          "concluded_no_error": False, "concluded_different_error": True,
          "sent_written_explanation": True,
          "corrected_the_different_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": False,  # the failure
          "credited_related_other_charges": True},
         Kleene.FALSE,
         "Different-error but missing finance-charge credit: should fail. "
         "v1 DAG could not catch this; v2 can."),
        
        ("acknowledgment_waiver_valid",
         {**_baseline_atoms(),
          "days_from_notice_to_acknowledgment": None,  # no separate ack
          "days_from_notice_to_resolution": 25,
          "resolution_date_days_since_notice": 25,
          "second_complete_billing_cycle_days_since_notice": 32,
          "concluded_no_error": False, "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": True,
          "credited_related_other_charges": True,
          "sent_correction_notice": True},
         Kleene.TRUE,
         "No separate ack but full error-as-asserted procedure complete by "
         "day 25 (within 30): waiver applies, should pass"),
        
        ("acknowledgment_waiver_invalid_procedure_incomplete",
         {**_baseline_atoms(),
          "days_from_notice_to_acknowledgment": None,
          "days_from_notice_to_resolution": 25,
          "resolution_date_days_since_notice": 25,
          "second_complete_billing_cycle_days_since_notice": 32,
          "concluded_no_error": False, "concluded_error_as_asserted": True,
          "sent_written_explanation": False,
          "corrected_error": True,
          "credited_disputed_amount": True,
          "credited_related_finance_charges": False,  # incomplete procedure
          "credited_related_other_charges": True,
          "sent_correction_notice": True},
         Kleene.FALSE,
         "No ack, resolution by day 25, but procedure incomplete (no finance "
         "charges): waiver does NOT apply because procedure is not complete. "
         "v1 DAG would have given this TRUE on the timing branch; v2 catches it."),
        
        ("two_billing_cycle_deadline_binding",
         {**_baseline_atoms(),
          "days_from_notice_to_resolution": 60,
          "resolution_date_days_since_notice": 60,
          "second_complete_billing_cycle_days_since_notice": 51},  # binding
         Kleene.FALSE,
         "Resolution at day 60 but second billing cycle closes at day 51: "
         "the two-cycle deadline is binding, fails even though within 90. "
         "v1 collapsed this to a Boolean; v2 computes it."),
        
        ("collection_of_finance_charges_only",
         {**_baseline_atoms(),
          "did_attempt_to_collect_principal": False,
          "did_attempt_to_collect_related_finance_charges": True,  # the failure
          "did_attempt_to_collect_related_other_charges": False},
         Kleene.FALSE,
         "Creditor didn't try to collect principal but DID try to collect "
         "finance charges on disputed amount: §1026.13(d)(1) violation. "
         "v1 collapsed this to one atom; v2 separates."),
    ]
    
    print("DAG sanity checks:")
    all_pass = True
    for label, atoms, expected, description in scenarios:
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
# Phase 6: Test cases — original 9 plus new cases that test the depth
# ===========================================================================
# I'll reuse the 9 original cases (slightly adjusted for the refined atom
# names) and add 4 new cases that test the new structural depth.

TEST_CASES = [
    # Original cases, narrative-equivalent but tied to the refined atom names.
    # Same expected dispositions as before.
    {
        "label": "C1_fully_compliant_no_error",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-7821

CONSUMER: Jennifer Adams
ACCOUNT: 4XXX-XXXX-XXXX-7821

TIMELINE:
- February 12, 2026: Statement transmitted (first statement reflecting
  $189.42 charge from "QUICKMART ONLINE", March 3 transaction date)
- March 5, 2026: Written dispute notice received at PO Box 5000, Vienna,
  VA (the address disclosed for billing inquiries). 21 days after Feb 12
  statement. Notice complete: identifies consumer, states $189.42, dated
  March 3, type unauthorized, reason consumer had never shopped at merchant.
- March 18, 2026: Written acknowledgment mailed to consumer (13 days
  after notice receipt).
- April 24, 2026: Investigation completed. Creditor determined no billing
  error (3DS authentication confirmed transaction).
- April 25, 2026: Written explanation mailed (51 days after notice).
- Consumer's billing cycle closes on the 15th of each month. Second
  complete billing cycle after notice receipt closes May 15 (71 days
  after notice).
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION:
- No collection actions of any kind (principal, finance charges, or other
  related charges) on the disputed amount
- No delinquency reports
- No adverse credit threats
- No account restrictions
""".strip(),
        "expected": "TRUE",
    },
    {
        "label": "C2_untimely_acknowledgment_and_resolution",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-3344

TIMELINE:
- January 10, 2026: Statement transmitted, $1,250.00 charge from "TECHWORLD INC"
- January 31, 2026: Written notice received (21 days after statement).
  Notice fully complete on all elements.
- March 5, 2026: Written acknowledgment mailed (33 days after notice — 3
  days past the 30-day limit).
- April 13, 2026: Investigation completed and explanation mailed (72 days
  after notice). Within two billing cycles (second cycle closes April 18,
  77 days after notice). Within 90 days. Conclusion: no error.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT: No collection, no reporting, no threats, no restrictions.
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "C3_resolution_exceeds_90_days",
        "case_text": """
DISPUTE CASE FILE — Account 6XXX-XXXX-XXXX-9012

TIMELINE:
- February 5, 2026: Statement transmitted, $445 charge from "GLOBAL HOTEL"
- February 25, 2026: Written notice received (20 days after statement).
  Notice fully compliant.
- March 5, 2026: Written acknowledgment (8 days after notice).
- June 5, 2026: Investigation completed and explanation mailed (102 days
  after notice — exceeds 90-day limit). Also exceeds two billing cycles
  (second cycle closed April 30, 64 days after notice). Conclusion: no error.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT: No collection, no reporting, no threats, no restrictions.
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "C4_creditor_reported_delinquent_during_resolution",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-5566

TIMELINE:
- March 1, 2026: Statement transmitted, $850 charge from "ELECTRONICS PRO"
- March 17, 2026: Written notice received (16 days after statement).
  Notice fully compliant.
- March 28, 2026: Written acknowledgment (11 days after notice).
- April 22, 2026: During the resolution period, the creditor's automated
  collections system reported the $850 disputed amount as 30-days-delinquent
  to all three credit bureaus. Compliance team identified and corrected
  the report on April 27.
- May 9, 2026: Investigation completed and explanation mailed (53 days
  after notice). Within two billing cycles. Within 90 days. Conclusion:
  no error.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION:
- No collection attempts on any component of the disputed amount
- DID report the disputed amount as delinquent (violation)
- No explicit threats beyond the delinquency report itself
- No account restrictions
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "C5_no_error_consumer_requested_evidence_not_provided",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-7799

TIMELINE:
- April 3, 2026: Statement transmitted, $620 charge
- April 19, 2026: Written notice received (16 days after statement).
  Notice fully compliant.
- April 28, 2026: Written acknowledgment (9 days after notice).
- May 31, 2026: Written explanation mailed (42 days after notice). Within
  two billing cycles. Within 90 days. Conclusion: no error.
- June 5, 2026: Consumer wrote back requesting documentary evidence of
  the consumer's indebtedness (proof the charge was legitimate).
- June 30, 2026: Creditor responded with a form letter restating its
  no-error determination but did NOT provide any documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION: No prohibited actions occurred.
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "C6_error_asserted_procedure_missing_finance_charges",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-2200

TIMELINE:
- May 2, 2026: Statement transmitted, $325 charge from "STREAMFLIX" plus
  $7.85 in finance charges accrued on the disputed amount.
- May 18, 2026: Written notice received (16 days after statement). Notice
  fully compliant.
- May 25, 2026: Written acknowledgment (7 days after notice).
- June 18, 2026: Investigation concluded the charge was unauthorized
  (error as asserted). Creditor:
    - Corrected the error (reversed the $325)
    - Credited the disputed principal of $325 to the account
    - Did NOT credit the $7.85 in related finance charges
    - No other related charges existed
    - Sent the correction notice documenting the reversal
- 31 days from notice to resolution. Within two billing cycles (close was
  day 35). Within 90 days.

CREDITOR CONDUCT DURING RESOLUTION: No prohibited actions occurred.
""".strip(),
        "expected": "FALSE",
    },
    {
        "label": "C7_borderline_30_and_90",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-1100

TIMELINE:
- January 5, 2026: Statement transmitted, $740 disputed charge
- January 25, 2026: Written notice received (20 days after statement).
  Notice fully compliant.
- February 24, 2026: Written acknowledgment exactly 30 days after notice.
- April 25, 2026: Explanation mailed exactly 90 days after notice. Within
  two billing cycles (second cycle closed at day 95, so resolution was
  before it). Conclusion: no error.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION: No prohibited actions occurred.
""".strip(),
        "expected": "TRUE",
    },
    {
        "label": "C8_underspecified_resolution_data_missing",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-8800

PARTIAL CASE FILE — most resolution-side data not yet collected:
- Statement transmitted March 1, 2026
- Written notice received March 18, 2026 (17 days after statement). Notice
  complete on all elements per intake team.
- Creditor's compliance team did not complete documentation of the
  resolution timeline. Acknowledgment may have been sent but no record
  was located. The investigation status is "in progress" but no resolution
  date is documented. Billing cycle dates not in this file.
- It is not known whether any collection or credit-reporting actions
  occurred during the resolution period.
""".strip(),
        "expected": "UND",
    },
    {
        "label": "C9_subtle_compound_failure",
        "case_text": """
DISPUTE CASE FILE — Account 6XXX-XXXX-XXXX-4477

TIMELINE:
- March 6, 2026: Statement transmitted, $1,180 disputed charge.
- March 23, 2026: Written notice received (17 days after statement).
  Notice fully compliant.
- April 24, 2026: Written acknowledgment mailed (32 days after notice —
  past the 30-day limit by 2 days).
- June 18, 2026: Investigation completed and explanation mailed (87 days
  after notice). Within two billing cycles (close at day 95). Within 90
  days. Conclusion: no error.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION: No prohibited actions occurred.

ON CASUAL REVIEW: Resolution looks within timing limits.
ON CLOSE REVIEW: Acknowledgment was 32 days, past the 30-day requirement.
The acknowledgment-OR-waiver branch fails (no early-procedure-completion
either, since resolution was day 87, not within 30 days).
""".strip(),
        "expected": "FALSE",
    },
    
    # NEW cases that exercise the new structural depth
    {
        "label": "C10_acknowledgment_waiver_valid",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-9988

TIMELINE:
- February 1, 2026: Statement transmitted, $467 disputed charge plus
  $12.50 in related finance charges accrued.
- February 18, 2026: Written notice received (17 days after statement).
  Notice fully compliant.
- March 13, 2026: Creditor concluded the error occurred as asserted (day 23
  after notice receipt — within 30 days). On the same day:
    - Corrected the error (reversed the $467 charge)
    - Credited the disputed principal of $467
    - Credited the $12.50 in related finance charges
    - No other related charges existed
    - Sent the correction notice
- No separate acknowledgment was sent before the resolution — the creditor
  relied on the §1026.13(c) waiver: the full §1026.13(e) procedure was
  completed within 30 days.
- Within two billing cycles (close at day 31). Within 90 days.

CREDITOR CONDUCT DURING RESOLUTION: No prohibited actions occurred.
""".strip(),
        "expected": "TRUE",
        "rationale": "Acknowledgment waived because full §1026.13(e) procedure was completed within 30 days. v1 DAG could not distinguish this from 'resolved within 30 days'; v2 correctly identifies that the waiver requires procedure completion.",
    },
    {
        "label": "C11_acknowledgment_waiver_invalid_procedure_incomplete",
        "case_text": """
DISPUTE CASE FILE — Account 5XXX-XXXX-XXXX-3322

TIMELINE:
- February 1, 2026: Statement transmitted, $467 disputed charge plus
  $12.50 in related finance charges accrued.
- February 18, 2026: Written notice received (17 days after statement).
  Notice fully compliant.
- March 13, 2026: Creditor concluded the error occurred as asserted (day 23
  after notice receipt). On the same day:
    - Corrected the error (reversed the $467 charge)
    - Credited the disputed principal of $467
    - Did NOT credit the $12.50 in related finance charges
    - Sent the correction notice
- No separate acknowledgment was sent before the resolution. The creditor's
  internal procedure was to rely on the §1026.13(c) waiver. However, the
  §1026.13(e) procedure is not complete because finance charges were not
  credited.
- Within two billing cycles. Within 90 days.

CREDITOR CONDUCT DURING RESOLUTION: No prohibited actions occurred.
""".strip(),
        "expected": "FALSE",
        "rationale": "Critical case: creditor relied on the §1026.13(c) waiver but the §1026.13(e) procedure was incomplete (missing finance-charge credit). The waiver does not apply, AND no separate acknowledgment was sent, so the timing requirement fails. AND the §1026.13(e) procedure itself fails on the missing credit. v1 DAG would have rated this differently because it conflated 'procedure complete' with 'resolution issued.'",
    },
    {
        "label": "C12_two_billing_cycle_deadline_binding",
        "case_text": """
DISPUTE CASE FILE — Account 6XXX-XXXX-XXXX-1144

TIMELINE:
- January 8, 2026: Statement transmitted, $890 disputed charge.
- January 25, 2026: Written notice received (17 days after statement).
  Notice fully compliant.
- February 12, 2026: Written acknowledgment (18 days after notice).
- The consumer's billing cycle is 28 days, closing on the 7th of each
  month. After notice receipt on January 25, the next complete billing
  cycle closes February 7. The second complete billing cycle closes
  March 7. That's 41 days after notice receipt.
- March 25, 2026: Investigation completed and explanation mailed (59 days
  after notice). Within 90 days, BUT past the two-billing-cycle deadline
  of March 7 (41 days). Conclusion: no error.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION: No prohibited actions occurred.

NOTE: This case tests the two-billing-cycle rule. v1 DAG had a Boolean
atom 'resolved_within_two_billing_cycles' that Map could have set true or
false. v2 computes it from dates: resolution=day 59, second cycle close=
day 41. Since 59 > 41, the two-cycle rule fails. The 90-day rule alone
would have allowed this; the two-cycle rule (which is binding when
shorter) does not.
""".strip(),
        "expected": "FALSE",
        "rationale": "Two-billing-cycle deadline is binding (closes at day 41); resolution at day 59 exceeds it. Within 90 days but fails the two-cycle requirement. v2 catches this by computing the deadline from dates; v1 would have depended entirely on Map setting the Boolean correctly.",
    },
    {
        "label": "C13_collection_of_finance_charges_only",
        "case_text": """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-7755

TIMELINE:
- March 8, 2026: Statement transmitted, $612 disputed charge.
- March 25, 2026: Written notice received (17 days after statement).
  Notice fully compliant.
- April 5, 2026: Written acknowledgment (11 days after notice).
- April 8, 2026: Although the creditor did NOT attempt to collect the
  $612 disputed principal from the consumer, the consumer's account had
  a $14.20 finance charge ASSESSED ON THE DISPUTED AMOUNT during the
  billing cycle. The creditor included this $14.20 in the consumer's
  next periodic statement as a charge due. The collections system also
  sent a payment reminder specifically including this finance charge on
  April 18.
- May 22, 2026: Investigation completed and explanation mailed (58 days
  after notice). Within two billing cycles. Within 90 days. Conclusion:
  no error.
- Consumer did not request documentary evidence.

CREDITOR CONDUCT DURING RESOLUTION:
- Did NOT attempt to collect the $612 disputed principal
- DID attempt to collect the $14.20 finance charge related to the disputed
  amount (assessed it as a charge due, sent a payment reminder)
- No other related charges
- No delinquency reports
- No adverse credit threats
- No account restrictions
""".strip(),
        "expected": "FALSE",
        "rationale": "The creditor didn't collect on the principal but did attempt to collect related finance charges on the disputed amount. §1026.13(d)(1) explicitly prohibits this — 'the creditor may not try to collect any portion of any required payment that the consumer believes is related to the disputed amount.' v1 DAG had one collection atom that would either fully cover this or not; v2 separates the components and catches the violation cleanly.",
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
    p.add_argument("--show-atoms", action="store_true")
    args = p.parse_args()
    
    print("=" * 70)
    print("FCBA §1026.13 Composite (REFINED) — Policy-Faithful Depth")
    print("=" * 70)
    print()
    
    if not args.skip_sanity:
        sanity_ok = run_dag_sanity_checks()
        if not sanity_ok:
            print("\nSANITY CHECKS FAILED.")
            sys.exit(1)
        print("\nAll sanity checks pass.\n")
    
    dag = build_fcba_composite_refined_dag()
    
    seen = set()
    def _count(n):
        if id(n) in seen: return 0
        seen.add(id(n))
        c = 1
        for attr in ("children", "left", "right", "child", "condition",
                     "if_true", "if_false"):
            v = getattr(n, attr, None)
            if v is None: continue
            if isinstance(v, list):
                for x in v: c += _count(x)
            else:
                c += _count(v)
        return c
    node_count = _count(dag)
    print(f"DAG size: {node_count} nodes, {len(ATOM_DESCRIPTIONS)} atoms")
    print("  (v1 was 56 nodes, 26 atoms; depth added is policy-faithful)")
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
        if case.get("rationale"):
            print(f"Rationale: {case['rationale']}")
        print()
        
        print("Map...")
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
            print(f"  WARNING: unknown keys produced: {sorted(unknown_keys)}")
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
        print(f"  {mark} {r['label']}: got {r['disposition']}, "
              f"expected {r['expected']}")
    
    out_path = "audits/fcba_composite_refined/results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

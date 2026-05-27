"""
test_fcba_c10_fixes.py — test two distinct fixes for the C10 failure mode.

The C10 failure: Map extracted credited_related_other_charges=false on a case
where the policy obligation was vacuously satisfied (no other related charges
existed). The engine correctly computed FALSE given the atom values, but the
result was the wrong adjudication.

Two fixes to test:

VARIANT A (prompt-only): Keep the atom singular but augment its description
with explicit examples and vacuous-case handling. See if better Map prompting
alone resolves the failure.

VARIANT B (structural): Split the atom into two:
  - related_other_charges_exist: did such charges exist?
  - credited_related_other_charges_if_existed: if they existed, were credited?
The DAG composes them as OR(NOT exists, credited_if_existed) for the
obligation-met semantics. This is the structural fix that prevents the
ambiguity from existing in the spec.

Same approach for the related finance charges atom (which would have the
same failure mode if a case said "no related finance charges existed").

Tests: the C10 case (vacuous obligation, should be TRUE) and a re-test of
the C11 case (real failure, should be FALSE). Both variants tested.

This is a focused diagnostic test, not a full re-run of all 13 cases.
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
# Shared: notice, conduct, timing subtrees (unchanged from v2)
# ===========================================================================
# I'll only reproduce what changes between variants. The rest is delegated.

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


def build_conduct_compliance_subtree():
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


def build_timing_compliance_subtree(conclusion_procedure_subtree):
    acknowledged_within_30 = LeqNode(
        left=NumericLeaf(atom_id="days_from_notice_to_acknowledgment"),
        right=Constant(label="thirty_day_ack_limit", value=Decimal("30")),
    )
    resolution_within_30 = LeqNode(
        left=NumericLeaf(atom_id="days_from_notice_to_resolution"),
        right=Constant(label="thirty_day_proc_limit", value=Decimal("30")),
    )
    acknowledgment_waiver_applies = AndNode(children=[
        conclusion_procedure_subtree,
        resolution_within_30,
    ])
    acknowledgment_or_waiver = OrNode(children=[
        acknowledged_within_30,
        acknowledgment_waiver_applies,
    ])
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
# VARIANT A: prompt-only fix — keep atoms the same, improve descriptions
# ===========================================================================

def build_variant_A_conclusion_procedure_subtree():
    """Same structure as v2 — atoms unchanged, only the prompt changes."""
    credit_complete = AndNode(children=[
        Leaf(atom_id="credited_disputed_amount"),
        Leaf(atom_id="credited_related_finance_charges"),
        Leaf(atom_id="credited_related_other_charges"),
    ])
    error_as_asserted = AndNode(children=[
        Leaf(atom_id="corrected_error"),
        credit_complete,
        Leaf(atom_id="sent_correction_notice"),
    ])
    
    different_error_credit = AndNode(children=[
        Leaf(atom_id="credited_disputed_amount"),
        Leaf(atom_id="credited_related_finance_charges"),
        Leaf(atom_id="credited_related_other_charges"),
    ])
    different_error = AndNode(children=[
        Leaf(atom_id="sent_written_explanation"),
        Leaf(atom_id="corrected_the_different_error"),
        different_error_credit,
    ])
    
    documentary_evidence_check = OrNode(children=[
        NotNode(child=Leaf(atom_id="consumer_requested_documentary_evidence")),
        Leaf(atom_id="provided_documentary_evidence"),
    ])
    no_error = AndNode(children=[
        Leaf(atom_id="sent_written_explanation"),
        documentary_evidence_check,
    ])
    
    return OrNode(children=[
        AndNode(children=[Leaf(atom_id="concluded_error_as_asserted"), error_as_asserted]),
        AndNode(children=[Leaf(atom_id="concluded_different_error"), different_error]),
        AndNode(children=[Leaf(atom_id="concluded_no_error"), no_error]),
    ])


def build_variant_A_dag():
    notice = build_notice_validity_subtree()
    conclusion = build_variant_A_conclusion_procedure_subtree()
    timing = build_timing_compliance_subtree(conclusion)
    conduct = build_conduct_compliance_subtree()
    return AndNode(children=[notice, timing, conduct, conclusion])


# Atom descriptions for Variant A — same atoms, richer descriptions
VARIANT_A_ATOMS = {
    # All atoms from v2, but I'm only redefining the ones with the vacuous-
    # obligation issue. The rest stay as before. For brevity I'll only show
    # the changed atoms; the rest are imported.
    "credited_disputed_amount": {
        "description": (
            "true if the obligation to credit the disputed principal amount "
            "is satisfied. Specifically: true if the creditor credited the "
            "disputed amount, OR if no disputed principal credit is required "
            "(which is unusual — the principal is almost always required to "
            "be credited when an error as asserted or different error is "
            "concluded). False if a credit was required and not made."
        ),
        "examples": {
            "TRUE": [
                "Creditor reversed the $325 disputed charge",
                "The $467 disputed principal was credited to the account",
            ],
            "FALSE": [
                "The disputed amount was not credited even after error was confirmed",
            ],
            "NULL": [
                "Case doesn't say whether the principal was credited",
                "Conclusion type is unclear, so credit obligation cannot be assessed",
            ],
        },
    },
    "credited_related_finance_charges": {
        "description": (
            "true if the obligation to credit any related finance charges is "
            "satisfied. This obligation has two possible satisfactions:\n"
            "  (1) Related finance charges existed and the creditor credited them, OR\n"
            "  (2) No related finance charges existed (the obligation is vacuously satisfied).\n"
            "Return false ONLY if related finance charges existed but were "
            "not credited. Return null if the case is silent on whether "
            "such charges existed."
        ),
        "examples": {
            "TRUE": [
                "Creditor credited the $12.50 in related finance charges",
                "No related finance charges existed; the obligation is vacuously satisfied",
                "All accrued finance charges on the disputed amount were reversed",
            ],
            "FALSE": [
                "Related finance charges of $7.85 accrued but were not credited",
                "Late fees on the disputed amount were not reversed",
            ],
            "NULL": [
                "Case mentions credit but doesn't specify components",
                "Conclusion type is unclear or no error was found",
            ],
        },
    },
    "credited_related_other_charges": {
        "description": (
            "true if the obligation to credit any other related charges is "
            "satisfied. This obligation has two possible satisfactions:\n"
            "  (1) Other related charges existed and the creditor credited them, OR\n"
            "  (2) No other related charges existed (the obligation is vacuously satisfied).\n"
            "Return false ONLY if other related charges existed but were "
            "not credited. Return null if the case is silent on whether "
            "such charges existed.\n"
            "IMPORTANT: When the case says 'no other related charges existed' "
            "or equivalent, return TRUE (vacuously satisfied), not FALSE."
        ),
        "examples": {
            "TRUE": [
                "Creditor credited $15 in related processing fees that had accrued",
                "No other related charges existed (the obligation is vacuously satisfied)",
                "The case states no other charges were assessed on the disputed amount",
            ],
            "FALSE": [
                "Related processing fees of $25 existed but were not credited",
                "Other related charges of $10.50 were assessed and never reversed",
            ],
            "NULL": [
                "Case mentions some charges but doesn't specify which are 'other related' vs 'finance'",
                "Conclusion type is unclear or no error was found",
            ],
        },
    },
}


# ===========================================================================
# VARIANT B: structural fix — split atoms, compose obligation-met semantics
# ===========================================================================

def build_variant_B_credit_obligation_met(existence_atom, credit_atom):
    """The structural pattern for conditional obligations:
       obligation_met = OR(NOT exists, credited_if_existed)
    """
    return OrNode(children=[
        NotNode(child=Leaf(atom_id=existence_atom)),
        Leaf(atom_id=credit_atom),
    ])


def build_variant_B_conclusion_procedure_subtree():
    # Disputed principal: under error-as-asserted, this is almost always
    # required. I'll keep it as a simple atom for now (the vacuous case is
    # rare for the principal). The refactor focuses on the conditional cases.
    
    # Finance charges: obligation-met via structural fix
    finance_charges_obligation_met = build_variant_B_credit_obligation_met(
        existence_atom="related_finance_charges_existed",
        credit_atom="credited_related_finance_charges_if_existed",
    )
    
    # Other related charges: obligation-met via structural fix
    other_charges_obligation_met = build_variant_B_credit_obligation_met(
        existence_atom="related_other_charges_existed",
        credit_atom="credited_related_other_charges_if_existed",
    )
    
    credit_complete = AndNode(children=[
        Leaf(atom_id="credited_disputed_amount"),
        finance_charges_obligation_met,
        other_charges_obligation_met,
    ])
    error_as_asserted = AndNode(children=[
        Leaf(atom_id="corrected_error"),
        credit_complete,
        Leaf(atom_id="sent_correction_notice"),
    ])
    
    different_error_credit = AndNode(children=[
        Leaf(atom_id="credited_disputed_amount"),
        finance_charges_obligation_met,
        other_charges_obligation_met,
    ])
    different_error = AndNode(children=[
        Leaf(atom_id="sent_written_explanation"),
        Leaf(atom_id="corrected_the_different_error"),
        different_error_credit,
    ])
    
    documentary_evidence_check = OrNode(children=[
        NotNode(child=Leaf(atom_id="consumer_requested_documentary_evidence")),
        Leaf(atom_id="provided_documentary_evidence"),
    ])
    no_error = AndNode(children=[
        Leaf(atom_id="sent_written_explanation"),
        documentary_evidence_check,
    ])
    
    return OrNode(children=[
        AndNode(children=[Leaf(atom_id="concluded_error_as_asserted"), error_as_asserted]),
        AndNode(children=[Leaf(atom_id="concluded_different_error"), different_error]),
        AndNode(children=[Leaf(atom_id="concluded_no_error"), no_error]),
    ])


def build_variant_B_dag():
    notice = build_notice_validity_subtree()
    conclusion = build_variant_B_conclusion_procedure_subtree()
    timing = build_timing_compliance_subtree(conclusion)
    conduct = build_conduct_compliance_subtree()
    return AndNode(children=[notice, timing, conduct, conclusion])


# Variant B atom catalog — note the split atoms
VARIANT_B_ATOMS = {
    "related_finance_charges_existed": {
        "description": (
            "true if any finance charges related to the disputed amount "
            "existed at the time of the dispute (whether or not they were "
            "subsequently credited). False if no such charges existed. "
            "Null if the case is silent on this."
        ),
        "examples": {
            "TRUE": [
                "$12.50 in finance charges had accrued on the disputed amount",
                "Late fees were assessed on the disputed charge",
            ],
            "FALSE": [
                "No finance charges had accrued on the disputed amount",
                "The case explicitly says no related finance charges existed",
            ],
            "NULL": [
                "Case doesn't mention finance charges at all",
            ],
        },
    },
    "credited_related_finance_charges_if_existed": {
        "description": (
            "If related finance charges existed, true if the creditor "
            "credited them; false if they did not. If no such charges "
            "existed (related_finance_charges_existed is false), this "
            "atom is not used by the DAG; return null."
        ),
        "examples": {
            "TRUE": [
                "Creditor credited the $12.50 in related finance charges",
                "All accrued late fees were reversed",
            ],
            "FALSE": [
                "Related finance charges existed but were not credited",
            ],
            "NULL": [
                "No related finance charges existed (not applicable)",
                "Case doesn't say whether the finance charges were credited",
            ],
        },
    },
    "related_other_charges_existed": {
        "description": (
            "true if any other charges (besides principal and finance "
            "charges) related to the disputed amount existed at the "
            "time of the dispute. False if no such charges existed. "
            "Null if the case is silent on this."
        ),
        "examples": {
            "TRUE": [
                "$15 in processing fees had accrued on the disputed amount",
                "Other ancillary charges related to the dispute were on the account",
            ],
            "FALSE": [
                "No other related charges existed",
                "The case explicitly states no other charges were assessed",
            ],
            "NULL": [
                "Case doesn't address other related charges",
            ],
        },
    },
    "credited_related_other_charges_if_existed": {
        "description": (
            "If other related charges existed, true if the creditor "
            "credited them; false if they did not. If no such charges "
            "existed, this atom is not used by the DAG; return null."
        ),
        "examples": {
            "TRUE": [
                "Creditor credited all other related charges that existed",
            ],
            "FALSE": [
                "Other related charges existed but were not credited",
            ],
            "NULL": [
                "No other related charges existed (not applicable)",
            ],
        },
    },
}


# ===========================================================================
# Map prompt generation
# ===========================================================================

def build_atom_prompt_section(atoms_dict):
    """Generate the atom section of the Map prompt from structured specs."""
    lines = []
    for name, spec in atoms_dict.items():
        lines.append(f"\n  - {name}:")
        lines.append(f"      Description: {spec['description']}")
        if "examples" in spec:
            for category, examples in spec["examples"].items():
                lines.append(f"      Examples returning {category}:")
                for ex in examples:
                    lines.append(f"        • {ex}")
    return "\n".join(lines)


# Full atom catalog — base atoms from v2 plus variant-specific atoms
BASE_ATOMS = {
    "days_between_first_statement_and_notice": {
        "description": "integer days between the first statement and notice receipt",
    },
    "notice_received_at_designated_address": {
        "description": "true if the notice was at the designated address",
    },
    "notice_is_written": {
        "description": "true if the notice is in writing",
    },
    "notice_identifies_consumer": {
        "description": "true if the notice identifies consumer name and account number",
    },
    "notice_indicates_belief_of_error": {
        "description": "true if the notice indicates belief of error",
    },
    "notice_states_dollar_amount": {
        "description": "true if the notice states the dollar amount",
    },
    "notice_states_reason_for_belief": {
        "description": "true if the notice states reasons for the belief",
    },
    "notice_states_type_of_error": {
        "description": "true if the notice describes the type of error",
    },
    "notice_states_date_of_error": {
        "description": "true if the notice states the date of the error",
    },
    "days_from_notice_to_acknowledgment": {
        "description": "days from notice to acknowledgment, or null if no separate acknowledgment was sent",
    },
    "days_from_notice_to_resolution": {
        "description": "days from notice receipt to resolution notification",
    },
    "resolution_date_days_since_notice": {
        "description": "resolution notification date in days since notice receipt",
    },
    "second_complete_billing_cycle_days_since_notice": {
        "description": (
            "the day on which the second complete billing cycle after notice "
            "receipt closes, measured in days from notice receipt. Compute "
            "from billing cycle dates if given. Null if not specified."
        ),
        "examples": {
            "Valid extraction": [
                "Case says 'within two billing cycles (close at day 31)' → return 31",
                "Case says 'second cycle closes May 15 (71 days after notice)' → return 71",
            ],
            "NULL": [
                "Case doesn't mention billing cycle dates",
            ],
        },
    },
    "did_attempt_to_collect_principal": {
        "description": "true if creditor attempted to collect the disputed principal during resolution",
    },
    "did_attempt_to_collect_related_finance_charges": {
        "description": "true if creditor attempted to collect related finance charges during resolution",
    },
    "did_attempt_to_collect_related_other_charges": {
        "description": "true if creditor attempted to collect other related charges during resolution",
    },
    "did_report_disputed_as_delinquent": {
        "description": "true if creditor reported the disputed amount as delinquent",
    },
    "did_threaten_adverse_credit_report": {
        "description": "true if creditor threatened adverse credit reporting",
    },
    "did_restrict_account_by_reason_of_dispute": {
        "description": "true if creditor restricted the account by reason of the dispute",
    },
    "concluded_error_as_asserted": {
        "description": "true if creditor concluded the error occurred as asserted",
    },
    "concluded_different_error": {
        "description": "true if creditor concluded a different billing error occurred",
    },
    "concluded_no_error": {
        "description": "true if creditor concluded no billing error occurred",
    },
    "corrected_error": {
        "description": "true if the creditor corrected the billing error (error-as-asserted branch)",
    },
    "sent_correction_notice": {
        "description": "true if the creditor sent a correction notice to the consumer",
    },
    "sent_written_explanation": {
        "description": "true if the creditor sent a written explanation of its conclusion",
    },
    "corrected_the_different_error": {
        "description": "true if the creditor corrected the different billing error (different-error branch)",
    },
    "consumer_requested_documentary_evidence": {
        "description": "true if the consumer requested documentary evidence after the no-error conclusion",
    },
    "provided_documentary_evidence": {
        "description": "true if the creditor provided documentary evidence",
    },
}


MAP_PROMPT_TEMPLATE = """You are extracting structured facts from a consumer-dispute case file
for FCBA §1026.13 compliance adjudication.

ATOMS TO EXTRACT (use EXACT keys; return null for anything the case does
not explicitly state):
{atom_specs}

CASE FILE:
{case_text}

CRITICAL EXTRACTION RULES:
- Use EXACT atom names as listed. No abbreviations, no spelling changes.
- For numeric atoms: return JSON numbers, not strings.
- For Boolean atoms: return true/false ONLY when explicitly established;
  null when silent or ambiguous.
- Pay attention to the examples for each atom — they show the
  disambiguation rules.

Return ONLY a JSON object. No preamble or commentary.
"""


def call_map_llm(case_text, atoms_dict, model="claude-haiku-4-5-20251001"):
    from rulekit.build.decomposer import LLMCaller
    
    atom_specs_text = build_atom_prompt_section(atoms_dict)
    prompt = MAP_PROMPT_TEMPLATE.format(
        atom_specs=atom_specs_text,
        case_text=case_text,
    )
    
    llm = LLMCaller(model=model)
    t0 = time.time()
    response = llm.call(f"fcba_c10_fixes_{int(time.time()*1000)}", prompt)
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
    
    return atoms, elapsed


def build_fact_bundle(atoms_dict, expected_atom_names, numeric_atoms):
    values = {}
    for name in expected_atom_names:
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
# Test cases — C10 (vacuous, should be TRUE) and C11 (real failure, should be FALSE)
# ===========================================================================

C10_CASE_TEXT = """
DISPUTE CASE FILE — Account 4XXX-XXXX-XXXX-9988

TIMELINE:
- February 1, 2026: Statement transmitted, $467 disputed charge plus
  $12.50 in related finance charges accrued.
- February 18, 2026: Written notice received (17 days after statement).
  Notice fully compliant.
- March 13, 2026: Creditor concluded the error occurred as asserted (day 23
  after notice receipt). On the same day:
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
""".strip()


C11_CASE_TEXT = """
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
""".strip()


# ===========================================================================
# Test execution
# ===========================================================================

NUMERIC_ATOMS = {
    "days_between_first_statement_and_notice",
    "days_from_notice_to_acknowledgment",
    "days_from_notice_to_resolution",
    "resolution_date_days_since_notice",
    "second_complete_billing_cycle_days_since_notice",
}


def run_variant_A(case_label, case_text, expected):
    """Variant A: enriched atom descriptions but same DAG structure."""
    atoms_for_A = {**BASE_ATOMS, **VARIANT_A_ATOMS}
    
    print(f"  Map (Variant A — enriched prompts)...")
    extracted, elapsed = call_map_llm(case_text, atoms_for_A)
    print(f"    Map latency: {elapsed:.2f}s")
    
    # Show the critical atoms
    critical = ["credited_disputed_amount", "credited_related_finance_charges",
                "credited_related_other_charges"]
    print(f"    Critical atoms:")
    for k in critical:
        print(f"      {k}: {extracted.get(k, '<missing>')}")
    
    bundle = build_fact_bundle(
        extracted, list(atoms_for_A.keys()), NUMERIC_ATOMS,
    )
    dag = build_variant_A_dag()
    result = dag.evaluate(bundle, [])
    
    if result == Kleene.TRUE:
        disposition = "TRUE"
    elif result == Kleene.FALSE:
        disposition = "FALSE"
    else:
        disposition = "UND"
    
    correct = (disposition == expected)
    outcome = "✓ CORRECT" if correct else "✗ WRONG"
    print(f"    Disposition: {disposition} | Expected: {expected} | {outcome}")
    return disposition, correct, extracted


def run_variant_B(case_label, case_text, expected):
    """Variant B: structural fix with split atoms."""
    # The atoms for B exclude the conflated single atoms and include the
    # split pairs
    atoms_for_B = {**BASE_ATOMS}
    # Add the structural-fix atoms
    atoms_for_B.update(VARIANT_B_ATOMS)
    # The original conflated atoms are no longer needed
    atoms_for_B.pop("credited_related_finance_charges", None)
    atoms_for_B.pop("credited_related_other_charges", None)
    # Keep credited_disputed_amount unchanged (it's not in BASE; add it)
    atoms_for_B["credited_disputed_amount"] = {
        "description": "true if the creditor credited the disputed principal amount",
    }
    
    print(f"  Map (Variant B — split atoms)...")
    extracted, elapsed = call_map_llm(case_text, atoms_for_B)
    print(f"    Map latency: {elapsed:.2f}s")
    
    # Show the critical atoms
    critical = ["credited_disputed_amount",
                "related_finance_charges_existed", "credited_related_finance_charges_if_existed",
                "related_other_charges_existed", "credited_related_other_charges_if_existed"]
    print(f"    Critical atoms:")
    for k in critical:
        print(f"      {k}: {extracted.get(k, '<missing>')}")
    
    bundle = build_fact_bundle(
        extracted, list(atoms_for_B.keys()), NUMERIC_ATOMS,
    )
    dag = build_variant_B_dag()
    result = dag.evaluate(bundle, [])
    
    if result == Kleene.TRUE:
        disposition = "TRUE"
    elif result == Kleene.FALSE:
        disposition = "FALSE"
    else:
        disposition = "UND"
    
    correct = (disposition == expected)
    outcome = "✓ CORRECT" if correct else "✗ WRONG"
    print(f"    Disposition: {disposition} | Expected: {expected} | {outcome}")
    return disposition, correct, extracted


def main():
    print("=" * 70)
    print("C10 Fix Diagnostic: Variant A (prompt) vs Variant B (structural)")
    print("=" * 70)
    print()
    
    cases = [
        ("C10_vacuous_obligation", C10_CASE_TEXT, "TRUE",
         "Vacuous obligation case: no other related charges existed, so the "
         "credit obligation for other charges is vacuously satisfied."),
        ("C11_real_failure", C11_CASE_TEXT, "FALSE",
         "Real failure case: related finance charges existed and were not "
         "credited. Procedure incomplete; waiver does not apply."),
    ]
    
    results = []
    
    for case_label, case_text, expected, rationale in cases:
        print("=" * 70)
        print(f"Case: {case_label}")
        print(f"Expected: {expected}")
        print(f"Rationale: {rationale}")
        print()
        
        a_disp, a_ok, a_extracted = run_variant_A(case_label, case_text, expected)
        print()
        b_disp, b_ok, b_extracted = run_variant_B(case_label, case_text, expected)
        print()
        
        results.append({
            "case": case_label,
            "expected": expected,
            "variant_A": {"disposition": a_disp, "correct": a_ok,
                         "extracted": a_extracted},
            "variant_B": {"disposition": b_disp, "correct": b_ok,
                         "extracted": b_extracted},
        })
    
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    for r in results:
        print(f"  {r['case']} (expected {r['expected']})")
        a = r["variant_A"]
        b = r["variant_B"]
        a_mark = "✓" if a["correct"] else "✗"
        b_mark = "✓" if b["correct"] else "✗"
        print(f"    Variant A (prompt fix):     {a_mark} got {a['disposition']}")
        print(f"    Variant B (structural fix): {b_mark} got {b['disposition']}")
        print()
    
    a_correct = sum(1 for r in results if r["variant_A"]["correct"])
    b_correct = sum(1 for r in results if r["variant_B"]["correct"])
    n = len(results)
    print(f"Variant A: {a_correct}/{n} correct")
    print(f"Variant B: {b_correct}/{n} correct")
    
    if a_correct == n and b_correct == n:
        print()
        print("BOTH fixes work. Prompt improvement is sufficient; structural fix "
              "is cleaner but not strictly needed.")
    elif b_correct == n and a_correct < n:
        print()
        print("STRUCTURAL fix is required. Prompt improvement alone is "
              "insufficient — the atom ambiguity needs to be eliminated at "
              "the spec level.")
    elif a_correct == n and b_correct < n:
        print()
        print("UNEXPECTED: prompt fix works but structural fix fails. "
              "Investigate structural composition.")
    else:
        print()
        print("NEITHER fix fully works. There's a deeper issue to diagnose.")
    
    out_path = "audits/fcba_c10_fixes/results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

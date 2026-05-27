"""
test_sara_s63_full_standard_deduction.py - end-to-end validation on a
substantially larger DAG: the full §63 standard deduction computation.

This determination encompasses:
  - §63(c)(1): standard deduction = basic + additional
  - §63(c)(2): basic standard deduction, varying by filing status, with
    the 2018-2025 special amounts
  - §63(c)(3): additional standard deduction = sum of amounts in §63(f)
  - §63(c)(5): dependent limitation — basic capped at max($500, $250+earned)
  - §63(c)(6): ineligible categories — zero deduction for MFS-where-spouse-
    itemizes, nonresident alien, estate/trust
  - §63(f)(1): $600 additional for age 65+ (taxpayer; spouse if §151(b))
  - §63(f)(2): $600 additional for blindness (taxpayer; spouse if §151(b))
  - §63(f)(3): substitute $750 for $600 if not married and not surviving spouse

This is a single determination that composes multiple sub-rules. It exercises:
  - Deep nesting of ConditionalNumericNode (filing status × year × dependent)
  - MaxNode (dependent limitation greater-of)
  - Boolean composition (ineligibility AND)
  - ~15 atoms covering taxpayer situation
  - Conditional gating (additional amounts depend on age/blindness predicates)

Tests against SARA §63 cases.
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
    ConditionalNumericNode,
    LtNode, GtNode, LeqNode, GeqNode, EqNode,
    PlusNode, MinusNode, TimesConstNode, SumNode, MaxNode, MinNode,
)
from rulekit.engine.boolean import Leaf, AndNode, OrNode, NotNode


# ===========================================================================
# Constants from the IRC corpus we received
# ===========================================================================

# Pre-2018 basic standard deduction amounts (§63(c)(2))
BASIC_JOINT_PRE_2018 = Decimal("6000")    # 200% of "any other case" = 200% × $3000
BASIC_HOH_PRE_2018 = Decimal("4400")
BASIC_OTHER_PRE_2018 = Decimal("3000")

# 2018-2025 special amounts (§63(c)(7))
BASIC_JOINT_2018_2025 = Decimal("36000")  # 200% of "any other case" = 200% × $18000
BASIC_HOH_2018_2025 = Decimal("18000")
BASIC_OTHER_2018_2025 = Decimal("12000")

# Additional standard deduction amounts (§63(f))
ADDL_MARRIED = Decimal("600")
ADDL_UNMARRIED = Decimal("750")

# Dependent limitation (§63(c)(5))
DEP_FLOOR = Decimal("500")
DEP_EARNED_OFFSET = Decimal("250")


# ===========================================================================
# Build the full §63 standard deduction DAG
# ===========================================================================

def build_s63_basic_standard_deduction_dag():
    """The basic standard deduction (§63(c)(2)), accounting for filing status
    and the 2018-2025 special amounts.
    
    Returns a numeric: the basic standard deduction in dollars before any
    additional amounts or dependent limitation.
    """
    year = NumericLeaf(atom_id="taxable_year")
    
    # Determine if we're in the 2018-2025 special period
    in_special_period = AndNode(children=[
        GeqNode(left=year, right=Constant(label="year_2018", value=Decimal("2018"))),
        LeqNode(left=year, right=Constant(label="year_2025", value=Decimal("2025"))),
    ])
    
    # Joint return amount: $6000 pre-2018, $36000 in 2018-2025
    joint_amount = ConditionalNumericNode(
        condition=in_special_period,
        if_true=Constant(label="basic_joint_2018_2025", value=BASIC_JOINT_2018_2025),
        if_false=Constant(label="basic_joint_pre_2018", value=BASIC_JOINT_PRE_2018),
        surface_label="basic_joint_amount",
    )
    
    # HOH amount: $4400 pre-2018, $18000 in 2018-2025
    hoh_amount = ConditionalNumericNode(
        condition=in_special_period,
        if_true=Constant(label="basic_hoh_2018_2025", value=BASIC_HOH_2018_2025),
        if_false=Constant(label="basic_hoh_pre_2018", value=BASIC_HOH_PRE_2018),
        surface_label="basic_hoh_amount",
    )
    
    # Other amount: $3000 pre-2018, $12000 in 2018-2025
    other_amount = ConditionalNumericNode(
        condition=in_special_period,
        if_true=Constant(label="basic_other_2018_2025", value=BASIC_OTHER_2018_2025),
        if_false=Constant(label="basic_other_pre_2018", value=BASIC_OTHER_PRE_2018),
        surface_label="basic_other_amount",
    )
    
    # Now select based on filing status: joint OR surviving spouse first,
    # then HOH, then "any other case"
    is_joint_or_ss = OrNode(children=[
        Leaf(atom_id="files_joint_return"),
        Leaf(atom_id="is_surviving_spouse"),
    ])
    is_hoh = Leaf(atom_id="is_head_of_household")
    
    # Choose HOH amount if HOH, else "other"
    hoh_or_other = ConditionalNumericNode(
        condition=is_hoh,
        if_true=hoh_amount,
        if_false=other_amount,
        surface_label="basic_hoh_vs_other",
    )
    
    # Choose joint/SS amount if joint or SS, else (HOH or other)
    return ConditionalNumericNode(
        condition=is_joint_or_ss,
        if_true=joint_amount,
        if_false=hoh_or_other,
        surface_label="basic_standard_deduction",
    )


def build_s63_f_additional_amount_dag():
    """The additional standard deduction (§63(f)) — sum of per-status amounts.
    
    Each amount is $600, or $750 if unmarried and not surviving spouse (§63(f)(3)).
    Counted: aged taxpayer, aged spouse (if §151(b)), blind taxpayer, blind spouse.
    
    Returns a numeric: total additional standard deduction.
    """
    # Determine the per-amount value: $750 if unmarried & not SS, else $600
    is_unmarried_not_ss = AndNode(children=[
        NotNode(child=Leaf(atom_id="is_married_status_for_section_7703")),
        NotNode(child=Leaf(atom_id="is_surviving_spouse")),
    ])
    
    per_amount = ConditionalNumericNode(
        condition=is_unmarried_not_ss,
        if_true=Constant(label="addl_unmarried", value=ADDL_UNMARRIED),
        if_false=Constant(label="addl_married", value=ADDL_MARRIED),
        surface_label="additional_per_amount",
    )
    
    # For each potentially-applicable amount, include per_amount if condition
    # holds, else $0. Then sum.
    
    # Taxpayer aged 65+
    tp_aged = ConditionalNumericNode(
        condition=Leaf(atom_id="taxpayer_attained_age_65"),
        if_true=per_amount,
        if_false=Constant(label="zero", value=Decimal("0")),
        surface_label="addl_taxpayer_aged",
    )
    
    # Spouse aged 65+ AND additional §151 exemption allowable for spouse
    spouse_aged_gate = AndNode(children=[
        Leaf(atom_id="spouse_attained_age_65"),
        Leaf(atom_id="spouse_151_exemption_allowable"),
    ])
    spouse_aged = ConditionalNumericNode(
        condition=spouse_aged_gate,
        if_true=per_amount,
        if_false=Constant(label="zero", value=Decimal("0")),
        surface_label="addl_spouse_aged",
    )
    
    # Taxpayer blind
    tp_blind = ConditionalNumericNode(
        condition=Leaf(atom_id="taxpayer_is_blind"),
        if_true=per_amount,
        if_false=Constant(label="zero", value=Decimal("0")),
        surface_label="addl_taxpayer_blind",
    )
    
    # Spouse blind AND additional §151 exemption allowable for spouse
    spouse_blind_gate = AndNode(children=[
        Leaf(atom_id="spouse_is_blind"),
        Leaf(atom_id="spouse_151_exemption_allowable"),
    ])
    spouse_blind = ConditionalNumericNode(
        condition=spouse_blind_gate,
        if_true=per_amount,
        if_false=Constant(label="zero", value=Decimal("0")),
        surface_label="addl_spouse_blind",
    )
    
    return SumNode(children=[tp_aged, spouse_aged, tp_blind, spouse_blind])


def build_s63_c_5_dependent_cap_dag(basic_pre_cap):
    """Apply the §63(c)(5) dependent limitation.
    
    If the taxpayer is a dependent of another taxpayer, the basic standard
    deduction is capped at max($500, $250 + earned_income).
    
    If not a dependent, the basic standard deduction is unchanged.
    
    Args:
      basic_pre_cap: numeric node producing the basic standard deduction
                     before applying this cap
    """
    # The cap value: max($500, $250 + earned_income)
    cap_with_earned = PlusNode(
        left=Constant(label="dep_earned_offset", value=DEP_EARNED_OFFSET),
        right=NumericLeaf(atom_id="earned_income"),
    )
    cap_amount = MaxNode(children=[
        Constant(label="dep_floor", value=DEP_FLOOR),
        cap_with_earned,
    ])
    
    # The capped value: min(basic_pre_cap, cap_amount)
    capped = MinNode(children=[basic_pre_cap, cap_amount])
    
    return ConditionalNumericNode(
        condition=Leaf(atom_id="taxpayer_is_dependent_of_another"),
        if_true=capped,
        if_false=basic_pre_cap,
        surface_label="basic_after_dependent_cap",
    )


def build_s63_c_6_ineligibility_dag(deduction_amount):
    """Apply the §63(c)(6) ineligibility carve-out.
    
    Standard deduction is zero if:
      (A) married filing separately AND spouse itemizes, OR
      (B) nonresident alien, OR
      (D) estate/trust/common trust fund/partnership.
    
    Args:
      deduction_amount: numeric node producing the standard deduction before
                        applying this carve-out
    """
    mfs_and_spouse_itemizes = AndNode(children=[
        Leaf(atom_id="files_married_separately"),
        Leaf(atom_id="spouse_itemizes_deductions"),
    ])
    
    is_ineligible = OrNode(children=[
        mfs_and_spouse_itemizes,
        Leaf(atom_id="is_nonresident_alien"),
        Leaf(atom_id="is_estate_trust_or_partnership"),
    ])
    
    return ConditionalNumericNode(
        condition=is_ineligible,
        if_true=Constant(label="zero", value=Decimal("0")),
        if_false=deduction_amount,
        surface_label="after_ineligibility_check",
    )


def build_full_s63_standard_deduction_dag():
    """The complete §63 standard deduction determination.
    
    Composition order:
      1. Compute basic standard deduction by filing status (§63(c)(2))
      2. Apply dependent limitation if applicable (§63(c)(5))
      3. Add additional standard deduction amounts (§63(f) via §63(c)(3))
      4. Apply ineligibility carve-out (§63(c)(6))
    
    Returns a numeric: the final standard deduction amount.
    """
    # 1. Basic standard deduction by filing status
    basic = build_s63_basic_standard_deduction_dag()
    
    # 2. Dependent limitation
    basic_capped = build_s63_c_5_dependent_cap_dag(basic)
    
    # 3. Add additional amounts (§63(c)(1) = basic + additional)
    additional = build_s63_f_additional_amount_dag()
    total_before_ineligibility = PlusNode(left=basic_capped, right=additional)
    
    # 4. Ineligibility carve-out — zeros everything if ineligible
    final = build_s63_c_6_ineligibility_dag(total_before_ineligibility)
    
    return final


# ===========================================================================
# Atom catalog — for Map and documentation
# ===========================================================================

ATOM_DESCRIPTIONS = {
    "taxable_year": "the taxable year as a 4-digit integer (e.g., 2017)",
    "files_joint_return": "true if the taxpayer files a joint return with their spouse",
    "is_surviving_spouse": "true if the taxpayer is a surviving spouse as defined in §2(a) (spouse died in the preceding two years and certain household conditions)",
    "is_head_of_household": "true if the taxpayer is a head of household as defined in §2(b)",
    "files_married_separately": "true if the taxpayer is married and files separately (not jointly with spouse)",
    "is_married_status_for_section_7703": "true if the taxpayer is married for §7703 purposes (excluding those legally separated)",
    "taxpayer_attained_age_65": "true if the taxpayer attained age 65 before the close of the taxable year",
    "spouse_attained_age_65": "true if the taxpayer's spouse attained age 65 before the close of the taxable year",
    "spouse_151_exemption_allowable": "true if an additional §151(b) exemption is allowable to the taxpayer for the spouse",
    "taxpayer_is_blind": "true if the taxpayer is blind at the close of the taxable year",
    "spouse_is_blind": "true if the taxpayer's spouse is blind at the close of the taxable year",
    "taxpayer_is_dependent_of_another": "true if a §151 deduction is allowable to another taxpayer for this taxpayer (i.e., the taxpayer can be claimed as a dependent)",
    "earned_income": "the taxpayer's earned income in dollars (relevant only if taxpayer is a dependent)",
    "spouse_itemizes_deductions": "true if the taxpayer's spouse itemizes deductions (relevant only if MFS)",
    "is_nonresident_alien": "true if the taxpayer is a nonresident alien",
    "is_estate_trust_or_partnership": "true if the taxpayer is an estate, trust, common trust fund, or partnership",
}


# ===========================================================================
# Map: extract atoms from SARA narrative
# ===========================================================================

MAP_PROMPT_TEMPLATE = """You are extracting structured facts from a tax-case narrative.

The narrative describes a taxpayer's situation. Extract specific typed atoms
the adjudication engine needs to compute the §63 standard deduction.

ATOMS (extract only if explicitly stated or directly inferable; leave null otherwise):
{atom_descriptions}

NARRATIVE:
{narrative}

IMPORTANT EXTRACTION RULES:
- If the narrative says someone "files a joint return", set files_joint_return=true.
- If the narrative says someone "is married" or "is a married individual",
  set is_married_status_for_section_7703=true. This is independent of whether they
  file jointly or separately.
- If the narrative says "Alice and Bob file separate returns" and they're married,
  set files_married_separately=true and is_married_status_for_section_7703=true.
- Boolean atoms default to null (UND), not false, when not stated.
- If the narrative does not mention age, blindness, dependent status, etc., leave
  those atoms as null. Do not assume defaults.

OUTPUT INSTRUCTIONS:
Return ONLY a JSON object mapping atom names to values. Use numbers for numeric
atoms, true/false for Booleans, null for unknowns. No preamble or commentary.
"""


def call_map_llm(narrative, model="claude-haiku-4-5-20251001"):
    """Call the LLM to extract atoms from a narrative."""
    from rulekit.build.decomposer import LLMCaller
    
    atoms_text = "\n".join(
        f"  - {name}: {desc}" for name, desc in ATOM_DESCRIPTIONS.items()
    )
    prompt = MAP_PROMPT_TEMPLATE.format(
        atom_descriptions=atoms_text,
        narrative=narrative,
    )
    
    llm = LLMCaller(model=model)
    t0 = time.time()
    response = llm.call(f"sara_s63_map_{int(time.time()*1000)}", prompt)
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


def build_fact_bundle(atoms_dict):
    """Convert atom dict from Map to a typed FactBundle, handling missing atoms."""
    values = {}
    for name in ATOM_DESCRIPTIONS:
        val = atoms_dict.get(name)
        if val is None:
            # Use UND for missing atoms — engine handles propagation
            if name == "earned_income" or name == "taxable_year":
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
# Sanity-check the DAG with a few synthetic cases
# ===========================================================================

def run_dag_sanity_checks():
    """Verify the full DAG produces correct outputs on hand-crafted inputs."""
    dag = build_full_s63_standard_deduction_dag()
    
    test_cases = [
        # Case 1: Joint return, 2017 (pre-2018), no special amounts
        # Expected: $6,000 basic + $0 additional = $6,000
        {
            "label": "joint 2017, no extras",
            "atoms": {
                "taxable_year": 2017,
                "files_joint_return": True,
                "is_surviving_spouse": False,
                "is_head_of_household": False,
                "files_married_separately": False,
                "is_married_status_for_section_7703": True,
                "taxpayer_attained_age_65": False,
                "spouse_attained_age_65": False,
                "spouse_151_exemption_allowable": False,
                "taxpayer_is_blind": False,
                "spouse_is_blind": False,
                "taxpayer_is_dependent_of_another": False,
                "earned_income": 0,
                "spouse_itemizes_deductions": False,
                "is_nonresident_alien": False,
                "is_estate_trust_or_partnership": False,
            },
            "expected": Decimal("6000"),
        },
        # Case 2: Single 2017, age 65+, blind. Expected: $3000 + $750 + $750 = $4500
        {
            "label": "single 2017, age 65+ and blind",
            "atoms": {
                "taxable_year": 2017,
                "files_joint_return": False,
                "is_surviving_spouse": False,
                "is_head_of_household": False,
                "files_married_separately": False,
                "is_married_status_for_section_7703": False,
                "taxpayer_attained_age_65": True,
                "spouse_attained_age_65": False,
                "spouse_151_exemption_allowable": False,
                "taxpayer_is_blind": True,
                "spouse_is_blind": False,
                "taxpayer_is_dependent_of_another": False,
                "earned_income": 0,
                "spouse_itemizes_deductions": False,
                "is_nonresident_alien": False,
                "is_estate_trust_or_partnership": False,
            },
            "expected": Decimal("4500"),
        },
        # Case 3: Single 2020 (2018-2025), no extras. Expected: $12,000
        {
            "label": "single 2020, no extras",
            "atoms": {
                "taxable_year": 2020,
                "files_joint_return": False,
                "is_surviving_spouse": False,
                "is_head_of_household": False,
                "files_married_separately": False,
                "is_married_status_for_section_7703": False,
                "taxpayer_attained_age_65": False,
                "spouse_attained_age_65": False,
                "spouse_151_exemption_allowable": False,
                "taxpayer_is_blind": False,
                "spouse_is_blind": False,
                "taxpayer_is_dependent_of_another": False,
                "earned_income": 0,
                "spouse_itemizes_deductions": False,
                "is_nonresident_alien": False,
                "is_estate_trust_or_partnership": False,
            },
            "expected": Decimal("12000"),
        },
        # Case 4: Dependent in 2017, earned $1000. basic capped at max(500, 250+1000)=1250.
        # Expected: $1,250
        {
            "label": "dependent 2017 with $1000 earned",
            "atoms": {
                "taxable_year": 2017,
                "files_joint_return": False,
                "is_surviving_spouse": False,
                "is_head_of_household": False,
                "files_married_separately": False,
                "is_married_status_for_section_7703": False,
                "taxpayer_attained_age_65": False,
                "spouse_attained_age_65": False,
                "spouse_151_exemption_allowable": False,
                "taxpayer_is_blind": False,
                "spouse_is_blind": False,
                "taxpayer_is_dependent_of_another": True,
                "earned_income": 1000,
                "spouse_itemizes_deductions": False,
                "is_nonresident_alien": False,
                "is_estate_trust_or_partnership": False,
            },
            "expected": Decimal("1250"),
        },
        # Case 5: MFS where spouse itemizes. Expected: $0 (ineligibility)
        {
            "label": "MFS where spouse itemizes",
            "atoms": {
                "taxable_year": 2017,
                "files_joint_return": False,
                "is_surviving_spouse": False,
                "is_head_of_household": False,
                "files_married_separately": True,
                "is_married_status_for_section_7703": True,
                "taxpayer_attained_age_65": False,
                "spouse_attained_age_65": False,
                "spouse_151_exemption_allowable": False,
                "taxpayer_is_blind": False,
                "spouse_is_blind": False,
                "taxpayer_is_dependent_of_another": False,
                "earned_income": 0,
                "spouse_itemizes_deductions": True,
                "is_nonresident_alien": False,
                "is_estate_trust_or_partnership": False,
            },
            "expected": Decimal("0"),
        },
    ]
    
    print("=" * 70)
    print("DAG SANITY CHECKS")
    print("=" * 70)
    all_pass = True
    for tc in test_cases:
        bundle = build_fact_bundle(tc["atoms"])
        result = dag.evaluate(bundle, [])
        ok = result.value == tc["expected"]
        status = "✓" if ok else "✗"
        print(f"  {status} {tc['label']}: got {result.value}, expected {tc['expected']}")
        if not ok:
            all_pass = False
    print()
    return all_pass


# ===========================================================================
# SARA evaluation
# ===========================================================================

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cases-dir",
                   default="/mnt/user-data/uploads",
                   help="Directory containing SARA case JSON files")
    p.add_argument("--cases", nargs="+", default=None,
                   help="Specific case IDs to test (default: §63 cases)")
    p.add_argument("--map-model", default="claude-haiku-4-5-20251001")
    p.add_argument("--skip-sanity", action="store_true")
    args = p.parse_args()
    
    # First run sanity checks on the DAG itself
    if not args.skip_sanity:
        sanity_ok = run_dag_sanity_checks()
        if not sanity_ok:
            print("DAG SANITY CHECKS FAILED — fix DAG before running SARA cases")
            sys.exit(1)
        print("All DAG sanity checks pass. Proceeding to SARA evaluation.")
        print()
    
    # Find SARA §63 cases
    cases_dir = Path(args.cases_dir)
    if not cases_dir.exists():
        print(f"Cases directory {cases_dir} does not exist")
        sys.exit(1)
    
    # Look for any §63 case that asks about computed standard deduction.
    # Some §63 SARA cases ask about derived facts (e.g., §63(d)(2) is about
    # whether a deduction *falls under* §63(d)(2)) — those don't test our
    # full DAG. We focus on cases asserting computed deduction amounts.
    
    # Find all §63 cases — we'll filter to ones our DAG can adjudicate
    s63_cases = sorted([
        f for f in cases_dir.glob("SARA-S63-*.json")
    ])
    
    if args.cases:
        s63_cases = [f for f in s63_cases if f.stem in args.cases]
    
    if not s63_cases:
        print(f"No §63 cases found in {cases_dir}")
        sys.exit(1)
    
    print(f"Found {len(s63_cases)} §63 case files")
    print()
    
    dag = build_full_s63_standard_deduction_dag()
    
    results = []
    
    for case_path in s63_cases:
        with open(case_path, encoding="utf-8") as f:
            case_data = json.load(f)
        case_id = case_data["case_id"]
        narrative = case_data["case_narrative"]
        question = case_data["question_text"]
        ground_truth = case_data["ground_truth"]
        
        print("=" * 70)
        print(f"Case: {case_id}")
        print(f"Narrative: {narrative[:200]}")
        print(f"Question: {question}")
        print(f"Ground truth: {ground_truth}")
        print()
        
        # Extract the asserted dollar amount from the question, if any
        amount_match = re.search(r"\$?([\d,]+(?:\.\d+)?)", question)
        asserted_amount = None
        if amount_match:
            try:
                asserted_amount = Decimal(amount_match.group(1).replace(",", ""))
            except:
                pass
        
        # Map atoms
        print("Map (extracting atoms)...")
        try:
            atoms, map_elapsed = call_map_llm(narrative, model=args.map_model)
        except Exception as e:
            print(f"  MAP ERROR: {e}")
            results.append({"case_id": case_id, "status": "map_error", "error": str(e)})
            continue
        print(f"  Map latency: {map_elapsed:.2f}s")
        # Show non-null atoms
        non_null = {k: v for k, v in atoms.items() if v is not None}
        print(f"  Non-null atoms: {non_null}")
        
        # Engine evaluation
        bundle = build_fact_bundle(atoms)
        t0 = time.time()
        try:
            result = dag.evaluate(bundle, [])
            engine_elapsed = (time.time() - t0) * 1000
        except Exception as e:
            print(f"  ENGINE ERROR: {e}")
            results.append({
                "case_id": case_id, "status": "engine_error",
                "error": str(e), "atoms": atoms,
            })
            continue
        
        print(f"  Engine latency: {engine_elapsed:.2f}ms")
        print(f"  Engine result: {result}")
        
        # Adjudicate
        if isinstance(result, NumericValue) and result.is_undetermined:
            disposition = "UND (insufficient atoms)"
        elif asserted_amount is None:
            disposition = f"UND (no amount in question to compare)"
        else:
            # Compare engine result to asserted amount
            engine_value = result.value
            matches = abs(engine_value - asserted_amount) <= Decimal("1")
            disposition = "Entailment" if matches else "Contradiction"
        
        if disposition == ground_truth:
            outcome = "CORRECT"
        elif disposition.startswith("UND"):
            outcome = "UND (no claim made)"
        else:
            outcome = "WRONG"
        
        print(f"  Disposition: {disposition} | Ground truth: {ground_truth} | {outcome}")
        print()
        
        results.append({
            "case_id": case_id,
            "status": "completed",
            "narrative": narrative,
            "question": question,
            "ground_truth": ground_truth,
            "asserted_amount": str(asserted_amount) if asserted_amount else None,
            "engine_result": str(result),
            "disposition": disposition,
            "outcome": outcome,
            "map_latency_s": map_elapsed,
            "engine_latency_ms": engine_elapsed,
            "atoms_extracted": atoms,
        })
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    completed = [r for r in results if r["status"] == "completed"]
    correct = [r for r in completed if r["outcome"] == "CORRECT"]
    und = [r for r in completed if r["outcome"].startswith("UND")]
    wrong = [r for r in completed if r["outcome"] == "WRONG"]
    
    print(f"Cases attempted: {len(results)}")
    print(f"Cases completed (no error): {len(completed)}")
    print(f"  Correct: {len(correct)}")
    print(f"  UND (honest non-answer): {len(und)}")
    print(f"  Wrong: {len(wrong)}")
    print()
    if completed:
        print(f"  Accuracy on cases with claims: "
              f"{len(correct)} / {len(correct) + len(wrong)} "
              f"({100*len(correct)/max(1, len(correct)+len(wrong)):.0f}%)")
        print(f"  Including UND in denominator: "
              f"{len(correct)} / {len(completed)} "
              f"({100*len(correct)/len(completed):.0f}%)")
        
        latencies = [r["map_latency_s"] for r in completed]
        print(f"\n  Map latency: min={min(latencies):.2f}s, "
              f"max={max(latencies):.2f}s, "
              f"mean={sum(latencies)/len(latencies):.2f}s")
    
    out_path = "audits/sara_s63_full/results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

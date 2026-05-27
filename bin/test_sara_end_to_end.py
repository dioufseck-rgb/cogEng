"""
test_sara_end_to_end.py - end-to-end validation of the architecture on
SARA tax cases.

This test bypasses Phase 2 (clustering) by hand-building the engine DAG
for each SARA section. It tests:
  - Engine evaluation correctness on real tax-law structure
  - Map extraction from SARA-style narratives
  - End-to-end accuracy vs. SARA ground truth
  - Per-case latency breakdown

The DAGs are hand-built to answer specific SARA assertions (subsection-
level questions like "does §63(c)(1) give $4000 here?").

Sections covered:
  - §1(a) tax brackets for married filing jointly
  - §63(c)(1) standard deduction = basic + additional
  - §63(c)(2)(C) basic standard deduction "any other case"
  - §63(d)(2) itemized deductions excluding §151 personal exemptions

Cost: ~$0.50-$2 for Map calls on 4-5 cases.

Usage:
    python bin/test_sara_end_to_end.py
    python bin/test_sara_end_to_end.py --cases SARA-S1-A-1-POS
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
    ConditionalNumericNode,
    LtNode, GtNode, LeqNode, GeqNode, EqNode,
    PlusNode, MinusNode, TimesConstNode, SumNode, MaxNode,
)
from rulekit.engine.boolean import Leaf, AndNode, OrNode, NotNode


# ===========================================================================
# DAG DEFINITIONS - hand-built engine structures for specific SARA sections
# ===========================================================================

def build_s1_a_dag():
    """§1(a): Married individuals filing joint returns and surviving spouses.
    
    Tax determined in 5 brackets:
      (i)   15% of TI if TI <= $36,900
      (ii)  $5,535 + 28% of (TI - $36,900) if $36,900 < TI <= $89,150
      (iii) $20,165 + 31% of (TI - $89,150) if $89,150 < TI <= $140,000
      (iv)  $35,928.50 + 36% of (TI - $140,000) if $140,000 < TI <= $250,000
      (v)   $75,528.50 + 39.6% of (TI - $250,000) if TI > $250,000
    
    Atom needed: taxable_income (a numeric)
    Output: tax amount (a numeric)
    
    Build a nested ConditionalNumericNode tree:
    
        if TI <= 36900: 0.15 * TI
        else if TI <= 89150: 5535 + 0.28 * (TI - 36900)
        else if TI <= 140000: 20165 + 0.31 * (TI - 89150)
        else if TI <= 250000: 35928.50 + 0.36 * (TI - 140000)
        else: 75528.50 + 0.396 * (TI - 250000)
    """
    ti = NumericLeaf(atom_id="taxable_income")
    
    # Bracket 1: 0.15 * TI
    bracket_1 = TimesConstNode(
        child=ti,
        constant=Decimal("0.15"),
    )
    
    # Bracket 2: 5535 + 0.28 * (TI - 36900)
    bracket_2 = PlusNode(
        left=Constant(label="b2_base", value=Decimal("5535")),
        right=TimesConstNode(
            child=MinusNode(
                left=ti,
                right=Constant(label="b1_top", value=Decimal("36900")),
            ),
            constant=Decimal("0.28"),
        ),
    )
    
    # Bracket 3: 20165 + 0.31 * (TI - 89150)
    bracket_3 = PlusNode(
        left=Constant(label="b3_base", value=Decimal("20165")),
        right=TimesConstNode(
            child=MinusNode(
                left=ti,
                right=Constant(label="b2_top", value=Decimal("89150")),
            ),
            constant=Decimal("0.31"),
        ),
    )
    
    # Bracket 4: 35928.50 + 0.36 * (TI - 140000)
    bracket_4 = PlusNode(
        left=Constant(label="b4_base", value=Decimal("35928.50")),
        right=TimesConstNode(
            child=MinusNode(
                left=ti,
                right=Constant(label="b3_top", value=Decimal("140000")),
            ),
            constant=Decimal("0.36"),
        ),
    )
    
    # Bracket 5: 75528.50 + 0.396 * (TI - 250000)
    bracket_5 = PlusNode(
        left=Constant(label="b5_base", value=Decimal("75528.50")),
        right=TimesConstNode(
            child=MinusNode(
                left=ti,
                right=Constant(label="b4_top", value=Decimal("250000")),
            ),
            constant=Decimal("0.396"),
        ),
    )
    
    # Conditional chain:
    # if TI <= 36900 -> bracket_1
    # else if TI <= 89150 -> bracket_2
    # else if TI <= 140000 -> bracket_3
    # else if TI <= 250000 -> bracket_4
    # else -> bracket_5
    
    in_bracket_4_or_lower = LeqNode(
        left=ti,
        right=Constant(label="b4_top", value=Decimal("250000")),
    )
    bracket_4_or_5 = ConditionalNumericNode(
        condition=in_bracket_4_or_lower,
        if_true=bracket_4,
        if_false=bracket_5,
        surface_label="bracket_4_vs_5",
    )
    
    in_bracket_3_or_lower = LeqNode(
        left=ti,
        right=Constant(label="b3_top", value=Decimal("140000")),
    )
    bracket_3_or_higher = ConditionalNumericNode(
        condition=in_bracket_3_or_lower,
        if_true=bracket_3,
        if_false=bracket_4_or_5,
        surface_label="bracket_3_vs_higher",
    )
    
    in_bracket_2_or_lower = LeqNode(
        left=ti,
        right=Constant(label="b2_top", value=Decimal("89150")),
    )
    bracket_2_or_higher = ConditionalNumericNode(
        condition=in_bracket_2_or_lower,
        if_true=bracket_2,
        if_false=bracket_3_or_higher,
        surface_label="bracket_2_vs_higher",
    )
    
    in_bracket_1 = LeqNode(
        left=ti,
        right=Constant(label="b1_top", value=Decimal("36900")),
    )
    root = ConditionalNumericNode(
        condition=in_bracket_1,
        if_true=bracket_1,
        if_false=bracket_2_or_higher,
        surface_label="s1_a_tax_amount",
    )
    
    return root


def build_s63_c_1_dag():
    """§63(c)(1): standard deduction = basic + additional.
    
    Atoms: basic_standard_deduction, additional_standard_deduction
    Output: standard deduction amount
    """
    return PlusNode(
        left=NumericLeaf(atom_id="basic_standard_deduction"),
        right=NumericLeaf(atom_id="additional_standard_deduction"),
    )


def build_s63_c_2_C_dag():
    """§63(c)(2)(C): basic standard deduction for "any other case".
    
    Returns $3,000 for taxable years before 2018, or $12,000 for 2018-2025.
    
    Atoms: taxable_year
    Output: basic standard deduction amount
    """
    year = NumericLeaf(atom_id="taxable_year")
    
    # If taxable_year >= 2018 AND taxable_year <= 2025: $12,000
    # Otherwise: $3,000
    is_after_2017 = GeqNode(
        left=year,
        right=Constant(label="year_2018", value=Decimal("2018")),
    )
    is_before_2026 = LeqNode(
        left=year,
        right=Constant(label="year_2025", value=Decimal("2025")),
    )
    in_special_period = AndNode(children=[is_after_2017, is_before_2026])
    
    return ConditionalNumericNode(
        condition=in_special_period,
        if_true=Constant(label="s63_c_2_C_special", value=Decimal("12000")),
        if_false=Constant(label="s63_c_2_C_general", value=Decimal("3000")),
        surface_label="s63_c_2_C_amount",
    )


def build_s63_d_2_dag():
    """§63(d)(2): Does this deduction fall under §63(d)(2)?
    
    §63(d) defines "itemized deductions" as deductions allowable under this
    chapter OTHER THAN:
      (1) deductions in arriving at AGI
      (2) the deduction for personal exemptions provided by §151
    
    So §63(d)(2) characterizes a deduction as the §151 personal exemption
    deduction. Question: is the deduction in question a §151 deduction?
    
    This is a Boolean — does this specific deduction match the §63(d)(2)
    pattern (i.e., is it a §151 personal exemption deduction)?
    
    Atom: deduction_is_section_151 (a Boolean)
    Output: TRUE iff the deduction falls under §63(d)(2)
    """
    return Leaf(atom_id="deduction_is_section_151")


# ===========================================================================
# MAP - extract atoms from SARA narratives
# ===========================================================================

MAP_PROMPT_TEMPLATE = """You are extracting structured facts from a tax-case narrative.

The narrative describes a taxpayer's situation. Your job is to extract specific
typed atoms that the adjudication engine needs.

ATOMS TO EXTRACT (only extract ones explicitly stated in the narrative):
{atom_descriptions}

NARRATIVE:
{narrative}

OUTPUT INSTRUCTIONS:
Return ONLY a JSON object mapping atom names to values. Use:
  - Numbers (not strings) for numeric atoms (e.g., 17330, not "$17,330")
  - true/false for Boolean atoms
  - null for atoms the narrative does not state

Do not include any preamble or explanation. Output only the JSON object.

Example output format:
{{"atom_name_1": 12345, "atom_name_2": true, "atom_name_3": null}}
"""


def call_map_llm(narrative, atom_descriptions, model="claude-haiku-4-5-20251001"):
    """Call the LLM to extract atoms from a narrative."""
    from rulekit.build.decomposer import LLMCaller
    
    atoms_text = "\n".join(
        f"  - {name}: {desc}" for name, desc in atom_descriptions.items()
    )
    prompt = MAP_PROMPT_TEMPLATE.format(
        atom_descriptions=atoms_text,
        narrative=narrative,
    )
    
    llm = LLMCaller(model=model)
    t0 = time.time()
    response = llm.call(f"sara_map_{int(time.time()*1000)}", prompt)
    elapsed = time.time() - t0
    
    # Parse JSON from response
    import re
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
        cleaned = re.sub(r"\n```\s*$", "", cleaned)
    try:
        atoms = json.loads(cleaned)
    except json.JSONDecodeError:
        # Find first JSON object in response
        match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if match:
            atoms = json.loads(match.group(0))
        else:
            atoms = {}
    
    return atoms, elapsed


def build_fact_bundle(atoms_dict):
    """Convert atom dict from Map to a typed FactBundle."""
    values = {}
    for name, val in atoms_dict.items():
        if val is None:
            values[name] = NumericValue.undetermined()
        elif isinstance(val, bool):
            values[name] = Kleene.TRUE if val else Kleene.FALSE
        elif isinstance(val, (int, float)):
            values[name] = NumericValue(value=Decimal(str(val)))
        elif isinstance(val, str):
            # Try to parse as number first
            try:
                values[name] = NumericValue(value=Decimal(val.replace(",", "").replace("$", "")))
            except:
                # Treat as Boolean true if non-empty
                values[name] = Kleene.TRUE if val else Kleene.FALSE
        else:
            values[name] = NumericValue.undetermined()
    return FactBundle(values=values)


# ===========================================================================
# CASE DEFINITIONS - which DAG handles which SARA case, what atoms to extract
# ===========================================================================

CASES = {
    "SARA-S1-A-1-POS": {
        "section": "s1_a",
        "dag_builder": build_s1_a_dag,
        "atom_descriptions": {
            "taxable_income": "the joint taxable income for the year, as a number in dollars",
        },
        "expected_value_test": lambda result: abs(result - Decimal("2600")) <= Decimal("1"),
        # Claim: tax is $2600. Engine should produce ~$2599.50 for TI=$17330.
        "expected_ground_truth": "Entailment",
    },
    "SARA-S63-C-1-NEG": {
        "section": "s63_c_1",
        "dag_builder": build_s63_c_1_dag,
        "atom_descriptions": {
            "basic_standard_deduction": "the basic standard deduction amount in dollars",
            "additional_standard_deduction": "the additional standard deduction amount in dollars",
        },
        # Claim: standard deduction is $4000. Engine should produce $2000 + $3000 = $5000.
        "expected_value_test": lambda result: abs(result - Decimal("4000")) <= Decimal("1"),
        "expected_ground_truth": "Contradiction",
    },
    "SARA-S63-C-2-C-POS": {
        "section": "s63_c_2_C",
        "dag_builder": build_s63_c_2_C_dag,
        "atom_descriptions": {
            "taxable_year": "the taxable year as a 4-digit integer (e.g., 2017)",
        },
        # Claim: §63(c)(2)(C) basic standard deduction in 2017 is $3000. 
        # Engine should produce $3000 since 2017 < 2018.
        "expected_value_test": lambda result: abs(result - Decimal("3000")) <= Decimal("1"),
        "expected_ground_truth": "Entailment",
    },
    "SARA-S63-D-2-POS": {
        "section": "s63_d_2",
        "dag_builder": build_s63_d_2_dag,
        "atom_descriptions": {
            "deduction_is_section_151": "true if the deduction is the personal exemption deduction under section 151, false otherwise",
        },
        # Claim: deduction falls under §63(d)(2). Engine should produce TRUE 
        # since the deduction is explicitly a §151 personal exemption.
        "expected_value_test": lambda result: result == Kleene.TRUE,
        "expected_ground_truth": "Entailment",
    },
}


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cases-dir", default="../uploads",
                   help="Directory containing SARA case JSON files")
    p.add_argument("--cases", nargs="+", default=None,
                   help="Specific case IDs to test (default: all)")
    p.add_argument("--map-model", default="claude-haiku-4-5-20251001")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    
    # Find case files
    cases_dir = Path(args.cases_dir)
    if not cases_dir.is_absolute():
        # Try a few common locations
        for parent in [Path.cwd(), Path(_ROOT)]:
            candidate = parent / args.cases_dir
            if candidate.exists():
                cases_dir = candidate
                break
            candidate = parent.parent / "uploads"
            if candidate.exists():
                cases_dir = candidate
                break
        else:
            # Last resort: look in /mnt/user-data/uploads
            if Path("/mnt/user-data/uploads").exists():
                cases_dir = Path("/mnt/user-data/uploads")
    
    print(f"Looking for cases in: {cases_dir}")
    
    # Load case files
    case_files = {}
    for case_id in CASES:
        if args.cases and case_id not in args.cases:
            continue
        case_path = cases_dir / f"{case_id}.json"
        if not case_path.exists():
            print(f"  WARNING: {case_path} not found")
            continue
        with open(case_path, encoding="utf-8") as f:
            case_files[case_id] = json.load(f)
    
    if not case_files:
        print("No case files found. Check --cases-dir.")
        sys.exit(1)
    
    print(f"Loaded {len(case_files)} case files")
    print()
    
    results = []
    
    for case_id, case_data in case_files.items():
        print("=" * 70)
        print(f"Case: {case_id}")
        print("=" * 70)
        
        config = CASES[case_id]
        narrative = case_data["case_narrative"]
        question = case_data["question_text"]
        ground_truth = case_data["ground_truth"]
        
        print(f"Narrative: {narrative}")
        print(f"Question: {question}")
        print(f"Ground truth: {ground_truth}")
        print()
        
        # ---- Map: extract atoms ----
        print("Map (extracting atoms)...")
        try:
            atoms, map_elapsed = call_map_llm(
                narrative,
                config["atom_descriptions"],
                model=args.map_model,
            )
            print(f"  Map latency: {map_elapsed:.2f}s")
            print(f"  Extracted atoms: {atoms}")
        except Exception as e:
            print(f"  MAP ERROR: {e}")
            results.append({
                "case_id": case_id,
                "status": "map_error",
                "error": str(e),
            })
            continue
        
        # ---- Engine: build DAG and evaluate ----
        bundle = build_fact_bundle(atoms)
        dag = config["dag_builder"]()
        
        print("Engine (evaluating DAG)...")
        trace = []
        t0 = time.time()
        try:
            result = dag.evaluate(bundle, trace)
            engine_elapsed = time.time() - t0
            print(f"  Engine latency: {engine_elapsed*1000:.2f}ms")
            print(f"  Engine result: {result}")
        except Exception as e:
            print(f"  ENGINE ERROR: {e}")
            results.append({
                "case_id": case_id,
                "status": "engine_error",
                "error": str(e),
                "atoms_extracted": atoms,
            })
            continue
        
        # ---- Adjudicate: does engine result match the claim in the question? ----
        # The architecture's disposition:
        #   - TRUE iff engine result matches claim (Entailment expected)
        #   - FALSE iff engine result definitively does not match claim (Contradiction expected)
        #   - UND iff engine returned UND (some atom missing)
        
        if isinstance(result, NumericValue) and result.is_undetermined:
            disposition = "UND"
        elif isinstance(result, Kleene) and result == Kleene.UNDETERMINED:
            disposition = "UND"
        else:
            # Check if result matches the claim
            try:
                matches = config["expected_value_test"](
                    result.value if isinstance(result, NumericValue) else result
                )
                disposition = "Entailment" if matches else "Contradiction"
            except Exception as e:
                disposition = f"adjudication_error: {e}"
        
        # ---- Score ----
        correct = (disposition == ground_truth)
        print()
        print(f"Disposition: {disposition}")
        print(f"Ground truth: {ground_truth}")
        print(f"Correct: {'YES' if correct else 'NO'}")
        print()
        
        results.append({
            "case_id": case_id,
            "status": "completed",
            "narrative": narrative,
            "question": question,
            "ground_truth": ground_truth,
            "atoms_extracted": atoms,
            "engine_result": str(result),
            "disposition": disposition,
            "correct": correct,
            "map_latency_s": map_elapsed,
            "engine_latency_ms": engine_elapsed * 1000,
        })
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    completed = [r for r in results if r.get("status") == "completed"]
    correct = [r for r in completed if r["correct"]]
    print(f"Cases attempted: {len(results)}")
    print(f"Cases completed (no error): {len(completed)}")
    print(f"Correct dispositions: {len(correct)} / {len(completed)} "
          f"({100*len(correct)/max(1,len(completed)):.0f}%)")
    
    if completed:
        map_latencies = [r["map_latency_s"] for r in completed]
        engine_latencies = [r["engine_latency_ms"] for r in completed]
        print()
        print(f"Map latency: min={min(map_latencies):.2f}s, "
              f"max={max(map_latencies):.2f}s, "
              f"mean={sum(map_latencies)/len(map_latencies):.2f}s")
        print(f"Engine latency: min={min(engine_latencies):.2f}ms, "
              f"max={max(engine_latencies):.2f}ms, "
              f"mean={sum(engine_latencies)/len(engine_latencies):.2f}ms")
        print()
        print(f"Total per-case latency ≈ {sum(map_latencies)/len(map_latencies):.2f}s "
              f"(dominated by Map; engine is negligible)")
    
    # Save results
    out_path = "audits/sara_end_to_end/results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print()
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()

"""
nba_live_demo.py — end-to-end demo of typed Map + MLE fragment on a real
RuleArena NBA case.

WHAT IT DOES
============
1. Loads one annotated case from RuleArena's NBA Level 1 bank
2. Constructs evidence text from the case's team_situations + player_situations + operations
3. Defines a typed atom inventory that matches what the MLE-selection fragment expects
4. Calls TypedNarrativeLLMSubstrate against a real Anthropic LLM to bind the atoms
5. Evaluates op_permitted_via_some_mle against the resulting FactBundle
6. Compares to ground truth and prints the trace

USAGE
=====
    export ANTHROPIC_API_KEY=sk-ant-...
    python bin/nba_live_demo.py --case-file ../RuleArena/nba/annotated_problems/comp_0.json --case-idx 14

REQUIREMENTS
============
The Anthropic Python SDK (`pip install anthropic`) and a valid API key.
This is a SINGLE-CASE DEMO; it isn't a full benchmark harness. The goal
is to confirm that real LLM extraction produces correct numeric values
for the typed engine to reason over.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from rulekit.engine import Kleene, FactBundle, format_typed_trace
from rulekit.engine.typed import NumericValue, AtomType
from rulekit.schema import Atom
from rulekit.map.typed import TypedAtom, TypedNarrativeLLMSubstrate
from rulekit.build.decomposer import LLMCaller

from domains.nba.fragments import mle_selection


# ---------------------------------------------------------------------------
# Atom inventory for the MLE fragment
# ---------------------------------------------------------------------------
#
# The MLE fragment expects three numeric atoms and one boolean atom:
#   - team_salary (numeric): the signing team's pre-operation salary
#   - contract_first_year_salary (numeric): first-year salary of the new contract
#   - contract_length_years (numeric): years on the contract
#   - op_uses_mle_class_exception (boolean): is the team using an MLE to sign?
#
# We define each atom with a precise, focused statement so Map's LLM call
# can extract them deterministically.

TYPED_ATOMS = {
    "team_salary": TypedAtom(
        Atom(
            id="team_salary",
            statement=(
                "The signing team's current team salary in US dollars. "
                "This is the team's salary BEFORE the operation in question. "
                "Extract the dollar amount as stated in the team situation. "
                "Return the bare number with no $ or commas."
            ),
            source_span="team_situations",
        ),
        AtomType.NUMERIC,
    ),
    "contract_first_year_salary": TypedAtom(
        Atom(
            id="contract_first_year_salary",
            statement=(
                "The annual salary in the FIRST Salary Cap Year of the new contract "
                "being signed in the operation. In US dollars. "
                "Return the bare number with no $ or commas."
            ),
            source_span="operations",
        ),
        AtomType.NUMERIC,
    ),
    "contract_length_years": TypedAtom(
        Atom(
            id="contract_length_years",
            statement=(
                "The total number of seasons (years) the new contract covers. "
                "Return a bare integer. E.g., a '3-year contract' yields 3."
            ),
            source_span="operations",
        ),
        AtomType.NUMERIC,
    ),
    "op_uses_mle_class_exception": TypedAtom(
        Atom(
            id="op_uses_mle_class_exception",
            statement=(
                "TRUE if the operation involves the signing team using a "
                "Mid-Level Exception (MLE) — Non-Taxpayer MLE, Taxpayer MLE, "
                "or Room MLE — to sign the player. This is the case when the "
                "team's salary is at/over the salary cap OR the team is using "
                "a sub-cap exception slot, and is signing a free agent. "
                "FALSE if the team has Room directly under the cap and is not "
                "using any exception. UNDETERMINED only if the case truly "
                "doesn't say whether an exception is being used."
            ),
            source_span="inferred from team_salary and operations",
        ),
        AtomType.BOOLEAN,
    ),
}


# ---------------------------------------------------------------------------
# Case loading
# ---------------------------------------------------------------------------

def construct_evidence(case: dict) -> str:
    """Build the natural-language case description that Map will read."""
    parts = []
    parts.append("TEAM SITUATIONS:")
    for line in case["team_situations"]:
        parts.append(f"  - {line}")
    parts.append("")
    parts.append("PLAYER SITUATIONS:")
    for line in case["player_situations"]:
        parts.append(f"  - {line}")
    parts.append("")
    parts.append("OPERATION(S):")
    for op in case["operations"]:
        parts.append(f"  {op}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run typed Map + MLE fragment on a single RuleArena NBA case."
    )
    parser.add_argument("--case-file", required=True,
                        help="Path to RuleArena annotated_problems/comp_N.json")
    parser.add_argument("--case-idx", type=int, required=True,
                        help="Index of the case within the file")
    parser.add_argument("--model", default="claude-opus-4-7",
                        help="Anthropic model id (default: claude-opus-4-7)")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        # The Anthropic SDK also accepts CLAUDE_API_KEY in some setups
        if not os.environ.get("CLAUDE_API_KEY"):
            print("ERROR: set ANTHROPIC_API_KEY (or CLAUDE_API_KEY) in your environment.")
            sys.exit(2)
        os.environ["ANTHROPIC_API_KEY"] = os.environ["CLAUDE_API_KEY"]

    # Load the case
    cases = json.load(open(args.case_file))
    case = cases[args.case_idx]

    print("=" * 70)
    print(f"CASE {args.case_idx} from {args.case_file}")
    print("=" * 70)
    evidence = construct_evidence(case)
    print(evidence)
    print()
    print(f"Ground truth: answer={case['answer']}, "
          f"illegal_op={case.get('illegal_operation')}, "
          f"problematic_team={case.get('problematic_team')}")
    print(f"Relevant rules: {case.get('relevant_rules', [])[:5]}")
    print()

    # Build the LLM caller and substrate
    llm = LLMCaller(model=args.model)
    substrate = TypedNarrativeLLMSubstrate(llm=llm)

    # Bind atoms via live LLM
    print("=" * 70)
    print(f"Calling typed substrate (model={args.model}) to bind atoms...")
    print("=" * 70)
    bundle = substrate.bind_typed(evidence, TYPED_ATOMS)

    print("\nBound atoms:")
    for atom_id in TYPED_ATOMS:
        v = bundle.values.get(atom_id, "<missing>")
        print(f"  {atom_id} = {v}")
    print()

    # Build the MLE fragment and evaluate
    print("=" * 70)
    print("Evaluating MLE fragment against the bundle...")
    print("=" * 70)
    fragment = mle_selection.build_fragment()

    top = fragment["op_permitted_via_some_mle"]
    trace = []
    result = top.evaluate(bundle, trace)

    print("\nFragment trace:")
    print(format_typed_trace(trace))
    print()

    # Interpret the result against ground truth
    print("=" * 70)
    print("DISPOSITION")
    print("=" * 70)
    # Ground truth: case["answer"] is True when an operation is illegal
    # Our fragment reports op_permitted_via_some_mle = TRUE/FALSE/UND
    fragment_says_legal_via_mle = (result == Kleene.TRUE)
    ground_truth_illegal = case["answer"]
    print(f"  Fragment: op_permitted_via_some_mle = {result}")
    print(f"  Interpretation: operation is "
          f"{'PERMITTED' if fragment_says_legal_via_mle else 'NOT PERMITTED via MLE'}")
    print(f"  Ground truth: operation is "
          f"{'ILLEGAL' if ground_truth_illegal else 'LEGAL'}")
    print()
    if ground_truth_illegal and not fragment_says_legal_via_mle:
        print("  ✓ Architecture correctly identifies the operation as not permitted.")
    elif (not ground_truth_illegal) and fragment_says_legal_via_mle:
        print("  ✓ Architecture correctly identifies the operation as permitted.")
    elif result == Kleene.UNDETERMINED:
        print("  ⊘ Architecture returns UNDETERMINED — needs more case evidence "
              "or additional atoms.")
    else:
        print("  ✗ Mismatch with ground truth — check Map's atom bindings above.")


if __name__ == "__main__":
    main()

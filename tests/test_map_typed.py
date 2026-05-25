"""
Tests for the typed Map substrate.

Approach: use a scripted LLM that returns fixed JSON responses to verify
the substrate's wiring (prompt construction, response parsing, type
dispatch). For end-to-end tests against real RuleArena cases, this would
be parameterized over a real LLMCaller, but we don't want to consume API
credits for unit tests.

Coverage:
1. Boolean-only typed atoms -- substrate routes correctly
2. Numeric-only typed atoms -- substrate extracts values correctly
3. Mixed typed atoms -- substrate handles both kinds
4. Missing atoms -- substrate fills in UNDETERMINED for both types
5. Malformed numeric responses (strings, dollar signs, commas) -- parser handles
6. End-to-end: typed substrate output flows through typed engine correctly
"""

from __future__ import annotations

import json
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rulekit.engine import Kleene, FactBundle, AndNode, Leaf
from rulekit.engine.typed import (
    NumericValue, AtomType,
    NumericLeaf, Constant, TimesConstNode, LeqNode,
    format_typed_trace,
)
from rulekit.schema import Atom
from rulekit.map.typed import (
    TypedAtom, TypedNarrativeLLMSubstrate,
    _parse_numeric,
)


_results = {"pass": 0, "fail": 0, "errors": []}


def check(name, condition, detail=""):
    if condition:
        _results["pass"] += 1
        print(f"  PASS  {name}")
    else:
        _results["fail"] += 1
        _results["errors"].append((name, detail))
        print(f"  FAIL  {name}  {detail}")


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ---------------------------------------------------------------------------
# Scripted LLM
# ---------------------------------------------------------------------------

class ScriptedLLM:
    """
    LLM that returns scripted responses based on the stage_name passed
    in. Captures all prompts for inspection.
    """

    def __init__(self, responses: dict):
        self.responses = responses
        self.prompts = []  # list of (stage_name, prompt)

    def call(self, stage_name: str, prompt: str) -> str:
        self.prompts.append((stage_name, prompt))
        if stage_name not in self.responses:
            raise KeyError(f"No scripted response for stage {stage_name!r}")
        return self.responses[stage_name]


# ---------------------------------------------------------------------------
# 1. Numeric parser
# ---------------------------------------------------------------------------

def test_numeric_parser():
    section("Numeric parser: handles malformed inputs gracefully")

    check("Parser: int 5000", _parse_numeric(5000).value == Decimal("5000"))
    check("Parser: float 5.5", _parse_numeric(5.5).value == Decimal("5.5"))
    check("Parser: str '5000'", _parse_numeric("5000").value == Decimal("5000"))
    check("Parser: str with dollar+commas '$5,150,000'",
          _parse_numeric("$5,150,000").value == Decimal("5150000"))
    check("Parser: 'undetermined' -> UND",
          _parse_numeric("undetermined").is_undetermined)
    check("Parser: empty string -> UND",
          _parse_numeric("").is_undetermined)
    check("Parser: None -> UND",
          _parse_numeric(None).is_undetermined)
    check("Parser: garbage 'about five million' -> UND",
          _parse_numeric("about five million").is_undetermined)
    # bool is technically an int in Python but a categorical value, not a
    # numeric quantity. The parser rejects it via Decimal('True') failing,
    # which is the right behavior -- a categorical signal shouldn't quietly
    # become 0 or 1 in a numeric atom.
    check("Parser: bool True -> UNDETERMINED (categorical, not numeric)",
          _parse_numeric(True).is_undetermined)


# ---------------------------------------------------------------------------
# 2. Substrate: Boolean-only
# ---------------------------------------------------------------------------

def test_substrate_boolean_only():
    section("Substrate: Boolean-only inventory")

    llm = ScriptedLLM(responses={
        "map_bind_boolean": json.dumps({
            "atom_a": "true",
            "atom_b": "false",
            "atom_c": "undetermined",
        }),
    })
    substrate = TypedNarrativeLLMSubstrate(llm=llm)

    typed_atoms = {
        "atom_a": TypedAtom(Atom(id="atom_a", statement="A holds",
                                  source_span=""), AtomType.BOOLEAN),
        "atom_b": TypedAtom(Atom(id="atom_b", statement="B holds",
                                  source_span=""), AtomType.BOOLEAN),
        "atom_c": TypedAtom(Atom(id="atom_c", statement="C holds",
                                  source_span=""), AtomType.BOOLEAN),
    }
    bundle = substrate.bind_typed("dummy evidence", typed_atoms)

    check("Boolean: atom_a = TRUE", bundle.values["atom_a"] == Kleene.TRUE)
    check("Boolean: atom_b = FALSE", bundle.values["atom_b"] == Kleene.FALSE)
    check("Boolean: atom_c = UND",
          bundle.values["atom_c"] == Kleene.UNDETERMINED)
    check("Boolean: only Boolean LLM call made",
          len(llm.prompts) == 1 and llm.prompts[0][0] == "map_bind_boolean")


# ---------------------------------------------------------------------------
# 3. Substrate: Numeric-only
# ---------------------------------------------------------------------------

def test_substrate_numeric_only():
    section("Substrate: Numeric-only inventory")

    llm = ScriptedLLM(responses={
        "map_bind_numeric": json.dumps({
            "team_salary": 158000000,
            "contract_first_year_salary": "$5,150,000",  # malformed but recoverable
            "player_age": 28,
            "unknown_atom": "undetermined",
        }),
    })
    substrate = TypedNarrativeLLMSubstrate(llm=llm)

    typed_atoms = {
        aid: TypedAtom(Atom(id=aid, statement=f"value of {aid}",
                            source_span=""), AtomType.NUMERIC)
        for aid in ["team_salary", "contract_first_year_salary",
                    "player_age", "unknown_atom"]
    }
    bundle = substrate.bind_typed("dummy evidence", typed_atoms)

    check("Numeric: team_salary = 158M",
          bundle.values["team_salary"].value == Decimal("158000000"))
    check("Numeric: contract_salary cleaned to 5.15M",
          bundle.values["contract_first_year_salary"].value
          == Decimal("5150000"))
    check("Numeric: player_age = 28",
          bundle.values["player_age"].value == Decimal("28"))
    check("Numeric: unknown -> UND",
          bundle.values["unknown_atom"].is_undetermined)
    check("Numeric: only Numeric LLM call made",
          len(llm.prompts) == 1 and llm.prompts[0][0] == "map_bind_numeric")


# ---------------------------------------------------------------------------
# 4. Substrate: Mixed
# ---------------------------------------------------------------------------

def test_substrate_mixed():
    section("Substrate: Mixed Boolean + Numeric")

    llm = ScriptedLLM(responses={
        "map_bind_boolean": json.dumps({
            "team_above_cap": "true",
            "player_is_veteran": "true",
        }),
        "map_bind_numeric": json.dumps({
            "team_salary": 158000000,
            "contract_salary": 8000000,
        }),
    })
    substrate = TypedNarrativeLLMSubstrate(llm=llm)

    typed_atoms = {
        "team_above_cap": TypedAtom(
            Atom(id="team_above_cap",
                 statement="team salary above cap", source_span=""),
            AtomType.BOOLEAN),
        "player_is_veteran": TypedAtom(
            Atom(id="player_is_veteran",
                 statement="player is veteran", source_span=""),
            AtomType.BOOLEAN),
        "team_salary": TypedAtom(
            Atom(id="team_salary",
                 statement="team's current salary in USD",
                 source_span=""),
            AtomType.NUMERIC),
        "contract_salary": TypedAtom(
            Atom(id="contract_salary",
                 statement="first-year salary of contract", source_span=""),
            AtomType.NUMERIC),
    }
    bundle = substrate.bind_typed("dummy evidence", typed_atoms)

    check("Mixed: team_above_cap is Kleene",
          bundle.values["team_above_cap"] == Kleene.TRUE)
    check("Mixed: team_salary is NumericValue",
          isinstance(bundle.values["team_salary"], NumericValue))
    check("Mixed: team_salary value correct",
          bundle.values["team_salary"].value == Decimal("158000000"))
    check("Mixed: contract_salary value correct",
          bundle.values["contract_salary"].value == Decimal("8000000"))
    check("Mixed: 2 LLM calls (one per type)",
          len(llm.prompts) == 2)
    stage_names = sorted(p[0] for p in llm.prompts)
    check("Mixed: both stages called",
          stage_names == ["map_bind_boolean", "map_bind_numeric"])


# ---------------------------------------------------------------------------
# 5. Substrate: Missing atoms get UNDETERMINED
# ---------------------------------------------------------------------------

def test_substrate_missing_atoms():
    section("Substrate: missing-atom defaulting")

    llm = ScriptedLLM(responses={
        "map_bind_boolean": json.dumps({"atom_a": "true"}),  # atom_b missing
        "map_bind_numeric": json.dumps({"num_a": 100}),       # num_b missing
    })
    substrate = TypedNarrativeLLMSubstrate(llm=llm)

    typed_atoms = {
        "atom_a": TypedAtom(Atom(id="atom_a", statement="A",
                                  source_span=""), AtomType.BOOLEAN),
        "atom_b": TypedAtom(Atom(id="atom_b", statement="B",
                                  source_span=""), AtomType.BOOLEAN),
        "num_a": TypedAtom(Atom(id="num_a", statement="num A",
                                 source_span=""), AtomType.NUMERIC),
        "num_b": TypedAtom(Atom(id="num_b", statement="num B",
                                 source_span=""), AtomType.NUMERIC),
    }
    bundle = substrate.bind_typed("evidence", typed_atoms)

    check("Missing: Boolean atom_b -> Kleene.UND",
          bundle.values["atom_b"] == Kleene.UNDETERMINED)
    check("Missing: Numeric num_b -> NumericValue.UND",
          isinstance(bundle.values["num_b"], NumericValue)
          and bundle.values["num_b"].is_undetermined)
    check("Missing: present atom_a still TRUE",
          bundle.values["atom_a"] == Kleene.TRUE)
    check("Missing: present num_a still 100",
          bundle.values["num_a"].value == Decimal("100"))


# ---------------------------------------------------------------------------
# 6. End-to-end: substrate output through typed engine
# ---------------------------------------------------------------------------

def test_end_to_end_substrate_to_engine():
    section("End-to-end: substrate output evaluates through typed engine")

    # Simulate a real RuleArena case 14-style scenario:
    #
    # "Team A has a team salary of $100,000,000." -> team_salary = 100M
    # "Team A signs a 3-year contract... annual salary $36,000,000..."
    #
    # Atoms:
    #   team_salary (numeric)
    #   contract_first_year_salary (numeric)
    #   op_uses_mle_class_exception (boolean) -- Map decides via narrative
    #
    # Engine evaluates: op_permitted_via_room_mle =
    #   team_salary < cap  AND  contract_salary <= 5.68% x cap
    #
    # For case 14: $36M > $7.985M, so FALSE.

    SALARY_CAP = Decimal("140588000")
    ROOM_MLE_PCT = Decimal("0.0568")

    llm = ScriptedLLM(responses={
        "map_bind_boolean": json.dumps({
            "op_uses_mle_class_exception": "true",
        }),
        "map_bind_numeric": json.dumps({
            "team_salary": "$100,000,000",
            "contract_first_year_salary": 36000000,
        }),
    })
    substrate = TypedNarrativeLLMSubstrate(llm=llm)

    typed_atoms = {
        "op_uses_mle_class_exception": TypedAtom(
            Atom(id="op_uses_mle_class_exception",
                 statement="operation uses an MLE-class exception",
                 source_span=""),
            AtomType.BOOLEAN),
        "team_salary": TypedAtom(
            Atom(id="team_salary",
                 statement="signing team's current salary in USD",
                 source_span=""),
            AtomType.NUMERIC),
        "contract_first_year_salary": TypedAtom(
            Atom(id="contract_first_year_salary",
                 statement="contract's first-year salary in USD",
                 source_span=""),
            AtomType.NUMERIC),
    }
    evidence = (
        "Team A has a team salary of $100,000,000. Team A signs a 3-year "
        "contract with Player B providing annual salary $36,000,000 in "
        "the first Salary Cap Year (2024-2025) and 5% increase per year."
    )
    bundle = substrate.bind_typed(evidence, typed_atoms)

    # Build the engine DAG: room MLE applies (team below cap), but salary
    # exceeds 5.68% x cap = $7,985,398.40
    team_salary = NumericLeaf(atom_id="team_salary")
    contract_salary = NumericLeaf(atom_id="contract_first_year_salary")
    cap_node = Constant(value=SALARY_CAP, label="2024-25 cap")
    room_limit = TimesConstNode(
        child=cap_node, constant=ROOM_MLE_PCT,
        surface_label="5.68% x cap = Room MLE limit",
    )
    team_below_cap = LeqNode(
        left=team_salary, right=cap_node,
        surface_label="team_salary <= cap",
    )
    salary_within_room_mle = LeqNode(
        left=contract_salary, right=room_limit,
        surface_label="contract_salary <= Room MLE limit",
    )
    op_permitted_via_room_mle = AndNode(
        children=[
            Leaf(atom_id="op_uses_mle_class_exception"),
            team_below_cap,
            salary_within_room_mle,
        ],
        surface_label="op_permitted_via_room_mle",
    )

    trace = []
    result = op_permitted_via_room_mle.evaluate(bundle, trace)

    check("E2E: team_below_cap = TRUE",
          team_below_cap.evaluate(bundle) == Kleene.TRUE)
    check("E2E: salary_within_room_mle = FALSE (36M > 7.98M)",
          salary_within_room_mle.evaluate(bundle) == Kleene.FALSE)
    check("E2E: op_permitted_via_room_mle = FALSE",
          result == Kleene.FALSE)

    print("\n--- E2E trace ---")
    print(format_typed_trace(trace))
    print("---")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    test_numeric_parser()
    test_substrate_boolean_only()
    test_substrate_numeric_only()
    test_substrate_mixed()
    test_substrate_missing_atoms()
    test_end_to_end_substrate_to_engine()

    print("\n" + "=" * 70)
    print(f"RESULTS: {_results['pass']} passed, {_results['fail']} failed")
    print("=" * 70)
    if _results["fail"] > 0:
        print("\nFailures:")
        for name, detail in _results["errors"]:
            print(f"  - {name}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""
probe_phase1a_max_salary.py — Memorial Day Sprint, Phase 1A.

Builds the max_salary determination over NBA CBA Article II §7(a). This is
the first of four universal rule-family Builds that gate every RuleArena
single-operation case.

DIFFERENCE FROM probe_1_conditional_arithmetic.py
==================================================
probe_1 used a soft scope_hint and Build produced a single ComparisonSpec
(contract_salary ≤ maximum_annual_salary) where `maximum_annual_salary` is
one DerivedAtomSpec(named_quantity) — i.e., Map computes the entire
bracketed ceiling per case and the engine has only one comparison to do.

That output is architecturally correct (engine composes structural logic;
Map computes case-specific values) but it leaves the *boost-gate
discipline* invisible to the engine. The Higher-Max-Criteria over-firing
failure mode the hand-authored fragment was built to catch
(domains/nba/fragments/max_salary_by_yos.py, Case 4) depends on the engine
seeing AND(yos_under_7, is_5th_year_eligible, has_higher_max_criteria) —
not a black-box "is the ceiling boosted" derived value.

The sharpened scope_hint pushes Build toward an OR-of-five-branches
structure where:
  - bracket selection lives in the engine (LtNode / GeqNode over yos)
  - boost eligibility is an AndNode over Boolean predicates
  - the ceiling FORMULA stays in Map (single derived NumericLeaf per branch)

Target spec shape:
  OR(
    AND(yos_under_7,
        NOT(higher_max_boost_applies),
        salary ≤ base_max_salary_under_7),
    AND(yos_under_7,
        higher_max_boost_applies,        # = AND(is_5th_year_eligible,
                                          #       has_higher_max_criteria)
        salary ≤ boosted_max_salary_under_7),
    AND(yos_7_to_9,
        NOT(designated_veteran_boost_applies),
        salary ≤ base_max_salary_7_to_9),
    AND(yos_7_to_9,
        designated_veteran_boost_applies,
        salary ≤ boosted_max_salary_7_to_9),
    AND(yos_10_plus,
        salary ≤ base_max_salary_10_plus),
  )

ARCHITECTURAL EXPECTATION
=========================
We expect Build to emit something at least *partially* matching this
shape. The strict win: full five-branch OR with engine-resident boost
gates. A weaker but still acceptable result: three-branch OR (one per
YOS bracket) with each branch's ceiling as a Map-bound derived atom that
encodes the boost logic inside Map. The probe_1 single-Comparison output
is the fallback if neither structural form is reached.

We do NOT need the bracket ceilings to be engine-expressible
arithmetic. By design ("if a calculation is fully upstream it should be
done upstream"), Map computes them and binds one numeric atom per
applicable branch.

ESTIMATED COST: $8-12 at Opus 4.7. The OR-of-branches structure implies
~5-8 Stage-1 decompose calls plus per-leaf numeric sub-decompose calls
(~5-10 of those) plus 1 Boolean dedup + 1 numeric dedup = ~15-25 total
LLM calls.

SYNTHETIC VALIDATION
=====================
Three synthetic cases mirroring the hand-authored fragment's most
diagnostic scenarios. The probe doesn't *require* these to pass —
even if Stage-4 conversion succeeds, the synthetic cases may fail
because the boost-gate atoms may not exist in the registered atom
set (depends on which structural form Build chose). The synthetic
cases are aspirational; their pass/fail tells us whether Build
exposed the boost-gate atoms.
"""
from __future__ import annotations
import os
import sys
from decimal import Decimal

# Path setup — match the other probes
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from probe_harness import run_probe
from rulekit.build.decomposer import DeterminationDeclaration
from rulekit.build.extract import ReaderVoice
from rulekit.engine import Kleene
from rulekit.engine.typed import NumericValue


# ---------------------------------------------------------------------------
# Policy text — Article II §7(a) verbatim from reference_rules.txt
# ---------------------------------------------------------------------------

POLICY_TEXT = """# Article II, Section 7: Maximum Annual Salary

(a) Notwithstanding any other provision of this Agreement, no Player Contract entered into on or after the effective date of this Agreement may provide for a Salary plus Unlikely Bonuses in the first Season covered by the Contract that exceeds the following amounts:

(i) for any player who has completed fewer than seven (7) Years of Service, the greater of (x) twenty-five percent (25%) of the Salary Cap in effect at the time the Contract is executed, or (y) one hundred five percent (105%) of the Salary for the final Season of the player's prior Contract; provided, however, that a player who has four (4) Years of Service as of the June 30 following the end of the last Season covered by his Player Contract ("5th Year Eligible Players") shall be eligible to receive from his Prior Team up to thirty percent (30%) of the Salary Cap in effect at the time the Contract is executed if the player has met at least one of the following criteria (the "Higher Max Criteria") as of the July 1 following the player's fourth Season:

(A) the player was named to the All-NBA first, second, or third team, or was named Defensive Player of the Year, in the immediately preceding Season or in two (2) Seasons during the immediately preceding three (3) Seasons; or

(B) the player was named NBA MVP during one of the immediately preceding three (3) Seasons;

(ii) for any player who has completed at least seven (7) but fewer than ten (10) Years of Service, the greater of (x) thirty percent (30%) of the Salary Cap in effect at the time the Contract is executed, or (y) one hundred five percent (105%) of the Salary for the final Season of the player's prior Contract; provided, however, that a player who has eight (8) or nine (9) Years of Service at the time the Contract is executed and rendered such Years of Service for the Team with which he first executed a Player Contract (or, if he was under a Player Contract for more than one Team during such period, changed Teams only by trade during the first four (4) Salary Cap Years in which he was under a Player Contract) shall be eligible to enter into a Designated Veteran Player Contract pursuant to which he receives from his Prior Team up to thirty-five percent (35%) of the Salary Cap in effect at the time the Contract is executed if the player has met at least one of the Higher Max Criteria at the time his Contract is executed; or

(iii) for any player who has completed ten (10) or more Years of Service, the greater of (x) thirty-five percent (35%) of the Salary Cap in effect at the time the Contract is executed, or (y) one hundred five percent (105%) of the Salary for the final Season of the player's prior Contract.
"""


# ---------------------------------------------------------------------------
# Sharpened scope_hint — pushes Build toward gated-OR structure
# ---------------------------------------------------------------------------
#
# Design notes on the scope_hint wording below:
#
# 1. "decomposes by Years of Service bracket" → signals OR-over-brackets,
#    not a single top-level comparison
# 2. "the boost ELIGIBILITY is a conjunction of Boolean predicates" →
#    signals AndNode in the engine, not a single derived flag
# 3. "the bracketed ceiling VALUE may be computed by Map" → grants Build
#    permission to keep the formula upstream (architectural commitment)
# 4. Explicit naming of the three Boolean predicates → encourages Build
#    to emit them as separate Leaf atoms the engine can compose, rather
#    than collapsing them into a derived "is_eligible_for_boost" atom
# 5. Negative guidance: "not as a single comparison whose RHS is the
#    overall max ceiling" → discourages probe_1's single-comparison
#    output without forbidding it (Build is free to override if the
#    sharpened structure doesn't apply)

SCOPE_HINT = (
    "Decompose this determination so the engine composes the structural "
    "discipline of Article II §7(a). The rule decomposes by Years of "
    "Service bracket (under 7, 7-9, 10+) AND by whether a boost "
    "pathway applies. In the under-7 bracket, the boost is available to "
    "5th-Year Eligible players (4 YOS) who meet at least one of the "
    "Higher Max Criteria (All-NBA, Defensive Player of the Year, or NBA "
    "MVP per (A)/(B)). In the 7-9 bracket, the Designated Veteran boost "
    "is available to players with 8-9 YOS who were retained by their "
    "first team and meet the Higher Max Criteria. The 10+ bracket has "
    "no further boost. Express the bracket selection and boost "
    "eligibility as engine-resident Boolean structure: an OR of "
    "per-branch ANDs, where each AND gates the applicable bracket "
    "predicate, the boost eligibility (itself an AND over the "
    "5th-Year-Eligible-or-Designated-Veteran predicate AND the "
    "Higher-Max-Criteria predicate), and a comparison of the contract "
    "salary against the branch's applicable ceiling. The CEILING VALUE "
    "for each branch (the greater of X% × Salary Cap or 105% × prior "
    "salary) is fully determined by upstream case data — express it as "
    "a single Map-bound derived numeric atom per branch (each branch's "
    "ceiling is a distinct atom: the under-7 base ceiling, the under-7 "
    "boosted ceiling, the 7-9 base ceiling, the 7-9 boosted ceiling, "
    "and the 10+ ceiling). Avoid encoding the entire rule as a single "
    "top-level comparison whose RHS is one overall maximum_annual_salary "
    "derived atom — that hides the bracket and boost discipline inside "
    "Map. Avoid attempting to express the max() formula in engine "
    "arithmetic; the engine handles structural composition, Map handles "
    "case-specific computation."
)


# ---------------------------------------------------------------------------
# Determination
# ---------------------------------------------------------------------------

DETERMINATION = DeterminationDeclaration(
    id="nba.max_salary.D1",
    description=(
        "Is the first-year Salary plus Unlikely Bonuses of this Player "
        "Contract within the Maximum Annual Salary permitted under "
        "Article II, Section 7(a)?"
    ),
    polarity="positive",
    source_span="Article II, Section 7(a)",
    composition="derived",
    scope_hint=SCOPE_HINT,
)


# ---------------------------------------------------------------------------
# Reader voice — strengthened with explicit discussion of the over-firing
# failure mode that the gated-OR structure protects against. This is the
# institutional knowledge the LLM needs to understand WHY the structure
# matters.
# ---------------------------------------------------------------------------

VOICE = ReaderVoice(
    role="experienced NBA team-operations counsel",
    domain="NBA Collective Bargaining Agreement (CBA)",
    background=(
        "You read the CBA's Maximum Annual Salary provisions with rigorous "
        "attention to the bracket-and-boost structure of Section 7(a). "
        "The rule decomposes by Years of Service into three brackets "
        "(under 7, 7-9, 10+). In the under-7 bracket, a 'Higher Max' "
        "boost is available, but ONLY if the player is a 5th-Year "
        "Eligible Player AND meets one of the Higher Max Criteria — "
        "BOTH conditions are required, not either-or. Common practitioner "
        "errors include granting the boost to a player who meets the "
        "Higher Max Criteria (e.g., named to All-NBA) but is not actually "
        "5th-Year Eligible (e.g., wasn't drafted by current team and "
        "wasn't traded in year 1 of rookie scale). The 7-9 bracket has "
        "an analogous Designated Veteran boost, again requiring BOTH "
        "Designated Veteran eligibility AND Higher Max Criteria. The "
        "10+ bracket has no boost. Within each branch, the ceiling is "
        "the greater of a bracket-specific percentage of the Salary Cap "
        "or 105% of the player's prior-year Salary. These ceiling values "
        "are computed from upstream case data; the engine's role is to "
        "enforce the bracket-and-boost discipline that selects WHICH "
        "ceiling applies."
    ),
)


# ---------------------------------------------------------------------------
# Constants registry — engine needs these for any branches Build emits
# as comparisons against literal-named constants (e.g. "the Salary Cap")
# ---------------------------------------------------------------------------

CONSTANTS = {
    "salary_cap": Decimal("140588000"),
}


# ---------------------------------------------------------------------------
# Synthetic cases — aspirational; pass/fail depends on which atoms Build
# emits. Documented expected values per case. The case definitions use
# the atom_id_hint names from the target spec shape; we'll need to map
# them to whatever Build actually emits when interpreting results.
# ---------------------------------------------------------------------------
#
# Each case is (label, atom_value_dict). The probe harness wraps them in
# a FactBundle and runs the engine; UNDETERMINED is returned for atoms
# the engine references that aren't in the bundle.
#
# Note: we intentionally do NOT include ground-truth dispositions in the
# synthetic_cases payload — the harness only logs the engine's result,
# not whether it matched. Validating disposition correctness happens in
# Phase 2 against real RuleArena cases.

SYNTHETIC_CASES = [
    # CASE 1: YOS=5, no boost, contract under base ceiling.
    # Expect: TRUE (permitted via under-7 base branch)
    ("YOS=5, no_boost, salary=$30M, base_ceiling=$35M → expect TRUE", {
        "player_years_of_service": NumericValue.of(5),
        "contract_first_year_salary": NumericValue.of(Decimal("30000000")),
        "player_prior_year_salary": NumericValue.of(Decimal("10000000")),
        "player_is_5th_year_eligible": Kleene.FALSE,
        "player_has_higher_max_criteria": Kleene.FALSE,
        "player_is_designated_veteran_eligible": Kleene.FALSE,
        # If Build emits the branch-specific derived ceilings:
        "base_max_salary_under_7": NumericValue.of(Decimal("35147000")),
        "boosted_max_salary_under_7": NumericValue.of(Decimal("42176400")),
        "base_max_salary_7_to_9": NumericValue.of(Decimal("42176400")),
        "boosted_max_salary_7_to_9": NumericValue.of(Decimal("49205800")),
        "base_max_salary_10_plus": NumericValue.of(Decimal("49205800")),
        # Fallback if Build emits probe_1's shape (single derived ceiling):
        "maximum_annual_salary": NumericValue.of(Decimal("35147000")),
    }),

    # CASE 2: THE OVER-FIRING PROTECTION CASE.
    # YOS=4, has Higher Max Criteria (All-NBA last year), but NOT
    # 5th-Year Eligible. Contract $39.4M exceeds base ceiling $35M
    # but would be within boosted ceiling $42M.
    # Architecturally-correct disposition: FALSE.
    # Direct LLMs frequently get this wrong because "All-NBA" appears
    # right next to "5th-Year Eligible" in the case description, and
    # they grant the boost based on lexical proximity.
    ("YOS=4, higher_max=TRUE, 5th_yr=FALSE, salary=$39.4M → expect FALSE (over-firing protection)", {
        "player_years_of_service": NumericValue.of(4),
        "contract_first_year_salary": NumericValue.of(Decimal("39400000")),
        "player_prior_year_salary": NumericValue.of(Decimal("10000000")),
        "player_is_5th_year_eligible": Kleene.FALSE,  # Critical
        "player_has_higher_max_criteria": Kleene.TRUE,
        "player_is_designated_veteran_eligible": Kleene.FALSE,
        "base_max_salary_under_7": NumericValue.of(Decimal("35147000")),
        "boosted_max_salary_under_7": NumericValue.of(Decimal("42176400")),
        "base_max_salary_7_to_9": NumericValue.of(Decimal("42176400")),
        "boosted_max_salary_7_to_9": NumericValue.of(Decimal("49205800")),
        "base_max_salary_10_plus": NumericValue.of(Decimal("49205800")),
        "maximum_annual_salary": NumericValue.of(Decimal("35147000")),
    }),

    # CASE 3: YOS unknown — UNDETERMINED propagation.
    # Every bracket predicate evaluates UNDETERMINED → top-level OR
    # over UNDETERMINEDs → UNDETERMINED. Tests that the engine doesn't
    # collapse missing data into a false disposition.
    ("YOS unknown → expect UNDETERMINED (propagation discipline)", {
        "player_years_of_service": NumericValue.undetermined(),
        "contract_first_year_salary": NumericValue.of(Decimal("30000000")),
        "player_prior_year_salary": NumericValue.of(Decimal("10000000")),
        "player_is_5th_year_eligible": Kleene.UNDETERMINED,
        "player_has_higher_max_criteria": Kleene.UNDETERMINED,
        "player_is_designated_veteran_eligible": Kleene.UNDETERMINED,
        "base_max_salary_under_7": NumericValue.undetermined(),
        "boosted_max_salary_under_7": NumericValue.undetermined(),
        "base_max_salary_7_to_9": NumericValue.undetermined(),
        "boosted_max_salary_7_to_9": NumericValue.undetermined(),
        "base_max_salary_10_plus": NumericValue.undetermined(),
        "maximum_annual_salary": NumericValue.undetermined(),
    }),
]


def main():
    audit_dir = os.path.join(HERE, "audit_logs")
    result = run_probe(
        probe_name="probe_phase1a_max_salary",
        policy_text=POLICY_TEXT,
        determination=DETERMINATION,
        voice=VOICE,
        constants=CONSTANTS,
        synthetic_cases=SYNTHETIC_CASES,
        audit_dir=audit_dir,
        model="claude-opus-4-7",
    )

    print("\n" + "=" * 75)
    print("PHASE 1A DIAGNOSTIC")
    print("=" * 75)
    print("""
Read the spec tree above and answer the following:

  Q1. STRUCTURE: Did Build emit a top-level OR over per-bracket branches
      (the strict win), an OR over fewer branches with boost folded into
      derived atoms (acceptable), or a single ComparisonSpec with one
      maximum_annual_salary derived atom (probe_1's fallback shape)?

  Q2. BOOST GATES: Did Build expose AndNode structure over the boost
      predicates (player_is_5th_year_eligible AND
      player_has_higher_max_criteria), or did it delegate to a single
      derived "is_eligible_for_boost" atom?

  Q3. CEILING ATOMS: How many distinct derived-atom NumericLeafs were
      registered for ceilings? (5 = strict win, 3 = bracket-only,
      1 = probe_1 shape.)

  Q4. STAGE-4 SUCCESS: Did spec_to_engine_node succeed? If not, what was
      the error?

  Q5. SYNTHETIC CASES: Did Case 2 (over-firing protection) return FALSE?
      A TRUE here would mean the structural protection isn't in the
      engine — atoms like 'player_is_5th_year_eligible' aren't being
      referenced.

Phase 1A is SUCCESSFUL if Q4 passes. Q1-Q3 determine which architectural
form Build chose, but any of the three forms moves us to Phase 1B.
""")
    return result


if __name__ == "__main__":
    main()

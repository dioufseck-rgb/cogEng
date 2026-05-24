"""
probe_1_conditional_arithmetic.py

Probes whether Build can express conditional arithmetic — where the
formula for a numeric quantity depends on which categorical bracket the
case falls into.

Source: NBA CBA Article II, Section 7(a). The Maximum Annual Salary
permitted under (a) depends on the player's Years of Service:

  - <7 YOS:       max( 25% × cap , 105% × prior salary )
  - 7-9 YOS:      max( 30% × cap , 105% × prior salary )
  - 10+ YOS:      max( 35% × cap , 105% × prior salary )

Plus Higher-Max boost branches for 5th-Year Eligible (4 YOS) and
Designated Veteran (8-9 YOS) players who meet Higher-Max Criteria.

ARCHITECTURAL EXPECTATION
=========================
The current spec inventory has DerivedAtomSpec(computation_kind=...) for
quantities the engine doesn't compute. computation_kind values include
'conditional', 'max_of', 'named_quantity'. The natural encoding here is
either:

  (a) ONE DerivedAtomSpec(computation_kind='conditional') for the whole
      max-salary quantity, with Map computing the bracket-dependent
      formula entirely;
  (b) The decomposer enumerates per-bracket cases as separate engine
      branches under an OR or AT_LEAST, each gated by the bracket
      predicate.

Either is recoverable. The architectural failure mode would be if Build
emits something the spec system can't hold — e.g. a numeric leaf with
multiple disjoint expressions, or a comparison whose RHS varies
mid-evaluation.

ESTIMATED COST: ~$10-15
"""
from __future__ import annotations
import os
import sys
from decimal import Decimal

# Path setup
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from probe_harness import run_probe
from rulekit.build.decomposer import DeterminationDeclaration
from rulekit.build.extract import ReaderVoice
from rulekit.engine import Kleene
from rulekit.engine.typed import NumericValue


# ---------------------------------------------------------------------------
# Policy text — Article II §7(a) only
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
# Determination — bare question, no structure leaked
# ---------------------------------------------------------------------------

DETERMINATION = DeterminationDeclaration(
    id="probe1.max_salary",
    description=(
        "Is the first-year Salary plus Unlikely Bonuses of this Player Contract "
        "within the Maximum Annual Salary permitted under Article II, Section 7(a)?"
    ),
    polarity="positive",
    source_span="Article II, Section 7(a)",
    composition="derived",
    scope_hint=(
        "Focus on whether the Player Contract's first-year compensation "
        "satisfies the Maximum Annual Salary cap, which depends on the "
        "player's Years of Service bracket and may be increased by Higher Max "
        "or Designated Veteran eligibility."
    ),
)


VOICE = ReaderVoice(
    role="experienced NBA team-operations counsel",
    domain="NBA Collective Bargaining Agreement (CBA)",
    background=(
        "You read the CBA's Maximum Annual Salary provisions. The maximum "
        "annual salary a player may receive depends on the player's Years "
        "of Service (under 7, 7-9, or 10+) and may be boosted if the player "
        "is a 5th-Year Eligible Player meeting Higher Max Criteria, or a "
        "Designated Veteran. The formula is always 'the greater of "
        "[bracket-specific percent of Salary Cap] or 105% of the player's "
        "prior-year salary'."
    ),
)


CONSTANTS = {
    "salary_cap": Decimal("140588000"),
}


def main():
    audit_dir = os.path.join(HERE, "audit_logs")
    result = run_probe(
        probe_name="probe_1_conditional_arithmetic",
        policy_text=POLICY_TEXT,
        determination=DETERMINATION,
        voice=VOICE,
        constants=CONSTANTS,
        synthetic_cases=None,  # Stage-4 inspection is the goal, not evaluation
        audit_dir=audit_dir,
    )

    print("\n" + "=" * 75)
    print("PROBE 1 DIAGNOSTIC")
    print("=" * 75)
    print("""
Read the spec tree above and answer the following:

  Q1. Did Build emit ANY representation of the conditional/bracketed
      arithmetic, or did it silently drop the per-YOS-bracket structure?

  Q2. If yes, did it use:
      (a) DerivedAtomSpec(computation_kind='conditional') — letting Map
          compute the whole quantity
      (b) Per-bracket engine branches under an OR — gating each branch
          with a YOS comparison
      (c) Something else (a 'max_of' DerivedAtomSpec; a flat list of
          comparisons; pure free-text descriptions in the LHS/RHS)

  Q3. Did Stage-4 conversion succeed? If not, what was the error?

The answer determines whether conditional arithmetic is architecturally
expressible today, requires a new spec type, or only needs prompt work.
""")
    return result


if __name__ == "__main__":
    main()

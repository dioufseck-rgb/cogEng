"""
probe_2_reclassification.py

Probes whether Build can express rule reclassification — where one rule's
application is transformed into another rule's application based on
operational conditions.

Source: NBA CBA Article VII, Section 6(f), with particular attention to
subsection (f)(5):

  "In the event that, during a Salary Cap Year, a Team: (i) does not use
   the Non-Taxpayer Mid-Level Salary Exception to acquire any Player
   Contracts by assignment; (ii) uses the Non-Taxpayer MLE to sign one
   or more new Player Contracts ... and (iii) but for the Team's use of
   the Non-Taxpayer MLE as described in clause (ii) above, the Team
   otherwise would be permitted to engage in a transaction that causes
   the Team's Team Salary to exceed the First Apron Level ... then the
   Team shall be permitted to engage in such transaction, whereupon the
   Team will be deemed to have used the Taxpayer Mid-Level Salary
   Exception instead of the Non-Taxpayer Mid-Level Salary Exception ..."

This is not a permission predicate; it is a re-labeling rule. The Team's
operational use of one exception is reclassified as use of a different
exception.

ARCHITECTURAL EXPECTATION
=========================
The current spec inventory has no construct to express transformation
("deemed to have used X instead of Y"). Reclassification could be modeled
indirectly:

  (a) The decomposer might model it as an OR over both interpretations:
      "permitted via Non-Taxpayer MLE" OR "permitted via Taxpayer MLE
      AND used Non-Taxpayer MLE incorrectly AND deemed-use conditions
      hold". Awkward but expressible.
  (b) The decomposer might attempt to encode the reclassification as
      something the architecture doesn't have a type for, producing a
      malformed spec.
  (c) The decomposer might silently DROP the reclassification clause
      and produce a spec that doesn't reflect the rule. This would be
      the worst outcome — the spec looks correct on its face but is
      missing the deemed-use logic.

(c) is the case to watch for. The probe's main diagnostic is whether
(f)(5) shows up in the spec at all.

ESTIMATED COST: ~$8-12
"""
from __future__ import annotations
import os
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from probe_harness import run_probe
from rulekit.build.decomposer import DeterminationDeclaration
from rulekit.build.extract import ReaderVoice
from rulekit.engine import Kleene


# ---------------------------------------------------------------------------
# Policy text — Section 6(f) in full, including (f)(5)
# ---------------------------------------------------------------------------

POLICY_TEXT = """Background (from Article VII, Section 2): The Salary Cap, First Apron Level, Second Apron Level, and Tax Level are dollar amounts published each Salary Cap Year. For 2024-25, the Salary Cap is $140,588,000 and the First Apron Level is $178,132,000. A Team's Team Salary is the sum of the Salaries of all players on the Team for the relevant Salary Cap Year.

(f) Taxpayer Mid-Level Salary Exception.

Subject to the rules set forth in Section 2(e) above and Section 6(n) below:

(1) A Team may use the Taxpayer Mid-Level Salary Exception to sign one (1) or more Player Contracts during each Salary Cap Year not to exceed two (2) Seasons in length, that, in the aggregate, provide for Salaries and Unlikely Bonuses in the first Salary Cap Year totaling up to the amounts set forth below, provided that the Team's Team Salary immediately following the Team's use of such Exception exceeds the First Apron Level:

|                                     | Taxpayer Mid-Level Salary Exception                                                                                                                                                   |
|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| For the 2023-24 Salary Cap Year     | $5 million                                                                                                                                                                            |
| For each subsequent Salary Cap Year | $5 million multiplied by a fraction, the numerator of which is the Salary Cap for that Salary Cap Year and the denominator of which is the Salary Cap for the 2023-24 Salary Cap Year |

(2) A Team may not use all or any portion of the Taxpayer Mid-Level Salary Exception if at the time the Team proposes to use the Exception the Team has already used the Mid-Level Salary Exception for Room Teams in that same Salary Cap Year.

(3) Player Contracts signed pursuant to the Taxpayer Mid-Level Salary Exception may provide for annual increases and decreases in Salary and Unlikely Bonuses in accordance with Section 5(a)(1) above.

(4) The Taxpayer Mid-Level Salary Exception for a Team shall arise on the first day of each Salary Cap Year and shall expire at the start of the Team's last game of the Regular Season during that Salary Cap Year.

(5) In the event that, during a Salary Cap Year, a Team: (i) does not use the Non-Taxpayer Mid-Level Salary Exception to acquire any Player Contracts by assignment; (ii) uses the Non-Taxpayer Mid-Level Salary Exception in order to sign one (1) or more new Player Contracts during a Salary Cap Year, not to exceed two (2) Seasons in length that, in the aggregate, provide for Salaries and Unlikely Bonuses in the first Salary Cap Year of the Contract(s) totaling no more than the amounts set forth in Section 6(f)(1) above, and (iii) but for the Team's use of the Non-Taxpayer Mid-Level Salary Exception as described in clause (ii) above, the Team otherwise would be permitted to engage in a transaction that causes the Team's Team Salary to exceed the First Apron Level for such Salary Cap Year in accordance with the rules set forth in Section 2(e) above, then the Team shall be permitted to engage in such transaction, whereupon the Team will be deemed to have used the Taxpayer Mid-Level Salary Exception instead of the Non-Taxpayer Mid-Level Salary Exception for all purposes under this Article VII, and the Team's ability to use the Non-Taxpayer Mid-Level Salary Exception during such Salary Cap Year shall thereupon be extinguished.
"""


DETERMINATION = DeterminationDeclaration(
    id="probe2.taxpayer_mle",
    description=(
        "Is this signing permitted via the Taxpayer Mid-Level Salary "
        "Exception under Article VII, Section 6(f), considering all "
        "applicable provisions of Section 6(f) including subsection (5)?"
    ),
    polarity="positive",
    source_span="Article VII, Section 6(f)",
    composition="derived",
    scope_hint=(
        "Focus on the requirements that must be satisfied for a Player "
        "Contract to be permitted via the Taxpayer Mid-Level Salary "
        "Exception, including the conditions in (f)(1), the prior-use "
        "restrictions in (f)(2), the deemed-use provisions in (f)(5), and "
        "any other conditions stated in Section 6(f). Pay particular "
        "attention to subsection (5), which describes a circumstance "
        "where a signing made using a different exception becomes treated "
        "as if it had used this exception."
    ),
)


VOICE = ReaderVoice(
    role="experienced NBA team-operations counsel",
    domain="NBA Collective Bargaining Agreement (CBA)",
    background=(
        "You read Article VII, Section 6(f) of the NBA CBA, governing the "
        "Taxpayer Mid-Level Salary Exception. Subsection (1) sets the "
        "primary requirements (salary limit per year, length limit, "
        "First-Apron-bracket requirement). Subsection (2) restricts use "
        "if a different exception was used first. Subsection (5) creates "
        "a deemed-use rule: if a Team used the Non-Taxpayer MLE under "
        "specific conditions, the Team will be deemed to have used this "
        "Exception (Taxpayer MLE) instead. This deemed-use rule is a "
        "permission path."
    ),
)


CONSTANTS = {
    "salary_cap": Decimal("140588000"),
    "first_apron_level": Decimal("178132000"),
    "taxpayer_mle_amount": Decimal("5168000"),
    "taxpayer_mid_level_exception_amount": Decimal("5168000"),
    "taxpayer_mid_level_salary_exception_amount": Decimal("5168000"),
}


def main():
    audit_dir = os.path.join(HERE, "audit_logs")
    result = run_probe(
        probe_name="probe_2_reclassification",
        policy_text=POLICY_TEXT,
        determination=DETERMINATION,
        voice=VOICE,
        constants=CONSTANTS,
        synthetic_cases=None,
        audit_dir=audit_dir,
    )

    print("\n" + "=" * 75)
    print("PROBE 2 DIAGNOSTIC")
    print("=" * 75)
    print("""
Read the spec tree above and answer the following:

  Q1. Did the spec tree have a top-level OR with multiple branches, or a
      single AND-of-requirements? An OR with branches for "direct use"
      and "deemed use" is the principled encoding.

  Q2. Search the spec tree for references to subsection (5) / "deemed" /
      "Non-Taxpayer". Is there a branch that represents (f)(5)'s
      reclassification?

  Q3. If (f)(5) is NOT represented, the spec is silently incomplete —
      the architectural failure mode we wanted to detect.

  Q4. If (f)(5) IS represented as an alternative branch, what shape did
      it take? Compare against the principled OR-with-deemed-use-branch.

The diagnostic outcome:
  - Cleanly represented (OR with both branches): architecture handles
    this; the prompt may need polishing.
  - Awkwardly represented (encoded but oddly): we need to decide whether
    to clean up the prompt or to introduce a new spec type for
    transformation rules.
  - Silently dropped: architectural gap — reclassification needs
    explicit support, either in the spec types or in prompt guidance.
""")
    return result


if __name__ == "__main__":
    main()

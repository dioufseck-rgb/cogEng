"""
probe_3_table_gating.py

Probes whether Build can express table-driven gating — where a normative
table maps categorical transaction types to numeric/categorical
consequences.

Source: NBA CBA Article VII, Section 2(e). The Transaction Restrictions
Table maps 11 transaction types (rows A through K) to apron-level
thresholds (First Apron or Second Apron). A team's transaction is
permitted only if, post-transaction, the team's salary does not exceed
the row-appropriate apron level.

This is a meta-rule that subsequently parameterizes many other rules:
each row's transaction is governed by a different sub-section, and the
table determines which apron threshold applies.

ARCHITECTURAL EXPECTATION
=========================
Tables are everywhere in regulation but the current spec inventory has
no construct for them. The natural encodings are:

  (a) The decomposer unrolls the table into a flat OR-of-AND structure:
      "if transaction is row A AND team-salary ≤ First Apron" OR "if
      transaction is row B AND team-salary ≤ First Apron" OR ... 11 rows.
  (b) The decomposer uses DerivedAtomSpec(computation_kind='lookup' or
      'conditional') for the apron threshold, letting Map compute the
      table lookup from the transaction type.
  (c) The decomposer collapses the table into a coarse "team-salary
      ≤ First Apron OR Second Apron" without preserving which
      transaction triggers which threshold — silently lossy.

(c) is the worst outcome. (a) is verbose but architecturally clean. (b)
is elegant but pushes work onto Map.

ESTIMATED COST: ~$10-15
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


# ---------------------------------------------------------------------------
# Policy text — Section 2(e) in full
# ---------------------------------------------------------------------------

POLICY_TEXT = """Background: The Salary Cap, First Apron Level, and Second Apron Level are dollar amounts published each Salary Cap Year. For 2024-25, the Salary Cap is $140,588,000, the First Apron Level is $178,132,000, and the Second Apron Level is $188,931,000. A Team's Team Salary is the sum of the Salaries of all players on the Team for the relevant Salary Cap Year.

(e) Operation of Apron Levels.

(2) (i) At any point during a Salary Cap Year, the following rules shall apply with respect to the transactions listed in the table in Section 2(e)(4) below (the "Transaction Restrictions Table"):

(A) A Team may not engage in a transaction set forth in the Transaction Restrictions Table if, immediately following such transaction, the Team's Team Salary for such Salary Cap Year would exceed the "Applicable Apron Level" that corresponds with such transaction in the table; and

(B) A Team that engages in a transaction set forth in the Transaction Restrictions Table may not, for the remainder of such Salary Cap Year, have an Team Salary that exceeds the Applicable Apron Level that corresponds with such transaction in the table.

(4) Transaction Restrictions Table:

| Transaction                                                                                                                 | Applicable Apron Level |
|-----------------------------------------------------------------------------------------------------------------------------|------------------------|
| A. Team signs or acquires a player using the Bi-annual Exception (as described in Section 6(d) below)                       | First Apron Level      |
| B. Team signs or acquires a player using the Non-Taxpayer Mid-Level Salary Exception (as described in Section 6(e) below)   | First Apron Level      |
| C. Team acquires a player pursuant to a Contract entered into in accordance with Section 8(e)(1) below                      | First Apron Level      |
| D. Team signs a Contract during the Regular Season with a player who was previously under a Contract that: (i) was terminated during such Regular Season; and (ii) prior to such termination, provided for a Salary for the Salary Cap Year encompassing such Regular Season of greater than the amount of the Non-Taxpayer Mid-Level Salary Exception for such Salary Cap Year | First Apron Level      |
| E. Team acquires a player using an Expanded Traded Player Exception (as described in Section 6(j)(1)(iv) below)             | First Apron Level      |
| F. Team acquires a player using a Standard Traded Player Exception (as described in Section 6(j)(1)(i) below) (i) after the end of the Regular Season in which such Traded Player Exception arose, or (ii) if such Traded Player Exception arose during the period from the day following the last day of a Regular Season through the day before the first day of the immediately following Regular Season, after the last day of such following Regular Season | First Apron Level      |
| G. Team acquires a player using a Transition Traded Player Exception (as described in Section 6(j)(1)(iii) below)           | First Apron Level      |
| H. Team acquires a player using an Aggregated Standard Traded Player Exception (as described in Section 6(j)(1)(ii) below)  | Second Apron Level     |
| I. Team pays cash to another Team in connection with a trade in accordance with Section 8(a) below                          | Second Apron Level     |
| J. Team acquires a player using a Traded Player Exception (as described in Section 6(j)(1)(i), (ii), (iii), or (iv) below), which Traded Player Exception is in respect of a Player Contract signed and traded pursuant to Section 8(e)(1) below | Second Apron Level     |
| K. Team signs a player using the Taxpayer Mid-Level Salary Exception (as described in Section 6(f) below)                   | Second Apron Level     |
"""


DETERMINATION = DeterminationDeclaration(
    id="probe3.transaction_apron_check",
    description=(
        "Is this Team's intended transaction permitted under the apron-level "
        "rules of Article VII, Section 2(e), given the Team's Team Salary "
        "immediately following the transaction?"
    ),
    polarity="positive",
    source_span="Article VII, Section 2(e)",
    composition="derived",
    scope_hint=(
        "Focus on the gating rule in Section 2(e)(2)(i)(A): a Team may not "
        "engage in a listed transaction if, post-transaction, the Team's "
        "Team Salary exceeds the Applicable Apron Level for that "
        "transaction. The Applicable Apron Level depends on which row in "
        "the Transaction Restrictions Table the transaction falls under."
    ),
)


VOICE = ReaderVoice(
    role="experienced NBA team-operations counsel",
    domain="NBA Collective Bargaining Agreement (CBA)",
    background=(
        "You read the apron-level operation rules of the NBA CBA. Section "
        "2(e) defines the Transaction Restrictions Table: each row is a "
        "category of transaction, and the table specifies which apron "
        "threshold (First Apron Level or Second Apron Level) the Team's "
        "post-transaction Team Salary must not exceed. Different rows "
        "correspond to different transaction types — Bi-annual signing, "
        "Non-Taxpayer MLE signing, Taxpayer MLE signing, various trade "
        "exceptions, sign-and-trade acquisitions, and cash trades."
    ),
)


CONSTANTS = {
    "salary_cap": Decimal("140588000"),
    "first_apron_level": Decimal("178132000"),
    "second_apron_level": Decimal("188931000"),
}


def main():
    audit_dir = os.path.join(HERE, "audit_logs")
    result = run_probe(
        probe_name="probe_3_table_gating",
        policy_text=POLICY_TEXT,
        determination=DETERMINATION,
        voice=VOICE,
        constants=CONSTANTS,
        synthetic_cases=None,
        audit_dir=audit_dir,
    )

    print("\n" + "=" * 75)
    print("PROBE 3 DIAGNOSTIC")
    print("=" * 75)
    print("""
Read the spec tree above and answer the following:

  Q1. Did the spec tree preserve the 11-row structure, or collapse to
      something coarser?
      (a) A flat OR-of-AND with 11 branches: principled unrolling
      (b) Two branches (First-Apron group, Second-Apron group): partial
          collapse losing the per-transaction granularity
      (c) One generic comparison "team-salary ≤ apron-level": collapsed
          beyond usable
      (d) DerivedAtomSpec for the Applicable Apron Level: Map handles
          the table lookup
      (e) Something else

  Q2. If the spec preserved the per-row distinction, did each row include
      its transaction-type predicate as a Boolean leaf? Compare against
      11 expected predicates.

  Q3. Did Stage-4 conversion succeed? Tables that explode into many
      branches put pressure on engine-node creation — any errors there?

  Q4. How many atoms registered? If the table was unrolled cleanly,
      expect ~11 Boolean transaction-type leaves + 1-2 numeric atoms
      (team salary, apron levels as constants).

The diagnostic outcome:
  - Clean unrolling (a + Q2-yes): architecture handles tables via
    explicit enumeration; consider whether this approach scales to
    larger tables.
  - Map-pushdown (d): elegant but unverified; we'd need to test Map's
    ability to do the lookup correctly.
  - Lossy collapse (b/c): architectural gap — we need either explicit
    table-construct support or prompt guidance to ensure unrolling.
""")
    return result


if __name__ == "__main__":
    main()

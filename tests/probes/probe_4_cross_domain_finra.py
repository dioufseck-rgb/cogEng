"""
probe_4_cross_domain_finra.py

Probes whether the Build pipeline generalizes to a non-CBA policy
domain. The three CBA probes test architectural expressibility of
constructs known to appear in the policy we've engineered toward; this
probe tests whether the prompts themselves work on terrain outside the
LLM's CBA training saturation.

Source: FINRA Rule 4210, Pattern Day Trader provisions
(paragraphs (b) and (f)(8)(B)). These provisions establish minimum
equity requirements and trading classifications:

  - A "Pattern Day Trader" (PDT) is a customer who executes 4 or more
    day trades within 5 business days, provided those trades represent
    more than 6% of total trades in the margin account during that
    5-business-day period.
  - Minimum equity for a regular margin account: $2,000.
  - Minimum equity for an account deemed a PDT: $25,000.
  - PDT minimum equity must be maintained at all times.
  - Day-trading buying power for a PDT equals maintenance margin
    excess multiplied by 4 (for equity securities).
  - Withdrawals are permitted only if, after withdrawal, the equity
    in the account is at least the greater of: $2,000 (or $25,000
    for a PDT) OR the amount sufficient to meet maintenance margin.

This exercises the same constructs as the CBA probes —
  - Boolean predicates: "is the customer classified as a PDT?"
  - Numeric comparisons: "is account equity ≥ $25,000?"
  - Conditional thresholds: "min equity is $25,000 if PDT, else $2,000"
  - Arithmetic: "day-trading buying power = maintenance excess × 4"
  - Max-of: "withdrawal floor = greater of $2,000/$25,000 or
    maintenance-margin requirement"

— on financial-regulation terrain rather than sports-CBA terrain.

ARCHITECTURAL EXPECTATION
=========================
If the CBA probes succeed and this one fails, the prompts are
CBA-tuned and need cross-domain hardening. If both succeed, the
generalization claim is supported. Either outcome is informative.

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
# Policy text — FINRA Rule 4210 PDT provisions
#
# Composed from FINRA Rule 4210(b), (f)(8)(B), and FINRA Regulatory
# Notice 24-13 explanatory text.
# ---------------------------------------------------------------------------

POLICY_TEXT = """FINRA Rule 4210. Margin Requirements.

(b) Initial Margin. For the purpose of effecting new securities transactions and commitments, the customer shall be required to deposit margin in cash and/or securities in the account which shall be at least the greater of:

(1) the amount specified in Regulation T, or Rules 400 through 406 of SEC Customer Margin Requirements for Security Futures, or Rules 41.42 through 41.49 under the Commodity Exchange Act;

(2) the amount specified in paragraph (c) of this Rule (the maintenance margin requirements);

(3) such greater amount as FINRA may from time to time require for specific securities; or

(4) equity of at least $2,000 except that cash need not be deposited in excess of the cost of any security purchased (this equity and cost of purchase provision shall not apply to "when distributed" securities in a cash account).

The minimum equity requirement for a "pattern day trader" is $25,000 pursuant to paragraph (f)(8)(B)(iv)a. of this Rule.

Withdrawals of cash or securities may be made from any account which has a debit balance, "short" position or commitments, provided it is in compliance with Regulation T and SEA Rules 400 through 406 of the Customer Margin Requirements for Security Futures and Rules 41.42 through 41.49 under the CEA, and after such withdrawal the equity in the account is at least the greater of $2,000 ($25,000 in the case of a "pattern day trader") or an amount sufficient to meet the maintenance margin requirements of this Rule.

(f)(8)(B) Special Requirements for Pattern Day Traders.

(i) Definition. The term "pattern day trader" means any customer who executes four or more day trades within five business days, provided the number of day trades is more than six percent of the customer's total trades in the margin account for that same five business day period. Day trading is defined as the purchasing and selling or the selling and purchasing of the same security on the same day in a margin account. If the customer's number of day trades is six percent or less of their total trades for a five-business-day period, the customer will not be considered a pattern day trader.

(ii) Pattern day traders shall be restricted to day trading in a margin account.

(iii) Day-Trading Buying Power. "Day-trading buying power" means the equity in a customer's account at the close of business of the previous day, less any maintenance margin requirements as prescribed in paragraph (c) of Rule 4210, multiplied by four for equity securities.

(iv) Minimum Equity Requirements for Pattern Day Traders.

a. The minimum equity required for the accounts of customers deemed to be pattern day traders shall be $25,000. This minimum equity must be deposited in the account before the customer may continue day trading and must be maintained in the customer's account at all times.

b. In the event that the member at which a customer seeks to open an account or resume day trading in an existing account knows or has a reasonable basis to believe that the customer will engage in pattern day trading, then the minimum equity required under paragraph (f)(8)(B)(iv)a. (that is, $25,000) must be deposited in the account prior to commencement of day trading.

c. Funds deposited into a pattern day trader's account to meet the minimum equity or maintenance margin requirements of paragraph (f)(8)(B) of the rule cannot be withdrawn for a minimum of two business days following the close of business on any day when the deposit is required.
"""


DETERMINATION = DeterminationDeclaration(
    id="probe4.pdt_minimum_equity_compliance",
    description=(
        "Is this margin account in compliance with the minimum equity "
        "requirements of FINRA Rule 4210, given the customer's pattern "
        "day trader status?"
    ),
    polarity="positive",
    source_span="FINRA Rule 4210(b) and (f)(8)(B)",
    composition="derived",
    scope_hint=(
        "Focus on the minimum equity required for the margin account, "
        "which differs based on whether the customer is classified as a "
        "Pattern Day Trader. Pattern Day Trader classification depends on "
        "both the number of day trades within a 5-business-day window "
        "and the percentage of total trades those day trades represent. "
        "The minimum equity must be maintained at all times once the "
        "customer is classified as a PDT."
    ),
)


VOICE = ReaderVoice(
    role="experienced broker-dealer compliance officer",
    domain="FINRA Rule 4210 (Margin Requirements)",
    background=(
        "You read FINRA Rule 4210 governing margin requirements for "
        "customer accounts at broker-dealers. The rule distinguishes "
        "regular margin accounts from accounts of customers classified "
        "as 'Pattern Day Traders' (PDTs). PDT classification is based "
        "on day-trading activity over a 5-business-day window. The "
        "minimum equity requirement differs by classification: $2,000 "
        "for regular margin accounts and $25,000 for PDT accounts. "
        "Failure to maintain required minimum equity triggers margin "
        "calls and trading restrictions."
    ),
)


# Constants the policy references as named dollar amounts. The
# pre-classification regular minimum and the PDT minimum are both
# named in the policy text.
CONSTANTS = {
    "regular_margin_minimum_equity": Decimal("2000"),
    "pattern_day_trader_minimum_equity": Decimal("25000"),
    "pdt_minimum_equity": Decimal("25000"),
    "pdt_day_trade_count_threshold": Decimal("4"),
    "pdt_day_trade_percentage_threshold": Decimal("0.06"),
    "pdt_lookback_business_days": Decimal("5"),
    "pdt_buying_power_multiplier": Decimal("4"),
}


def main():
    audit_dir = os.path.join(HERE, "audit_logs")
    result = run_probe(
        probe_name="probe_4_cross_domain_finra",
        policy_text=POLICY_TEXT,
        determination=DETERMINATION,
        voice=VOICE,
        constants=CONSTANTS,
        synthetic_cases=None,
        audit_dir=audit_dir,
    )

    print("\n" + "=" * 75)
    print("PROBE 4 DIAGNOSTIC")
    print("=" * 75)
    print("""
Read the spec tree above and answer the following:

  Q1. Did Build emit a sensible spec tree for a non-CBA policy?
      Compare structural complexity and naming hygiene against the CBA
      probes' output.

  Q2. Did it correctly identify the conditional minimum equity (PDT vs
      non-PDT)? This is a conditional-arithmetic check on a different
      domain. Cross-reference with Probe 1's findings.

  Q3. Did it identify the PDT classification predicate (4+ day trades
      AND >6% of total trades, within a 5-business-day window)? This is
      a compound Boolean condition on a categorical concept.

  Q4. Did Stage-4 conversion succeed? Note any naming mismatches in
      the constants registry — same pattern as Piece 7 with
      taxpayer_mle_amount.

  Q5. Sanity check: do the atom IDs and statements read naturally? If
      they have CBA-residual phrasing ("Salary Cap Year", "Player
      Contract"), the prompts have CBA-specific bleed-through and need
      cross-domain hardening.

The diagnostic outcome:
  - Clean tree comparable to CBA probes: prompts generalize, claim
    supported.
  - Sensible structure but degraded naming/precision: prompts mostly
    generalize, polish needed.
  - Broken or CBA-residual output: prompts are CBA-tuned, real cross-
    domain hardening required.
""")
    return result


if __name__ == "__main__":
    main()

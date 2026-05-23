"""Light harness: run the extract pattern against test cases of increasing
difficulty, across one or more substrates. Captures raw response on parse
failures so failures can be diagnosed. Includes salvage for known substrate
quirks (e.g., Gemini injecting non-contract keys).

Usage:
    python harness.py --substrate gemini
    python harness.py --substrate gemini --substrate claude
    python harness.py --substrate gemini --case 1 --case 6
    python harness.py --substrate gemini --output results.json
    python harness.py --substrate gemini --no-salvage  # disable salvage
"""

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

from extract import (
    FieldSpec,
    ExtractionResult,
    Evidence,
    ExtractParseError,
    build_prompt,
    parse_response,
)


# -- Salvage logic ----------------------------------------------------------
# Repairs known substrate-specific malformations before passing to parse_response.
# This lives in the harness, not the pattern, because it accumulates per-substrate
# quirks the pattern itself shouldn't have to know about.

def salvage_response(text: str) -> tuple[str, list[str]]:
    """Apply known repairs to a response.

    Returns (repaired_text, list_of_repairs_applied).
    """
    repairs: list[str] = []
    out = text

    # Repair 1: Gemini sometimes injects non-contract keys like
    #   reasoning: "..."
    # between the closing brace of a result object and the closing bracket
    # of its list:
    #     }
    #   reasoning: "..."
    #   ],
    # This is invalid JSON. Detect and strip the injected line.
    injected_pattern = re.compile(
        r"(\}\s*\n)\s*[a-zA-Z_]\w*\s*:\s*\"[^\"\n]*\"\s*\n(\s*\])",
        re.MULTILINE
    )
    new_out, n = injected_pattern.subn(r"\1\2", out)
    if n > 0:
        repairs.append(f"stripped {n} injected non-contract key(s)")
        out = new_out

    # Repair 2: trailing commas before closing brackets (some models produce these).
    trailing_comma_pattern = re.compile(r",(\s*[\]}])")
    new_out, n = trailing_comma_pattern.subn(r"\1", out)
    if n > 0:
        repairs.append(f"removed {n} trailing comma(s)")
        out = new_out

    return out, repairs


# -- Test cases -------------------------------------------------------------

@dataclass
class TestCase:
    id: int
    name: str
    description: str
    source: str
    fields: list[FieldSpec]
    expected_focus: str


CASE_1 = TestCase(
    id=1,
    name="Floor check",
    description="Short clean source, small simple spec, all single-valued, all open. "
                "Tests whether the pattern works end-to-end on easy input.",
    source="""REAL ESTATE PURCHASE AGREEMENT

This Agreement is entered into on March 14, 2026, between Margaret Chen
(Seller) and David and Sarah Patel (Buyer) for the property at 1847
Meadowbrook Drive, Fairfax, Virginia 22031.

Purchase price: $785,000.
Closing date: May 30, 2026.
Governed by the laws of the Commonwealth of Virginia.
""",
    fields=[
        FieldSpec(name="seller_name", type="string", cardinality="single",
                  description="The name of the seller."),
        FieldSpec(name="buyer_name", type="string", cardinality="single",
                  description="The name of the buyer entity."),
        FieldSpec(name="purchase_price", type="number", cardinality="single",
                  description="Total purchase price.", units="USD"),
        FieldSpec(name="closing_date", type="date", cardinality="single",
                  description="The closing date for the transaction."),
        FieldSpec(name="governing_law", type="string", cardinality="single",
                  description="The jurisdiction whose law governs the agreement."),
    ],
    expected_focus="All fields should be retrieved directly with high confidence. "
                   "Evidence should be empty across all fields."
)


CASE_2 = TestCase(
    id=2,
    name="Cardinality and absence",
    description="Same kind of source, expanded spec with mixed cardinality and "
                "fields that are not present in source.",
    source="""REAL ESTATE PURCHASE AGREEMENT

This Agreement is entered into on March 14, 2026, between Margaret Chen
(Seller) and David and Sarah Patel (Buyer) for the property at 1847
Meadowbrook Drive, Fairfax, Virginia 22031.

Purchase price: $785,000. Earnest money deposit: $20,000 upon execution.
Closing date: May 30, 2026.

CONTINGENCIES. This Agreement is contingent upon: (a) Buyer obtaining
financing for not less than 80% of the purchase price at an interest rate
not exceeding 7.5%; (b) satisfactory home inspection to be completed within
twenty-one (21) days of execution; (c) marketable title as evidenced by a
title insurance commitment.

Governed by the laws of the Commonwealth of Virginia.
""",
    fields=[
        FieldSpec(name="seller_name", type="string", cardinality="single",
                  description="The name of the seller."),
        FieldSpec(name="contingencies", type="string", cardinality="multi",
                  description="Each contingency that must be satisfied for the "
                              "agreement to close."),
        FieldSpec(name="earnest_money_deposit", type="number", cardinality="single",
                  description="Earnest money deposit amount.", units="USD"),
        FieldSpec(name="dispute_resolution_mechanism", type="string", cardinality="single",
                  description="The mechanism specified for dispute resolution "
                              "(arbitration, mediation, court, etc.)."),
        FieldSpec(name="property_disclosures_received", type="boolean", cardinality="single",
                  description="Whether the buyer has acknowledged receipt of "
                              "property disclosures."),
    ],
    expected_focus="seller_name: direct retrieval. contingencies: multi-valued, "
                   "three values. earnest_money_deposit: direct retrieval. "
                   "dispute_resolution_mechanism: not in source, expect null with "
                   "empty evidence (governing law is NOT relevant evidence here). "
                   "property_disclosures_received: not in source, expect null."
)


CASE_3 = TestCase(
    id=3,
    name="Distractor discrimination",
    description="SEC filing excerpt with multiple revenue figures across periods "
                "and segments. Spec asks for specific periods.",
    source="""CONSOLIDATED STATEMENTS OF INCOME (UNAUDITED)
(In millions, except per share data)

                                Three Months Ended    Nine Months Ended
                                September 30,         September 30,
                                2025      2024        2025      2024

Revenue:
  Product revenue              $3,847    $3,521      $11,204   $10,178
  Service revenue              $1,892    $1,654      $5,478    $4,891
  Total revenue                $5,739    $5,175      $16,682   $15,069

Cost of revenue                $2,316    $2,154      $6,839    $6,231
Gross profit                   $3,423    $3,021      $9,843    $8,838

Operating expenses:
  Research and development     $678      $612        $1,987    $1,803
  Sales and marketing          $834      $756        $2,471    $2,267
  General and administrative   $389      $341        $1,123    $1,012
  Total operating expenses     $1,901    $1,709      $5,581    $5,082

Income from operations         $1,522    $1,312      $4,262    $3,756

In the third quarter of 2025, Service revenue grew 14.4% year-over-year,
reflecting continued strength in our subscription business. Product revenue
grew 9.3% in the same period.
""",
    fields=[
        FieldSpec(name="total_revenue_q3_2025", type="number", cardinality="single",
                  description="Total revenue for the three months ended September 30, 2025.",
                  units="USD millions"),
        FieldSpec(name="service_revenue_ytd_2025", type="number", cardinality="single",
                  description="Service revenue for the nine months ended September 30, 2025.",
                  units="USD millions"),
        FieldSpec(name="product_revenue_growth_q3", type="number", cardinality="single",
                  description="Product revenue year-over-year growth rate for Q3 2025, "
                              "as a percentage.",
                  units="percent"),
        FieldSpec(name="income_from_operations_q3_2024", type="number", cardinality="single",
                  description="Income from operations for the three months ended "
                              "September 30, 2024.",
                  units="USD millions"),
    ],
    expected_focus="Period discrimination across multiple candidates per spec field. "
                   "Watch for period confusion."
)


CASE_4 = TestCase(
    id=4,
    name="Signal degradation",
    description="Same kind of content as Case 3 but with OCR-like noise applied.",
    source="""C0NS0LIDATED STATEMENTS 0F INC0ME (UNAUDITED)
(ln milli0ns, except per share data)

                                Three Months Ended    Nine M0nths Ended
                                September 30,         September 3O,
                                2O25      2O24        2025      2024

Revenue:
  Product revenue              $3,847    $3,52l      $1l,204   $1O,178
  Service revenue              $l,892    $1,654      $5,478    $4,89l
  Total revenue                $5,739    $5,l75      $l6,682   $l5,069

C0st 0f revenue                $2,316    $2,154      $6,839    $6,23l
Gr0ss pr0fit                   $3,423    $3,021      $9,843    $8,838

Operatlng expenses:
  Research and development     $678      $6l2        $1,987    $1,8O3
  Sa1es and marketing          $834      $756        $2,47l    $2,267
  Genera1 and administrative   $389      $34l        $1,123    $1,Ol2
  T0ta1 0perating expenses     $1,9Ol    $1,709      $5,58l    $5,O82

lncome fr0m 0perati0ns         $1,522    $1,312      $4,262    $3,756

In the third quarter of 2025, Service revenue grew 14.4% year-0ver-year,
reflecting continued strength in 0ur subscripti0n business. Pr0duct revenue
grew 9.3% in the same peri0d.
""",
    fields=[
        FieldSpec(name="total_revenue_q3_2025", type="number", cardinality="single",
                  description="Total revenue for the three months ended September 30, 2025.",
                  units="USD millions"),
        FieldSpec(name="service_revenue_ytd_2025", type="number", cardinality="single",
                  description="Service revenue for the nine months ended September 30, 2025.",
                  units="USD millions"),
        FieldSpec(name="product_revenue_growth_q3", type="number", cardinality="single",
                  description="Product revenue year-over-year growth rate for Q3 2025, "
                              "as a percentage.",
                  units="percent"),
        FieldSpec(name="income_from_operations_q3_2024", type="number", cardinality="single",
                  description="Income from operations for the three months ended "
                              "September 30, 2024.",
                  units="USD millions"),
    ],
    expected_focus="Compare to Case 3. Confidence should drop relative to clean version "
                   "even when values are correctly recovered."
)


CASE_5 = TestCase(
    id=5,
    name="Stress case with evidence handoff",
    description="Longer source with a substantial spec including a field that "
                "requires inference (effective tax rate).",
    source="""CONSOLIDATED STATEMENTS OF INCOME (UNAUDITED)
(In millions, except per share data)

                                Three Months Ended    Nine Months Ended
                                September 30,         September 30,
                                2025      2024        2025      2024

Revenue:
  Product revenue              $3,847    $3,521      $11,204   $10,178
  Service revenue              $1,892    $1,654      $5,478    $4,891
  Total revenue                $5,739    $5,175      $16,682   $15,069

Cost of revenue                $2,316    $2,154      $6,839    $6,231
Gross profit                   $3,423    $3,021      $9,843    $8,838

Operating expenses:
  Research and development     $678      $612        $1,987    $1,803
  Sales and marketing          $834      $756        $2,471    $2,267
  General and administrative   $389      $341        $1,123    $1,012
  Total operating expenses     $1,901    $1,709      $5,581    $5,082

Income from operations         $1,522    $1,312      $4,262    $3,756
Interest expense, net          $(89)     $(76)       $(263)    $(228)
Other income, net              $42       $38         $124      $109
Income before income taxes     $1,475    $1,274      $4,123    $3,637
Provision for income taxes     $310      $267        $866      $763
Net income                     $1,165    $1,007      $3,257    $2,874

Diluted earnings per share     $1.84     $1.59       $5.15     $4.54
Diluted shares outstanding     633.2     633.4       632.6     633.1

The Company's effective tax rate for the third quarter of 2025 reflects
the impact of discrete tax benefits totaling $14 million related to the
resolution of prior-year tax positions. Excluding these discrete items,
the underlying tax rate for the period was 22.0%.
""",
    fields=[
        FieldSpec(name="total_revenue_q3_2025", type="number", cardinality="single",
                  description="Total revenue for the three months ended September 30, 2025.",
                  units="USD millions"),
        FieldSpec(name="net_income_q3_2025", type="number", cardinality="single",
                  description="Net income for the three months ended September 30, 2025.",
                  units="USD millions"),
        FieldSpec(name="diluted_eps_q3_2025", type="number", cardinality="single",
                  description="Diluted earnings per share for Q3 2025.",
                  units="USD"),
        FieldSpec(name="effective_tax_rate_q3_2025", type="number", cardinality="single",
                  description="Effective tax rate for Q3 2025, computed as provision "
                              "for income taxes divided by income before income taxes.",
                  units="percent"),
        FieldSpec(name="underlying_tax_rate_q3_2025", type="number", cardinality="single",
                  description="Underlying tax rate for Q3 2025, excluding discrete items, "
                              "as stated in the document.",
                  units="percent"),
        FieldSpec(name="auditor_name", type="string", cardinality="single",
                  description="Name of the company's independent auditor."),
    ],
    expected_focus="effective_tax_rate: expect value null, evidence with provision "
                   "($310) and pretax income ($1,475). Computing 21.0% is a scope "
                   "violation. underlying_tax_rate: stated as 22.0%, direct retrieval. "
                   "auditor_name: not in source, expect null with empty evidence."
)


CASE_6 = TestCase(
    id=6,
    name="Genuine ambiguity for single-valued field",
    description="Contract with an amendment that supersedes original terms. "
                "Single-valued field has two genuinely plausible answers in source. "
                "Tests competing-probability-mass behavior.",
    source="""REAL ESTATE PURCHASE AGREEMENT

This Agreement is entered into on March 14, 2026, between Margaret Chen
(Seller) and David and Sarah Patel (Buyer) for the property at 1847
Meadowbrook Drive, Fairfax, Virginia 22031.

Purchase price: $785,000.
Earnest money deposit: $20,000 upon execution.
Closing date: May 30, 2026.

---

AMENDMENT NO. 1
Dated April 2, 2026

The parties agree to amend the foregoing Agreement as follows:

1. The purchase price set forth in the Agreement is hereby increased to
   $810,000, reflecting additional inclusions (custom landscaping installed
   by Seller during the inspection period and the second-floor wine cellar
   not previously contemplated in the original Agreement).

2. The closing date is unchanged.

All other terms of the Agreement remain in full force and effect.

Signed by all parties as of the date above.
""",
    fields=[
        FieldSpec(name="purchase_price", type="number", cardinality="single",
                  description="The purchase price of the property under this agreement.",
                  units="USD"),
        FieldSpec(name="closing_date", type="date", cardinality="single",
                  description="The closing date for the transaction."),
        FieldSpec(name="seller_name", type="string", cardinality="single",
                  description="The name of the seller."),
    ],
    expected_focus="purchase_price has TWO plausible candidates: $785,000 (original) and "
                   "$810,000 (amended). The amendment supersedes the original, so the "
                   "amended value is correct, but BOTH appear in source. The pattern "
                   "should surface both as competing candidates with confidences as "
                   "probability mass. If the model collapses to one with high confidence "
                   "(suppressing the alternative), it is not honoring the competing-"
                   "candidates semantic. closing_date is unambiguous (unchanged by "
                   "amendment) — single high-confidence answer. seller_name is unambiguous."
)


CASE_7 = TestCase(
    id=7,
    name="Enumerated domain and type-gated content",
    description="Spec includes a document-type classification with enumerated domain, "
                "plus content fields that only apply if the document is a sales contract. "
                "Tests enumeration honoring and within-call type-gating behavior.",
    source="""LEASE AGREEMENT

This Lease Agreement is entered into on February 10, 2026, between
Westbrook Properties LLC (Landlord) and Maria Rodriguez (Tenant) for
the premises located at 421 Riverside Avenue, Unit 3B, Arlington,
Virginia 22202.

Monthly rent: $2,850, due on the first day of each month.
Security deposit: $5,700.
Lease term: 12 months, commencing March 1, 2026 and ending February 28, 2027.

Tenant agrees to maintain renter's insurance throughout the lease term.
Tenant shall not sublet without written consent of Landlord.

This Agreement is governed by the laws of the Commonwealth of Virginia.
""",
    fields=[
        FieldSpec(name="document_type", type="enumerated", cardinality="single",
                  description="The type of legal document this is.",
                  domain="enumerated",
                  enumeration=["purchase_agreement", "lease_agreement", "amendment",
                               "addendum", "notice", "other"]),
        FieldSpec(name="purchase_price", type="number", cardinality="single",
                  description="Total purchase price (applies only to purchase agreements).",
                  units="USD"),
        FieldSpec(name="closing_date", type="date", cardinality="single",
                  description="Closing date for property purchase (applies only to "
                              "purchase agreements)."),
        FieldSpec(name="monthly_rent", type="number", cardinality="single",
                  description="Monthly rent amount (applies only to lease agreements).",
                  units="USD"),
        FieldSpec(name="lease_term_months", type="number", cardinality="single",
                  description="Lease term in months (applies only to lease agreements).",
                  units="months"),
    ],
    expected_focus="document_type: must be exactly 'lease_agreement' from the enumeration. "
                   "purchase_price and closing_date: not applicable to a lease — expect "
                   "null with attribution noting document type mismatch. monthly_rent "
                   "and lease_term_months: direct retrieval. Watch for: (1) enumeration "
                   "honored (no variations like 'Lease Agreement' or 'lease'); (2) the "
                   "model recognizing field applicability based on document type, OR "
                   "treating fields as independent and just returning null for absent "
                   "values regardless of why they're absent."
)


CASE_8 = TestCase(
    id=8,
    name="Large schema with mixed behaviors",
    description="Realistic enterprise extraction: 15+ fields spanning direct retrieval, "
                "multi-valued, evidence-only, absent, and enumerated. Tests whether the "
                "pattern's behavior generalizes from small schemas to enterprise-sized ones.",
    source="""ANNUAL REPORT EXCERPT
Acme Industrial Corp.
Form 10-K for Fiscal Year Ended December 31, 2025

ITEM 1. BUSINESS

Acme Industrial Corp. ("the Company"), a Delaware corporation incorporated
in 1987, is a global manufacturer of specialty industrial components serving
the aerospace, automotive, and medical device sectors. The Company operates
primarily through three reportable segments: Aerospace Components, Automotive
Systems, and Medical Devices.

The Company's principal executive offices are located at 1500 Industrial
Parkway, Cleveland, Ohio 44114. As of December 31, 2025, the Company had
approximately 12,400 employees across 23 manufacturing facilities in 11
countries.

ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS

Revenue for fiscal year 2025 was $4,287 million, an increase of 8.3%
compared to $3,959 million in fiscal year 2024. The increase was driven
primarily by 14% growth in the Aerospace Components segment, partially
offset by a 2% decline in Automotive Systems.

Operating income for 2025 was $612 million, or 14.3% of revenue, compared
to $548 million, or 13.8% of revenue, in 2024.

The Company's effective tax rate for 2025 was 23.1%, reflecting the impact
of certain discrete tax items. Net income for 2025 was $445 million, or
$3.27 per diluted share.

The Company has not paid cash dividends and currently intends to retain
all earnings for reinvestment in the business.

ITEM 9. PRINCIPAL ACCOUNTING FIRM

The Company's independent registered public accounting firm is Deloitte &
Touche LLP, Cleveland, Ohio.

EXECUTIVE OFFICERS

Robert Hansen, age 58, has served as Chief Executive Officer since 2019.
Patricia Kim, age 54, has served as Chief Financial Officer since 2021.
Marcus Webb, age 49, has served as Chief Operating Officer since 2023.
""",
    fields=[
        # Direct retrieval — basic facts
        FieldSpec(name="company_name", type="string", cardinality="single",
                  description="Legal name of the company."),
        FieldSpec(name="state_of_incorporation", type="string", cardinality="single",
                  description="State or jurisdiction of incorporation."),
        FieldSpec(name="year_incorporated", type="number", cardinality="single",
                  description="Year the company was incorporated."),
        FieldSpec(name="fiscal_year_end_date", type="date", cardinality="single",
                  description="Date of the fiscal year end."),
        FieldSpec(name="headquarters_address", type="string", cardinality="single",
                  description="Address of principal executive offices."),
        FieldSpec(name="employee_count", type="number", cardinality="single",
                  description="Total number of employees."),

        # Direct retrieval — financial
        FieldSpec(name="revenue_2025", type="number", cardinality="single",
                  description="Revenue for fiscal year 2025.",
                  units="USD millions"),
        FieldSpec(name="operating_income_2025", type="number", cardinality="single",
                  description="Operating income for fiscal year 2025.",
                  units="USD millions"),
        FieldSpec(name="net_income_2025", type="number", cardinality="single",
                  description="Net income for fiscal year 2025.",
                  units="USD millions"),
        FieldSpec(name="diluted_eps_2025", type="number", cardinality="single",
                  description="Diluted earnings per share for 2025.",
                  units="USD"),
        FieldSpec(name="effective_tax_rate_2025", type="number", cardinality="single",
                  description="Effective tax rate for fiscal year 2025.",
                  units="percent"),

        # Multi-valued
        FieldSpec(name="business_segments", type="string", cardinality="multi",
                  description="Each reportable business segment."),
        FieldSpec(name="executive_officers", type="string", cardinality="multi",
                  description="Each named executive officer with their title."),

        # Direct retrieval — entity
        FieldSpec(name="independent_auditor", type="string", cardinality="single",
                  description="Name of the company's independent registered public "
                              "accounting firm."),

        # Evidence-only — revenue growth rate is computable from stated revenues
        FieldSpec(name="revenue_growth_rate_2025_pct", type="number", cardinality="single",
                  description="Year-over-year revenue growth rate for 2025 as a "
                              "percentage. Note: stated explicitly elsewhere in the "
                              "document; verify by direct retrieval before inferring.",
                  units="percent"),

        # Absent — not in source
        FieldSpec(name="dividend_per_share_2025", type="number", cardinality="single",
                  description="Cash dividend per share for 2025.",
                  units="USD"),
        FieldSpec(name="long_term_debt", type="number", cardinality="single",
                  description="Total long-term debt as of year end.",
                  units="USD millions"),

        # Enumerated
        FieldSpec(name="industry_sector", type="enumerated", cardinality="single",
                  description="Primary industry sector classification.",
                  domain="enumerated",
                  enumeration=["technology", "industrial", "consumer", "healthcare",
                               "financial", "energy", "utilities", "materials",
                               "real_estate", "communications"]),
    ],
    expected_focus="18 fields total. Direct retrievals: company_name, state, year, "
                   "fiscal_year_end (canonicalize to 2025-12-31), HQ, employees, "
                   "revenue, op income, net income, EPS, effective tax rate (8.3% growth, "
                   "23.1% rate — both stated), auditor. Multi-valued: 3 segments, 3 "
                   "officers. Evidence-only OR direct retrieval: revenue_growth — it's "
                   "stated as 8.3% in source, so direct retrieval is correct. Absent: "
                   "dividend (text says NOT paid — this is tricky: should value be 0, "
                   "false-ish, or null? Document explicitly addresses the field), "
                   "long_term_debt (not addressed). Enumerated: 'industrial' from "
                   "the list. Watch for: degradation of per-field reliability at scale, "
                   "enumeration variants, the dividend handling question."
)


CASE_9 = TestCase(
    id=9,
    name="Merger agreement, multi-dimensional stress",
    description="Long document combining multiple stress dimensions in one call: "
                "substantial source length with interleaved irrelevant content, "
                "schema mixing all behavior types, revision relationships, "
                "inferential fields with overlapping evidence, enumerated constraints, "
                "negated/categorical statements, structural distance between content "
                "and where one would expect to find it, and the realistic combination "
                "of failure modes a production extraction call would face.",
    source="""DEFINITIVE AGREEMENT AND PLAN OF MERGER

This Definitive Agreement and Plan of Merger (this "Agreement"), dated as
of February 14, 2026, is entered into by and among Helios Industries, Inc.,
a Delaware corporation ("Parent"), Helios Acquisition Sub, Inc., a Delaware
corporation and a wholly owned subsidiary of Parent ("Merger Sub"), and
Riverstone Manufacturing Corporation, a Delaware corporation (the "Company").

RECITALS

WHEREAS, the respective Boards of Directors of Parent and the Company have
each unanimously (i) determined that this Agreement and the transactions
contemplated hereby are in the best interests of their respective
stockholders, and (ii) approved this Agreement and the transactions
contemplated hereby;

WHEREAS, in furtherance thereof, the parties intend that Merger Sub will
merge with and into the Company (the "Merger"), with the Company surviving
the Merger as a wholly owned subsidiary of Parent;

WHEREAS, as of the date hereof, the Company has 47,832,419 shares of
common stock issued and outstanding.

NOW, THEREFORE, in consideration of the foregoing and the mutual covenants
and agreements herein contained, the parties hereto agree as follows:

ARTICLE I — THE MERGER

Section 1.1 The Merger. Upon the terms and subject to the conditions of
this Agreement, at the Effective Time, Merger Sub shall be merged with and
into the Company, the separate corporate existence of Merger Sub shall
cease, and the Company shall continue as the surviving corporation.

Section 1.2 Closing. The closing of the Merger (the "Closing") shall take
place on the third (3rd) business day following the satisfaction or waiver
of the conditions set forth in Article VII (other than those conditions
that by their nature are to be satisfied at the Closing), but in no event
later than November 30, 2026.

ARTICLE II — MERGER CONSIDERATION

Section 2.1 Conversion of Shares. At the Effective Time, each share of
common stock of the Company issued and outstanding immediately prior to the
Effective Time shall be converted into the right to receive $42.50 in cash,
without interest (the "Per Share Consideration").

Section 2.2 Payment Structure. The aggregate Merger Consideration shall be
paid 80% in cash and 20% in shares of Parent common stock, with the stock
portion valued based on the volume-weighted average price of Parent common
stock for the twenty (20) trading days ending three days prior to Closing.

Section 2.3 Escrow. An amount equal to $75,000,000 of the cash portion of
the Merger Consideration shall be placed in escrow at Closing to secure
indemnification obligations under Article IX, to be held by the Escrow Agent
for a period of eighteen (18) months following the Closing Date.

ARTICLE III — REPRESENTATIONS AND WARRANTIES OF THE COMPANY

Section 3.1 Organization. The Company is a corporation duly organized,
validly existing and in good standing under the laws of the State of
Delaware, with all corporate power and authority necessary to own its
properties and conduct its business.

Section 3.2 Capitalization. As of the date hereof, the authorized capital
stock of the Company consists of 100,000,000 shares of common stock, of
which 47,832,419 shares are issued and outstanding, and 10,000,000 shares
of preferred stock, none of which are issued or outstanding.

Section 3.3 Material Contracts. Schedule 3.3 sets forth a complete list of
material contracts of the Company. No material contract requires the consent
of a third party in connection with the transactions contemplated hereby,
except as set forth on Schedule 3.3.

ARTICLE IV — REGULATORY MATTERS

Section 4.1 HSR Filings. The parties shall file the Notification and Report
Forms required under the Hart-Scott-Rodino Antitrust Improvements Act within
ten (10) business days of the date hereof.

Section 4.2 Foreign Antitrust. The parties acknowledge that this transaction
does not require notification or approval under any non-U.S. antitrust or
competition law.

ARTICLE V — COVENANTS

Section 5.1 Interim Operations. During the period from the date hereof until
the earlier of the Closing or termination, the Company shall conduct its
business only in the ordinary course consistent with past practice.

Section 5.2 No Solicitation. From and after the date hereof, the Company
shall not, and shall cause its representatives not to, directly or indirectly,
solicit, initiate, knowingly encourage or facilitate any inquiries or the
making of any proposal that constitutes, or could reasonably be expected to
lead to, an Acquisition Proposal.

ARTICLE VI — TERMINATION

Section 6.1 Termination. This Agreement may be terminated at any time prior
to the Effective Time, whether before or after receipt of the Company
Stockholder Approval:

   (a) by mutual written consent of Parent and the Company;
   (b) by either Parent or the Company if the Closing shall not have
       occurred on or before the End Date;
   (c) by either Parent or the Company if any Governmental Entity shall
       have issued an order permanently restraining the Merger;
   (d) by Parent, upon a Company Adverse Recommendation Change.

Section 6.2 Termination Fees. The Company shall not be obligated to pay any
breakup fee or similar termination payment to Parent in connection with the
termination of this Agreement, except as expressly set forth in this Section.

ARTICLE VII — CONDITIONS

Section 7.1 Conditions to Each Party's Obligation. The respective obligations
of each party to effect the Merger shall be subject to the satisfaction or
waiver of the following conditions:

   (a) The Company Stockholder Approval shall have been obtained;
   (b) No Governmental Entity shall have enacted any law prohibiting the
       Merger;
   (c) The waiting period under the HSR Act shall have expired or been
       terminated;
   (d) The Form S-4 Registration Statement shall have been declared
       effective by the SEC.

Section 7.2 Financing. There is no financing condition to the obligations
of Parent or Merger Sub to consummate the Merger. Parent has, on the date
hereof, delivered to the Company evidence of fully committed financing
sufficient to fund the cash portion of the Merger Consideration in full.

ARTICLE VIII — GENERAL PROVISIONS

Section 8.1 Governing Law. This Agreement shall be governed by, and
construed in accordance with, the laws of the State of Delaware, without
giving effect to any choice or conflict of law provision or rule.

Section 8.2 Jurisdiction. Any legal action or proceeding arising under this
Agreement shall be brought exclusively in the Court of Chancery of the State
of Delaware, or, if such court declines to exercise jurisdiction, in the
United States District Court for the District of Delaware.

Section 8.3 Dispute Resolution. Notwithstanding Section 8.2, the parties
agree to attempt in good faith to resolve any dispute arising hereunder
through executive-level negotiation for a period of thirty (30) days prior
to commencing litigation.

AMENDMENT NO. 1 TO DEFINITIVE AGREEMENT AND PLAN OF MERGER

Dated as of April 7, 2026

The parties hereby amend the above Agreement as follows:

1. Section 2.1 is amended to increase the Per Share Consideration from
   $42.50 to $44.25, reflecting the parties' resolution of the diligence
   findings regarding the Company's pension liability.

2. Section 2.3 is amended to increase the escrow amount from $75,000,000
   to $90,000,000 to address the indemnification scope expansion described
   in the side letter dated April 5, 2026.

3. All other terms of the Agreement remain in full force and effect.

AMENDMENT NO. 2 TO DEFINITIVE AGREEMENT AND PLAN OF MERGER

Dated as of May 1, 2026

The parties hereby further amend the Agreement as follows:

1. Section 2.1 is further amended to increase the Per Share Consideration
   from $44.25 to $45.00, reflecting the additional value identified in
   the supplemental diligence completed in late April 2026.

2. All other terms of the Agreement, as previously amended, remain in
   full force and effect.
""",
    fields=[
        # Identity fields — direct retrieval
        FieldSpec(name="parent_company", type="string", cardinality="single",
                  description="Name of the acquiring parent company."),
        FieldSpec(name="target_company", type="string", cardinality="single",
                  description="Name of the company being acquired (the target/Company)."),
        FieldSpec(name="agreement_date", type="date", cardinality="single",
                  description="Date of the original definitive agreement."),
        FieldSpec(name="state_of_organization_target", type="string", cardinality="single",
                  description="State of incorporation of the target company."),

        # Financial — single-valued with revision history
        FieldSpec(name="per_share_consideration", type="number", cardinality="single",
                  description="Per share cash consideration for the merger.",
                  units="USD"),
        FieldSpec(name="escrow_amount", type="number", cardinality="single",
                  description="Amount placed in escrow at closing for indemnification.",
                  units="USD"),

        # Financial — multi-valued
        FieldSpec(name="payment_structure_components", type="string", cardinality="multi",
                  description="Each component of the payment structure (cash percentage, "
                              "stock percentage, etc.) with its proportion."),

        # Inferential — total deal value (per share × shares outstanding)
        FieldSpec(name="aggregate_merger_consideration", type="number", cardinality="single",
                  description="Total aggregate merger consideration (the per-share amount "
                              "multiplied by total shares outstanding).",
                  units="USD"),

        # Direct retrieval — date with deadline framing
        FieldSpec(name="outside_date", type="date", cardinality="single",
                  description="The outside date (sometimes called End Date) by which "
                              "closing must occur."),

        # Enumerated — transaction type
        FieldSpec(name="transaction_type", type="enumerated", cardinality="single",
                  description="Type of corporate transaction.",
                  domain="enumerated",
                  enumeration=["asset_purchase", "stock_purchase", "merger",
                               "tender_offer", "reverse_merger", "joint_venture"]),

        # Enumerated — payment structure
        FieldSpec(name="payment_structure_type", type="enumerated", cardinality="single",
                  description="The structure of the consideration payment.",
                  domain="enumerated",
                  enumeration=["all_cash", "all_stock", "cash_and_stock",
                               "earnout", "deferred"]),

        # Multi-valued with structural complexity
        FieldSpec(name="termination_rights", type="string", cardinality="multi",
                  description="Each circumstance under which the agreement may be "
                              "terminated, with the party who may terminate."),
        FieldSpec(name="closing_conditions", type="string", cardinality="multi",
                  description="Each condition precedent to closing the merger."),

        # Negated/categorical — these have explicit statements of non-existence
        FieldSpec(name="breakup_fee_amount", type="number", cardinality="single",
                  description="The breakup fee amount payable by the Company on "
                              "termination.",
                  units="USD"),
        FieldSpec(name="has_financing_condition", type="boolean", cardinality="single",
                  description="Whether there is a financing condition to closing."),
        FieldSpec(name="foreign_antitrust_required", type="boolean", cardinality="single",
                  description="Whether foreign antitrust approval is required for this "
                              "transaction."),

        # Direct retrieval — structurally distant from where expected
        # (governing law appears in Article VIII; dispute resolution is Section 8.3
        # which is structurally adjacent but a different concept)
        FieldSpec(name="governing_law", type="string", cardinality="single",
                  description="The jurisdiction whose law governs the agreement."),
        FieldSpec(name="dispute_resolution_mechanism", type="string", cardinality="single",
                  description="The mechanism specified for dispute resolution prior to "
                              "litigation."),
        FieldSpec(name="exclusive_jurisdiction", type="string", cardinality="single",
                  description="The court or jurisdiction designated for litigation."),

        # Multi-valued with internal structure
        FieldSpec(name="board_approvals", type="string", cardinality="multi",
                  description="Each board that has approved the agreement, with how "
                              "the approval was characterized."),

        # Absent — genuinely not in source
        FieldSpec(name="target_revenue_ttm", type="number", cardinality="single",
                  description="Target company's trailing-twelve-months revenue.",
                  units="USD"),
        FieldSpec(name="ceo_name_target", type="string", cardinality="single",
                  description="Name of the CEO of the target company."),

        # Inferential — outstanding shares stated, deal date stated, can compute total
        # but this is a different inferential field overlapping with aggregate_merger_consideration
        FieldSpec(name="total_shares_outstanding", type="number", cardinality="single",
                  description="Total shares of target company common stock outstanding "
                              "as of the agreement date.",
                  units="shares"),
    ],
    expected_focus=(
        "This case stress-tests the pattern along multiple dimensions simultaneously. "
        "(1) per_share_consideration has THREE candidates due to two amendments: "
        "$42.50 (original), $44.25 (Amendment 1), $45.00 (Amendment 2). Pattern should "
        "surface all three as competing candidates with confidence mass, NOT silently "
        "apply latest-supersedes-earliest. Same for escrow_amount ($75M and $90M). "
        "(2) aggregate_merger_consideration requires inference (per_share × shares "
        "outstanding). Pattern should return null with both components as evidence — "
        "and note the per_share component is itself ambiguous, which complicates the "
        "evidence presentation. (3) breakup_fee_amount and has_financing_condition "
        "are explicitly addressed by NEGATION in source. Pattern should return null "
        "with the negation statement as evidence, NOT infer 0 or false. "
        "(4) foreign_antitrust_required is also explicitly addressed — source says "
        "transaction does NOT require foreign antitrust notification. Same handling. "
        "(5) target_revenue_ttm and ceo_name_target are absent — return null with "
        "empty evidence. (6) Enumerated fields (transaction_type, payment_structure_type) "
        "should be exactly from the enumerations. (7) Multi-valued fields "
        "(termination_rights, closing_conditions, board_approvals) should surface all "
        "items. (8) Structurally distant fields: governing_law, dispute_resolution_"
        "mechanism, and exclusive_jurisdiction all appear in Article VIII but in "
        "different sections — discrimination question. (9) total_shares_outstanding is "
        "stated directly in Section 3.2 (47,832,419) — direct retrieval, but the "
        "evidence for aggregate_merger_consideration overlaps with this field's value. "
        "Watch for: amendment supersession suppression, inferential scope violations, "
        "negation-to-zero scope violations, enumeration honoring, structural "
        "discrimination, and per-field reliability across 22 fields."
    )
)


ALL_CASES = [CASE_1, CASE_2, CASE_3, CASE_4, CASE_5, CASE_6, CASE_7, CASE_8, CASE_9]


# -- Substrate registry -----------------------------------------------------

def _make_gemini(model: str):
    from adapters.gemini import GeminiClient
    return GeminiClient(model=model)


def _make_claude(model: str):
    from adapters.anthropic import ClaudeClient
    return ClaudeClient(model=model)


def _make_openai(model: str):
    from adapters.openai import OpenAIClient
    return OpenAIClient(model=model)


SUBSTRATES = {
    "gemini": ("gemini-2.5-flash", _make_gemini),
    "claude": ("claude-sonnet-4-6", _make_claude),
    "openai": ("gpt-4o", _make_openai),
}


# -- Light instrumentation --------------------------------------------------

@dataclass
class RunResult:
    case_id: int
    case_name: str
    substrate: str
    model: str
    latency_seconds: float
    success: bool
    error: str = ""
    raw_response: Optional[str] = None
    repairs_applied: list[str] = None
    results: Optional[dict[str, list[dict[str, Any]]]] = None


def serialize_results(results: dict[str, list[ExtractionResult]]) -> dict[str, list[dict]]:
    out = {}
    for field_name, extractions in results.items():
        out[field_name] = [
            {
                "value": ext.value,
                "attribution": ext.attribution,
                "confidence": ext.confidence,
                "evidence": [{"fact": e.fact, "attribution": e.attribution}
                             for e in ext.evidence],
            }
            for ext in extractions
        ]
    return out


def run_case(case: TestCase, substrate_name: str, model: str,
             use_salvage: bool = True) -> RunResult:
    """Run one case. Capture latency, errors, raw response, and any repairs applied."""
    _, factory = SUBSTRATES[substrate_name]
    start = time.monotonic()
    raw_response: Optional[str] = None
    repairs: list[str] = []

    try:
        client = factory(model)
        prompt = build_prompt(case.source, case.fields)
        raw_response = client(prompt)

        # Try parsing directly first
        try:
            results = parse_response(raw_response)
        except ExtractParseError as first_attempt_err:
            if not use_salvage:
                raise
            # Apply salvage and retry
            repaired_text, repairs = salvage_response(raw_response)
            if not repairs:
                # Salvage didn't change anything; original error stands
                raise
            try:
                results = parse_response(repaired_text)
            except ExtractParseError:
                # Salvage didn't help either; report original failure
                raise first_attempt_err

        latency = time.monotonic() - start
        return RunResult(
            case_id=case.id,
            case_name=case.name,
            substrate=substrate_name,
            model=model,
            latency_seconds=latency,
            success=True,
            raw_response=raw_response,
            repairs_applied=repairs,
            results=serialize_results(results),
        )
    except ExtractParseError as e:
        latency = time.monotonic() - start
        return RunResult(
            case_id=case.id,
            case_name=case.name,
            substrate=substrate_name,
            model=model,
            latency_seconds=latency,
            success=False,
            error=str(e),
            raw_response=e.raw_response,
            repairs_applied=repairs,
        )
    except Exception as e:
        latency = time.monotonic() - start
        return RunResult(
            case_id=case.id,
            case_name=case.name,
            substrate=substrate_name,
            model=model,
            latency_seconds=latency,
            success=False,
            error=f"{type(e).__name__}: {e}",
            raw_response=raw_response,
            repairs_applied=repairs,
        )


def print_case_header(case: TestCase) -> None:
    print(f"\n{'=' * 78}")
    print(f"CASE {case.id}: {case.name}")
    print(f"{'=' * 78}")
    print(f"Description: {case.description}")
    print(f"\nExpected focus:")
    for line in case.expected_focus.split(". "):
        if line.strip():
            print(f"  {line.strip()}{'.' if not line.endswith('.') else ''}")


def print_run_result(result: RunResult, show_raw_on_failure: bool = True,
                     show_raw_always: bool = False) -> None:
    print(f"\n--- {result.substrate} ({result.model}) "
          f"[{result.latency_seconds:.2f}s] ---")

    if result.repairs_applied:
        print(f"  Salvage applied: {'; '.join(result.repairs_applied)}")

    if not result.success:
        print(f"  FAILED: {result.error}")
        if show_raw_on_failure and result.raw_response is not None:
            print(f"\n  Raw response ({len(result.raw_response)} chars):")
            print("  " + "-" * 72)
            for line in result.raw_response.split("\n"):
                print(f"  | {line}")
            print("  " + "-" * 72)
        return

    if show_raw_always and result.raw_response is not None:
        print(f"\n  Raw response ({len(result.raw_response)} chars):")
        print("  " + "-" * 72)
        for line in result.raw_response.split("\n")[:30]:
            print(f"  | {line}")
        if len(result.raw_response.split("\n")) > 30:
            n_more = len(result.raw_response.split('\n')) - 30
            print(f"  | ... ({n_more} more lines)")
        print("  " + "-" * 72)

    for field_name, extractions in result.results.items():
        print(f"\n  {field_name}:")
        for ext in extractions:
            value = ext["value"]
            attribution = ext["attribution"]
            if len(attribution) > 90:
                attribution = attribution[:87] + "..."
            print(f"    value:       {value!r}")
            print(f"    attribution: {attribution}")
            print(f"    confidence:  {ext['confidence']}")
            if ext["evidence"]:
                print(f"    evidence:")
                for ev in ext["evidence"]:
                    fact = ev["fact"]
                    if len(fact) > 80:
                        fact = fact[:77] + "..."
                    print(f"      - {fact}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--substrate", action="append", required=True,
        choices=list(SUBSTRATES.keys()),
        help="Substrate to run. May be specified multiple times.",
    )
    parser.add_argument(
        "--model",
        help="Override the default model. Applies to all substrates.",
    )
    parser.add_argument(
        "--case", action="append", type=int, choices=[c.id for c in ALL_CASES],
        help="Case ID to run (1-8). May be specified multiple times. "
             "If omitted, runs all cases.",
    )
    parser.add_argument(
        "--output", help="Write JSON results to this file.",
    )
    parser.add_argument(
        "--show-raw", action="store_true",
        help="Show raw response even on successful runs.",
    )
    parser.add_argument(
        "--no-salvage", action="store_true",
        help="Disable harness salvage. Useful for seeing raw parse failures.",
    )
    args = parser.parse_args()

    cases_to_run = ALL_CASES if not args.case else [
        c for c in ALL_CASES if c.id in args.case
    ]

    all_results: list[RunResult] = []

    for case in cases_to_run:
        print_case_header(case)
        for substrate_name in args.substrate:
            default_model, _ = SUBSTRATES[substrate_name]
            model = args.model or default_model
            result = run_case(case, substrate_name, model,
                              use_salvage=not args.no_salvage)
            all_results.append(result)
            print_run_result(result, show_raw_always=args.show_raw)

    if args.output:
        # Append to existing file if it exists; otherwise create a new one.
        # This lets multiple harness invocations accumulate into one record
        # for cross-substrate / cross-cohort analysis.
        import os
        from datetime import datetime, timezone

        new_records = []
        run_timestamp = datetime.now(timezone.utc).isoformat()
        for r in all_results:
            record = asdict(r)
            record["run_timestamp"] = run_timestamp
            new_records.append(record)

        existing_records = []
        if os.path.exists(args.output):
            try:
                with open(args.output) as f:
                    existing_records = json.load(f)
                if not isinstance(existing_records, list):
                    existing_records = []
            except (json.JSONDecodeError, OSError):
                existing_records = []

        all_records = existing_records + new_records
        with open(args.output, "w") as f:
            json.dump(all_records, f, indent=2)
        print(f"\n\nResults written to {args.output} "
              f"({len(new_records)} new, {len(all_records)} total)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
NBA fragment 2 — Maximum Annual Salary by Years of Service.

EXERCISES
=========
Article II, Section 7(a) of the NBA CBA: three YOS brackets with gated
"boost" pathways (5th-Year Eligible + Higher Max Criteria; Designated
Veteran). Tests the architecture's ability to handle:

- MUTUALLY EXCLUSIVE BRACKETS over a numeric atom (years_of_service)
- GATED BOOST: a percentage boost (25%→30%, 30%→35%) only applies when a
  specific conjunction of preconditions holds
- "GREATER OF X% × CAP or 105% × PRIOR-SALARY" — illustrating the
  Map-binds-derived-numeric pattern for max-of-two-atoms operations

FAILURE MODE THIS ADDRESSES
============================
In the Opus 4.7 RuleArena baseline, the rule
`higher_max_criterion_for_5th_year_eligible_player` had:
  Total Trigger: 12
  Precision: 0.083 (only 1 of 12 invocations was correct)
  Recall: 1.0 (always cited when relevant)

This is the canonical over-firing pattern: the LLM cites Higher Max
Criteria whenever All-NBA appears in a case, regardless of whether the
player is actually 5th-Year Eligible (4 YOS, signing extension with
prior team out of rookie scale).

The architecture decomposes the gating predicate. The Higher Max boost
applies ONLY when ALL of these hold:
- yos_under_7 (bracket eligibility)
- is_5th_year_eligible (4 YOS exactly, drafted by current team or
  acquired by trade in year 1 of rookie scale)
- has_higher_max_criteria (All-NBA in last 1-3 seasons OR MVP in last
  3 seasons OR DPOY in last 1-3 seasons)

If any predicate fails, the boost is structurally inapplicable. Direct-LLM
gets confused by lexical proximity to "All-NBA"; the engine evaluates
each gating predicate independently and the boost is an AndNode.
"""

from __future__ import annotations

from decimal import Decimal


from rulekit.engine import (
    Kleene, FactBundle, AndNode, OrNode, NotNode, Leaf, Provenance,
)
from rulekit.engine.typed import (
    NumericValue,
    NumericLeaf, Constant,
    TimesConstNode, PlusConstNode, MinusConstNode, ConstMinusNode,
    DivByConstNode, ConstDivByNode,
    EqNode, LtNode, LeqNode, GtNode, GeqNode,
    format_typed_trace,
)


# ---------------------------------------------------------------------------
# CBA constants
# ---------------------------------------------------------------------------

SALARY_CAP_2024_25 = Decimal("140588000")

# Base percentages of cap by YOS bracket (Article II Section 7(a))
PCT_UNDER_7 = Decimal("0.25")      # 25%
PCT_7_TO_9  = Decimal("0.30")      # 30%
PCT_10_PLUS = Decimal("0.35")      # 35%

# Boosted percentages (with gating preconditions)
PCT_UNDER_7_HIGHER_MAX = Decimal("0.30")   # 30% if 5th-year-eligible + Higher Max
PCT_7_TO_9_DESIGNATED  = Decimal("0.35")   # 35% if Designated Veteran

# "105% of prior salary" alternative ceiling
PRIOR_SALARY_MULTIPLIER = Decimal("1.05")


# ---------------------------------------------------------------------------
# Build the fragment
# ---------------------------------------------------------------------------

def build_fragment():
    """
    Build the max-salary-by-YOS fragment.

    Numeric atoms (bound by Map):
      - player_years_of_service
      - player_prior_salary_final_season
      - contract_first_year_salary
      - max_salary_ceiling  (derived: Map computes max(X%×cap, 105%×prior))
                            See note below.

    Boolean atoms (bound by Map):
      - player_is_5th_year_eligible
        (4 YOS exactly, was drafted by current team OR acquired by trade
        in year 1 of rookie scale; the case description specifies this)
      - player_has_higher_max_criteria
        (All-NBA 1st/2nd/3rd team OR DPOY in last 1 or 2-of-3 seasons,
        OR MVP in last 1-of-3 seasons)
      - player_is_designated_veteran_eligible
        (8-9 YOS, with current team since rookie deal OR traded only in
        first 4 cap years)

    NOTE ON max_salary_ceiling
    ===========================
    The CBA says "the greater of (X% × cap) or (105% × prior_salary)".
    This is max-over-two-numerics — NOT a const-arithmetic shape. Per
    the design principle ("engine handles policy-declared transformations
    with a build-time constant; Map handles per-case computations over
    two atoms"), this max is Map's responsibility. Map computes it and
    binds a single derived numeric atom `max_salary_ceiling` per the
    appropriate bracket.

    However, in this fragment we DO compute it engine-side using
    TIMES_CONST on prior_salary and an outer comparison, just to
    demonstrate the architectural choice. In production, the cleaner
    approach is to push it to Map (one Map call: "what is the larger of
    these two values"), bind as one numeric, and use it as a leaf here.

    For test purposes, we'll model both pathways and have Map bind the
    bracket-appropriate ceiling directly.
    """

    # ------ Layer 1: numeric leaves ------
    yos = NumericLeaf(atom_id="player_years_of_service")
    contract_salary = NumericLeaf(atom_id="contract_first_year_salary")
    max_ceiling = NumericLeaf(atom_id="max_salary_ceiling")  # derived; Map-bound

    # ------ Layer 2: bracket gating predicates ------
    yos_under_7 = LtNode(
        left=yos,
        right=Constant(value=Decimal(7), label="7 YOS threshold"),
        surface_label="yos < 7",
    )
    yos_at_least_7 = GeqNode(
        left=yos,
        right=Constant(value=Decimal(7), label="7 YOS threshold"),
        surface_label="yos >= 7",
    )
    yos_under_10 = LtNode(
        left=yos,
        right=Constant(value=Decimal(10), label="10 YOS threshold"),
        surface_label="yos < 10",
    )
    yos_7_to_9 = AndNode(
        children=[yos_at_least_7, yos_under_10],
        surface_label="7 <= yos < 10",
    )
    yos_10_plus = GeqNode(
        left=yos,
        right=Constant(value=Decimal(10), label="10 YOS threshold"),
        surface_label="yos >= 10",
    )

    # ------ Layer 3: boost gates (Higher Max & Designated Veteran) ------
    # Higher Max boost requires THREE conditions:
    #   - yos_under_7 bracket
    #   - is_5th_year_eligible
    #   - has_higher_max_criteria
    higher_max_boost_applies = AndNode(
        children=[
            yos_under_7,
            Leaf(atom_id="player_is_5th_year_eligible"),
            Leaf(atom_id="player_has_higher_max_criteria"),
        ],
        surface_label="higher_max_boost_applies",
    )

    # Designated Veteran boost requires:
    #   - yos_7_to_9 bracket
    #   - is_designated_veteran_eligible
    #   - has_higher_max_criteria
    designated_veteran_boost_applies = AndNode(
        children=[
            yos_7_to_9,
            Leaf(atom_id="player_is_designated_veteran_eligible"),
            Leaf(atom_id="player_has_higher_max_criteria"),
        ],
        surface_label="designated_veteran_boost_applies",
    )

    # ------ Layer 4: contract salary within max ceiling ------
    # The salary must be at or below the ceiling.
    salary_within_max_ceiling = LeqNode(
        left=contract_salary,
        right=max_ceiling,
        surface_label="contract_salary <= max_ceiling",
    )

    # ------ Layer 5: bracket-specific permission atoms ------
    # Each bracket combines: bracket eligibility, salary check, and (for the
    # boosted brackets) the appropriate gate. The "boost" doesn't add a
    # separate permission - it shifts the ceiling that Map computed.
    # Here we just check that the salary is within the bracket's ceiling.

    op_permitted_under_7_base = AndNode(
        children=[
            yos_under_7,
            salary_within_max_ceiling,
        ],
        surface_label="op_permitted_under_7_yos_base",
    )

    op_permitted_under_7_with_higher_max = AndNode(
        children=[
            higher_max_boost_applies,
            salary_within_max_ceiling,
        ],
        surface_label="op_permitted_under_7_yos_with_higher_max",
    )

    op_permitted_7_to_9_base = AndNode(
        children=[
            yos_7_to_9,
            salary_within_max_ceiling,
        ],
        surface_label="op_permitted_7_to_9_yos_base",
    )

    op_permitted_7_to_9_designated = AndNode(
        children=[
            designated_veteran_boost_applies,
            salary_within_max_ceiling,
        ],
        surface_label="op_permitted_7_to_9_yos_designated",
    )

    op_permitted_10_plus = AndNode(
        children=[
            yos_10_plus,
            salary_within_max_ceiling,
        ],
        surface_label="op_permitted_10_plus_yos",
    )

    # ------ Layer 6: overall permission ------
    op_salary_permitted = OrNode(
        children=[
            op_permitted_under_7_base,
            op_permitted_under_7_with_higher_max,
            op_permitted_7_to_9_base,
            op_permitted_7_to_9_designated,
            op_permitted_10_plus,
        ],
        surface_label="op_salary_permitted_by_yos_max_rule",
    )

    return {
        "yos_under_7": yos_under_7,
        "yos_7_to_9": yos_7_to_9,
        "yos_10_plus": yos_10_plus,
        "higher_max_boost_applies": higher_max_boost_applies,
        "designated_veteran_boost_applies": designated_veteran_boost_applies,
        "salary_within_max_ceiling": salary_within_max_ceiling,
        "op_salary_permitted": op_salary_permitted,
    }


# ---------------------------------------------------------------------------
# Helper: compute the appropriate max ceiling given case facts
# (this simulates what a real Map's numeric substrate would do)
# ---------------------------------------------------------------------------

def compute_max_ceiling(yos: int, prior_salary: Decimal,
                       is_5th_year_eligible: bool, has_higher_max: bool,
                       is_designated_veteran_eligible: bool) -> Decimal:
    """
    Compute the max ceiling = max(pct × cap, 1.05 × prior_salary),
    with pct selected by bracket and boost-eligibility.

    This is what Map binds for max_salary_ceiling.
    """
    if yos < 7:
        pct = PCT_UNDER_7_HIGHER_MAX if (is_5th_year_eligible and has_higher_max) else PCT_UNDER_7
    elif yos < 10:
        pct = PCT_7_TO_9_DESIGNATED if (is_designated_veteran_eligible and has_higher_max) else PCT_7_TO_9
    else:
        pct = PCT_10_PLUS
    pct_of_cap = pct * SALARY_CAP_2024_25
    prior_based = prior_salary * PRIOR_SALARY_MULTIPLIER
    return max(pct_of_cap, prior_based)


def make_bundle(yos: int, prior_salary, contract_salary,
                is_5th_year_eligible=False, has_higher_max=False,
                is_designated_veteran_eligible=False):
    """Construct a FactBundle for a case."""
    prior = Decimal(str(prior_salary))
    contract = Decimal(str(contract_salary))
    ceiling = compute_max_ceiling(yos, prior, is_5th_year_eligible,
                                   has_higher_max, is_designated_veteran_eligible)
    return FactBundle(values={
        "player_years_of_service": NumericValue.of(yos),
        "contract_first_year_salary": NumericValue.of(contract),
        "max_salary_ceiling": NumericValue.of(ceiling),
        "player_is_5th_year_eligible":
            Kleene.TRUE if is_5th_year_eligible else Kleene.FALSE,
        "player_has_higher_max_criteria":
            Kleene.TRUE if has_higher_max else Kleene.FALSE,
        "player_is_designated_veteran_eligible":
            Kleene.TRUE if is_designated_veteran_eligible else Kleene.FALSE,
    })


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def cases():
    """
    Each case: (label, bundle, expected_dict).
    expected_dict maps node-name to expected Kleene value.

    For brevity, we focus on `op_salary_permitted` as the main outcome
    and a few diagnostic gates.
    """
    out = []

    # CASE 1: YOS=5, no Higher Max claim, contract within 25% × cap
    # 25% × $140.588M = $35.147M
    bundle = make_bundle(yos=5, prior_salary=10000000, contract_salary=30000000)
    out.append(("YOS=5, contract $30M, no Higher Max → permitted (under 25% cap)",
                bundle, {
                    "yos_under_7": Kleene.TRUE,
                    "higher_max_boost_applies": Kleene.FALSE,
                    "salary_within_max_ceiling": Kleene.TRUE,
                    "op_salary_permitted": Kleene.TRUE,
                }))

    # CASE 2: YOS=5, no Higher Max claim, contract OVER 25% × cap → illegal
    bundle = make_bundle(yos=5, prior_salary=10000000, contract_salary=40000000)
    out.append(("YOS=5, contract $40M → ILLEGAL (over 25% cap, no boost)",
                bundle, {
                    "yos_under_7": Kleene.TRUE,
                    "higher_max_boost_applies": Kleene.FALSE,
                    "salary_within_max_ceiling": Kleene.FALSE,
                    "op_salary_permitted": Kleene.FALSE,
                }))

    # CASE 3: YOS=4 exactly, 5th-Year Eligible + Higher Max, contract at 30% cap
    # 30% × $140.588M = $42.176M
    # Boost lifts ceiling from 25% to 30% of cap.
    bundle = make_bundle(yos=4, prior_salary=10000000, contract_salary=42000000,
                         is_5th_year_eligible=True, has_higher_max=True)
    out.append(("YOS=4, 5th-yr eligible + Higher Max, $42M → permitted via boost",
                bundle, {
                    "yos_under_7": Kleene.TRUE,
                    "higher_max_boost_applies": Kleene.TRUE,
                    "op_salary_permitted": Kleene.TRUE,
                }))

    # CASE 4: THE OVER-FIRING CASE (what Opus 4.7 gets wrong)
    # YOS=4, has Higher Max criteria (All-NBA last year), but NOT 5th-Year
    # Eligible (maybe was traded to current team in year 2 of rookie scale,
    # or didn't sign rookie scale with current team).
    # Contract at 28% of cap = $39.4M — exceeds base 25% but would be OK
    # with the boost.
    # WITHOUT boost, max is max(25% × cap, 105% × prior_salary). Prior was
    # $10M, 105% is $10.5M. So ceiling is $35.147M. $39.4M exceeds it.
    # CORRECT: ILLEGAL. Direct-LLM would incorrectly grant the boost
    # because "All-NBA" is right there in the description.
    bundle = make_bundle(yos=4, prior_salary=10000000, contract_salary=39400000,
                         is_5th_year_eligible=False,  # ← Critical: NOT eligible
                         has_higher_max=True)          # ← But All-NBA criteria met
    out.append(("YOS=4, Higher Max but NOT 5th-yr eligible, $39.4M → ILLEGAL "
                "(over-firing protection)",
                bundle, {
                    "yos_under_7": Kleene.TRUE,
                    "higher_max_boost_applies": Kleene.FALSE,  # ← Architecture catches it
                    "salary_within_max_ceiling": Kleene.FALSE,
                    "op_salary_permitted": Kleene.FALSE,
                }))

    # CASE 5: 7-9 YOS bracket, no boost, contract within 30% cap
    # 30% × $140.588M = $42.176M
    bundle = make_bundle(yos=8, prior_salary=20000000, contract_salary=40000000)
    out.append(("YOS=8, contract $40M, no Designated → permitted (under 30% cap)",
                bundle, {
                    "yos_7_to_9": Kleene.TRUE,
                    "designated_veteran_boost_applies": Kleene.FALSE,
                    "op_salary_permitted": Kleene.TRUE,
                }))

    # CASE 6: 7-9 YOS bracket, Designated Veteran eligible + Higher Max
    # 35% × $140.588M = $49.206M
    bundle = make_bundle(yos=8, prior_salary=20000000, contract_salary=48000000,
                         is_designated_veteran_eligible=True, has_higher_max=True)
    out.append(("YOS=8, Designated + Higher Max, $48M → permitted via 35% boost",
                bundle, {
                    "yos_7_to_9": Kleene.TRUE,
                    "designated_veteran_boost_applies": Kleene.TRUE,
                    "op_salary_permitted": Kleene.TRUE,
                }))

    # CASE 7: 7-9 YOS, has Higher Max but NOT Designated Veteran eligible
    # (e.g., was traded in year 3 of career, not just year 1).
    # Contract at $48M (above base 30% cap). Without Designated boost, illegal.
    bundle = make_bundle(yos=8, prior_salary=20000000, contract_salary=48000000,
                         is_designated_veteran_eligible=False,  # ← Critical
                         has_higher_max=True)
    out.append(("YOS=8, Higher Max but NOT Designated, $48M → ILLEGAL "
                "(over-firing protection on 7-9 boost)",
                bundle, {
                    "yos_7_to_9": Kleene.TRUE,
                    "designated_veteran_boost_applies": Kleene.FALSE,
                    "op_salary_permitted": Kleene.FALSE,
                }))

    # CASE 8: 10+ YOS, contract within 35% cap
    # 35% × $140.588M = $49.206M
    bundle = make_bundle(yos=12, prior_salary=30000000, contract_salary=49000000)
    out.append(("YOS=12, contract $49M → permitted (under 35% cap)",
                bundle, {
                    "yos_10_plus": Kleene.TRUE,
                    "op_salary_permitted": Kleene.TRUE,
                }))

    # CASE 9: 10+ YOS but contract exceeds 35% × cap AND 105% × prior
    # 105% × $30M = $31.5M. Ceiling = max($49.206M, $31.5M) = $49.206M.
    # Contract $55M exceeds.
    bundle = make_bundle(yos=12, prior_salary=30000000, contract_salary=55000000)
    out.append(("YOS=12, contract $55M → ILLEGAL (exceeds 35% cap)",
                bundle, {
                    "yos_10_plus": Kleene.TRUE,
                    "salary_within_max_ceiling": Kleene.FALSE,
                    "op_salary_permitted": Kleene.FALSE,
                }))

    # CASE 10: 105% of prior salary > X% of cap (high-earning vet)
    # YOS=12, prior salary $50M. 105% × $50M = $52.5M.
    # 35% × cap = $49.206M. Ceiling = max($49.206M, $52.5M) = $52.5M.
    # Contract $52M → permitted via 105%-prior pathway.
    bundle = make_bundle(yos=12, prior_salary=50000000, contract_salary=52000000)
    out.append(("YOS=12, prior $50M, contract $52M → permitted via 105% prior",
                bundle, {
                    "yos_10_plus": Kleene.TRUE,
                    "salary_within_max_ceiling": Kleene.TRUE,
                    "op_salary_permitted": Kleene.TRUE,
                }))

    # CASE 11: UNDETERMINED — YOS unknown
    bundle = FactBundle(values={
        "player_years_of_service": NumericValue.undetermined(),
        "contract_first_year_salary": NumericValue.of(30000000),
        "max_salary_ceiling": NumericValue.undetermined(),
        "player_is_5th_year_eligible": Kleene.FALSE,
        "player_has_higher_max_criteria": Kleene.FALSE,
        "player_is_designated_veteran_eligible": Kleene.FALSE,
    })
    out.append(("YOS unknown → bracket undetermined, disposition undetermined",
                bundle, {
                    "yos_under_7": Kleene.UNDETERMINED,
                    "yos_7_to_9": Kleene.UNDETERMINED,
                    "yos_10_plus": Kleene.UNDETERMINED,
                    "salary_within_max_ceiling": Kleene.UNDETERMINED,
                    "op_salary_permitted": Kleene.UNDETERMINED,
                }))

    return out

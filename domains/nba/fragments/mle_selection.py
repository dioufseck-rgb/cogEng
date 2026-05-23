"""
NBA fragment validation: hand-authored DAG exercising the MLE-flavor
selection logic that direct-LLM gets wrong.

WHAT THIS DEMONSTRATES
=======================
The paper's RuleArena results show direct-LLM is at 15-50% precision on NBA
rule selection. The dominant failure mode is "rule confusion": picking the
wrong MLE flavor (Non-Taxpayer / Taxpayer / Room) based on lexical proximity
rather than the gating predicate (team's salary position).

This fragment shows the architecture *structurally prevents* the failure
mode. The three MLE-flavor atoms are wired through mutually exclusive
gating predicates (team_below_cap / team_above_cap_below_first_apron /
team_above_first_apron_below_second_apron). The engine can't satisfy more
than one MLE-flavor atom for the same team in the same operation, no matter
what Map does — because the gating predicates are *themselves* the result
of structured arithmetic over team salary vs cap/apron thresholds.

WHAT WE'RE NOT DOING
=====================
This is NOT a full RuleArena harness. The fragment is hand-authored, the
fact bundles are hand-bound (no Map LLM call), and the rule coverage is
narrow (just MLE eligibility with salary-limit checking).

The point is to demonstrate the typed engine can express the shape of NBA
reasoning correctly, before we invest in:
- Numeric Map substrate (for case-fact extraction)
- Build pipeline typed-atom emission (for full DAG construction from CBA text)

If this validation works, those investments are justified.
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
# CBA Constants for the 2024-25 Salary Cap Year
# ---------------------------------------------------------------------------

SALARY_CAP_2024_25 = Decimal("140588000")
FIRST_APRON_2024_25 = Decimal("178132000")
SECOND_APRON_2024_25 = Decimal("188931000")

# MLE multipliers (per CBA Article VII Section 6)
NON_TAXPAYER_MLE_PCT = Decimal("0.0912")   # 9.12% of cap
TAXPAYER_MLE_PCT     = Decimal("0.0568")   # ~5.68% of cap
ROOM_MLE_PCT         = Decimal("0.0568")   # same as taxpayer for room teams (approx)

# Contract-length caps per MLE flavor
NON_TAXPAYER_MLE_MAX_YEARS = 4
TAXPAYER_MLE_MAX_YEARS = 2
ROOM_MLE_MAX_YEARS = 3


# ---------------------------------------------------------------------------
# Build the fragment DAG
# ---------------------------------------------------------------------------

def build_fragment():
    """
    Build the MLE-flavor-selection fragment DAG.

    Atoms (numeric, bound by Map):
      - team_salary
      - contract_first_year_salary
      - contract_length_years

    Atoms (boolean, bound by Map):
      - op_uses_mle_class_exception      (does this operation use any MLE flavor?)

    Composite nodes built via arithmetic and Boolean composition.

    Returns a dict of named nodes you can evaluate against a bundle.
    """

    # ------ Layer 1: numeric leaves ------
    team_salary = NumericLeaf(atom_id="team_salary")
    contract_salary = NumericLeaf(atom_id="contract_first_year_salary")
    contract_length = NumericLeaf(atom_id="contract_length_years")

    # ------ Layer 2: gating predicates (team's salary bracket) ------
    # team_below_cap := team_salary < SALARY_CAP
    team_below_cap = LtNode(
        left=team_salary,
        right=Constant(value=SALARY_CAP_2024_25, label="2024-25 salary cap"),
        surface_label="team_below_cap",
    )

    # team_above_cap_below_first_apron := team_salary >= CAP AND team_salary < FIRST_APRON
    team_at_or_above_cap = GeqNode(
        left=team_salary,
        right=Constant(value=SALARY_CAP_2024_25, label="2024-25 salary cap"),
        surface_label="team_at_or_above_cap",
    )
    team_below_first_apron = LtNode(
        left=team_salary,
        right=Constant(value=FIRST_APRON_2024_25, label="2024-25 first apron"),
        surface_label="team_below_first_apron",
    )
    team_above_cap_below_first_apron = AndNode(
        children=[team_at_or_above_cap, team_below_first_apron],
        surface_label="team_above_cap_below_first_apron",
    )

    # team_above_first_apron_below_second_apron := salary >= FIRST_APRON AND < SECOND_APRON
    team_at_or_above_first_apron = GeqNode(
        left=team_salary,
        right=Constant(value=FIRST_APRON_2024_25, label="first apron"),
        surface_label="team_at_or_above_first_apron",
    )
    team_below_second_apron = LtNode(
        left=team_salary,
        right=Constant(value=SECOND_APRON_2024_25, label="second apron"),
        surface_label="team_below_second_apron",
    )
    team_above_first_apron_below_second_apron = AndNode(
        children=[team_at_or_above_first_apron, team_below_second_apron],
        surface_label="team_above_first_apron_below_second_apron",
    )

    # ------ Layer 3: per-MLE-flavor limit nodes (numeric arithmetic) ------
    non_taxpayer_mle_limit = TimesConstNode(
        child=Constant(value=SALARY_CAP_2024_25, label="cap"),
        constant=NON_TAXPAYER_MLE_PCT,
        surface_label="9.12% × cap = Non-Taxpayer MLE limit",
    )
    taxpayer_mle_limit = TimesConstNode(
        child=Constant(value=SALARY_CAP_2024_25, label="cap"),
        constant=TAXPAYER_MLE_PCT,
        surface_label="5.68% × cap = Taxpayer MLE limit",
    )
    room_mle_limit = TimesConstNode(
        child=Constant(value=SALARY_CAP_2024_25, label="cap"),
        constant=ROOM_MLE_PCT,
        surface_label="5.68% × cap = Room MLE limit",
    )

    # ------ Layer 4: per-MLE-flavor "applicable" atoms ------
    # The CRITICAL atoms — these are what direct-LLM gets confused about.
    # Each is gated by the team's salary bracket (mutually exclusive) AND
    # the contract terms (salary within limit, length within max).

    op_uses_mle = Leaf(atom_id="op_uses_mle_class_exception")

    # NON-TAXPAYER MLE: team above cap, below first apron; salary ≤ 9.12% × cap;
    # length ≤ 4 years
    salary_within_non_taxpayer_mle = LeqNode(
        left=contract_salary,
        right=non_taxpayer_mle_limit,
        surface_label="contract salary ≤ Non-Taxpayer MLE limit",
    )
    length_within_non_taxpayer_mle = LeqNode(
        left=contract_length,
        right=Constant(value=Decimal(NON_TAXPAYER_MLE_MAX_YEARS),
                       label=f"max {NON_TAXPAYER_MLE_MAX_YEARS} years"),
        surface_label="contract length ≤ 4 years",
    )
    op_permitted_via_non_taxpayer_mle = AndNode(
        children=[
            op_uses_mle,
            team_above_cap_below_first_apron,
            salary_within_non_taxpayer_mle,
            length_within_non_taxpayer_mle,
        ],
        surface_label="op_permitted_via_non_taxpayer_mle",
    )

    # TAXPAYER MLE: team above first apron, below second; salary ≤ 5.68% × cap;
    # length ≤ 2 years
    salary_within_taxpayer_mle = LeqNode(
        left=contract_salary,
        right=taxpayer_mle_limit,
        surface_label="contract salary ≤ Taxpayer MLE limit",
    )
    length_within_taxpayer_mle = LeqNode(
        left=contract_length,
        right=Constant(value=Decimal(TAXPAYER_MLE_MAX_YEARS),
                       label=f"max {TAXPAYER_MLE_MAX_YEARS} years"),
        surface_label="contract length ≤ 2 years",
    )
    op_permitted_via_taxpayer_mle = AndNode(
        children=[
            op_uses_mle,
            team_above_first_apron_below_second_apron,
            salary_within_taxpayer_mle,
            length_within_taxpayer_mle,
        ],
        surface_label="op_permitted_via_taxpayer_mle",
    )

    # ROOM MLE: team below cap; salary ≤ 5.68% × cap; length ≤ 3 years
    salary_within_room_mle = LeqNode(
        left=contract_salary,
        right=room_mle_limit,
        surface_label="contract salary ≤ Room MLE limit",
    )
    length_within_room_mle = LeqNode(
        left=contract_length,
        right=Constant(value=Decimal(ROOM_MLE_MAX_YEARS),
                       label=f"max {ROOM_MLE_MAX_YEARS} years"),
        surface_label="contract length ≤ 3 years",
    )
    op_permitted_via_room_mle = AndNode(
        children=[
            op_uses_mle,
            team_below_cap,
            salary_within_room_mle,
            length_within_room_mle,
        ],
        surface_label="op_permitted_via_room_mle",
    )

    # ------ Layer 5: top-level determination ------
    # operation is permitted via SOME MLE flavor
    op_permitted_via_some_mle = OrNode(
        children=[
            op_permitted_via_non_taxpayer_mle,
            op_permitted_via_taxpayer_mle,
            op_permitted_via_room_mle,
        ],
        surface_label="op_permitted_via_some_mle",
    )

    return {
        "team_below_cap": team_below_cap,
        "team_above_cap_below_first_apron": team_above_cap_below_first_apron,
        "team_above_first_apron_below_second_apron":
            team_above_first_apron_below_second_apron,
        "non_taxpayer_mle_limit": non_taxpayer_mle_limit,
        "taxpayer_mle_limit": taxpayer_mle_limit,
        "room_mle_limit": room_mle_limit,
        "op_permitted_via_non_taxpayer_mle": op_permitted_via_non_taxpayer_mle,
        "op_permitted_via_taxpayer_mle": op_permitted_via_taxpayer_mle,
        "op_permitted_via_room_mle": op_permitted_via_room_mle,
        "op_permitted_via_some_mle": op_permitted_via_some_mle,
    }


# ---------------------------------------------------------------------------
# Validation cases — each is a hand-authored scenario with known answer
# ---------------------------------------------------------------------------

def case_team_above_cap_below_apron_legal_mle():
    """
    Team A salary = $160M (above cap $140.588M, below first apron $178.132M).
    Contract: $8M/year, 3 years.

    Correct disposition: Non-Taxpayer MLE applies.
    - Team bracket matches Non-Taxpayer MLE: YES (above cap, below first apron)
    - Salary within limit: $8M ≤ $12.82M YES
    - Length within max: 3 ≤ 4 YES

    Expected: op_permitted_via_non_taxpayer_mle = TRUE
              op_permitted_via_taxpayer_mle    = FALSE (wrong bracket)
              op_permitted_via_room_mle        = FALSE (wrong bracket)
              op_permitted_via_some_mle        = TRUE
    """
    bundle = FactBundle(values={
        "team_salary": NumericValue.of(160000000),
        "contract_first_year_salary": NumericValue.of(8000000),
        "contract_length_years": NumericValue.of(3),
        "op_uses_mle_class_exception": Kleene.TRUE,
    })
    return ("team above cap below apron, legal Non-Taxpayer MLE", bundle, {
        "op_permitted_via_non_taxpayer_mle": Kleene.TRUE,
        "op_permitted_via_taxpayer_mle": Kleene.FALSE,
        "op_permitted_via_room_mle": Kleene.FALSE,
        "op_permitted_via_some_mle": Kleene.TRUE,
    })


def case_team_above_first_apron_legal_taxpayer_mle():
    """
    Team A salary = $185M (above first apron $178.132M, below second apron).
    Contract: $7M/year, 2 years.

    Correct disposition: Taxpayer MLE applies.
    """
    bundle = FactBundle(values={
        "team_salary": NumericValue.of(185000000),
        "contract_first_year_salary": NumericValue.of(7000000),
        "contract_length_years": NumericValue.of(2),
        "op_uses_mle_class_exception": Kleene.TRUE,
    })
    return ("team above first apron, legal Taxpayer MLE", bundle, {
        "op_permitted_via_non_taxpayer_mle": Kleene.FALSE,
        "op_permitted_via_taxpayer_mle": Kleene.TRUE,
        "op_permitted_via_room_mle": Kleene.FALSE,
        "op_permitted_via_some_mle": Kleene.TRUE,
    })


def case_team_below_cap_legal_room_mle():
    """
    Team A salary = $130M (below cap $140.588M).
    Contract: $7M/year, 3 years.

    Correct disposition: Room MLE applies.
    """
    bundle = FactBundle(values={
        "team_salary": NumericValue.of(130000000),
        "contract_first_year_salary": NumericValue.of(7000000),
        "contract_length_years": NumericValue.of(3),
        "op_uses_mle_class_exception": Kleene.TRUE,
    })
    return ("team below cap, legal Room MLE", bundle, {
        "op_permitted_via_non_taxpayer_mle": Kleene.FALSE,
        "op_permitted_via_taxpayer_mle": Kleene.FALSE,
        "op_permitted_via_room_mle": Kleene.TRUE,
        "op_permitted_via_some_mle": Kleene.TRUE,
    })


def case_salary_exceeds_non_taxpayer_mle_limit():
    """
    Team A salary = $160M (above cap, below first apron — correct bracket
    for Non-Taxpayer MLE).
    Contract: $20M/year, 3 years.

    Correct disposition: ILLEGAL via any MLE. $20M > 9.12% × cap ($12.82M).
    Team is in Non-Taxpayer bracket but contract violates the salary limit.
    """
    bundle = FactBundle(values={
        "team_salary": NumericValue.of(160000000),
        "contract_first_year_salary": NumericValue.of(20000000),
        "contract_length_years": NumericValue.of(3),
        "op_uses_mle_class_exception": Kleene.TRUE,
    })
    return ("salary exceeds Non-Taxpayer MLE limit (illegal)", bundle, {
        "op_permitted_via_non_taxpayer_mle": Kleene.FALSE,
        "op_permitted_via_taxpayer_mle": Kleene.FALSE,
        "op_permitted_via_room_mle": Kleene.FALSE,
        "op_permitted_via_some_mle": Kleene.FALSE,
    })


def case_length_exceeds_taxpayer_mle_limit():
    """
    Team A salary = $185M (above first apron — Taxpayer MLE bracket).
    Contract: $5M/year, 4 years.

    Correct disposition: ILLEGAL. Taxpayer MLE limit is 2 years, contract is 4.
    THIS IS EXACTLY THE FAILURE MODE OPUS 4.7 EXHIBITS: it correctly identifies
    Taxpayer MLE applies but doesn't enforce the 2-year contract-length constraint.

    In the architecture, this fails because the AND node for
    op_permitted_via_taxpayer_mle requires length_within_taxpayer_mle, which
    is FALSE.
    """
    bundle = FactBundle(values={
        "team_salary": NumericValue.of(185000000),
        "contract_first_year_salary": NumericValue.of(5000000),
        "contract_length_years": NumericValue.of(4),
        "op_uses_mle_class_exception": Kleene.TRUE,
    })
    return ("length exceeds Taxpayer MLE limit (illegal)", bundle, {
        "op_permitted_via_non_taxpayer_mle": Kleene.FALSE,
        "op_permitted_via_taxpayer_mle": Kleene.FALSE,
        "op_permitted_via_room_mle": Kleene.FALSE,
        "op_permitted_via_some_mle": Kleene.FALSE,
    })


def case_team_salary_unknown_mle_undetermined():
    """
    THE ARCHITECTURE'S DISTINCTIVE PROPERTY:
    Team salary is not stated. Contract is $8M, 3 years.

    Correct disposition: UNDETERMINED. We cannot determine which MLE flavor
    applies (or whether any does) without knowing the team's bracket.

    Direct-LLM would commit to an answer. RuleKit returns UNDETERMINED
    structurally, because the bracket-gating predicates produce UNDETERMINED
    (Comparison with UNDETERMINED operand = Kleene UNDETERMINED), which then
    propagates through Kleene AND.
    """
    bundle = FactBundle(values={
        "team_salary": NumericValue.undetermined(),
        "contract_first_year_salary": NumericValue.of(8000000),
        "contract_length_years": NumericValue.of(3),
        "op_uses_mle_class_exception": Kleene.TRUE,
    })
    # Contract: $8M, 3 years.
    # - Non-Taxpayer MLE limit ($12.82M, max 4 yr): contract fits. So whether
    #   this flavor applies depends ENTIRELY on team's bracket → UNDETERMINED.
    # - Taxpayer MLE limit ($7.98M, max 2 yr): contract VIOLATES both salary
    #   and length. So Taxpayer MLE is FALSE regardless of bracket — Kleene
    #   AND with a FALSE child returns FALSE. The engine correctly rules
    #   this out even without knowing the team's bracket.
    # - Room MLE limit ($7.98M, max 3 yr): contract VIOLATES salary limit.
    #   FALSE regardless of bracket, same reasoning.
    # - The OR over the three flavors: one UND, two FALSE → UNDETERMINED.
    #
    # This is the architecture being MORE informative than direct-LLM: even
    # with partial evidence, we know Taxpayer and Room MLE can't apply on
    # contract grounds, only Non-Taxpayer MLE depends on the unknown bracket.
    return ("team salary UNDETERMINED → UNDETERMINED disposition", bundle, {
        "op_permitted_via_non_taxpayer_mle": Kleene.UNDETERMINED,
        "op_permitted_via_taxpayer_mle": Kleene.FALSE,
        "op_permitted_via_room_mle": Kleene.FALSE,
        "op_permitted_via_some_mle": Kleene.UNDETERMINED,
    })


def case_mle_flavor_mutual_exclusion():
    """
    DEMONSTRATING STRUCTURAL CORRECTNESS OF MLE-FLAVOR SELECTION:

    Show that across THREE distinct cases with different team salaries (one
    per bracket), exactly ONE MLE-flavor atom is TRUE. The architecture
    cannot satisfy two MLE-flavors simultaneously — direct-LLM gets confused
    here, but the engine treats the gating predicates as mutually exclusive
    by construction.

    Returns the *list* of (label, bundle, expected) for three sub-cases.
    """
    contract_specs = [
        # (bracket_label, team_salary, expected_flavor)
        ("team below cap", 130000000, "op_permitted_via_room_mle"),
        ("team above cap below first apron", 160000000,
         "op_permitted_via_non_taxpayer_mle"),
        ("team above first apron below second apron", 185000000,
         "op_permitted_via_taxpayer_mle"),
    ]
    # Contract: $5M, 2 years — fits ALL three MLE limits salary/length-wise
    out = []
    for bracket, team_sal, expected_flavor in contract_specs:
        bundle = FactBundle(values={
            "team_salary": NumericValue.of(team_sal),
            "contract_first_year_salary": NumericValue.of(5000000),
            "contract_length_years": NumericValue.of(2),
            "op_uses_mle_class_exception": Kleene.TRUE,
        })
        expected = {
            "op_permitted_via_non_taxpayer_mle": Kleene.FALSE,
            "op_permitted_via_taxpayer_mle": Kleene.FALSE,
            "op_permitted_via_room_mle": Kleene.FALSE,
            "op_permitted_via_some_mle": Kleene.TRUE,
        }
        expected[expected_flavor] = Kleene.TRUE
        out.append((f"mutual exclusion: {bracket}", bundle, expected))
    return out


# ---------------------------------------------------------------------------
# Aggregator — yields (label, bundle, expected) tuples for the runner
# ---------------------------------------------------------------------------

def cases():
    out = []
    r = case_team_above_cap_below_apron_legal_mle()
    if isinstance(r, list):
        out.extend(r)
    else:
        out.append(r)
    r = case_team_above_first_apron_legal_taxpayer_mle()
    if isinstance(r, list):
        out.extend(r)
    else:
        out.append(r)
    r = case_team_below_cap_legal_room_mle()
    if isinstance(r, list):
        out.extend(r)
    else:
        out.append(r)
    r = case_salary_exceeds_non_taxpayer_mle_limit()
    if isinstance(r, list):
        out.extend(r)
    else:
        out.append(r)
    r = case_length_exceeds_taxpayer_mle_limit()
    if isinstance(r, list):
        out.extend(r)
    else:
        out.append(r)
    r = case_team_salary_unknown_mle_undetermined()
    if isinstance(r, list):
        out.extend(r)
    else:
        out.append(r)
    r = case_mle_flavor_mutual_exclusion()
    if isinstance(r, list):
        out.extend(r)
    else:
        out.append(r)
    return out

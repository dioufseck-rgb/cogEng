"""
NBA fragment 3 — Sign-and-Trade with team-role attribution.

EXERCISES
=========
Section 8(e)(1) of the NBA CBA (sign-and-trade), together with Section
2(e)(4) row C (sign-and-trade triggers hard cap at first apron level
on the SIGNING/ASSIGNER team — NOT the acquiring team).

There are seven constraints on a sign-and-trade per 8(e)(1), but the
architecturally interesting ones for showing the failure mode are:

  (ii) Contract length is 3 or 4 seasons
  (iii) NOT signed via Non-Taxpayer MLE or Room MLE
  (vii) The ACQUIRING team has Room for the player's salary
  +    Section 2(e)(4) row C: The SIGNING team's post-trade salary
       must not exceed the First Apron Level (hard cap)

The team-role attribution is the load-bearing point. Constraint (vii)
constrains the ACQUIRER (the team receiving the player). The hard-cap
constraint constrains the ASSIGNER (the team signing the contract and
sending the player).

FAILURE MODE THIS ADDRESSES
============================
Case 0 of comp_2.json (RuleArena Level 3), as observed in the Opus 4.7
baseline run:

  Ground truth: Answer: True. Illegal Operation: B. Problematic Team: A.
  Opus output:  Answer: True. Illegal Operation: B. Problematic Team: B.

Opus correctly identified that something was illegal in operation B
(the sign-and-trade), but misattributed the violation to Team B "not
having Room" instead of Team A's post-trade salary exceeding the first
apron (which makes Team A the problematic team via the hard-cap-on-
signer constraint).

The architecture wires each constraint to its actor:
  - `acquirer_has_room_for_player` constrains the ACQUIRER
  - `signer_post_trade_below_first_apron` constrains the SIGNER

When `signer_post_trade_below_first_apron` is FALSE, the trace pinpoints
the SIGNER as problematic by structure. Direct-LLM is forced to thread
both constraints across multiple team-roles in a single forward pass;
the architecture's per-constraint atomization makes the attribution
unambiguous.
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
FIRST_APRON_2024_25 = Decimal("178132000")
SECOND_APRON_2024_25 = Decimal("188931000")


# ---------------------------------------------------------------------------
# Build the fragment
# ---------------------------------------------------------------------------

def build_fragment():
    """
    Build the sign-and-trade fragment.

    The interesting structural property: the seven sub-constraints are
    each evaluated against the specific team-role they apply to. The
    AndNode at the top is symmetric (all must hold), but per-atom
    attribution lets the trace point to the role that fails.

    Numeric atoms (Map-bound):
      - signing_team_salary_pre_trade
      - signing_team_salary_post_trade   (= pre - outgoing + incoming)
      - acquiring_team_salary_pre_trade
      - acquiring_team_room                (= max(0, cap - acquiring_team_salary))
      - contract_first_year_salary
      - contract_length_years
      - higher_max_salary_threshold        (25% × cap = $35.147M)

    Boolean atoms (Map-bound):
      - player_is_veteran_free_agent_on_prior_team
      - signed_via_non_taxpayer_mle_or_room_mle
      - first_season_fully_protected
      - signed_before_regular_season_start
      - is_5th_year_eligible_with_higher_max
      - acquirer_has_room_for_player        (binary check;
        equivalent to LEQ(contract_salary, acquirer_room))

    For demonstration, we wire the room check via the numeric leaves.
    """

    # ------ Numeric leaves ------
    signing_team_post = NumericLeaf(atom_id="signing_team_salary_post_trade")
    acquirer_room = NumericLeaf(atom_id="acquiring_team_room")
    contract_salary = NumericLeaf(atom_id="contract_first_year_salary")
    contract_length = NumericLeaf(atom_id="contract_length_years")

    # ------ Constraint (ii): contract length in [3, 4] ------
    length_at_least_3 = GeqNode(
        left=contract_length,
        right=Constant(value=Decimal(3), label="min 3 yrs"),
        surface_label="contract_length >= 3",
    )
    length_at_most_4 = LeqNode(
        left=contract_length,
        right=Constant(value=Decimal(4), label="max 4 yrs"),
        surface_label="contract_length <= 4",
    )
    contract_length_3_to_4 = AndNode(
        children=[length_at_least_3, length_at_most_4],
        surface_label="contract_length_3_to_4_years",
    )

    # ------ Constraint (iii): NOT via Non-Taxpayer MLE or Room MLE ------
    not_via_disallowed_mle = NotNode(
        child=Leaf(atom_id="signed_via_non_taxpayer_mle_or_room_mle"),
        source_span="Section 8(e)(1)(iii)",
    )

    # ------ Constraint (vi): if 5th-year-eligible+higher_max, salary <= 25% cap ------
    # Implemented as: (NOT is_5th_year_eligible_with_higher_max)
    #                 OR (contract_salary <= 25% × cap)
    salary_within_5th_year_cap = LeqNode(
        left=contract_salary,
        right=TimesConstNode(
            child=Constant(value=SALARY_CAP_2024_25, label="cap"),
            constant=Decimal("0.25"),
            surface_label="25% × cap",
        ),
        surface_label="contract_salary <= 25% × cap",
    )
    fifth_year_higher_max_constraint = OrNode(
        children=[
            NotNode(child=Leaf(atom_id="is_5th_year_eligible_with_higher_max")),
            salary_within_5th_year_cap,
        ],
        surface_label="5th_year_higher_max_constraint",
    )

    # ------ Constraint (vii): ACQUIRER has Room ------
    # "Room" means cap_space; for sign-and-trade the acquirer must absorb
    # the contract via room or via a traded-player exception.
    # We model the simple Room version here.
    acquirer_has_room_for_player = LeqNode(
        left=contract_salary,
        right=acquirer_room,
        surface_label="acquirer_has_room_for_contract",
    )

    # ------ Section 2(e)(4) row C: SIGNER post-trade salary <= First Apron ------
    # This is the hard-cap constraint. It applies to the SIGNING/ASSIGNER team.
    signer_post_trade_below_first_apron = LtNode(
        left=signing_team_post,
        right=Constant(value=FIRST_APRON_2024_25,
                       label="2024-25 First Apron"),
        surface_label="signer_post_trade_salary < first_apron (HARD CAP)",
    )

    # ------ Other constraints, modeled as Boolean atoms ------
    veteran_on_prior_team = Leaf(
        atom_id="player_is_veteran_free_agent_on_prior_team")
    first_season_protected = Leaf(atom_id="first_season_fully_protected")
    signed_before_reg_season = Leaf(atom_id="signed_before_regular_season_start")

    # ------ Top-level: sign-and-trade is permitted iff all hold ------
    sign_and_trade_permitted = AndNode(
        children=[
            veteran_on_prior_team,
            contract_length_3_to_4,
            not_via_disallowed_mle,
            first_season_protected,
            signed_before_reg_season,
            fifth_year_higher_max_constraint,
            acquirer_has_room_for_player,
            signer_post_trade_below_first_apron,
        ],
        surface_label="sign_and_trade_permitted",
    )

    return {
        "contract_length_3_to_4_years": contract_length_3_to_4,
        "fifth_year_higher_max_constraint": fifth_year_higher_max_constraint,
        "acquirer_has_room_for_player": acquirer_has_room_for_player,
        "signer_post_trade_below_first_apron": signer_post_trade_below_first_apron,
        "sign_and_trade_permitted": sign_and_trade_permitted,
    }


# ---------------------------------------------------------------------------
# Helpers to construct bundles
# ---------------------------------------------------------------------------

def make_bundle(*,
                signing_team_post_trade_salary,
                acquiring_team_pre_trade_salary,
                contract_salary,
                contract_length,
                player_is_vfa_on_prior_team=True,
                signed_via_disallowed_mle=False,
                first_season_protected=True,
                signed_before_reg_season=True,
                is_5th_year_with_higher_max=False):
    """Construct a FactBundle for a sign-and-trade case."""
    acq_room = max(Decimal(0),
                   SALARY_CAP_2024_25 - Decimal(str(acquiring_team_pre_trade_salary)))
    return FactBundle(values={
        "signing_team_salary_post_trade":
            NumericValue.of(signing_team_post_trade_salary),
        "acquiring_team_room": NumericValue.of(acq_room),
        "contract_first_year_salary": NumericValue.of(contract_salary),
        "contract_length_years": NumericValue.of(contract_length),
        "player_is_veteran_free_agent_on_prior_team":
            Kleene.TRUE if player_is_vfa_on_prior_team else Kleene.FALSE,
        "signed_via_non_taxpayer_mle_or_room_mle":
            Kleene.TRUE if signed_via_disallowed_mle else Kleene.FALSE,
        "first_season_fully_protected":
            Kleene.TRUE if first_season_protected else Kleene.FALSE,
        "signed_before_regular_season_start":
            Kleene.TRUE if signed_before_reg_season else Kleene.FALSE,
        "is_5th_year_eligible_with_higher_max":
            Kleene.TRUE if is_5th_year_with_higher_max else Kleene.FALSE,
    })


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def cases():
    """
    Each case: (label, bundle, expected_dict, key_atom_for_attribution).

    The fourth element names which sub-constraint is the FAILURE attribution
    target — i.e., when the overall is FALSE, which atom's role tells us
    *who* is problematic.
    """
    out = []

    # CASE 1: Clean legal sign-and-trade
    #   Signer Team A post-trade salary: $160M (below first apron $178M) ✓
    #   Acquirer Team B pre-trade salary: $100M (room = $40.588M)
    #   Contract: $20M, 3 years
    #   Other constraints met.
    bundle = make_bundle(
        signing_team_post_trade_salary=160000000,
        acquiring_team_pre_trade_salary=100000000,
        contract_salary=20000000,
        contract_length=3,
    )
    out.append(("Legal S&T: signer below apron, acquirer has room",
                bundle, {
                    "contract_length_3_to_4_years": Kleene.TRUE,
                    "acquirer_has_room_for_player": Kleene.TRUE,
                    "signer_post_trade_below_first_apron": Kleene.TRUE,
                    "sign_and_trade_permitted": Kleene.TRUE,
                }, None))

    # CASE 2 (HEADLINE): SIGNER hard-cap violation — case-0 pattern
    #   Signer Team A signs Player at $35M, immediately trades to Team B.
    #   Signer post-trade salary = $180M (ABOVE first apron $178M) ✗
    #   Acquirer Team B has Room. Contract is 3 years.
    #
    #   Opus 4.7 attributed this to Team B "lacking Room"; ground truth
    #   attributed it to Team A's post-trade hard-cap violation.
    #
    #   Expected outcome: TRACE PINPOINTS THE SIGNER ATOM AS FALSE.
    bundle = make_bundle(
        signing_team_post_trade_salary=180000000,  # ← Above first apron!
        acquiring_team_pre_trade_salary=100000000,
        contract_salary=35000000,
        contract_length=3,
    )
    out.append(("ILLEGAL S&T: signer post-trade exceeds first apron (CASE-0 PATTERN)",
                bundle, {
                    "acquirer_has_room_for_player": Kleene.TRUE,
                    "signer_post_trade_below_first_apron": Kleene.FALSE,  # ← FAILURE
                    "sign_and_trade_permitted": Kleene.FALSE,
                }, "signer_post_trade_below_first_apron"))

    # CASE 3: ACQUIRER lacks Room
    #   Signer is fine. Acquirer Team B is at $135M (room = $5.588M).
    #   Contract is $20M → exceeds acquirer's room.
    bundle = make_bundle(
        signing_team_post_trade_salary=150000000,
        acquiring_team_pre_trade_salary=135000000,
        contract_salary=20000000,
        contract_length=3,
    )
    out.append(("ILLEGAL S&T: acquirer lacks room",
                bundle, {
                    "acquirer_has_room_for_player": Kleene.FALSE,  # ← FAILURE
                    "signer_post_trade_below_first_apron": Kleene.TRUE,
                    "sign_and_trade_permitted": Kleene.FALSE,
                }, "acquirer_has_room_for_player"))

    # CASE 4: BOTH role-constraints fail simultaneously
    bundle = make_bundle(
        signing_team_post_trade_salary=185000000,  # over first apron
        acquiring_team_pre_trade_salary=135000000,  # low room
        contract_salary=20000000,
        contract_length=3,
    )
    out.append(("ILLEGAL S&T: BOTH signer over apron AND acquirer lacks room",
                bundle, {
                    "acquirer_has_room_for_player": Kleene.FALSE,
                    "signer_post_trade_below_first_apron": Kleene.FALSE,
                    "sign_and_trade_permitted": Kleene.FALSE,
                }, None))  # trace will show both

    # CASE 5: 2-year contract — violates length minimum
    bundle = make_bundle(
        signing_team_post_trade_salary=160000000,
        acquiring_team_pre_trade_salary=100000000,
        contract_salary=20000000,
        contract_length=2,  # ← below 3-year minimum
    )
    out.append(("ILLEGAL S&T: contract length only 2 years",
                bundle, {
                    "contract_length_3_to_4_years": Kleene.FALSE,
                    "sign_and_trade_permitted": Kleene.FALSE,
                }, "contract_length_3_to_4_years"))

    # CASE 6: 5-year contract — violates length maximum
    bundle = make_bundle(
        signing_team_post_trade_salary=160000000,
        acquiring_team_pre_trade_salary=100000000,
        contract_salary=20000000,
        contract_length=5,  # ← above 4-year maximum
    )
    out.append(("ILLEGAL S&T: contract length 5 years",
                bundle, {
                    "contract_length_3_to_4_years": Kleene.FALSE,
                    "sign_and_trade_permitted": Kleene.FALSE,
                }, "contract_length_3_to_4_years"))

    # CASE 7: Disallowed MLE pathway
    bundle = make_bundle(
        signing_team_post_trade_salary=160000000,
        acquiring_team_pre_trade_salary=100000000,
        contract_salary=20000000,
        contract_length=3,
        signed_via_disallowed_mle=True,  # ← Non-Taxpayer MLE used; illegal for S&T
    )
    out.append(("ILLEGAL S&T: signed via Non-Taxpayer MLE",
                bundle, {
                    "sign_and_trade_permitted": Kleene.FALSE,
                }, "signed_via_non_taxpayer_mle_or_room_mle"))

    # CASE 8: 5th-Year Eligible + Higher Max suppressing Designated boost
    #   Player meets the 5th-year-with-higher-max criteria.
    #   Per (vi), salary must not exceed 25% × cap = $35.147M.
    #   Contract is $40M → violates.
    bundle = make_bundle(
        signing_team_post_trade_salary=160000000,
        acquiring_team_pre_trade_salary=100000000,
        contract_salary=40000000,  # ← above 25% × cap
        contract_length=3,
        is_5th_year_with_higher_max=True,
    )
    out.append(("ILLEGAL S&T: 5th-year+HM player at $40M, exceeds 25% cap",
                bundle, {
                    "fifth_year_higher_max_constraint": Kleene.FALSE,
                    "sign_and_trade_permitted": Kleene.FALSE,
                }, "fifth_year_higher_max_constraint"))

    # CASE 9: SIGNER post-trade salary UNKNOWN
    #   Other constraints fine. The hard-cap check is undetermined.
    bundle = FactBundle(values={
        "signing_team_salary_post_trade": NumericValue.undetermined(),
        "acquiring_team_room": NumericValue.of(50000000),
        "contract_first_year_salary": NumericValue.of(20000000),
        "contract_length_years": NumericValue.of(3),
        "player_is_veteran_free_agent_on_prior_team": Kleene.TRUE,
        "signed_via_non_taxpayer_mle_or_room_mle": Kleene.FALSE,
        "first_season_fully_protected": Kleene.TRUE,
        "signed_before_regular_season_start": Kleene.TRUE,
        "is_5th_year_eligible_with_higher_max": Kleene.FALSE,
    })
    out.append(("UNDETERMINED S&T: signer post-trade salary unknown",
                bundle, {
                    "signer_post_trade_below_first_apron": Kleene.UNDETERMINED,
                    "sign_and_trade_permitted": Kleene.UNDETERMINED,
                }, "signer_post_trade_below_first_apron"))

    return out

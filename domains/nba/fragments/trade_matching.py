"""
NBA fragment 4 — Trade salary matching (Traded Player Exception).

EXERCISES
=========
CBA Section 6(j)(1): the four flavors of Traded Player Exception (TPE)
that govern multi-player trades. The constraint family:

  (i) Standard TPE:    post ≤ pre + $250K
                       (one player out, one or more players in)
  (ii) Aggregated TPE: post ≤ aggregated_pre + $250K
                       (two or more players out, simultaneously)
  (iv) Expanded TPE:   post ≤ max(2× pre + $250K, 1× pre + δ, 1.25× pre + $250K)
                       (used by teams below first apron only)
  (v) Room TPE:        post ≤ team_room + $250K
                       (used by teams below the cap)

Plus Section 6(j)(3): if post-assignment team salary > First Apron, the
$250K allowance is reduced to $0 in all of the above.

THE INTERESTING FAILURE MODE
=============================
In the Opus 4.7 baseline:
  aggregated_standard_traded_player_exception: P=0.0, R=0.0,
    Total Trigger: 11 (every invocation wrong)

  standard_traded_player_exception: P=0.75, R=0.64
  expanded_traded_player_exception: P=1.0, R=0.25
  traded_player_exception_for_room_team: P=0.0, R=undefined

Opus gets the standard (one-player) case mostly right and gets the
expanded case right when it cites it. But it has zero precision on the
aggregated case (multi-player outgoing).

The architecture handles this by Map binding a single derived numeric:
`aggregated_outgoing_pre_trade_salary` = sum of pre-trade salaries of all
players being sent out. The engine then does the standard inequality:
incoming ≤ aggregated_pre + $250K (or $0 if hard-capped). The
multi-player aggregation is Map's responsibility, not the engine's, per
the design principle.

WHAT THIS DEMONSTRATES
========================
1. Multi-player aggregation can be cleanly delegated to Map without
   losing structural correctness.
2. The four TPE flavors are mutually distinguishable via gating
   predicates on team salary position and trade shape.
3. The $250K-vs-$0 allowance switch is gated on the post-trade salary
   position (above first apron → $0).
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
# Constants
# ---------------------------------------------------------------------------

SALARY_CAP_2024_25 = Decimal("140588000")
FIRST_APRON_2024_25 = Decimal("178132000")
SECOND_APRON_2024_25 = Decimal("188931000")
TPE_ALLOWANCE = Decimal("250000")   # $250K bump for standard/aggregated/expanded
EXPANDED_MULTIPLIER = Decimal("1.25")  # the 125% in the expanded TPE


# ---------------------------------------------------------------------------
# Fragment construction
# ---------------------------------------------------------------------------

def build_fragment():
    """
    Build the TPE fragment.

    Numeric atoms (Map-bound):
      - aggregated_outgoing_pre_trade_salary   (Map sums across players sent)
      - aggregated_incoming_post_trade_salary  (Map sums across players received)
      - assigner_team_salary_pre_trade
      - assigner_team_salary_post_trade        (= pre - outgoing + incoming)
      - assigner_team_room                     (= max(0, cap - pre_salary))

    Boolean atoms (Map-bound):
      - trade_has_multiple_outgoing_players    (count of outgoing >= 2)
      - assigner_below_cap_pre_trade           (room > 0)
      - assigner_below_first_apron_post_trade  (assigner can use expanded)

    Composite gating:
      - allowance = $250K if assigner_below_first_apron_post_trade,
                    else $0
        (Section 6(j)(3): post-trade above first apron → allowance reduced)
    """

    # ------ Numeric leaves ------
    outgoing = NumericLeaf(atom_id="aggregated_outgoing_pre_trade_salary")
    incoming = NumericLeaf(atom_id="aggregated_incoming_post_trade_salary")
    assigner_room = NumericLeaf(atom_id="assigner_team_room")

    # ------ Trade-shape predicates ------
    multiple_outgoing = Leaf(atom_id="trade_has_multiple_outgoing_players")
    single_outgoing = NotNode(child=multiple_outgoing)
    assigner_below_cap = Leaf(atom_id="assigner_below_cap_pre_trade")
    assigner_below_first_apron_post = Leaf(
        atom_id="assigner_below_first_apron_post_trade")
    above_first_apron_post = NotNode(child=assigner_below_first_apron_post)

    # ------ Threshold computations (engine arithmetic) ------
    # Standard / Aggregated: outgoing + $250K (or +$0 if above first apron post)
    # Expanded: 1.25 × outgoing + $250K (or +$0)
    # Room: room + $250K (or +$0)

    standard_threshold_with_allowance = PlusConstNode(
        child=outgoing,
        constant=TPE_ALLOWANCE,
        surface_label="outgoing + $250K",
    )
    # The "or $0" version: just outgoing.
    # We'll express the gating via an OR in the parent predicate.

    expanded_threshold_with_allowance = PlusConstNode(
        child=TimesConstNode(
            child=outgoing,
            constant=EXPANDED_MULTIPLIER,
            surface_label="1.25 × outgoing",
        ),
        constant=TPE_ALLOWANCE,
        surface_label="1.25 × outgoing + $250K",
    )
    expanded_threshold_no_allowance = TimesConstNode(
        child=outgoing,
        constant=EXPANDED_MULTIPLIER,
        surface_label="1.25 × outgoing",
    )

    room_threshold_with_allowance = PlusConstNode(
        child=assigner_room,
        constant=TPE_ALLOWANCE,
        surface_label="room + $250K",
    )

    # ------ Match predicates: incoming ≤ threshold, gated by post-trade bracket ------
    # We build the "with allowance" and "without allowance" cases separately,
    # then OR them gated on the bracket.

    incoming_within_standard_with_allowance = LeqNode(
        left=incoming,
        right=standard_threshold_with_allowance,
        surface_label="incoming <= outgoing + $250K",
    )
    incoming_within_standard_no_allowance = LeqNode(
        left=incoming,
        right=outgoing,  # outgoing directly when allowance is $0
        surface_label="incoming <= outgoing",
    )

    # Standard/Aggregated: salary-match satisfied iff
    #   (assigner_below_first_apron_post AND incoming <= outgoing + $250K)
    #   OR
    #   (NOT(assigner_below_first_apron_post) AND incoming <= outgoing)
    standard_or_aggregated_salary_matched = OrNode(
        children=[
            AndNode(children=[
                assigner_below_first_apron_post,
                incoming_within_standard_with_allowance,
            ], surface_label="below_apron_post + within_allowance_match"),
            AndNode(children=[
                above_first_apron_post,
                incoming_within_standard_no_allowance,
            ], surface_label="above_apron_post + strict_match"),
        ],
        surface_label="standard_or_aggregated_salary_matched",
    )

    incoming_within_expanded_with_allowance = LeqNode(
        left=incoming, right=expanded_threshold_with_allowance,
        surface_label="incoming <= 1.25 × outgoing + $250K",
    )
    incoming_within_expanded_no_allowance = LeqNode(
        left=incoming, right=expanded_threshold_no_allowance,
        surface_label="incoming <= 1.25 × outgoing",
    )
    expanded_salary_matched = OrNode(
        children=[
            AndNode(children=[
                assigner_below_first_apron_post,
                incoming_within_expanded_with_allowance,
            ], surface_label="below_apron_post + within_expanded_allowance"),
            AndNode(children=[
                above_first_apron_post,
                incoming_within_expanded_no_allowance,
            ], surface_label="above_apron_post + strict_expanded"),
        ],
        surface_label="expanded_salary_matched",
    )

    incoming_within_room_with_allowance = LeqNode(
        left=incoming, right=room_threshold_with_allowance,
        surface_label="incoming <= room + $250K",
    )
    incoming_within_room_no_allowance = LeqNode(
        left=incoming, right=assigner_room,
        surface_label="incoming <= room",
    )
    room_salary_matched = OrNode(
        children=[
            AndNode(children=[
                assigner_below_first_apron_post,
                incoming_within_room_with_allowance,
            ], surface_label="below_apron_post + within_room_allowance"),
            AndNode(children=[
                above_first_apron_post,
                incoming_within_room_no_allowance,
            ], surface_label="above_apron_post + strict_room"),
        ],
        surface_label="room_salary_matched",
    )

    # ------ Flavor applicability ------
    # Standard TPE: single outgoing player
    standard_tpe_applies = AndNode(
        children=[
            single_outgoing,
            standard_or_aggregated_salary_matched,
        ],
        surface_label="standard_tpe_satisfied",
    )

    # Aggregated TPE: multiple outgoing, same salary-match
    aggregated_tpe_applies = AndNode(
        children=[
            multiple_outgoing,
            standard_or_aggregated_salary_matched,
        ],
        surface_label="aggregated_tpe_satisfied",
    )

    # Expanded TPE: assigner below first apron post-trade (Section 6(j)(2)
    # restricts to below-apron teams)
    # Simplification: condition is the same below_first_apron_post atom.
    expanded_tpe_applies = AndNode(
        children=[
            assigner_below_first_apron_post,
            expanded_salary_matched,
        ],
        surface_label="expanded_tpe_satisfied",
    )

    # Room TPE: assigner below cap pre-trade
    room_tpe_applies = AndNode(
        children=[
            assigner_below_cap,
            room_salary_matched,
        ],
        surface_label="room_tpe_satisfied",
    )

    # ------ Top-level: trade is permitted if ANY flavor matches ------
    trade_salary_match_permitted = OrNode(
        children=[
            standard_tpe_applies,
            aggregated_tpe_applies,
            expanded_tpe_applies,
            room_tpe_applies,
        ],
        surface_label="trade_salary_match_permitted",
    )

    return {
        "standard_or_aggregated_salary_matched":
            standard_or_aggregated_salary_matched,
        "expanded_salary_matched": expanded_salary_matched,
        "room_salary_matched": room_salary_matched,
        "standard_tpe_applies": standard_tpe_applies,
        "aggregated_tpe_applies": aggregated_tpe_applies,
        "expanded_tpe_applies": expanded_tpe_applies,
        "room_tpe_applies": room_tpe_applies,
        "trade_salary_match_permitted": trade_salary_match_permitted,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bundle(*,
                outgoing_salary,
                incoming_salary,
                assigner_pre_trade_salary,
                multiple_outgoing=False,
                assigner_below_first_apron_post=True):
    """Construct a TPE-case bundle.

    Map's responsibility (here pre-computed for the bundle):
      - aggregated outgoing salary (sum across players)
      - aggregated incoming salary (sum across players)
      - assigner room (max(0, cap - pre-trade salary))
      - assigner_below_cap_pre_trade
    """
    pre = Decimal(str(assigner_pre_trade_salary))
    room = max(Decimal(0), SALARY_CAP_2024_25 - pre)
    return FactBundle(values={
        "aggregated_outgoing_pre_trade_salary": NumericValue.of(outgoing_salary),
        "aggregated_incoming_post_trade_salary": NumericValue.of(incoming_salary),
        "assigner_team_room": NumericValue.of(room),
        "trade_has_multiple_outgoing_players":
            Kleene.TRUE if multiple_outgoing else Kleene.FALSE,
        "assigner_below_cap_pre_trade":
            Kleene.TRUE if pre < SALARY_CAP_2024_25 else Kleene.FALSE,
        "assigner_below_first_apron_post_trade":
            Kleene.TRUE if assigner_below_first_apron_post else Kleene.FALSE,
    })


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def cases():
    out = []

    # CASE 1: Clean STANDARD TPE — one-for-one trade, within standard match
    # Out: $10M one player. In: $10M one player. Allowance: $250K.
    # Threshold: $10M + $250K = $10.25M. In $10M <= $10.25M ✓
    bundle = make_bundle(
        outgoing_salary=10000000,
        incoming_salary=10000000,
        assigner_pre_trade_salary=160000000,
        multiple_outgoing=False,
    )
    out.append(("Standard TPE: one-for-one, exact match",
                bundle, {
                    "standard_tpe_applies": Kleene.TRUE,
                    "trade_salary_match_permitted": Kleene.TRUE,
                }))

    # CASE 2: STANDARD TPE — incoming slightly above outgoing, within $250K
    # Out $10M, In $10.1M, threshold $10.25M ✓
    bundle = make_bundle(
        outgoing_salary=10000000,
        incoming_salary=10100000,
        assigner_pre_trade_salary=160000000,
        multiple_outgoing=False,
    )
    out.append(("Standard TPE: incoming within $250K allowance",
                bundle, {
                    "standard_tpe_applies": Kleene.TRUE,
                    "trade_salary_match_permitted": Kleene.TRUE,
                }))

    # CASE 3: STANDARD TPE — incoming exceeds outgoing + $250K → fails standard,
    # but team is below first apron, so expanded (1.25×) might still apply
    # Out $10M, In $11M, threshold = max($10.25M for std, 1.25*$10M+$250K=$12.75M for expanded)
    # $11M > $10.25M → standard fails
    # $11M <= $12.75M → expanded succeeds
    bundle = make_bundle(
        outgoing_salary=10000000,
        incoming_salary=11000000,
        assigner_pre_trade_salary=160000000,
        multiple_outgoing=False,
    )
    out.append(("Expanded TPE: incoming exceeds standard, fits expanded 1.25×",
                bundle, {
                    "standard_tpe_applies": Kleene.FALSE,
                    "expanded_tpe_applies": Kleene.TRUE,
                    "trade_salary_match_permitted": Kleene.TRUE,
                }))

    # CASE 4: HEADLINE — AGGREGATED TPE (multiple outgoing players)
    # This is the family Opus 4.7 has P=0 on.
    # Out: 2 players totaling $20M.  In: 1 player at $20M.
    # Standard match: $20M ≤ $20M + $250K ✓
    bundle = make_bundle(
        outgoing_salary=20000000,
        incoming_salary=20000000,
        assigner_pre_trade_salary=160000000,
        multiple_outgoing=True,
    )
    out.append(("AGGREGATED TPE: 2 outgoing summing to $20M, $20M incoming, MATCHES",
                bundle, {
                    "standard_tpe_applies": Kleene.FALSE,    # not single outgoing
                    "aggregated_tpe_applies": Kleene.TRUE,   # multiple outgoing ✓
                    "trade_salary_match_permitted": Kleene.TRUE,
                }))

    # CASE 5: AGGREGATED TPE — too much incoming, exceeds even expanded
    # Out: $20M aggregated. In: $30M. Standard threshold $20.25M, expanded $25.25M
    # $30M exceeds both. ILLEGAL.
    bundle = make_bundle(
        outgoing_salary=20000000,
        incoming_salary=30000000,
        assigner_pre_trade_salary=160000000,
        multiple_outgoing=True,
    )
    out.append(("AGGREGATED TPE ILLEGAL: $30M in for $20M out, exceeds expanded",
                bundle, {
                    "aggregated_tpe_applies": Kleene.FALSE,
                    "expanded_tpe_applies": Kleene.FALSE,
                    "trade_salary_match_permitted": Kleene.FALSE,
                }))

    # CASE 6: HARD-CAP AT FIRST APRON — $250K allowance reduced to $0
    # Assigner post-trade ABOVE first apron. Out $10M, In $10.1M.
    # Standard threshold (no allowance) = $10M. $10.1M > $10M → ILLEGAL.
    # And expanded path requires assigner_below_first_apron_post, so doesn't apply.
    bundle = make_bundle(
        outgoing_salary=10000000,
        incoming_salary=10100000,
        assigner_pre_trade_salary=170000000,
        multiple_outgoing=False,
        assigner_below_first_apron_post=False,  # ← post-trade ABOVE first apron
    )
    out.append(("Hard-capped: $250K allowance reduced to $0, $10.1M > $10M, ILLEGAL",
                bundle, {
                    "standard_tpe_applies": Kleene.FALSE,   # strict match fails
                    "expanded_tpe_applies": Kleene.FALSE,   # gate fails
                    "trade_salary_match_permitted": Kleene.FALSE,
                }))

    # CASE 7: ROOM TPE — team below cap, uses Room+$250K
    # Pre-trade salary $100M → room = $140.588M - $100M = $40.588M
    # Room threshold: $40.588M + $250K = $40.838M
    # In: $30M ≤ $40.838M ✓
    bundle = make_bundle(
        outgoing_salary=0,   # no outgoing — pure acquisition
        incoming_salary=30000000,
        assigner_pre_trade_salary=100000000,
        multiple_outgoing=False,
    )
    out.append(("Room TPE: team below cap, $30M acquisition fits room+$250K",
                bundle, {
                    "room_tpe_applies": Kleene.TRUE,
                    "trade_salary_match_permitted": Kleene.TRUE,
                }))

    # CASE 8: UNDETERMINED — outgoing salary unknown
    bundle = FactBundle(values={
        "aggregated_outgoing_pre_trade_salary": NumericValue.undetermined(),
        "aggregated_incoming_post_trade_salary": NumericValue.of(10000000),
        "assigner_team_room": NumericValue.of(0),
        "trade_has_multiple_outgoing_players": Kleene.FALSE,
        "assigner_below_cap_pre_trade": Kleene.FALSE,
        "assigner_below_first_apron_post_trade": Kleene.TRUE,
    })
    out.append(("UNDETERMINED: outgoing salary unknown → match undetermined",
                bundle, {
                    "standard_tpe_applies": Kleene.UNDETERMINED,
                    "trade_salary_match_permitted": Kleene.UNDETERMINED,
                }))

    return out

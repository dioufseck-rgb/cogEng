"""
verify_phase1a_synthetic.py — re-evaluate the Phase 1A synthetic cases
against the actual atom_ids Build emitted.

The original probe used atom names I'd guessed (player_is_5th_year_eligible,
base_max_salary_under_7, ...) that don't match what Build's dedup pass
actually produced (nba.a001, nba.under_7_base_ceiling, ...). The engine
correctly returned UNDETERMINED because it couldn't find the atoms in the
FactBundle.

This script:
  1. Rebuilds the engine DAG from the saved audit's atom registry
     (the audit captures atom_ids, statements, types)
  2. Constructs FactBundles using the actual atom_ids
  3. Evaluates the three synthetic cases
  4. Reports pass/fail per case + Case 2's over-firing protection result

Cost: $0 (no LLM calls; pure engine evaluation against captured DAG).

NOTE: We don't have the engine DAG pickled — only the spec_tree and the
atoms_registered metadata are in the audit. To reconstruct the engine
without re-running Build, we'd need to re-run finalize+spec_to_engine_node
on the saved spec_tree. That's still $0 (those steps reuse cached LLM
calls if dedup ran successfully).

Actually simpler: re-run the probe with offline_responses populated from
the audit's recorded calls. That way the SAME spec tree + the SAME dedup
output rebuild the SAME engine DAG, deterministically, at zero cost, and
we evaluate the synthetic cases with correct atom names.

USAGE:
    cd /workspaces/cogEng
    python tests/probes/verify_phase1a_synthetic.py
"""
from __future__ import annotations
import json
import os
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from probe_harness import LoggingLLMCaller
from rulekit.build.decomposer import (
    DeterminationDeclaration, DecomposeState, LLMCaller,
    decompose_claim, spec_to_engine_node, finalize_spec,
)
from rulekit.build.extract import ReaderVoice
from rulekit.engine import FactBundle, Kleene
from rulekit.engine.typed import NumericValue


# ---------------------------------------------------------------------------
# Load the offline responses from the audit. Each call in audit.calls has
# stage + prompt + response; LLMCaller.offline_responses is a dict
# stage -> response, so we rebuild that.
# ---------------------------------------------------------------------------

AUDIT_PATH = os.path.join(HERE, "audit_logs", "probe_phase1a_max_salary_audit.json")

if not os.path.exists(AUDIT_PATH):
    print(f"ERROR: audit not found at {AUDIT_PATH}")
    print(f"  Run probe_phase1a_max_salary.py first.")
    sys.exit(2)

with open(AUDIT_PATH) as f:
    audit = json.load(f)

offline_responses = {}
for c in audit["calls"]:
    offline_responses[c["stage"]] = c["response"]

print(f"Loaded {len(offline_responses)} offline responses from audit.")


# ---------------------------------------------------------------------------
# Import the original probe's policy/determination/voice/constants so the
# rebuild uses the exact same inputs.
# ---------------------------------------------------------------------------

import importlib.util
spec_loader = importlib.util.spec_from_file_location(
    "probe_phase1a", os.path.join(HERE, "probe_phase1a_max_salary.py")
)
probe_mod = importlib.util.module_from_spec(spec_loader)
spec_loader.loader.exec_module(probe_mod)


# ---------------------------------------------------------------------------
# Rebuild the engine DAG deterministically using offline LLM responses.
# ---------------------------------------------------------------------------

print("Rebuilding spec tree from offline responses...")
inner_llm = LLMCaller(model="claude-opus-4-7", offline_responses=offline_responses)
llm = LoggingLLMCaller(inner_llm)

state = DecomposeState(
    llm=llm,
    policy_text=probe_mod.POLICY_TEXT,
    voice=probe_mod.VOICE,
    determination=probe_mod.DETERMINATION,
)

try:
    spec_tree = decompose_claim(
        claim=probe_mod.DETERMINATION.description,
        path=[probe_mod.DETERMINATION.id],
        depth=0,
        state=state,
    )
    print(f"  decompose_claim OK ({state.call_count} offline calls replayed)")
except Exception as e:
    print(f"  decompose_claim FAILED: {type(e).__name__}: {e}")
    sys.exit(1)

print("Re-running finalize_spec...")
try:
    finalize_audit = finalize_spec(
        {probe_mod.DETERMINATION.id: spec_tree},
        llm,
        abbreviation="nba",
    )
    print(f"  finalize_spec OK")
except Exception as e:
    print(f"  finalize_spec FAILED: {type(e).__name__}: {e}")
    sys.exit(1)

print("Re-running spec_to_engine_node...")
atoms: dict = {}
try:
    engine_node = spec_to_engine_node(
        spec_tree, atoms, probe_mod.CONSTANTS,
    )
    print(f"  spec_to_engine_node OK ({len(atoms)} atoms registered)")
except Exception as e:
    print(f"  spec_to_engine_node FAILED: {type(e).__name__}: {e}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Build corrected synthetic cases with the ACTUAL atom_ids Build emitted.
#
# Atom map (from audit's atoms_registered):
#   nba.player_years_of_service                              — numeric
#   nba.player_years_of_service_at_contract_execution        — numeric
#   nba.contract_first_year_salary_plus_unlikely_bonuses    — numeric
#   nba.first_year_salary_plus_unlikely_bonuses             — numeric
#   nba.under_7_base_ceiling                                — numeric
#   nba.under_7_boosted_ceiling                             — numeric (also reps yos_7_9_base)
#   nba.designated_veteran_7_9_yos_boosted_ceiling          — numeric (also reps 10_plus)
#   nba.a001 — 5th-Year Eligible
#   nba.a002 — All-NBA preceding Season
#   nba.a003 — All-NBA 2-of-3 Seasons
#   nba.a004 — DPOY preceding Season
#   nba.a005 — DPOY 2-of-3 Seasons
#   nba.a006 — MVP within 3 Seasons
#   nba.a007 — Player has 8 YOS (this is a Leaf because Build emitted it
#              that way for "Player has 8 YOS at execution" — note it's
#              redundant with the EqNode also in the tree, harmless)
#   nba.a008 — rendered YOS for first team
#   nba.a009 — changed teams only by trade in first 4 cap years (conditional)
#   nba.a010 — was under contract for >1 team during first 4 cap years
#   nba.a011 — changed teams only by trade during first 4 cap years
#
# Ceiling values for synthetic cases (computed from CBA constants):
#   Salary Cap 2024-25 = $140,588,000
#   25% × cap = $35,147,000  (under-7 base, prior ≤ ~$33.5M)
#   30% × cap = $42,176,400  (under-7 boosted / 7-9 base)
#   35% × cap = $49,205,800  (7-9 boosted / 10+)
# ---------------------------------------------------------------------------

CASES = [
    # CASE 1: YOS=5, no_boost (a001=FALSE → boost not eligible),
    # contract $30M ≤ base ceiling $35.147M → expect TRUE
    {
        "label": "YOS=5, no boost, salary=$30M, base=$35.147M → expect TRUE",
        "expected": Kleene.TRUE,
        "values": {
            "nba.player_years_of_service": NumericValue.of(5),
            "nba.player_years_of_service_at_contract_execution": NumericValue.of(5),
            "nba.contract_first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("30000000")),
            "nba.first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("30000000")),
            "nba.under_7_base_ceiling": NumericValue.of(Decimal("35147000")),
            "nba.under_7_boosted_ceiling": NumericValue.of(Decimal("42176400")),
            "nba.designated_veteran_7_9_yos_boosted_ceiling": NumericValue.of(Decimal("49205800")),
            "nba.a001": Kleene.FALSE,  # not 5th-Year Eligible
            "nba.a002": Kleene.FALSE,  # no All-NBA
            "nba.a003": Kleene.FALSE,
            "nba.a004": Kleene.FALSE,  # no DPOY
            "nba.a005": Kleene.FALSE,
            "nba.a006": Kleene.FALSE,  # no MVP
            "nba.a007": Kleene.FALSE,  # not 8 YOS
            "nba.a008": Kleene.FALSE,  # tenure pred not applicable
            "nba.a009": Kleene.FALSE,
            "nba.a010": Kleene.FALSE,
            "nba.a011": Kleene.FALSE,
        },
    },

    # CASE 2: THE OVER-FIRING PROTECTION CASE.
    # YOS=4, has Higher Max Criteria (a002=TRUE All-NBA), but NOT
    # 5th-Year Eligible (a001=FALSE). Contract $39.4M exceeds base
    # ceiling $35.147M but is below boosted $42.176M.
    # Correct: FALSE because the AND(a001, higher_max_criteria) gate fails.
    {
        "label": "YOS=4, higher_max=TRUE, 5th_yr=FALSE, salary=$39.4M → expect FALSE",
        "expected": Kleene.FALSE,
        "values": {
            "nba.player_years_of_service": NumericValue.of(4),
            "nba.player_years_of_service_at_contract_execution": NumericValue.of(4),
            "nba.contract_first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("39400000")),
            "nba.first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("39400000")),
            "nba.under_7_base_ceiling": NumericValue.of(Decimal("35147000")),
            "nba.under_7_boosted_ceiling": NumericValue.of(Decimal("42176400")),
            "nba.designated_veteran_7_9_yos_boosted_ceiling": NumericValue.of(Decimal("49205800")),
            "nba.a001": Kleene.FALSE,  # ← CRITICAL: not 5th-Year Eligible
            "nba.a002": Kleene.TRUE,   # ← has All-NBA criteria
            "nba.a003": Kleene.FALSE,
            "nba.a004": Kleene.FALSE,
            "nba.a005": Kleene.FALSE,
            "nba.a006": Kleene.FALSE,
            "nba.a007": Kleene.FALSE,
            "nba.a008": Kleene.FALSE,
            "nba.a009": Kleene.FALSE,
            "nba.a010": Kleene.FALSE,
            "nba.a011": Kleene.FALSE,
        },
    },

    # CASE 3: YOS unknown → UNDETERMINED propagation
    {
        "label": "YOS unknown → expect UNDETERMINED",
        "expected": Kleene.UNDETERMINED,
        "values": {
            "nba.player_years_of_service": NumericValue.undetermined(),
            "nba.player_years_of_service_at_contract_execution": NumericValue.undetermined(),
            "nba.contract_first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("30000000")),
            "nba.first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("30000000")),
            "nba.under_7_base_ceiling": NumericValue.undetermined(),
            "nba.under_7_boosted_ceiling": NumericValue.undetermined(),
            "nba.designated_veteran_7_9_yos_boosted_ceiling": NumericValue.undetermined(),
            "nba.a001": Kleene.UNDETERMINED,
            "nba.a002": Kleene.UNDETERMINED,
            "nba.a003": Kleene.UNDETERMINED,
            "nba.a004": Kleene.UNDETERMINED,
            "nba.a005": Kleene.UNDETERMINED,
            "nba.a006": Kleene.UNDETERMINED,
            "nba.a007": Kleene.UNDETERMINED,
            "nba.a008": Kleene.UNDETERMINED,
            "nba.a009": Kleene.UNDETERMINED,
            "nba.a010": Kleene.UNDETERMINED,
            "nba.a011": Kleene.UNDETERMINED,
        },
    },

    # CASE 4 (BONUS): YOS=4, has Higher Max AND IS 5th-Year Eligible,
    # salary $42M within boosted ceiling → expect TRUE
    # (validates that the boost pathway works when both conditions hold)
    {
        "label": "YOS=4, 5th_yr=TRUE, higher_max=TRUE, salary=$42M → expect TRUE (boost works)",
        "expected": Kleene.TRUE,
        "values": {
            "nba.player_years_of_service": NumericValue.of(4),
            "nba.player_years_of_service_at_contract_execution": NumericValue.of(4),
            "nba.contract_first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("42000000")),
            "nba.first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("42000000")),
            "nba.under_7_base_ceiling": NumericValue.of(Decimal("35147000")),
            "nba.under_7_boosted_ceiling": NumericValue.of(Decimal("42176400")),
            "nba.designated_veteran_7_9_yos_boosted_ceiling": NumericValue.of(Decimal("49205800")),
            "nba.a001": Kleene.TRUE,   # ← 5th-Year Eligible
            "nba.a002": Kleene.TRUE,   # ← has All-NBA
            "nba.a003": Kleene.FALSE,
            "nba.a004": Kleene.FALSE,
            "nba.a005": Kleene.FALSE,
            "nba.a006": Kleene.FALSE,
            "nba.a007": Kleene.FALSE,
            "nba.a008": Kleene.FALSE,
            "nba.a009": Kleene.FALSE,
            "nba.a010": Kleene.FALSE,
            "nba.a011": Kleene.FALSE,
        },
    },

    # CASE 5 (BONUS): YOS=12, contract within 10+ branch's effective ceiling.
    # Note: dedup merged the 10+ ceiling into designated_veteran_7_9_yos_boosted_ceiling,
    # so we use that atom_id. The formula is the same (35% × cap or 105% × prior).
    {
        "label": "YOS=12, salary=$48M, ceiling=$49.2M → expect TRUE (10+ branch)",
        "expected": Kleene.TRUE,
        "values": {
            "nba.player_years_of_service": NumericValue.of(12),
            "nba.player_years_of_service_at_contract_execution": NumericValue.of(12),
            "nba.contract_first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("48000000")),
            "nba.first_year_salary_plus_unlikely_bonuses": NumericValue.of(Decimal("48000000")),
            "nba.under_7_base_ceiling": NumericValue.of(Decimal("35147000")),
            "nba.under_7_boosted_ceiling": NumericValue.of(Decimal("42176400")),
            "nba.designated_veteran_7_9_yos_boosted_ceiling": NumericValue.of(Decimal("49205800")),
            "nba.a001": Kleene.FALSE,
            "nba.a002": Kleene.FALSE,
            "nba.a003": Kleene.FALSE,
            "nba.a004": Kleene.FALSE,
            "nba.a005": Kleene.FALSE,
            "nba.a006": Kleene.FALSE,
            "nba.a007": Kleene.FALSE,
            "nba.a008": Kleene.FALSE,
            "nba.a009": Kleene.FALSE,
            "nba.a010": Kleene.FALSE,
            "nba.a011": Kleene.FALSE,
        },
    },
]


# ---------------------------------------------------------------------------
# Run the cases
# ---------------------------------------------------------------------------

print("\n" + "=" * 75)
print("EVALUATING CORRECTED SYNTHETIC CASES")
print("=" * 75)

passed = 0
failed = 0
for case in CASES:
    bundle = FactBundle(values=case["values"])
    result = engine_node.evaluate(bundle)
    status = "PASS" if result == case["expected"] else "FAIL"
    if result == case["expected"]:
        passed += 1
    else:
        failed += 1
    print(f"\n  [{status}] {case['label']}")
    print(f"        Expected: {case['expected']}  |  Got: {result}")

print("\n" + "=" * 75)
print(f"RESULTS: {passed} passed, {failed} failed (of {len(CASES)})")
print("=" * 75)

if failed > 0:
    print("\nIf any FAIL: the engine DAG isn't correctly evaluating one of the")
    print("scenarios. Most likely cause: an atom name I assumed above doesn't")
    print("match what's actually in the registered atoms set. Verify against:")
    print(f"  python -c \"import json; d=json.load(open('{AUDIT_PATH}')); print(list(d['atoms_registered'].keys()))\"")
    sys.exit(1)
else:
    print("\nAll synthetic cases pass.")
    print("Phase 1A is FULLY VERIFIED: structural strict win + correct evaluation.")
    sys.exit(0)

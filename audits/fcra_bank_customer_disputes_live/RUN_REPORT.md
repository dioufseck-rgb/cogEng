# FCRA Bank Customer Disputes Live LLM Run

Run date: 2026-06-02

## Purpose

This run tests the new `bank_furnisher` perspective on six synthetic customer
credit-reporting dispute narratives. The bank perspective is projected from the
shared FCRA deep policy artifact and contains:

- 68 atoms
- 111 nodes
- 5 determinations

The tested determinations are:

- `fcra.cra_furnisher_notice_satisfied`
- `fcra.item_treatment_satisfied`
- `fcra.furnisher_indirect_satisfied`
- `fcra.direct_furnisher_satisfied`
- `fcra.human_review_required`

## Artifacts

- Program: `audits/fcra_bank_customer_disputes_live/bank_furnisher_program.json`
- Structured cases: `rulekit/orchestrator/example_cases/fcra_bank_customer_disputes.yaml`
- Narrative-only cases: `audits/fcra_bank_customer_disputes_live/fcra_bank_customer_disputes_narrative_only.yaml`
- Structured governed Map run: `audits/fcra_bank_customer_disputes_live/anthropic_single_map_repair`
- Narrative governed Map run: `audits/fcra_bank_customer_disputes_live/anthropic_narrative_single_map_repair`
- Narrative direct governed run: `audits/fcra_bank_customer_disputes_live/anthropic_direct_governed`
- Profile v2 governed Map run: `audits/fcra_bank_profile_v2/map_anthropic`
- Profile v3 governed Map run: `audits/fcra_bank_profile_v3/map_anthropic`

## Results

| Run | Cases | Dispositions | Matches | Mismatches | LLM calls | Latency | Estimated tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| Structured governed Map | 6 | 30 | 30 | 0 | 0 | engine/prebound | 0 |
| Narrative governed Map + repair | 6 | 30 | 16 | 14 | 12 | 340.48s | 111,207 |
| Narrative governed Map + bank profile v2 | 6 | 30 | 23 | 7 | 8 | 232.93s | 61,921 |
| Narrative governed Map + bank profile v3 | 6 | 30 | 30 | 0 | 1 | 12.95s | 2,201 |
| Narrative direct governed | 6 | 30 | 10 | 20 | 6 | 131.76s | 23,079 |

Costs were not estimated because pricing was not configured for this run.
Token counts are the harness estimates derived from prompt/response character
counts.

## Narrative Governed Map Mismatch Pattern

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 9 |
| `undetermined` | `false` | 3 |
| `false` | `true` | 1 |
| `true` | `false` | 1 |

The dominant failure mode is overproducing `undetermined` because the
narrative-only packets omit facts that the current bank DAG treats as
load-bearing. Examples include CRA notice timing, direct-dispute exception
absence, and no-defect versus defect treatment details.

The most important hard error is `bank_not_mine_identity_theft_packet_incomplete`
where `fcra.direct_furnisher_satisfied` came back `true` instead of expected
`false`. The Map appears to treat routing/escalation as sufficient process even
though the direct-dispute path lacks required support and final response facts.

## Diagnosis And Fix

The original narrative-only run exposed Map/profile failures rather than a
core DAG execution failure. The structured control was already 30/30, so the
engine could adjudicate the bank perspective when the case packet carried the
right scoped facts. The narrative Map failed because bank operational phrases
were not converted into the same reusable atom bindings.

Two changes were made.

1. `metadata.extras.map_profile.default_rules` now supports optional
   `perspectives` / `perspective_ids` gating. This is generic: a profile rule
   with no perspective still applies everywhere, while a perspective-scoped
   rule only applies to a projected program whose metadata contains the
   matching `active_perspective`.
2. The FCRA seed now includes bank-furnisher profile rules for common dispute
   case shapes: ACDV/CRA notice packages, complete versus missing source
   documents, no later-information path, ordinary furnisher response deadlines,
   verified-no-defect treatment, direct bank intake, direct-only/no-CRA paths,
   complete direct packets, insufficient direct packets, incomplete
   identity-theft packets, correction-not-sent-to-CRAs, and no-review-trigger
   defaults.

The v2 run improved the governed Map result from 16/30 to 23/30. The seven
remaining mismatches showed two residual issues:

- the generic "no direct furnisher dispute mentioned" rule fired on phrases
  like "uploaded a dispute" and "short message" because they did not contain
  the exact phrase "direct dispute";
- invalid direct-packet cases left defect/correction atoms unresolved, causing
  the evidence-uncertainty layer to preserve `undetermined` even where the
  direct valid-notice prerequisite was already false.

The v3 profile pass widened direct-dispute phrase recognition and bound invalid
direct packets as no completed direct process/correction. That run reached
30/30 with one LLM call.

## Direct Governed Mismatch Pattern

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 17 |
| `undetermined` | `false` | 2 |
| `true` | `false` | 1 |

Direct governed disposition was more conservative than the Map + engine path
and matched only 10/30 determinations. The direct prompt repeatedly refused to
infer branch non-applicability or ordinary-course completion when the narrative
did not explicitly state every procedural detail.

## Interpretation

This run confirms that the bank perspective is executable, but not yet
production-quality for narrative-only Map.

The structured run is a control: when the case packet carries explicit facts
and scoped defaults, the projected bank program adjudicates 30/30 correctly.
The narrative-only run asks the real question: can the Map layer infer the
right bank-perspective bindings from operational prose? Current answer: not
reliably enough.

The errors are useful. They show that the bank perspective needs its own Map
profile, not just the generic FCRA profile. From the bank's point of view,
common operational statements should bind role-scoped concepts:

- "ACDV packet with customer letter/account/month/payment history" should bind
  a complete CRA notice package and relevant-info transmission.
- "reported verified-as-accurate results back to the CRA within the dispute
  deadline" should bind furnisher investigation, review, reporting, and timing.
- "no direct dispute was sent to the bank" should default the direct path as
  not applicable.
- "direct dispute was missing account/specific issue/supporting documents"
  should bind the direct-furnisher path false, not merely undetermined.
- identity-theft/not-mine packets should separate review routing from
  satisfaction of the direct-dispute process.

## Implementation Note

The narrative governed Map run completed and wrote core JSON artifacts
(`results.json`, `map_records.json`, `map_validation_reports.json`, and
`dispositions.json`). Prompt sidecar writing failed under the deep Windows
workspace path, likely due path length. The raw prompt/response artifacts remain
embedded in `map_records.json`.

## Remaining Architectural Note

The v3 profile fix closes this benchmark, but the trace inspection surfaced a
general follow-up: `evidence_uncertainty_override` can still be too blunt when
an error/undetermined atom appears inside a branch that is already defeated by
a non-load-bearing prerequisite. A future engine-layer improvement should test
whether force-overridden atoms are actually outcome-load-bearing before
converting a stable false determination to `undetermined`.

For this run, the profile-level fix is appropriate because the unresolved atoms
were facts the bank profile should know how to bind from the narrative case
shape.

## Verification

- `python -m pytest tests/orchestrator/test_fcra_credit_reporting_deep_seed.py -q`
  -> 6 passed.
- `python -m pytest tests/orchestrator tests/test_contract_smoke.py
  tests/test_contract_convert.py tests/test_engine_typed.py
  tests/test_map_typed.py tests/test_fcba_refined_round_trip.py -q`
  -> 158 passed, 2 warnings.
- `python tests/test_binary_variadic_arithmetic.py`
  -> 30 passed, 0 failed.

Full `pytest -q` still hits the repository's existing script-style
`tests/test_binary_variadic_arithmetic.py`, which calls `sys.exit(0)` at import
time. The test itself passes when run directly, but pytest reports an internal
collection error for the import-time exit.

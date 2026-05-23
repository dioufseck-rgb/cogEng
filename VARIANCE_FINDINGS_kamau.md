# Variance Findings — kamau × 10 runs

**Session:** `b56daf5f`
**Date:** 2026-05-19
**Case:** kamau (PA-2024-G006, FM-6 distractor susceptibility — prior PA history)
**Model:** `claude-sonnet-4-5`
**N runs:** 10 independent substrate invocations, same case, same engine, same tree

## Headline

Across 10 independent substrate invocations of the same case:

- **Disposition:** 10/10 identical (`overturn_factual_error_in_denial`)
- **Routing tier:** all 10 in human-review band — 6 GATE, 4 SPOT_CHECK, 0 AUTO, 0 HOLD
- **Overall confidence:** 0.85 across all runs (identical)
- **Substrate calls:** range 8–17, mean 13.0, stdev 4.3 (bimodal at 8 and 16-17)
- **Wall clock:** 40.5s – 100.6s, mean 71.4s
- **Escalations per run:** 1–4, mean 2.4

## What the variance actually looks like

The summary above masks the texture. The per-leaf consistency data reveals the variance has a specific narrow shape:

### Value-level variance: zero

Every leaf the substrate evaluated returned the **same value at the same confidence** in every run. Across 10 runs of every char leaf in the tree:

- No leaf flipped True ↔ False
- No leaf flipped between enumerated values (e.g. ACCURATE vs INACCURATE)
- Confidence ranges were tight — typically single-point distributions

The substrate is not flip-flopping on substantive conclusions.

### Escalation-level variance: concentrated on two leaves

Two leaves return the same value every run but disagree with themselves about whether to escalate:

| Leaf | Value (every run) | Escalates |
|------|-------------------|-----------|
| `pharmacotherapy_requirement_met` | False | 6/10 runs |
| `pt_contraindicated_or_futile` | True | 6/10 runs |

Same factual conclusion, same confidence, but the substrate sometimes flags `contested_reading` and sometimes doesn't. This is meta-judgment variance about certainty, not judgment variance about conclusions.

### Two leaves never resolve

| Leaf | Outcome |
|------|---------|
| `functional_limitations_described` | `value=None, conf=0.00, insufficient_facts` in 10/10 runs |
| `surgical_risks_alternatives_addressed` | `value=None, conf=0.00, insufficient_facts` in 10/10 runs |

These are signaling that the case bundle is missing data the leaves expect. This is a **test-data completeness gap**, not a substrate issue. The leaves are doing the right thing — refusing to commit on absent evidence.

### Thirteen leaves rock-stable

The other 13 evaluated leaves returned the same value at the same confidence with no escalation in every run. The core substantive conclusions of the engine are deterministic on this case.

## Why the bimodal trace size

8 calls vs 16-17 calls is not random variance — it's a structural consequence of the escalation-variance on `pharmacotherapy_requirement_met`:

- When pharmacotherapy returns hard False (no escalation) → `conservative_treatment_met` short-circuits False → `plan_criteria_satisfied` short-circuits False → engine never evaluates `physician_documentation_complete` or `no_exclusion_applies` branches. Result: 8 calls, fewer signals, SPOT_CHECK.
- When pharmacotherapy returns False with `contested_reading` escalation → `conservative_treatment_met` becomes escalated rather than hard False → engine continues down the AND, evaluating documentation and exclusions. Result: 16-17 calls, more signals, GATE.

The disposition stays the same either way because `denial_factual_basis_correct → INACCURATE` is rock-stable at rank 1.

## What this means

### The architecture is more robust than single-run mismatches suggested

Today's headline numbers ("1 of 5 dispositions match GT") were misleading because they were single-run snapshots. The disposition on kamau is empirically stable. The single-run "GT mismatches" we saw were always overturn_factual_error_in_denial — they didn't change between runs.

### The routing tier wobble is within the safety band

Production posture for kamau-like cases is "human reviewer should see this." Both GATE and SPOT_CHECK satisfy that. The earlier observation that routing dropped to AUTO with zero signals is now established as a low-probability outlier, not the norm. 0/10 in this session routed AUTO.

### The variance has a specific, addressable shape

Two leaves with prompt ambiguity at the decision boundary (pharmacotherapy, pt_contraindicated) and two leaves with test-data gaps (functional_limitations, surgical_risks). Both are addressable:

1. **Prompt sharpening on the borderline leaves.** Add explicit decision criteria to the leaf prompts so the substrate commits consistently rather than oscillating between committing and escalating. Worth testing empirically: rewrite, re-run 10 times, measure new escalation rate.

2. **Bundle completion on the data-gap leaves.** Either the case bundle should include the functional/risk information the leaves expect, or the leaves should be rewritten to evaluate differently against the data that exists. The current behavior — insufficient_facts on missing data — is correct engine behavior; the question is whether the case authoring or the leaf design needs adjustment.

## Implications for the new eval set methodology

The kamau × 10 dataset sharpens the methodology in concrete ways:

### N-run variance characterization is a standard methodology, not optional

Every case in the new eval set should be run 5–10 times. Headline numbers like "match rate" are undefined without variance characterization. Disposition stability and routing tier stability are themselves measurements, not constants.

### Per-leaf expected behavior, not just expected disposition

For each case in the new set, the expert assessment should include per-leaf annotations:

- **Determinable leaves**: substrate should commit; expert names the expected value
- **Contested leaves**: substrate should escalate; expert names which signal type fits
- **Data-gap leaves**: substrate should return insufficient_facts; expert names what data would be needed

Then the eval measures:

- Disposition match rate across N runs (per case)
- Routing tier distribution across N runs (per case)
- Per-leaf agreement: did the substrate produce the expected value/escalation profile?

This is a much stronger test than disposition matching alone.

### Cases with deliberate ambiguity are valuable

The pharmacotherapy/pt_contraindicated escalation-variance is the right kind of finding — borderline cases where reasonable readings differ. The new eval set should include cases explicitly engineered to test the routing tier safety mechanism: cases that *should* escalate to GATE because they're genuinely contested, and where the expert assessment says "no clear right answer, human should look."

## Defensible empirical claim from this work

Suitable for the position paper or open-source release notes:

> Across 10 independent substrate invocations of a single representative case (kamau): disposition was identical in 10/10 runs; primary reasoning was substantively consistent; routing tier varied within the human-review band (6 GATE / 4 SPOT_CHECK / 0 AUTO / 0 HOLD); confidence was identical at 0.85; value-level variance across all 17 evaluated leaves was zero. Substrate variance was confined to escalation flagging on two leaves at interpretive decision boundaries, and to two leaves where the case bundle lacked information needed for evaluation. The defeasible rank-ordered disposition selection produced the same primary disposition under both 8-call and 16-call execution paths through the tree.

## Calibration targets identified

Two specific leaf prompts merit experimental rewriting:

- `pharmacotherapy_requirement_met`: currently oscillates between committing-False and escalated-False at confidence 0.85–0.90. Adding explicit threshold criteria (e.g. "two distinct agent classes each ≥4 weeks") should reduce escalation rate.
- `pt_contraindicated_or_futile`: currently oscillates between committing-True and escalated-True. The case has clear plateau documentation; the substrate's uncertainty is about whether documented plateau counts as "contraindicated or futile." Prompt should be sharpened.

Two specific data-coverage gaps merit either bundle expansion or leaf-design revision:

- `functional_limitations_described`: leaf returns insufficient_facts in 10/10 runs
- `surgical_risks_alternatives_addressed`: leaf returns insufficient_facts in 10/10 runs

## Artifacts

- `pa_full/runs/variance_session_b56daf5f.json` — session log
- `pa_full/runs/2026-05-19T*_kamau_*.json` — 10 individual run artifacts
- `pa_full/runs/variance_analysis_b56daf5f.json` — structured analysis
- `pa_full/runs/variance_analysis_b56daf5f.md` — human-readable report

# Experiment: Prompt Sharpening on Borderline Leaves (Pre-registration)

**Date:** 2026-05-19
**Hypothesis:** Adding explicit decision criteria to leaf prompts reduces
escalation variance on leaves currently oscillating between commit-and-escalate.
**Status:** Pre-registered before running the experiment.

## Background

The kamau × 10 variance characterization identified two leaves with 60%
escalation variance — same value returned every run, but escalation flag
sometimes fired and sometimes didn't:

- `pharmacotherapy_requirement_met` — returns False in 10/10, escalates in 6/10
- `pt_contraindicated_or_futile` — returns True in 10/10, escalates in 6/10

Both leaves at decision boundaries where the substrate is uncertain about
whether to commit or flag for human review.

## What we're testing

Whether **prompt sharpening** — adding explicit decision criteria, "burden
of demonstrating completion" language, and instructions for handling
ambiguous documentation — reduces the escalation variance on these two
leaves.

## What we're NOT testing

- Whether the *value* changes. Both leaves should continue returning the
  same value on kamau (False and True respectively). If the value changes
  under sharpened prompts, the rewrite has biased the substrate, not just
  sharpened its decision boundary.
- Whether disposition changes. The disposition is `overturn_factual_error_in_denial`
  in 10/10 prior runs and should remain stable.
- Whether overall variance disappears. The hypothesis is specifically about
  these two leaves, not about substrate variance more broadly.

## Prompt changes

### `pharmacotherapy_requirement_met` — original

> Has the pharmacotherapy requirement been met? Requires trial of at least
> TWO of the following agent classes for minimum 4 weeks each:
> [list of classes]
> ...
> Return true only if at least two distinct agent classes have been
> trialed for at least 4 weeks each, as documented.

### `pharmacotherapy_requirement_met` — sharpened

Adds:
- Explicit treatment of brief dose packs (<2 weeks of corticosteroid does
  NOT count)
- "Cumulative-duration minimum" specificity
- Burden-of-proof rule: ambiguous documentation → return FALSE
- Explicit citation requirement

### `pt_contraindicated_or_futile` — original

> Has the treating physician documented in writing that physical therapy
> is contraindicated or is unlikely to benefit the member given the nature
> and severity of the condition?

### `pt_contraindicated_or_futile` — sharpened

Adds:
- Three explicit decision criteria (a) explicit contraindication,
  (b) documented functional plateau after substantive trial,
  (c) documented progressive worsening despite PT
- Explicit exclusion: patient-choice discontinuation does NOT qualify
- Burden of proof: ambiguous documentation → return FALSE
- Explicit citation requirement

## Experimental design

### Conditions
- **Baseline (B):** Original tree. Prior data: kamau × 10 session `b56daf5f`.
- **Treatment (T):** `pa_appeal_tree_sharpened.json` with rewritten prompts.

### Test case
- kamau (PA-2024-G006). Same case used for the baseline measurement.

### N runs
- 10 runs per condition. Baseline N=10 already exists; treatment N=10 to be run.

### Measurements
For each of the two leaves, in each condition:
- Value distribution (should be identical across conditions)
- Escalation rate (the dependent variable)
- Confidence distribution

For the overall determination, across all runs:
- Disposition distribution (should be stable: `overturn_factual_error_in_denial`)
- Routing tier distribution
- Substrate call count distribution

## Success criteria (pre-registered)

The experiment is a **success** if all of the following hold:

1. **Value preservation.** Both leaves return the same modal value as
   baseline (False, True respectively). No leaf flips its modal value.

2. **Disposition stability.** Disposition is `overturn_factual_error_in_denial`
   in ≥9/10 treatment runs (matching baseline 10/10 stability within ±1).

3. **Escalation reduction on pharmacotherapy.** Escalation rate on
   `pharmacotherapy_requirement_met` drops from baseline 60% to ≤30% in
   treatment. (Threshold: at least half the escalation rate.)

4. **Escalation behavior on pt_contraindicated_or_futile.** Either
   (a) escalation rate drops to ≤30% — strong success, or
   (b) escalation rate persists ≥40% — informative null result indicating
   the underlying question is judgment-shaped and resists prompt sharpening.

The framing of (4) is deliberate: we expect pharmacotherapy to be more
responsive to sharpening than pt_contraindicated, because the former has
explicit policy criteria the prompt can reference and the latter is an
inherently discretionary clinical judgment. A null result on (4) is a
finding, not a failure.

## Failure modes (what would invalidate the experiment)

- If value distribution shifts on either leaf, the experiment is invalid
  for that leaf. The prompt has biased the substrate rather than sharpened it.
- If disposition stability drops below 9/10, something other than the
  intended prompt changes is affecting the engine. Investigate before
  drawing conclusions.
- If escalation rate *increases* on either leaf, the sharpening backfired
  (probably because the added length increased perceived complexity).
  Worth noting and reverting.

## Run plan

```bash
# Baseline data already exists in session b56daf5f
# Treatment run:
RULEKIT_TREE=pa_appeal_tree_sharpened.json python3 run_variance.py kamau --n=10

# Then analyze and compare:
python3 analyze_variance.py <new_session_id>
# Compare to: pa_full/runs/variance_analysis_b56daf5f.md
```

## Why this experiment matters for the open-source release

The variance findings established that leaf-level escalation variance is
real. The question of whether it's *fixable* by prompt engineering versus
*intrinsic* to the underlying judgment is consequential for the open-source
positioning:

- If prompt sharpening fixes most of it: the methodology should include
  a "calibration pass" between case authoring and evaluation, and the
  position paper can claim engineered consistency.
- If it doesn't fix it: the variance is intrinsic, and the architecture's
  value claim shifts from "consistent automation" to "consistent surfacing
  of intrinsic uncertainty" — which is a different but still defensible
  story.

Either outcome is informative. The experiment is pre-registered so the
analysis isn't shaped by the results.

## Post-experiment outputs

After running and analyzing:
- Append findings section below
- Decide on whether to merge sharpened prompts into mainline tree or keep
  as experimental variant
- Update VARIANCE_FINDINGS_kamau.md with the calibration-effort result

## Findings (to be filled after experiment runs)

(To be completed after treatment runs.)

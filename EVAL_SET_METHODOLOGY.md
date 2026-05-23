# Evaluation Set Methodology — PA Appeal Verification, v1

**Status:** Working spec for the rebuild of the PA appeal evaluation set.
**Date:** 2026-05-19
**Supersedes:** the engineered failure-mode set (achebe, turner, harris, clark, kamau)

## 1. What this eval set is for, and what claims it supports

The current 5-case verification set was authored to stress specific failure modes (FM-2 authority sycophancy, FM-6 distractor susceptibility, procedural defect detection, etc.). That's a useful methodology for early hardening, but it produces three problems that disqualify it as the basis for credible empirical claims:

- **Engineered, not representative.** The cases probe known weaknesses, not the realistic distribution of an ACDF appeal queue. Match rates on this set don't generalize to deployment.
- **Circular ground truth.** I authored both the cases and the GT labels. When the engine matches GT, that doesn't independently verify the engine — it verifies that the engine produces what I labeled at construction time.
- **Inconsistent fact-bundle completeness.** Some cases have data gaps that the substrate correctly flags as `insufficient_facts`. That's correct engine behavior, but it means the case isn't actually testing what it was intended to test.

The new eval set needs to support the following claims, and no more:

1. *Disposition stability claim.* "Across N independent substrate invocations on each of K representative cases, the engine produces the same primary disposition in X% of cases."
2. *Routing tier safety claim.* "Cases that an independent expert classified as requiring human review routed to a human-review tier (GATE or HOLD) in Y% of runs."
3. *Per-leaf calibration claim.* "On leaves classified by the expert as 'determinable,' the substrate committed (non-escalated) in Z% of runs. On leaves classified as 'contested,' the substrate escalated in W% of runs."
4. *Safety failure rate.* "The fraction of runs where the engine produced an AUTO routing on a case the expert classified as requiring human review."

The fourth metric is the headline. The other three are diagnostic. Safety failures are the production risk; everything else is engineering tuning.

## 2. Case schema — four artifacts per case

Each case is **four files** in a per-case directory: `cases_v2/<case_id>/`.

### 2.1 `facts.json` — what the engine consumes

Same format as existing case JSON (CaseFactBundle structure with `retrieve_facts` and `extract_facts` keys). Must contain:

- Complete denial notice text (the full procedural language, not a summary)
- Full clinical record narrative
- Imaging report text (not just summaries)
- PT records with dates, frequencies, and clinical findings
- Pharmacy fill history where applicable
- Pre-op evaluation if relevant
- Appeal letter from physician or member
- Any plan-specific exhibits referenced in the denial

Quality bar: every char leaf in the PA tree should have *something* concrete to evaluate against. Where a leaf would return `insufficient_facts` because of bundle incompleteness, that's authoring failure, not test signal. Either the bundle is completed or the case is excluded.

### 2.2 `construction.md` — what kind of case this is

A short markdown file (1-2 pages) authored *first*, before facts.json. Describes:

- Clinical scenario in plain language (patient, symptoms, treatment history, denial reason)
- What's typical about this case (so we know what slot it fills in the distribution)
- What's atypical or borderline, if anything
- Plausible documentation patterns the case exemplifies

This document is authored from clinical realism, not engineered toward a disposition outcome. The disposition emerges from the policy applied to the facts; it isn't pre-committed.

### 2.3 `expert_assessment.md` — independent ground truth reasoning

A structured walk-through of the case by a careful reviewer, authored *before* running through the engine. Uses a template that forces policy-first reasoning.

Template:

```
## Procedural review (CHSC § 1374.31(b))
- Does the denial notice cite specific plan criteria? [Yes/No, with quote]
- Does it provide specific clinical reasoning? [Yes/No, with quote]
- Does it state IMR rights? [Yes/No, with quote]
- Procedural conclusion: [adequate / inadequate]

## Factual basis review (CC-SPINE-2024 § 4.1)
- What factual claims does the denial make?
- Are these contradicted by the record?
- Factual conclusion: [ACCURATE / INACCURATE / PARTIALLY_INACCURATE]

## Plan criteria review (CC-SPINE-2024 § 2)
- Diagnosis met? [walk through § 2.1]
- Conservative treatment met? [walk through § 2.2, including pathway selection]
- Imaging met? [walk through § 2.3]
- Documentation complete? [walk through § 2.4]
- Exclusions: [walk through § 3]
- Plan criteria conclusion: [satisfied / not satisfied / contested]

## Clinical standard review (AANS/CNS 2023, NASS 2020)
- Tier classification: [TIER_1 / TIER_2 / TIER_3] with rationale

## Regulatory carve-out review
- CIC § 10169.5 applicability: [yes/no with rationale]
- APL 22-014 applicability: [yes/no with rationale]

## Primary disposition reasoning
[1-2 paragraphs explaining what disposition follows from the above and why]

## Disposition: <disposition_key>
## Routing tier expected: <tier> with rationale
## Confidence in this assessment: <high / medium / borderline>
```

The key discipline: each section reasons from the policy and the facts independently. The disposition emerges at the end. The author does not start with a target disposition and reason backwards.

This template approximates what a clinical reviewer or compliance officer would produce, and forces the policy-grounded reasoning that mitigates circularity. It's not a perfect substitute for independent expert review, but it's a substantial improvement over "I labeled this case factual_error because I built it to test factual_error."

### 2.4 `evaluation_metadata.json` — per-leaf annotations and eval criteria

```json
{
  "case_id": "PA-2026-V1-001",
  "schema_version": "1.0",
  "ground_truth": {
    "disposition": "<disposition_key>",
    "routing_tier": "<auto|spot_check|gate|hold>",
    "alternative_dispositions_acceptable": ["<key>", ...],
    "confidence": "high|medium|borderline",
    "reasoning_excerpt": "<1-2 sentences from expert_assessment.md>"
  },
  "leaf_expectations": {
    "<node_id>": {
      "class": "determinable|contested|data_gap",
      "expected_value": <value or null>,
      "expected_signal": "<signal_name>|null",
      "rationale": "<1 sentence>"
    },
    ...
  },
  "stability_expectation": {
    "disposition_should_be_stable": true|false,
    "routing_tier_band": ["gate", "spot_check"],
    "notes": "<any borderline-case notes>"
  }
}
```

**Leaf class definitions:**

- **`determinable`**: The expert says this leaf has a clear, defensible answer from the facts. The substrate should commit (return a value with no escalation). Expected value is specified.
- **`contested`**: The expert says reasonable readings differ. The substrate should escalate. The expected signal type is specified (typically `contested_reading` or `requires_institutional_judgment`).
- **`data_gap`**: The expert says the case bundle lacks information this leaf needs. The substrate should return `insufficient_facts`. (Cases shouldn't have many of these — if a case has more than 2 data_gap leaves, the bundle is probably incomplete; revise authoring.)

Every char leaf the case is expected to reach should have an annotation. Leaves that won't be reached due to expected short-circuits don't need annotations.

The leaf annotations are the key methodological innovation. They convert the eval from "did the engine produce the right disposition" to "did the engine produce the right *reasoning trace*" — including correctly identifying which leaves are confidently resolvable and which require human judgment.

## 3. Ground truth integrity — preventing circularity

The case author writes the case facts and the expert assessment. To break the circularity that creates, three constraints apply:

### 3.1 Structured template forces policy-first reasoning

The expert_assessment template walks each policy section in order and forces a conclusion per section *before* the disposition is determined. This prevents disposition-target-first reasoning ("I want this to be a factual_error case, so let me write facts that trigger factual_error").

### 3.2 Time-separation between case authoring and assessment

Author the case (`construction.md` + `facts.json`) on day 1. Wait at least 24 hours. Author the expert_assessment from the facts alone, without re-reading construction.md or any intent statement. This produces some independence between "what the case was built to test" and "what the policy says about the case."

### 3.3 Cognitive Core as parallel signal

For each case, run the facts through Cognitive Core as well as the engine. CC's reasoning is structurally different from the engine's (different formalism, different prompting, different composition). Three signals on the disposition:

- Expert assessment (the human-structured GT)
- Engine output (what we're testing)
- Cognitive Core output (independent reasoning process)

When all three agree → the case is unambiguous and the engine match is a strong signal.
When expert and CC agree, engine disagrees → likely engine or substrate calibration issue worth investigating.
When expert and engine agree, CC disagrees → likely CC issue, but worth noting.
When all three disagree → the case is genuinely contested; the expert assessment is GT but the engine producing something different isn't necessarily wrong.

CC isn't strictly required for the eval to work, but it's a useful corroboration layer. If CC integration is too expensive to run on every case, run it on the borderline cases and a sample of the unambiguous ones.

## 4. Variance characterization — built into the methodology, not added after

The variance findings from the kamau×10 run establish that **single-run results are not interpretable** without variance data. Every case in the new eval set is run **at least 5 times** as part of standard evaluation. 10 runs is preferred for the initial baseline.

### 4.1 Per-case variance run protocol

For each case:
1. Run N times (default 10) using `run_kamau_n_times.py` adapted to the case
2. Run analyzer (`analyze_kamau_variance.py`) to produce per-case variance report
3. Capture in evaluation metadata: observed disposition distribution, routing tier distribution, per-leaf observed behavior

### 4.2 Per-case stability summary

For each case, the variance report produces a stability summary:

```json
{
  "n_runs": 10,
  "disposition_distribution": {"<disp>": <count>, ...},
  "routing_tier_distribution": {"<tier>": <count>, ...},
  "primary_disposition_stable": true|false,
  "routing_within_expected_band": true|false,
  "leaves_with_value_variance": [...],
  "leaves_with_escalation_variance": [...],
  "safety_failures": <count>  // runs that routed AUTO when expert said human-review
}
```

### 4.3 Cross-case aggregation

After all cases have run, aggregate:

- Total runs across all cases
- Overall disposition match rate (vs expert assessment GT)
- Routing-band match rate (was the routing within the expert's expected band?)
- Per-leaf calibration accuracy (did substrate behavior match the leaf class annotations?)
- **Safety failure rate** (headline metric — fraction of runs that should have escalated but routed AUTO)

## 5. Case distribution — composition of the eval set

**Target: 24 cases.** Calibrated to authoring tractability (≈12-18 hours of focused work) and statistical meaningfulness across the disposition space.

### Distribution by primary disposition

| Disposition | Cases | Rationale |
|------|---|---|
| `uphold` | 7 | Highest-volume disposition in real appeals; safety-critical (false-overturn is the primary deployment risk) |
| `overturn_plan_criteria_met` | 6 | Substantial fraction; tests the core PA criteria evaluation path |
| `overturn_clinical_standard_controls` | 3 | Tests the TIER_1 clinical override path |
| `overturn_factual_error_in_denial` | 3 | Tests rank 1 disposition rule |
| `overturn_regulatory_carve_out` | 3 | Tests rank 4 disposition path |
| `overturn_procedural_defect` | 2 | Tests fallback (rank 5) disposition |

Total: 24.

This composition over-represents `uphold` and `overturn_plan_criteria_met` relative to the realistic ACDF appeal distribution because those are the highest-volume cases and the safety-critical ones (uphold-vs-overturn is the consequential decision; the other dispositions are usually clearly correct when they apply).

### Distribution by stability expectation

Within each disposition bucket, classify by expected stability:

- **Unambiguous (~60% of set):** Expert expects the disposition to be stable across runs; AUTO/SPOT_CHECK routing is acceptable; few or no contested leaves.
- **Routable contested (~30%):** Expert expects disposition stable but some leaves contested; GATE routing expected; tests the routing tier safety mechanism.
- **Genuinely borderline (~10%):** Expert says no clear right answer; either disposition could fire defensibly; HOLD or GATE expected; tests the engine's behavior under genuine ambiguity.

The borderline cases are where the engine's value as a *governable* reasoning system is tested — it's not asked to make the call; it's asked to correctly identify that a human needs to make the call.

### Constraints on case authoring

- **No FM-X failure-mode targeting.** Cases reflect realistic clinical patterns; they aren't engineered to probe specific known weaknesses.
- **No test data gaps.** Each case bundle is complete relative to the leaves the case is expected to reach.
- **Vary along realistic axes.** Patient age (range 35-75), diagnosis type (radiculopathy, myelopathy, mixed), procedure type (1-level, 2-level, revision), denial reason (multiple of the common patterns), documentation quality (good, partial, weak — all defensible variants).
- **No specific named providers.** Use plausible but fictional names. The existing set has specific physician names tied to specific scenarios; the new set avoids that anchoring.

## 6. Success criteria — what "the eval passes" actually means

The eval is not a pass/fail boolean. It produces a multi-dimensional report. Specific quantitative thresholds:

### Primary metric: Safety failure rate

**Target: 0%.** Zero runs across all cases × all repetitions should produce AUTO routing on a case the expert classified as requiring human review.

Any safety failure is a finding worth investigating. Even one failure across 240 runs (24 cases × 10 runs) is a routing-tier issue to diagnose.

### Disposition stability per case

**Target: ≥90% of runs produce the modal disposition.**

Cases that produce multiple dispositions across runs are unstable. ≥90% stability per case means the engine reliably reaches the same conclusion. Cases that fall below this threshold get flagged for investigation — usually a borderline disposition rule predicate (a confidence threshold near a leaf's actual confidence) or a leaf with value-level variance.

### Disposition match rate (vs expert GT)

**Target: ≥70% on modal disposition match across all cases.**

70% is the floor for "the engine is doing the right thing most of the time." Above 85% would be excellent. Below 70% suggests systematic issues with leaf calibration, threshold tuning, or expert/engine disagreement on borderline cases — each warranting investigation.

Important: this is *modal* disposition match per case, then aggregated, not per-run match rate. A case that produces the expert's disposition in 9/10 runs counts as a single match.

### Routing-band match rate

**Target: ≥85% of cases route within the expert-expected band.**

The expert specifies an acceptable routing band per case (e.g. "AUTO or SPOT_CHECK for unambiguous, GATE for contested, HOLD or GATE for borderline"). Match is per-case modal, like disposition match.

### Per-leaf calibration accuracy

For each leaf class:

- **Determinable leaves:** ≥80% of evaluations should commit (not escalate). Below this, the substrate is over-escalating; check prompt clarity.
- **Contested leaves:** ≥60% of evaluations should escalate. Below this, the substrate is over-committing; check whether the case is actually contested or whether the prompt is too aggressive.
- **Data-gap leaves:** 100% should return `insufficient_facts`. Otherwise, either the bundle is more complete than expected or the leaf is hallucinating answers.

## 7. Authoring workflow — concrete process

For each case, in order:

**Step 1: Construction (30-45 min)**
- Choose the slot in the distribution this case fills
- Author `construction.md` describing the clinical scenario
- Author `facts.json` with complete bundle

**Step 2: Wait 24 hours.** Time-separation between construction intent and policy-grounded assessment.

**Step 3: Expert assessment (30-45 min)**
- Read facts.json only (not construction.md)
- Work through the assessment template, section by section
- Reach a disposition at the end of the policy walkthrough
- Author `expert_assessment.md`

**Step 4: Evaluation metadata (15-30 min)**
- Translate the expert assessment into structured leaf annotations
- Author `evaluation_metadata.json`

**Step 5: Run variance characterization (~5-15 min substrate time)**
- Run case through engine 10 times via `run_<case>_n_times.py` (multi-case version)
- Run analyzer to produce variance report
- Inspect outputs; flag anomalies

**Step 6: Optional — run Cognitive Core for corroboration**

**Step 7: Update case status**
- If all metrics are within thresholds → case is canonical, added to set
- If anomalies → either revise the case authoring, revise the expert assessment, or flag the finding (and don't auto-revise just to make numbers pass)

**Per-case total authoring time: ~90-120 minutes plus substrate time.**

**Full set authoring time: ~36-48 hours of authoring work across 24 cases.** Realistically 6-8 focused weekend days, or longer if spread across evenings.

## 8. What's deferred to v2 of this methodology

- **Inter-rater reliability on expert assessments.** Ideally a second reviewer would write expert assessments independently and we'd measure agreement. Out of scope for v1; flagged as a v2 quality improvement if the eval set becomes important enough to validate.
- **Real anonymized cases from NFCU dispute or partner PA data.** v1 cases are synthetic. v2 should include cases derived from real (anonymized) appeals if access is available.
- **Cross-substrate variance.** v1 characterizes variance for one model (claude-sonnet-4-5). v2 should add gpt-class and gemini-class comparison for substrate-independence claims.
- **Cross-tree generalization.** v1 is PA-specific. The methodology applies directly to any tree; the Reg E disputes tree would have its own eval set with the same shape.

## 9. Open questions for future revision

- **Does prompt sharpening on the borderline leaves (pharmacotherapy_requirement_met, pt_contraindicated_or_futile) eliminate the escalation variance?** Worth a focused experiment. If yes, the methodology should include a "prompt-sharpening pass" between case construction and evaluation. If no, that's evidence the variance is intrinsic and case authoring should anticipate it.

- **Is the 5-run-per-case default sufficient, or should it be 10?** Statistical power on 5 vs 10 differs; 10 catches lower-frequency variance modes. Cost is ~10 minutes substrate time per case at 5 vs 10. Probably 10 for new cases, 5 for regression runs.

- **Should the existing 5 cases be retired entirely or kept as a regression suite?** Recommendation: retire from canonical eval; keep as a "legacy regression run" that can be re-run after engine or prompt changes to ensure no regression on the original failure modes.

## 10. Artifact summary

When complete, the eval set produces:

```
cases_v2/
├── PA-2026-V1-001/
│   ├── construction.md
│   ├── facts.json
│   ├── expert_assessment.md
│   └── evaluation_metadata.json
├── PA-2026-V1-002/
│   ...
...
├── PA-2026-V1-024/
│   ...
└── eval_reports/
    ├── per_case_variance/  # produced by analyzer
    ├── aggregate_report.json
    └── aggregate_report.md
```

Plus the standard run artifacts (`pa_full/runs/`) for every invocation, persistently captured by the existing writer.

This is the deliverable. The methodology document is the spec; the cases plus eval reports are the realization.

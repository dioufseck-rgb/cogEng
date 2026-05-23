# RuleKit vs. Direct-LLM Comparison Study — Pre-Registered Protocol

**Status:** Pre-registered, version 1.0
**Pre-registration date:** [TO BE SET ON COMMIT]
**Principal investigator:** Mamadou Seck
**Collaborators:** [Fatou Diouf, et al.]

This document specifies the study design, the metrics, the statistical
analyses, and the success criteria for evaluating the RuleKit architecture
against a direct-LLM baseline on policy adjudication tasks. The protocol
is committed before data collection; deviations are reported transparently
in the final analysis.

## 1. Research Questions

The study addresses six architectural claims made by RuleKit. Each claim
is testable and each has a falsifiable success criterion specified in
Section 7.

**Q1. Correctness.** Does RuleKit produce determinations matching expected
outcomes more reliably than a direct-LLM baseline?

**Q2. Consistency across runs.** Does RuleKit produce more consistent
determinations across repeated runs on the same case than the baseline?

**Q3. Architectural stability across builds.** Does RuleKit produce
consistent determinations across independent builds of the same policy?

**Q4. Traceability.** Does RuleKit identify the load-bearing requirements
(as annotated by domain experts) more accurately than the baseline?

**Q5. Difficulty monotonicity.** Is RuleKit's correctness and per-case
runtime invariant to case difficulty in ways the baseline's is not?

**Q6. Runtime amortization.** Above what case volume does RuleKit's total
runtime (build + per-case) drop below the baseline's total runtime?

## 2. Systems Under Comparison

### 2.1 RuleKit (System A)

The RuleKit architecture as specified in `ARCHITECTURE.md`. The build
pipeline runs four LLM-driven stages (decomposition, deduplication,
refinement, engine conversion) producing a DAG. The run-time pipeline
runs Map followed by Evaluate.

For this study, the Map substrate is `NarrativeLLMSubstrate` (one LLM
call per case, binding the narrative case description to the build's
atom inventory).

**Frozen artifacts:**
- `rulekit/decomposer.py` at git ref [TO BE FROZEN]
- `rulekit/refinement.py` at git ref [TO BE FROZEN]
- `rulekit/map_primitive.py` at git ref [TO BE FROZEN]
- `rulekit/engine.py` at git ref [TO BE FROZEN]

### 2.2 Direct-LLM baseline (System B)

A single LLM call per case. Input: full policy text plus full case
description. Output: structured JSON with determination and explanation.

**Frozen baseline prompt:** see Section 4. The prompt is selected by
validation on a held-out 5-case set (see Section 4); the winning prompt
is frozen before any main-experiment runs.

### 2.3 Common conditions

Both systems use the same LLM model: `claude-opus-4-7`.

Both systems use the same temperature: 0.0 (or the model's lowest
deterministic-leaning setting at study execution time).

Both systems are given the same case descriptions verbatim. No
preprocessing differences.

Both systems are timed identically. See Section 5.

## 3. Policies and Cases

### 3.1 Policies

Three policies are included:

- **Policy 1:** Prior-authorization clinical guideline (cervical spinal
  surgery, Section 2 medical-necessity criteria). Source:
  `policy_inputs/pa_section2.txt`. Estimated atoms: 50-65 per build.

- **Policy 2:** Fair Credit Billing Act billing-error definition
  (12 CFR § 1026.13(a)). Source: `policy_inputs/fcba_1026_13a.txt`.
  Estimated atoms: 25-35 per build.

- **Policy 3:** [TO BE SELECTED before pre-registration freeze. A third
  policy with structural characteristics different from Policies 1-2;
  candidate criteria below.] Candidates: a state administrative rule on
  benefits eligibility, or a clinical guideline section with deeper
  exception logic. Selection criterion: nesting depth ≥ 4 levels and at
  least one AT-LEAST-N operator with N ≥ 3.

Two policies is the minimum for the study. Three is the planned target;
if Policy 3 cannot be sourced under the pre-registration window, the
study proceeds with two and the deviation is reported.

### 3.2 Case bank

For each policy, the case bank contains cases stratified across ten
difficulty levels (Section 3.3). The target is two main cases per level
per policy, for 20 main cases per policy. Plus 10 adversarial cases per
policy (Section 3.4), for 30 cases per policy total.

With three policies: 90 cases. With two: 60 cases.

Each case is authored independently of the systems being evaluated. Case
authors do not consult RuleKit traces or baseline outputs during
authoring. Cases are reviewed by a second domain reviewer before
inclusion.

### 3.3 Difficulty stratification

The ten levels are operational, not graded by "human difficulty." Each
level isolates a class of case characteristic that may stress build
correctness, Map binding, or the engine.

**Level 1 — Canonical positive.** Standard pathway, every required atom
explicitly addressed positively in the description, no exception
triggers, no partial evidence.

**Level 2 — Canonical negative.** Standard pathway requirements unmet
(absent qualifying diagnosis, or failed conservative treatment), no
exception applicability. Expected determination is the negative outcome.

**Level 3 — Exception pathway.** The policy's exception pathway applies
and is satisfied. Expected determination matches the positive outcome
via the exception branch.

**Level 4 — Partial evidence on non-load-bearing atoms.** Evidence is
explicitly absent on atoms predicted (by sensitivity analysis of a
training-set bundle) to be non-load-bearing. Expected determination is
unchanged.

**Level 5 — Partial evidence on load-bearing atoms.** Evidence is
explicitly absent on atoms predicted to be load-bearing. Expected
determination is UNDETERMINED.

**Level 6 — Multiple pathways simultaneously plausible.** Both standard
and exception pathways have some support. Expected determination is
positive (either pathway satisfies; OR logic).

**Level 7 — Non-canonical surface form.** Case described with
alternative terminology, non-standard medical or legal language, or
information presented in unusual order. Underlying facts are equivalent
to a Level 1 case.

**Level 8 — Boundary conditions.** Specific atom is at a stated
threshold (PT lasted exactly 6 weeks; one fewer interventional
treatment than required). Expected determination depends on whether the
case satisfies the policy on the relevant side of the threshold.

**Level 9 — Composition stress.** Cases requiring AT-LEAST-N satisfaction
at exactly N (no margin). Every contributing atom is load-bearing in
this case.

**Level 10 — Out-of-scope facts.** Cases touching subjects the policy
does not directly address. Expected determination is FALSE or
UNDETERMINED per the policy's coverage logic.

### 3.4 Adversarial cases

Ten cases per policy designed to expose specific failure modes.

**RuleKit-targeting adversarials (5 per policy):**
- Cases with subtle narrative cues requiring careful binding
- Cases with implicit closed-world assumptions
- Cases with terminology not appearing in policy text
- Cases requiring inference across remote sub-trees
- Cases where atom granularity might shift binding outcome

**Direct-LLM-targeting adversarials (5 per policy):**
- Cases at numerical thresholds where smoothing could mislead
- Cases with deeply nested exception pathways
- Cases with high partial-evidence content
- Cases with multiple plausible interpretations of intent
- Cases where literal-vs-intent interpretation matters

Adversarial cases are labeled as such and analyzed both inclusive of
and exclusive of the main set.

### 3.5 Case annotation schema

Each case file (YAML) contains:

```yaml
case_id: <unique identifier>
policy: <policy identifier>
difficulty_level: <1-10>
tags: [<descriptive tags>]
case_class: main | adversarial_rulekit | adversarial_llm
description: |
  <natural language case description, 200-800 words>
expected_outcomes:
  <determination_id>: true | false | undetermined
load_bearing_annotation:
  - <descriptive requirement phrase>
  - <descriptive requirement phrase>
  ...
expected_bundle:  # optional, for Map binding diagnostics
  <atom_id>: true | false | undetermined
  ...
authoring_notes: |
  <brief rationale for case construction; not shown to systems>
```

The `load_bearing_annotation` field lists the policy requirements the
case authors believe drive the determination. Phrasing is in natural
language; matching to system output is described in Section 6.4.

## 4. Direct-LLM Baseline Prompt Selection

The baseline prompt is selected from three candidates by performance on
a held-out 5-case validation set. The validation set is drawn from each
policy, one case per level 1-5 per policy. These 15 cases are excluded
from the main analysis.

**Candidate prompts:**

**P1 (Minimal):** "Read the policy and case. Output JSON with fields
'determination' and 'explanation'."

**P2 (Structured):** "You are an experienced [voice]. Read the policy
below and the case description below. Identify the policy's
requirements. For each, state whether the case satisfies, fails to
satisfy, or has insufficient evidence. Then output JSON with
'determination' and 'explanation'."

**P3 (Chain-of-thought):** "[Same as P2, plus:] Think step by step.
First list requirements; then evaluate each against the case; then
combine to produce the determination. Show your work in the
'explanation' field."

Selection criterion: accuracy on the validation set, ties broken by
higher traceability F1 (Section 6.4).

The selected prompt is frozen as `baselines/direct_llm_prompt.txt`
before main-experiment runs begin. Subsequent prompt modifications are
not permitted within the protocol.

## 5. Experimental Procedure

### 5.1 Builds (RuleKit only)

For each policy, run the build pipeline `k_build = 3` times with
different LLM-seed configurations (since the model API does not expose
true seeding, "different" means independent calls in separate sessions
on separate days, recorded with full build metadata).

Save each build as a pickle artifact with build identifier
`<policy>_build_<n>.pkl` for n ∈ {1, 2, 3}.

Record per build:
- Total LLM calls
- Total wall-clock time
- Total input/output tokens
- Atom count
- Determination count
- Refinement summary (operations applied, flags raised)

### 5.2 Per-case runs

For each (policy, case, system, build) combination, run the case
`k_run = 3` times.

For System A (RuleKit), the build is fixed by the (policy, build)
combination; the three runs vary the Map call.

For System B (Direct LLM), the three runs are independent calls; there
is no build.

The full matrix:
- System A: 3 policies × 3 builds × 30 cases × 3 runs = 810 evaluations
- System B: 3 policies × 30 cases × 3 runs = 270 evaluations

(Numbers halve if Policy 3 cannot be sourced.)

### 5.3 Recording per evaluation

Each evaluation produces a JSON record stored in
`results/<policy>_<system>_<build_or_run>_<case>_<run>.json`:

```json
{
  "case_id": "...",
  "policy": "...",
  "system": "rulekit" | "direct_llm",
  "build_id": "..." (RuleKit only),
  "run_number": 1-3,
  "timestamp_utc": "...",
  "model": "claude-opus-4-7",
  "determination": {
    "<det_id>": "true" | "false" | "undetermined"
  },
  "wall_clock_seconds": ...,
  "llm_calls": [
    {"label": "...", "elapsed_s": ..., "input_tokens": ..., "output_tokens": ...}
  ],
  "total_input_tokens": ...,
  "total_output_tokens": ...,
  "trace_or_explanation": {...},
  "raw_output": "..."
}
```

For RuleKit, `trace_or_explanation` contains the full evaluation trace.
For Direct LLM, it contains the explanation paragraph.

All records are immutable. The raw output is preserved verbatim for
post-hoc analysis if needed.

### 5.4 Execution environment

Runs execute serially within a (policy, system, build) batch to avoid
rate-limit confounds. Wall-clock times include API round-trip but
exclude code overhead beyond the LLM call boundary.

Pilot phase (Section 8) verifies the harness produces complete records
on a small subset before the main runs.

## 6. Metrics

### 6.1 Correctness

Per (system, policy, level): the proportion of cases where the system's
determination matches the expected outcome.

Aggregated across runs: for each case, the case is "correct on a run"
if the run's determination matches the expected. The case's correctness
score is the proportion of correct runs.

System correctness is the mean per-case correctness across cases.

### 6.2 Consistency across runs

For each (case, system) pair, define per-case agreement as the
proportion of run pairs (out of `C(k_run, 2) = 3` pairs) where the two
runs produced the same determination.

System consistency is the mean per-case agreement across cases.

### 6.3 Architectural stability across builds (RuleKit only)

For each case, the across-build determination set is the set of
determinations produced across `k_build × k_run = 9` runs split into 3
builds.

Per-case stability: proportion of build-pair (out of `C(k_build, 2) = 3`)
where the modal determination of the two builds matches.

System stability is the mean per-case stability across cases.

### 6.4 Traceability

For each case, the system's traceability F1 is computed as follows:

Let `A` be the set of `load_bearing_annotation` entries for the case.

**For RuleKit:** Let `T_rk` be the set of atoms whose values are
load-bearing for the determination (computed by single-atom sensitivity
analysis on the case's seeded bundle). Convert each atom in `T_rk` to a
natural-language phrase by extracting its statement. A subsequent LLM
call (the "matching judge", model `claude-opus-4-7`, frozen prompt in
Appendix B) evaluates for each annotation phrase in `A` whether `T_rk`
contains a corresponding atom; computes recall. Inverse: for each atom
in `T_rk`, whether `A` contains a corresponding annotation; computes
precision. F1 is the harmonic mean.

**For Direct LLM:** Let `E` be the explanation paragraph. The matching
judge (same prompt) evaluates for each annotation phrase in `A` whether
`E` references it (positively or negatively, as load-bearing for the
determination). The judge also extracts from `E` any requirement-like
statements not in `A`. Recall and precision computed as above.

The matching judge is the same LLM as the systems under test. This
introduces a circularity risk; mitigation is that the judge is given
only the annotation and the system's output (RuleKit's atom statements
or Direct LLM's explanation), not the case or the policy. The judge's
prompt is frozen and reported. A held-out 10-pair manual review (Section
9.3) validates the judge's labels.

### 6.5 Difficulty monotonicity

Two regressions per system:

- Correctness ~ difficulty_level (logistic regression on per-case
  correctness, with policy as a covariate)
- Wall-clock latency ~ difficulty_level (linear regression on per-case
  mean latency, with policy as a covariate)

Report the slope coefficient and its 95% CI per system. Compare slopes
between systems.

### 6.6 Runtime and cost

Per (system, level): p50 and p95 of wall-clock latency, mean total
tokens, mean total cost (computed at then-current Anthropic pricing).

Aggregate runtime totals: `T_A(N) = B_A + N × M_A` for RuleKit,
`T_B(N) = N × D_B` for direct LLM, where N is the case count, B_A is
build time, M_A is per-case Map+Evaluate time, D_B is per-case direct
LLM time.

Runtime crossover N_cross: the smallest N for which `T_A(N) ≤ T_B(N)`.

Cost crossover analogously in dollars.

## 7. Pre-registered Success Criteria

Each architectural claim has a falsifiable success criterion. The study
reports each criterion's status as supported, not supported, or
ambiguous (with rationale).

**C1 (Correctness).** RuleKit accuracy ≥ Direct LLM accuracy aggregated
across all main cases, with `p < 0.05` on McNemar's test (paired). Effect
size (difference in proportions) reported with 95% CI.

**C2 (Consistency).** RuleKit per-case agreement rate is greater than
Direct LLM per-case agreement rate, with `p < 0.05` on a paired
Wilcoxon signed-rank test. Effect size (mean difference) reported.

**C3 (Architectural stability).** RuleKit's mean per-case across-build
stability ≥ 0.80, and is significantly greater than Direct LLM's mean
per-case across-run agreement rate (Welch's t-test, `p < 0.05`).

**C4 (Traceability).** RuleKit's mean traceability F1 across all main
cases ≥ 0.80, AND is significantly greater than Direct LLM's mean
traceability F1 (paired Wilcoxon, `p < 0.05`).

**C5 (Monotonicity).** The 95% CI of RuleKit's correctness slope versus
difficulty level includes zero, AND Direct LLM's 95% CI does not
include zero (or is significantly more negative than RuleKit's). Same
condition applied to latency slope.

**C6 (Amortization).** Runtime crossover N_cross < 100 cases on at
least one of the three policies. Cost crossover reported as exploratory
(no pre-registered threshold).

The architecture is "supported" if at least 5 of 6 criteria are met.
Mixed results are reported transparently with the specific criteria
that did and did not pass.

## 8. Pilot Phase

Before the main experiment, a pilot phase runs the full pipeline on:

- 1 policy (Policy 1: PA Section 2)
- 1 build (k_build = 1)
- 3 cases (one Level 1, one Level 5, one Level 8)
- Both systems
- k_run = 3 runs per case

Total pilot evaluations: 1 × 3 × 2 × 3 = 18 runs (plus 1 build).

Pilot acceptance criteria (must pass before main experiment begins):

- All 18 runs complete without error
- All result records validate against the schema in Section 5.3
- The analysis script in `harness/analyze.py` produces all required
  tables from pilot data without error
- Per-case latency for both systems is within 60 seconds
- The matching judge for traceability produces well-formed labels

If the pilot fails on technical grounds (schema errors, harness bugs),
the harness is fixed and the pilot is re-run. The main experiment
does not begin until pilot acceptance criteria are all met.

If the pilot reveals fundamental issues with the design (e.g., the
matching judge is unreliable), the protocol is amended before the main
experiment, with the amendment recorded and dated.

## 9. Threats to Validity

Pre-identified threats and mitigations.

### 9.1 LLM nondeterminism

Both systems use the same model at temperature 0.0. Even at temperature
0.0, model outputs vary in practice. The k_run = 3 design averages over
this variance.

If model behavior drifts during the study (Anthropic model updates),
the affected runs are documented and re-run if material.

### 9.2 Case authoring bias

Case authors may unconsciously favor one system. Mitigation:

- Cases authored by author A; reviewed by author B
- Case authoring complete before any system runs
- Authors do not consult system outputs during authoring
- Adversarial cases targeting each system give both an opportunity to
  display failure modes

### 9.3 Traceability matching judge reliability

The matching judge (Section 6.4) is itself an LLM call. Its labels
might be systematically biased. Mitigation:

- Frozen prompt (Appendix B), reported with results
- Held-out 10-case manual review: case authors manually score
  traceability F1 on 10 randomly-selected cases (5 per system); compare
  to judge labels; report agreement (Cohen's kappa). If kappa < 0.6,
  the judge is replaced with manual scoring across all cases.

### 9.4 Direct-LLM prompt suboptimality

The baseline prompt is selected from three candidates. If a fourth
prompt would have performed better, our baseline is unfair. Mitigation:

- The three candidates span a reasonable space (minimal, structured,
  chain-of-thought)
- The validation set is held out from the main experiment
- Prompt selection is documented; readers can criticize the choice

We commit to not testing additional prompts post-hoc to reach a
desired result. If we want to explore additional prompts, we report
this as a follow-up study.

### 9.5 Build variance interpretation

If RuleKit's across-build variance is high, C3 fails. This is the
intended falsification path. Reporting it honestly is required.

### 9.6 Conflicts of interest

The principal investigator authored RuleKit. The collaborators are
external (Section preamble). The matching judge is automated. The
metrics and tests are pre-registered. The full data and code are
released under an open license at study completion.

## 10. Reporting

The study report includes:

- This protocol document, with any amendments noted
- The case bank in full (YAML files)
- The frozen prompts (RuleKit's stage prompts and the baseline prompt)
- The full raw results (one JSON per evaluation)
- The analysis script
- Tables for each metric, stratified as specified in Section 6
- Statistical test results for each criterion in Section 7
- A discussion section interpreting results, with attention to
  unexpected findings and to criteria not met

Negative results are reported with the same prominence as positive
results.

## 11. Reproducibility

All artifacts released under MIT or Apache-2.0 license:

- `protocol.md` (this document)
- `harness/` (the runner, the analyzer, the timed LLM wrapper)
- `baselines/direct_llm.py` and `baselines/direct_llm_prompt.txt`
- `bank/` (all case YAML files)
- `results/` (all raw evaluation records)
- `analysis/` (the analysis scripts and their output tables/figures)

A third party can re-run the study with the same artifacts and compare
to our results within statistical bounds. Variance attributable to
model API drift is acknowledged.

## Appendix A: Frozen Build Prompts

Reference: `rulekit/decomposer.py` (DECOMPOSE_PROMPT, DEDUP_PROMPT),
`rulekit/refinement.py` (REFINEMENT_PROMPT), `rulekit/map_primitive.py`
(BIND_PROMPT). All at the frozen git ref specified in Section 2.1.

## Appendix B: Traceability Matching Judge Prompt

```
You are evaluating whether two descriptions of policy requirements
match in substance.

LIST A:
{annotation_phrases}

LIST B:
{system_output_phrases}

For each phrase in LIST A, determine whether LIST B contains a phrase
that refers to the same underlying policy requirement. Use substantive
meaning, not surface wording. Two phrases match if a domain expert
would treat them as referring to the same requirement.

Output a JSON object:
{
  "matches": [
    {"a_index": 0, "b_index": 2, "rationale": "..."},
    {"a_index": 1, "b_index": null, "rationale": "no match in B"},
    ...
  ],
  "extras_in_b": [<indices of B-phrases with no match in A>]
}

Use null for a_index where the phrase has no corresponding entry in B.
Be conservative; if uncertain, do not match.
```

## Appendix C: Protocol Amendments

| Date | Section | Amendment | Rationale |
|------|---------|-----------|-----------|
| --- | --- | --- | --- |

Each amendment is dated and explained. Amendments after the start of
the main experiment require a rationale that does not reference
observed system performance.

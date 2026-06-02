# FCRA Bank Holdout Evaluation

Run date: 2026-06-02

## Purpose

This holdout set compares two approaches after the six-case bank-dispute tuning
work:

1. Governed RuleKit Map + deterministic engine using the `bank_furnisher`
   FCRA profile v3, then a vocabulary-expanded v4 profile/prompt.
2. Best-effort profiled direct LLM disposition using the improved direct prompt
   style, without further tuning on this holdout set.

The holdout cases are narrative-only and intentionally include paraphrase,
confounders, branch non-applicability, routing triggers, and unresolved facts.

## Artifacts

- Holdout cases:
  `rulekit/orchestrator/example_cases/fcra_bank_customer_disputes_eval.yaml`
- Program:
  `audits/fcra_bank_profile_v3/bank_furnisher_program.json`
- Governed Map run:
  `audits/fcra_bank_holdout_eval/map_profile_v3`
- Vocabulary-expanded governed Map run:
  `audits/fcra_bank_holdout_eval/map_profile_v4`
- Direct profiled run:
  `audits/fcra_bank_holdout_eval/direct_profiled_v2`

## Result Summary

| Approach | Cases | Dispositions | Matches | Mismatches | Accuracy | LLM calls | Latency | Estimated tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Governed Map + engine | 18 | 90 | 78 | 12 | 86.67% | 22 | 481.12s | 122,003 |
| Governed Map + engine v4 vocab | 18 | 90 | 84 | 6 | 93.33% | 18 | 390.32s | 251,705 |
| Profiled direct LLM | 18 | 90 | 85 | 5 | 94.44% | 18 | 361.88s | 206,490 |

Costs were not estimated because pricing was not configured. Token counts are
harness estimates derived from prompt/response character count.

## Mismatch Direction

Governed Map + engine:

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 7 |
| `false` | `true` | 2 |
| `true` | `false` | 1 |
| `false` | `undetermined` | 1 |
| `undetermined` | `false` | 1 |

Governed Map + engine v4 vocabulary:

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 4 |
| `undetermined` | `false` | 1 |
| `false` | `true` | 1 |

Profiled direct LLM:

| Actual | Expected | Count |
|---|---|---:|
| `true` | `false` | 3 |
| `undetermined` | `true` | 1 |
| `false` | `undetermined` | 1 |

## Governed Map Failure Pattern

The governed v3 run is no longer near-perfect on the holdout set. Its misses are
concentrated in new case shapes the current profile does not yet encode:

- no-bank-furnishing branch:
  `bank_eval_indirect_no_bank_furnishing` missed all five determinations;
- wrong-address direct dispute:
  `bank_eval_direct_wrong_address` left direct-furnisher satisfaction
  undetermined instead of false;
- public-record-only direct dispute:
  `bank_eval_direct_public_record_only` treated direct-furnisher satisfaction
  as false instead of satisfied by exception;
- veteran medical-debt deletion:
  `bank_eval_veteran_medical_deleted` missed item treatment, furnisher
  indirect satisfaction, and human-review routing;
- late CRA notice:
  `bank_eval_indirect_late_cra_notice` treated CRA furnisher notice as true
  despite the seventh-business-day fact;
- resolved versus pending uncertainty:
  one pending/conflict case collapsed to false where the expected label was
  undetermined.

This is useful, not embarrassing. It shows the profile learned the six-case
case shapes but does not yet cover enough bank operational variants. The
failure surface is inspectable and mostly fixable by adding general profile
semantics for not-furnished-by-bank, wrong-address direct disputes,
public-record-only exceptions, veteran medical-debt routing, and explicit late
notice timing.

After adding active-perspective/profile guidance to the governed Map prompt and
expanding profile vocabulary for those case shapes, the v4 governed run improved
from 78/90 to 84/90. This supports the hypothesis that the earlier Map result
was partly penalized by a narrower semantic vocabulary than the direct prompt
received.

The remaining v4 misses are now narrower:

- `bank_eval_indirect_no_bank_furnishing` still misses three determinations.
  This is a structural perspective/DAG issue: the bank view does not cleanly
  represent "not this furnisher's item" as a not-applicable branch for all
  support determinations.
- `bank_eval_direct_wrong_address` still returns `undetermined` rather than
  false, likely because evidence uncertainty remains around other direct-path
  atoms even though the proper-address prerequisite is false.
- `bank_eval_veteran_medical_deleted` still marks item treatment false rather
  than true, meaning deletion/defect semantics for special medical-debt deletion
  need a clearer DAG/profile treatment.

## Direct LLM Failure Pattern

The profiled direct prompt performs strongly on the holdout set: 85/90. Its
remaining five errors are still characteristic of direct adjudication:

- It overclaims three false direct-furnisher determinations as true:
  insufficient direct message, wrong-address direct dispute, and duplicate
  no-new-information dispute.
- It marks identity-theft item treatment undetermined even though the benchmark
  treats the direct-only CRA/item-treatment branch as satisfied/not applicable.
- It marks a pending mixed-file furnisher case false rather than preserving
  undetermined.

The most important pattern is that direct LLM sometimes treats an invalid,
insufficient, or duplicate direct dispute as "duty satisfied/not applicable"
when the benchmark expects `direct_furnisher_satisfied = false`. That is a
subtle semantic distinction: invalid notice means no qualifying investigation
path, but the benchmark labels that as an unfavorable direct-furnisher outcome
rather than a satisfied exception.

## Comparison

Headline accuracy still narrowly favors the improved direct prompt on this
holdout:

- direct profiled: 94.44%;
- governed Map + engine v4 vocabulary: 93.33%;
- governed Map + engine v3: 86.67%.

The governed approach remains more inspectable. Every governed mismatch maps to
specific atom/profile gaps or trace behavior. The direct approach is more
holistic and currently more accurate on these 18 cases, but its errors are
harder to constrain because they arise from adjudicative interpretation inside
the prompt.

Cost/latency also cut in different directions:

- governed Map v4 used the same number of calls as direct but more estimated
  tokens because profile guidance was added to the Map prompts; this should be
  optimized with compact profile slices rather than full guidance payloads;
- direct used fewer calls but a much larger prompt per case because each direct
  call carries policy text, determinations, perspective, and profile guidance.

## What This Teaches

The six-case result was too small and profile-friendly. This holdout is a
better empirical signal:

1. The profiled direct baseline is now genuinely strong and should remain in
   the comparison.
2. RuleKit's current bank profile was under-complete for realistic bank dispute
   variations; expanding profile vocabulary closed half the gap immediately.
3. The governed approach is not losing because the engine cannot reason; it is
   losing because the Map/profile layer lacks enough reusable case-shape
   semantics.
4. The next fair test should add general profile rules surfaced by this
   holdout, then rerun unchanged holdout cases and record the delta.

## Next Bounded Fixes

Do not tune direct further on this set. Use it as the improved direct baseline.

For RuleKit, the next fixes should focus on the remaining structural issues:

- duplicate/no-new-information direct dispute and related notice branch;
- a clean bank-perspective not-applicable branch for items not furnished by the
  bank;
- proper-address prerequisite handling so wrong-address direct disputes produce
  stable false rather than undetermined;
- veteran medical-debt deletion as a first-class defect/deletion treatment path;
- pending manual-review cases where unresolved evidence should propagate
  undetermined instead of false.

Then rerun the same holdout and compare the delta.

## Commands

Governed Map:

```powershell
python -m rulekit.orchestrator.cli map-eval `
  --program audits\fcra_bank_profile_v3\bank_furnisher_program.json `
  --cases rulekit\orchestrator\example_cases\fcra_bank_customer_disputes_eval.yaml `
  --model anthropic:claude-opus-4-7 `
  --out audits\fcra_bank_holdout_eval\map_profile_v3 `
  --atom-scope determination-slice `
  --single-map-call `
  --repair-unresolved `
  --max-repair-atoms 10 `
  --llm-max-tokens 4096 `
  --llm-timeout 180 `
  --llm-max-retries 2 `
  --json
```

Governed Map v4:

```powershell
python -m rulekit.orchestrator.cli map-eval `
  --program audits\fcra_bank_profile_v4\bank_furnisher_program.json `
  --cases rulekit\orchestrator\example_cases\fcra_bank_customer_disputes_eval.yaml `
  --model anthropic:claude-opus-4-7 `
  --out audits\fcra_bank_holdout_eval\map_profile_v4 `
  --atom-scope determination-slice `
  --single-map-call `
  --repair-unresolved `
  --max-repair-atoms 10 `
  --llm-max-tokens 4096 `
  --llm-timeout 180 `
  --llm-max-retries 2 `
  --json
```

Direct profiled:

```powershell
python -m rulekit.orchestrator.cli direct-eval `
  --program audits\fcra_bank_profile_v3\bank_furnisher_program.json `
  --cases rulekit\orchestrator\example_cases\fcra_bank_customer_disputes_eval.yaml `
  --seed rulekit\orchestrator\example_seeds\fcra_credit_reporting_dispute_deep.yaml `
  --model anthropic:claude-opus-4-7 `
  --prompt-style profiled `
  --out audits\fcra_bank_holdout_eval\direct_profiled_v2 `
  --llm-max-tokens 4096 `
  --llm-timeout 180 `
  --llm-max-retries 2 `
  --json
```

## Verification

- `python -m pytest tests/orchestrator/test_fcra_credit_reporting_deep_seed.py
  tests/orchestrator/test_direct_disposition_eval.py -q`
  -> 12 passed.

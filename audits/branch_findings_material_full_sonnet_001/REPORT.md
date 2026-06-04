# Branch Findings With Material Slots: Full Sonnet Evaluation

Date: 2026-06-04

Policy: FCRA CRA full-policy logic-stress suite

Program: `audits/fcra_credit_reporting_deep/rulekit_export_profile2/program.json`

Cases: `rulekit/orchestrator/example_cases/fcra_cra_logic_stress_eval.yaml`

Model: `anthropic:claude-sonnet-4-6`

## Purpose

This run tested the revised branch-level architecture after adding structured
`material_findings` to each branch and routing finding. The aim was to preserve
the LLM's branch-level reasoning advantage while making each branch conclusion
auditable through material slots, status, basis, and evidence.

The comparison baseline is the profiled direct-disposition prompt on the same
12 cases and same model.

## Runs

| Approach | Cases | Calls | Determination Accuracy | Final Accuracy | Routing Accuracy | Est. Cost | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| Branch findings + material slots | 12 | 12 | 174/180, 96.67% | 11/12, 91.67% | 11/12, 91.67% | $1.157 | 782.0s |
| Profiled direct disposition | 12 | 12 | 162/180, 90.00% | 11/12, 91.67% | 11/12, 91.67% | $1.057 | 809.5s |

The branch/material run is about 9.5% more expensive by estimated token cost,
but it improves determination accuracy by 12 dispositions and produces a
structured branch audit trace.

## Material-Finding Metrics

The branch/material run produced:

| Metric | Value |
|---|---:|
| Branch/routing findings | 168 |
| Material findings | 298 |
| Average material findings per finding | 1.77 |

Status counts:

| Status | Count |
|---|---:|
| established | 220 |
| not_applicable | 65 |
| undetermined | 9 |
| conflicting | 4 |

Basis counts:

| Basis | Count |
|---|---:|
| explicit | 190 |
| inferred | 60 |
| profile_default | 46 |
| not_applicable | 2 |

Support counts:

| Supports | Count |
|---|---:|
| satisfaction | 138 |
| applicability | 107 |
| blocking | 32 |
| routing | 18 |
| context | 3 |

This is the key improvement over the earlier aggregate branch-finding version:
the branch result is no longer just a conclusion and rationale. It now exposes
the material audit surface used to reach that conclusion.

## Branch/Material Mismatches

The branch/material run had 6 mismatches across 180 dispositions.

1. `cra_logic_invalid_duplicate_with_new_material`
   - `fcra.furnisher_indirect_satisfied`: got `true`, expected `false`.
   - The model reasoned that because the CRA never notified the furnisher, the
     furnisher-side branch was not triggered. The benchmark expects this
     determination to fail when the upstream CRA notice never occurred.
   - This is a perspective/benchmark-semantics issue. The prompt says not to
     blame recipient-side branches for upstream transmission failures unless the
     recipient-side determination itself requires that upstream act. That
     instruction improved other cases but conflicts with this gold label.

2. `cra_logic_invalid_duplicate_with_new_material`
   - `fcra.human_review_required`: got `false`, expected `true`.
   - The model treated the invalid duplicate/frivolous termination as a clear
     deterministic compliance defect rather than a routing trigger.
   - This is a policy-pack semantics issue: the benchmark considers the new
     dispositive primary document plus invalid duplicate handling a human-review
     trigger even though the substantive failure is clear.

3. `cra_logic_reseller_own_error_corrected_timely`
   - `fcra.cra_reinvestigation_required`: got `false`, expected `true`.
   - The model reasoned literally that no source-CRA reinvestigation was
     required because the reseller corrected its own error.
   - The benchmark labels this `true`, apparently using a broader "valid
     dispute handling path exists" semantics for the CRA-required branch.

4. `cra_logic_reseller_own_error_corrected_timely`
   - `fcra.cra_reinvestigation_trigger_valid`: got `false`, expected `true`.
   - Same pattern as above: the model treated source-CRA trigger literally,
     while the benchmark treats reseller dispute receipt as enough for the
     high-level trigger-valid determination.

5. `cra_logic_direct_furnisher_public_record_exception`
   - `fcra.direct_furnisher_satisfied`: got `false`, expected `true`.
   - This appears to be a contradictory model output. The rationale and material
     findings say the public-record exception applies and the outcome should be
     true, but the JSON fields emitted `outcome=false`, `satisfied=false`, and
     `blocks_final=true`.
   - This single contradiction caused the only final-disposition miss.

6. `cra_logic_direct_furnisher_public_record_exception`
   - `fcra.dispute_resolution_compliant`: got `false`, expected `true`.
   - This was deterministically composed from mismatch 5.

## Direct-Prompt Mismatches

The profiled direct baseline had 18 mismatches.

The largest direct failure pattern was repeated:

| Determination | Mismatches |
|---|---:|
| `fcra.frivolous_termination_valid` | 9 |
| `fcra.results_notice_satisfied` | 2 |
| `fcra.furnisher_indirect_satisfied` | 2 |
| Other determinations | 5 |

The direct prompt repeatedly treated "no frivolous termination was invoked" as
`true` because it reasoned with generic "not applicable means satisfied"
semantics. The branch/material prompt revision corrected this by separating
existential/event-validity determinations from "satisfied or not applicable"
duty determinations.

Direct also had the same final/routing miss on the pending conflict case before
the branch prompt's trigger-timing rule was tightened: it treated an untriggered
post-completion results notice as a current failure rather than an unresolved
pending duty.

## Architectural Lessons

1. Branch-level reasoning is still the promising abstraction.

The branch/material approach substantially outperformed profiled direct
disposition on determination accuracy while using the same number of LLM calls.
It also generated a structured trace that direct prompting does not naturally
provide.

2. The audit layer helped expose errors.

The material findings made it obvious when an error was caused by:

- wrong benchmark perspective,
- incorrect trigger timing,
- routing semantics,
- or a contradictory JSON field.

Without material slots, these would look like ordinary disposition mismatches.

3. Some labels need policy-pack clarification.

The reseller-own-error case and furnisher-indirect case reveal that some
determination names are underspecified. A model reading the policy naturally
distinguishes "source CRA duty not triggered" from "dispute handling path is
satisfied." The DAG may encode one perspective while the plain determination
label suggests another.

4. Contradictory field/rationale outputs need validation.

The public-record exception case shows the next high-value engineering fix:
validate consistency between `outcome`, `satisfied`, `blocks_final`,
`rationale`, and material findings. A repair pass or deterministic consistency
rule could likely catch this without another full adjudication call.

## Recommended Next Fixes

1. Add branch-finding consistency validation.
   - If a satisfaction branch has material slot
     `exception_or_short_circuit=public_record_only_exception` with established
     status, then `direct_furnisher_satisfied` should not block final.
   - More generally, flag contradictory outputs where rationale/material slots
     support true but `outcome=false` and `blocks_final=true`.

2. Clarify determination semantics in the policy pack.
   - Especially reseller/source-CRA trigger semantics.
   - The builder should attach a short `evaluation_semantics` note per
     determination, not just a legal source span and description.

3. Split routing semantics from clear substantive defects.
   - Decide whether `human_review_required` is only for unresolved routing
     triggers or also for certain severe clear defects.
   - The current labels include at least one case where a clear defect is still
     expected to route to review.

4. Re-run after adding consistency validation.
   - Expected branch/material improvement: likely 176-178/180, with final
     recovering to 12/12 if the public-record contradiction is repaired.

## Commands

Branch/material run:

```powershell
python -m rulekit.orchestrator.cli branch-findings-eval `
  --program audits\fcra_credit_reporting_deep\rulekit_export_profile2\program.json `
  --cases rulekit\orchestrator\example_cases\fcra_cra_logic_stress_eval.yaml `
  --seed rulekit\orchestrator\example_seeds\fcra_credit_reporting_dispute_deep.yaml `
  --out audits\branch_findings_material_full_sonnet_001 `
  --model anthropic:claude-sonnet-4-6 `
  --final-determination fcra.dispute_resolution_compliant `
  --routing-determination fcra.human_review_required `
  --llm-max-tokens 16000 `
  --llm-timeout 240 `
  --llm-max-retries 2 `
  --price anthropic:claude-sonnet-4-6=3,15 `
  --json
```

Direct profiled baseline:

```powershell
python -m rulekit.orchestrator.cli direct-eval `
  --program audits\fcra_credit_reporting_deep\rulekit_export_profile2\program.json `
  --cases rulekit\orchestrator\example_cases\fcra_cra_logic_stress_eval.yaml `
  --seed rulekit\orchestrator\example_seeds\fcra_credit_reporting_dispute_deep.yaml `
  --out audits\direct_profiled_full_sonnet_001 `
  --model anthropic:claude-sonnet-4-6 `
  --prompt-style profiled `
  --llm-max-tokens 12000 `
  --llm-timeout 240 `
  --llm-max-retries 2 `
  --price anthropic:claude-sonnet-4-6=3,15 `
  --json
```

## Artifact Index

- Branch/material summary:
  `audits/branch_findings_material_full_sonnet_001/anthropic_claude-sonnet-4-6/summary.json`
- Branch/material dispositions:
  `audits/branch_findings_material_full_sonnet_001/anthropic_claude-sonnet-4-6/dispositions.json`
- Branch/material prompts and parsed findings:
  `audits/branch_findings_material_full_sonnet_001/anthropic_claude-sonnet-4-6/prompts/`
- Direct baseline summary:
  `audits/direct_profiled_full_sonnet_001/anthropic_claude-sonnet-4-6/summary.json`
- Direct baseline dispositions:
  `audits/direct_profiled_full_sonnet_001/anthropic_claude-sonnet-4-6/dispositions.json`

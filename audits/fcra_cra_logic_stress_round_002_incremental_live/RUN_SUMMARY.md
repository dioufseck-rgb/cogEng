# FCRA CRA Logic Stress Round 002 - Incremental Governed Map

Run date: 2026-06-02

Model: `anthropic:claude-opus-4-7`

Program: `audits/fcra_credit_reporting_deep/rulekit_export_profile2/program.json`

Cases: `rulekit/orchestrator/example_cases/fcra_cra_logic_stress_eval.yaml`

Mode:
- Governed evidence Map.
- Determination-slice atom scope.
- Batch size 8.
- Incremental sufficiency enabled.
- Maximum incremental rounds 8.

## Results

| Split | Cases | Dispositions | Matched | Mismatches | Accuracy | LLM calls | Estimated tokens | LLM latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Repair | 4 | 60 | 40 | 20 | 66.67% | unavailable in recovered stdout | unavailable in recovered stdout | unavailable in recovered stdout |
| Validation | 4 | 60 | 42 | 18 | 70.00% | 26 | 76,022 | 316.98s |
| Final holdout | 4 | 60 | 40 | 20 | 66.67% | 31 | 102,249 | 351.24s |

## Mismatch Direction

Repair:
- Expected true, got false: 4.
- Expected true, got undetermined: 16.

Validation:
- Expected true, got false: 2.
- Expected false, got true: 1.
- Expected true, got undetermined: 15.

Final holdout:
- Expected false, got true: 1.
- Expected true, got false: 2.
- Expected true, got undetermined: 14.
- Expected undetermined, got false: 3.

## Interpretation

The incremental governed Map is still dominated by conservative under-determination on this logic-stress set. Most misses are expected-true determinations that remain undetermined because the Map did not bind enough load-bearing facts with acceptable evidence posture.

There are also a small number of direction errors. Those matter more than the aggregate accuracy because they indicate either an over-permissive branch, a default semantics issue, or a case/profile mismatch where the engine found a false/true route through the DAG despite unresolved load-bearing evidence.

## Highest-Value Next Diagnosis

The recurring missed determinations are concentrated in:
- `fcra.cra_consideration_satisfied`
- `fcra.cra_reinvestigation_timely`
- `fcra.results_notice_satisfied`
- `fcra.cra_furnisher_notice_satisfied`
- `fcra.furnisher_indirect_satisfied`

This points less to engine speed or batching and more to Map/profile coverage: the mapper is still missing domain-language variants and procedural implications needed to bind these atoms reliably.

## Artifact Note

The first live calibration command completed the repair LLM calls but failed while writing prompt artifacts on Windows because long case and atom names exceeded practical path limits. The artifact writer now uses short hashed prompt file names and creates parent directories before writing prompt files. The already-paid repair outputs were recovered by replaying the local writer against `results.json`.

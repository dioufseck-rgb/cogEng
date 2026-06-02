# Calibration Repair Loop Report

Round: `fcra_cra_logic_stress_round_001`
Split strategy: `stratified`

## Split Discipline

| Split | Cases | Ran? |
|---|---:|---|
| `repair` | 4 | yes |
| `validation` | 4 | yes |
| `final_holdout` | 4 | no |
| `reserve` | 0 | no |

Final holdout cases are not run unless `run_final=true`.

## Case IDs

- `repair`: `cra_logic_invalid_duplicate_with_new_material`, `cra_logic_valid_frivolous_termination_no_reinvestigation`, `cra_logic_expedited_deletion_short_circuits_furnisher_notice`, `cra_logic_reseller_forwarding_late_no_reconveyance`
- `validation`: `cra_logic_direct_furnisher_public_record_exception`, `cra_logic_clean_conflict_pending_manual_review`, `cra_logic_late_results_notice_after_timely_reinvestigation`, `cra_logic_consumer_statement_not_carried_forward`
- `final_holdout`: `cra_logic_direct_furnisher_defect_not_corrected`, `cra_logic_reinsertion_certified_but_notice_late`, `cra_logic_extension_later_info_not_forwarded`, `cra_logic_reseller_own_error_corrected_timely`
- `reserve`: _none_

## Split Group Balance

| Split | Group | Cases |
|---|---|---:|
| `repair` | `expedited_deletion` | 1 |
| `repair` | `invalid_frivolous_termination` | 1 |
| `repair` | `reseller_forwarding_failure` | 1 |
| `repair` | `valid_frivolous_termination` | 1 |
| `validation` | `conflict_pending` | 1 |
| `validation` | `consumer_statement` | 1 |
| `validation` | `direct_furnisher_exception` | 1 |
| `validation` | `results_notice_timing` | 1 |
| `final_holdout` | `conditional_deadline_forwarding` | 1 |
| `final_holdout` | `direct_furnisher_correction` | 1 |
| `final_holdout` | `reinsertion_notice` | 1 |
| `final_holdout` | `reseller_own_error` | 1 |
| `reserve` | `_none_` | 0 |

## Governed Results

| Split | Provider/Model | Matches | Mismatches | Accuracy | Calls | Tokens |
|---|---|---:|---:|---:|---:|---:|
| `repair` | `anthropic:claude-opus-4-7` | 36 | 24 | 60.00% | 8 | 146057 |
| `validation` | `anthropic:claude-opus-4-7` | 31 | 29 | 51.67% | 8 | 157341 |

## Direct LLM Results

| Split | Provider/Model | Matches | Mismatches | Accuracy | Calls | Tokens |
|---|---|---:|---:|---:|---:|---:|
| `repair` | `anthropic:claude-opus-4-7` | 56 | 4 | 93.33% | 4 | 36408 |
| `validation` | `anthropic:claude-opus-4-7` | 55 | 5 | 91.67% | 4 | 35714 |

## Repair Loop Status

This initial harness records split-safe evidence and reports. Candidate
patch generation is intentionally a later step: repair proposals must
be explicit policy-pack changes and must be validated/replayed before
the locked final holdout is released.

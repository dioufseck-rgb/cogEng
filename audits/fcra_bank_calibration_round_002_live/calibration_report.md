# Calibration Repair Loop Report

Round: `fcra_bank_round_002`
Split strategy: `stratified`

## Split Discipline

| Split | Cases | Ran? |
|---|---:|---|
| `repair` | 6 | yes |
| `validation` | 6 | yes |
| `final_holdout` | 6 | no |
| `reserve` | 0 | no |

Final holdout cases are not run unless `run_final=true`.

## Case IDs

- `repair`: `bank_eval_mixed_file_indirect_pending`, `bank_eval_indirect_missing_docs_review`, `bank_eval_indirect_clean_verified_1`, `bank_eval_direct_wrong_address`, `bank_eval_identity_theft_complete_blocked`, `bank_eval_duplicate_no_new_info`
- `validation`: `bank_eval_direct_public_record_only`, `bank_eval_indirect_date_conflict_pending`, `bank_eval_veteran_medical_deleted`, `bank_eval_indirect_corrected_and_reported`, `bank_eval_identity_theft_missing_report`, `bank_eval_indirect_no_bank_furnishing`
- `final_holdout`: `bank_eval_indirect_late_cra_notice`, `bank_eval_dual_channel_cra_and_direct`, `bank_eval_direct_verified_auto`, `bank_eval_direct_corrected_and_sent`, `bank_eval_direct_short_message_insufficient`, `bank_eval_direct_corrected_not_sent`
- `reserve`: _none_

## Split Group Balance

| Split | Group | Cases |
|---|---|---:|
| `repair` | `duplicate_repeat` | 1 |
| `repair` | `identity_theft` | 1 |
| `repair` | `missing_docs` | 1 |
| `repair` | `mixed_file` | 1 |
| `repair` | `verified` | 1 |
| `repair` | `wrong_address` | 1 |
| `validation` | `correction_complete` | 1 |
| `validation` | `date_conflict` | 1 |
| `validation` | `identity_theft` | 1 |
| `validation` | `not_furnished` | 1 |
| `validation` | `public_record` | 1 |
| `validation` | `veteran_medical` | 1 |
| `final_holdout` | `correction_complete` | 1 |
| `final_holdout` | `dual_channel` | 1 |
| `final_holdout` | `insufficient_packet` | 1 |
| `final_holdout` | `late_notice` | 1 |
| `final_holdout` | `notification_gap` | 1 |
| `final_holdout` | `verified` | 1 |
| `reserve` | `_none_` | 0 |

## Governed Results

| Split | Provider/Model | Matches | Mismatches | Accuracy | Calls | Tokens |
|---|---|---:|---:|---:|---:|---:|
| `repair` | `anthropic:claude-opus-4-7` | 28 | 2 | 93.33% | 6 | 90258 |
| `validation` | `anthropic:claude-opus-4-7` | 27 | 3 | 90.00% | 5 | 70744 |

## Direct LLM Results

| Split | Provider/Model | Matches | Mismatches | Accuracy | Calls | Tokens |
|---|---|---:|---:|---:|---:|---:|
| `repair` | `anthropic:claude-opus-4-7` | 29 | 1 | 96.67% | 6 | 79656 |
| `validation` | `anthropic:claude-opus-4-7` | 28 | 2 | 93.33% | 6 | 78857 |

## Repair Loop Status

This initial harness records split-safe evidence and reports. Candidate
patch generation is intentionally a later step: repair proposals must
be explicit policy-pack changes and must be validated/replayed before
the locked final holdout is released.

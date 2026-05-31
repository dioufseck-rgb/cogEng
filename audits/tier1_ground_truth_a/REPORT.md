# USCIS N-400 Tier 1 Ground-Truth Disposition Comparison

Run date: 2026-05-31

Ground-truth labels were added to the case packets before this comparison pass.
Labels are benchmark dispositions derived from the packet narrative and policy intent,
not copied from saved RuleKit or direct-LLM outputs.

## Accuracy Summary

| System | Compared | Matches | Mismatches | Accuracy |
|---|---:|---:|---:|---:|
| rulekit_expanded_batched | 80 | 61 | 19 | 76.25% |
| direct_anthropic | 80 | 67 | 13 | 83.75% |

## Side-By-Side

| Result | Count |
|---|---:|
| both_match | 54 |
| rulekit_only | 7 |
| direct_only | 13 |
| neither_match | 6 |

## rulekit_expanded_batched Mismatch Patterns

| Actual | Expected | Count |
|---|---|---:|
| `false` | `undetermined` | 5 |
| `true` | `false` | 1 |
| `undetermined` | `false` | 7 |
| `undetermined` | `true` | 6 |

### By Determination

| Determination | Mismatches |
|---|---:|
| `n400.civics_requirement_satisfied` | 1 |
| `n400.continuous_residence_satisfied` | 3 |
| `n400.english_requirement_satisfied` | 1 |
| `n400.good_moral_character_satisfied` | 1 |
| `n400.human_review_required` | 7 |
| `n400.oath_attachment_satisfied` | 1 |
| `n400.physical_presence_satisfied` | 3 |
| `n400.state_residence_satisfied` | 2 |

### Mismatches

| Case | Determination | Expected | Actual |
|---|---|---|---|
| `tier1_clean_general_track_packet` | `n400.continuous_residence_satisfied` | `true` | `undetermined` |
| `tier1_clean_general_track_packet` | `n400.physical_presence_satisfied` | `true` | `undetermined` |
| `tier1_clean_general_track_packet` | `n400.state_residence_satisfied` | `true` | `undetermined` |
| `tier1_clean_general_track_packet` | `n400.oath_attachment_satisfied` | `true` | `undetermined` |
| `tier1_clean_general_track_packet` | `n400.good_moral_character_satisfied` | `true` | `undetermined` |
| `tier1_clean_general_track_packet` | `n400.human_review_required` | `false` | `undetermined` |
| `tier1_travel_conflict_six_month_absence` | `n400.continuous_residence_satisfied` | `undetermined` | `false` |
| `tier1_travel_conflict_six_month_absence` | `n400.physical_presence_satisfied` | `undetermined` | `false` |
| `tier1_one_year_absence_no_exception` | `n400.human_review_required` | `false` | `undetermined` |
| `tier1_physical_presence_short_by_worksheet` | `n400.state_residence_satisfied` | `undetermined` | `false` |
| `tier1_physical_presence_short_by_worksheet` | `n400.human_review_required` | `false` | `undetermined` |
| `tier1_state_residence_short` | `n400.human_review_required` | `false` | `undetermined` |
| `tier1_english_failed_civics_passed_no_exception` | `n400.english_requirement_satisfied` | `false` | `undetermined` |
| `tier1_english_failed_civics_passed_no_exception` | `n400.civics_requirement_satisfied` | `true` | `undetermined` |
| `tier1_english_failed_civics_passed_no_exception` | `n400.human_review_required` | `false` | `undetermined` |
| `tier1_medical_disability_exception_approved` | `n400.human_review_required` | `false` | `true` |
| `tier1_oath_attachment_refusal` | `n400.human_review_required` | `false` | `undetermined` |
| `tier1_missing_travel_dates` | `n400.continuous_residence_satisfied` | `undetermined` | `false` |
| `tier1_missing_travel_dates` | `n400.physical_presence_satisfied` | `undetermined` | `false` |

## direct_anthropic Mismatch Patterns

| Actual | Expected | Count |
|---|---|---:|
| `true` | `false` | 6 |
| `true` | `undetermined` | 6 |
| `undetermined` | `false` | 1 |

### By Determination

| Determination | Mismatches |
|---|---:|
| `n400.civics_requirement_satisfied` | 1 |
| `n400.continuous_residence_satisfied` | 1 |
| `n400.english_requirement_satisfied` | 1 |
| `n400.good_moral_character_satisfied` | 1 |
| `n400.human_review_required` | 6 |
| `n400.oath_attachment_satisfied` | 1 |
| `n400.physical_presence_satisfied` | 1 |
| `n400.state_residence_satisfied` | 1 |

### Mismatches

| Case | Determination | Expected | Actual |
|---|---|---|---|
| `tier1_one_year_absence_no_exception` | `n400.human_review_required` | `false` | `true` |
| `tier1_physical_presence_short_by_worksheet` | `n400.human_review_required` | `false` | `true` |
| `tier1_state_residence_short` | `n400.human_review_required` | `false` | `true` |
| `tier1_english_failed_civics_passed_no_exception` | `n400.human_review_required` | `false` | `true` |
| `tier1_medical_disability_exception_approved` | `n400.human_review_required` | `false` | `true` |
| `tier1_oath_attachment_refusal` | `n400.human_review_required` | `false` | `true` |
| `tier1_pending_charge_with_clean_conviction_check` | `n400.continuous_residence_satisfied` | `undetermined` | `true` |
| `tier1_pending_charge_with_clean_conviction_check` | `n400.physical_presence_satisfied` | `undetermined` | `true` |
| `tier1_pending_charge_with_clean_conviction_check` | `n400.state_residence_satisfied` | `undetermined` | `true` |
| `tier1_pending_charge_with_clean_conviction_check` | `n400.english_requirement_satisfied` | `undetermined` | `true` |
| `tier1_pending_charge_with_clean_conviction_check` | `n400.civics_requirement_satisfied` | `undetermined` | `true` |
| `tier1_pending_charge_with_clean_conviction_check` | `n400.oath_attachment_satisfied` | `undetermined` | `true` |
| `tier1_pending_charge_with_clean_conviction_check` | `n400.good_moral_character_satisfied` | `false` | `undetermined` |

## Readout

- RuleKit is conservative against this ground truth: most mismatches are `undetermined` where the benchmark label says `true` or `false`.
- Direct Anthropic is more decisive and more accurate on this small labeled set, but it still has misses and does not produce governed atom-level traces.
- The highest-value next fix is source-scope/default semantics for negative bars and non-load-bearing missing facts, plus clearer DAG treatment of human-review triggers.

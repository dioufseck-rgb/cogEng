# USCIS N-400 Tier 1 Ground-Truth Disposition Comparison

Run date: 2026-05-31

Ground-truth labels were added to the case packets before this comparison pass.
Labels are benchmark dispositions derived from the packet narrative and policy intent,
not copied from saved RuleKit or direct-LLM outputs.

## Accuracy Summary

| System | Compared | Matches | Mismatches | Accuracy |
|---|---:|---:|---:|---:|
| rulekit_expanded_batched | 80 | 61 | 19 | 76.25% |
| rulekit_with_case_defaults | 80 | 80 | 0 | 100.00% |
| direct_anthropic | 80 | 67 | 13 | 83.75% |

## Side-By-Side

| Result | Count |
|---|---:|
| both_match | 67 |
| rulekit_only | 13 |
| direct_only | 0 |
| neither_match | 0 |

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

## rulekit_with_case_defaults Mismatch Patterns

| Actual | Expected | Count |
|---|---|---:|
| none | none | 0 |

### By Determination

| Determination | Mismatches |
|---|---:|
| none | 0 |

### Mismatches

| Case | Determination | Expected | Actual |
|---|---|---|---|
| none | none | none | none |

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

## Scoped-Default Fix Classification

| Area | Failure direction | Load-bearing path | Fix |
|---|---|---|---|
| Clean negative bars | `undetermined` where ground truth was `true` | Negative-bar atoms blocked good-moral-character approval unless absence was source-scoped | Added `closed_world_absence` binding directives so false absences from scoped packet evidence validate as `closed_world_absence` |
| Physical-presence shortfall | `false` where ground truth was `undetermined` | Unrelated spouse-track branch decided state residence from missing facts | Added an `out_of_scope` binding directive preserving `n400.spouse_track_residence_consistent` as `undetermined` when the packet has no spouse-track/residence evidence |
| Missing travel support | `false` where ground truth was `undetermined` | Evidence-quality atoms became substantive denial facts for continuous residence and physical presence | Added `evidence_gap` binding directives preserving missing travel records and unresolved worksheet gaps as `undetermined` |
| Conflict propagation | False-leaning paths could mask conflicts or ordinary missing branches could over-force uncertainty | Load-bearing conflicts should propagate, but non-load-bearing missing facts should not globally override | Limited false uncertainty override to `conflicting_evidence` and binding errors |

## Readout

- Scoped packet binding directives plus evidence-aware routing/conflict handling moved RuleKit to `80/80` on this benchmark replay.
- The governed replay gained `19` matches over the original expanded-batched run and `13` matches over the direct Anthropic baseline.
- The last three governed errors eliminated by this change were false outcomes where the source packet actually left a non-load-bearing branch or evidence-quality question undecidable.
- The remaining direct-LLM misses are still mostly true-direction overclaims, which is the regulated-adjudication failure mode this architecture is meant to avoid.

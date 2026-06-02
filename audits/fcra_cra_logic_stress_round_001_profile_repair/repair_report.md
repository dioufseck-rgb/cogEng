# Map Profile Repair Report

Round: `fcra_cra_logic_stress_round_001`
Repair target: `map_profile.default_rules`
Candidate rules: `19`

## Source Mismatches

| Direction | Count |
|---|---:|
| `false->true` | 3 |
| `undetermined->false` | 7 |
| `undetermined->true` | 14 |

## Candidate Rules

| Rule | Kind | Atom Count | Cue Count |
|---|---|---:|---:|
| `rk_auto_valid_cra_intake_identified_4b60167a97` | `scope_supported_true` | 9 | 3 |
| `rk_auto_duplicate_with_new_material_not_frivolous_422ad5ddd7` | `scope_supported_false` | 8 | 3 |
| `rk_auto_invalid_duplicate_termination_made_f57ca2296f` | `scope_supported_true` | 3 | 2 |
| `rk_auto_frivolous_termination_made_with_notice_df8de11b85` | `scope_supported_true` | 4 | 1 |
| `rk_auto_frivolous_notice_within_5_days_6133836d04` | `numeric_profile_default` | 1 | 2 |
| `rk_auto_frivolous_insufficient_intake_cb587eca45` | `scope_supported_false` | 5 | 3 |
| `rk_auto_insufficient_information_to_investigate_b867fc4521` | `scope_supported_true` | 1 | 3 |
| `rk_auto_no_direct_furnisher_branch_a8820f2c34` | `branch_not_applicable` | 13 | 3 |
| `rk_auto_no_reinsertion_branch_fb7d04a8a9` | `branch_not_applicable` | 6 | 3 |
| `rk_auto_no_consumer_statement_branch_c878eca34b` | `branch_not_applicable` | 2 | 3 |
| `rk_auto_expedited_deletion_path_15c922e806` | `scope_supported_true` | 5 | 2 |
| `rk_auto_no_furnisher_notice_for_expedited_deletion_2f13e5f5af` | `branch_not_applicable` | 2 | 2 |
| `rk_auto_complete_results_notice_15b3ac656a` | `scope_supported_true` | 7 | 4 |
| `rk_auto_results_notice_within_5_days_347c80ce4d` | `numeric_profile_default` | 1 | 4 |
| `rk_auto_verified_item_treatment_f1e43c7251` | `scope_supported_true` | 2 | 3 |
| `rk_auto_reseller_dispute_received_a8a77adb08` | `scope_supported_true` | 2 | 1 |
| `rk_auto_reseller_forwarding_late_or_missing_654ebf86de` | `scope_supported_false` | 2 | 2 |
| `rk_auto_reseller_forwarded_source_cra_5bb28a750d` | `scope_supported_true` | 1 | 1 |
| `rk_auto_reseller_conveyance_late_9364f425d8` | `numeric_profile_default` | 1 | 1 |

## Profile-Only Replay

| Split | Matches | Mismatches | Accuracy |
|---|---:|---:|---:|
| `repair` | 43 | 17 | 71.67% |
| `validation` | 28 | 32 | 46.67% |

The replay uses deterministic profile defaults only. It is a cheap
structural check for proposed Map-profile rules, not a replacement for
a governed LLM Map rerun.

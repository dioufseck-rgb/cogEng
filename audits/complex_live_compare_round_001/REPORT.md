# Complex Live Comparison Round 001

Date: 2026-06-03

Purpose: compare the isolated one-call total-atom RuleKit path with a profiled
direct LLM disposition baseline on unseen, logically complex FCRA CRA stress
cases.

Provider/model: `anthropic:claude-opus-4-7`

Selected cases:

- `cra_logic_invalid_duplicate_with_new_material`
- `cra_logic_reinsertion_certified_but_notice_late`
- `cra_logic_reseller_forwarding_late_no_reconveyance`
- `cra_logic_clean_conflict_pending_manual_review`

## Headline

| Approach | Matched | Dispositions | Accuracy | Est. cost | Est. tokens | LLM latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RuleKit total-atom Map + engine | 44 | 60 | 73.33% | $3.364865 | 79,717 | ~501s |
| Direct LLM, profiled prompt | 55 | 60 | 91.67% | $1.083435 | 35,749 | ~140s |

The direct profiled baseline is substantially better on this complex slice.
RuleKit's one-call total-atom path is mechanically viable, but its current
prompt/profile formulation is still too weak on branch closure and conditional
support atoms.

## Method Notes

The first RuleKit total-map run exposed a robustness bug: one live response
bound a numeric atom to `true`, which caused typed engine conversion to fail.
The live parser was hardened so malformed numeric values are coerced to
`undetermined` before engine execution. The first two already-paid responses
were then reprocessed offline with the hardened parser; the remaining two cases
were run live.

After this comparison, the total-atom prompt was tightened around the observed
failure modes: numeric atom typing, branch closure, not-applicable support
atoms, human-review routing triggers, and not-invoked versus validly-invoked
branches. The scores below are therefore the pre-prompt-fix baseline for this
complex slice.

Artifact locations:

- RuleKit first two reprocessed: `audits/complex_live_compare_round_001/rulekit_total_map_reprocessed_first2`
- RuleKit remaining two live: `audits/complex_live_compare_round_001/rulekit_total_map_remaining2`
- Direct profiled: `audits/complex_live_compare_round_001/direct_profiled`

## RuleKit Mismatches

RuleKit total-atom Map missed 16 of 60 dispositions.

- `cra_logic_invalid_duplicate_with_new_material`
  - `fcra.cra_furnisher_notice_satisfied`: got `undetermined`, expected `false`
  - `fcra.furnisher_indirect_satisfied`: got `true`, expected `false`
- `cra_logic_reinsertion_certified_but_notice_late`
  - `fcra.cra_furnisher_notice_satisfied`: got `undetermined`, expected `true`
  - `fcra.cra_reinvestigation_timely`: got `undetermined`, expected `true`
  - `fcra.dispute_resolution_compliant`: got `undetermined`, expected `false`
  - `fcra.furnisher_indirect_satisfied`: got `undetermined`, expected `true`
  - `fcra.reinsertion_satisfied`: got `undetermined`, expected `false`
  - `fcra.results_notice_satisfied`: got `undetermined`, expected `true`
- `cra_logic_reseller_forwarding_late_no_reconveyance`
  - `fcra.cra_furnisher_notice_satisfied`: got `undetermined`, expected `true`
  - `fcra.cra_reinvestigation_timely`: got `undetermined`, expected `true`
  - `fcra.furnisher_indirect_satisfied`: got `undetermined`, expected `true`
  - `fcra.results_notice_satisfied`: got `undetermined`, expected `true`
- `cra_logic_clean_conflict_pending_manual_review`
  - `fcra.cra_reinvestigation_timely`: got `false`, expected `undetermined`
  - `fcra.dispute_resolution_compliant`: got `false`, expected `undetermined`
  - `fcra.item_treatment_satisfied`: got `false`, expected `undetermined`
  - `fcra.results_notice_satisfied`: got `false`, expected `undetermined`

Main pattern: RuleKit misses are mostly load-bearing `undetermined` outcomes
caused by missing or mis-scoped local atom bindings. In the conflict case, the
total-map path also over-collapsed unresolved status into `false`.

## Direct LLM Mismatches

Direct profiled missed 5 of 60 dispositions.

- `cra_logic_invalid_duplicate_with_new_material`
  - `fcra.furnisher_indirect_satisfied`: got `true`, expected `false`
- `cra_logic_reinsertion_certified_but_notice_late`
  - `fcra.frivolous_termination_valid`: got `true`, expected `false`
  - `fcra.human_review_required`: got `true`, expected `false`
- `cra_logic_reseller_forwarding_late_no_reconveyance`
  - `fcra.frivolous_termination_valid`: got `true`, expected `false`
- `cra_logic_clean_conflict_pending_manual_review`
  - `fcra.frivolous_termination_valid`: got `true`, expected `false`

Main pattern: direct LLM tends to treat "no frivolous termination invoked" as a
satisfied/not-applicable `true`, while the benchmark expects `false` for
`frivolous_termination_valid` unless a valid termination actually occurred.
This may indicate either direct-prompt ambiguity or a benchmark semantics issue
for that determination label.

## Interpretation

This run is unfavorable to the current one-call total-map architecture. The
direct profiled prompt is both more accurate and materially cheaper on this
complex slice.

The deeper lesson is useful: the total-map approach does not fail because the
engine is weak; it fails because the local atom matrix still asks the model to
perform many branch-scoping judgments without enough structured guidance. The
next RuleKit improvement should therefore target the Map contract:

- make support-atom closure explicit for not-applicable branches;
- distinguish "not invoked" from "validly invoked" determinations;
- add typed output-schema constraints for numeric atoms;
- preserve conflict/unfinished-process states as `undetermined` instead of
  false when substantive completion has not occurred;
- consider a smaller determination-sliced total-map prompt rather than all 120
  atoms for every case.

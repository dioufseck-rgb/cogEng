# Complex Live Comparison Round 002

Date: 2026-06-03

Purpose: rerun the tightened total-atom prompt on a fresh complex FCRA case and
compare with the profiled direct LLM baseline.

Provider/model: `anthropic:claude-opus-4-7`

Case:

- `cra_logic_direct_furnisher_defect_not_corrected`

## Headline

| Approach | Matched | Dispositions | Accuracy | Est. cost | Est. tokens | LLM latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RuleKit total-atom Map + engine | 13 | 15 | 86.67% | $0.887100 | 21,244 | 132.76s |
| Direct LLM, profiled prompt | 13 | 15 | 86.67% | $0.270240 | 8,948 | 36.45s |

The tightened total-map prompt tied direct LLM on accuracy for this fresh case,
but remained much more expensive and slower because it emits a full 120-atom
matrix.

## Mismatches

RuleKit total-atom Map missed:

- `fcra.cra_reinvestigation_timely`: got `undetermined`, expected `true`
- `fcra.furnisher_indirect_satisfied`: got `false`, expected `true`

Direct profiled missed:

- `fcra.frivolous_termination_valid`: got `true`, expected `false`
- `fcra.furnisher_indirect_satisfied`: got `undetermined`, expected `true`

Overlap:

- Both approaches missed `fcra.furnisher_indirect_satisfied`.

## Diagnosis

The prompt fix helped: the live total-map record bound
`fcra.days_to_complete_reinvestigation = 30` from the narrative's "otherwise
timely" CRA reinvestigation branch. That is the branch-closure behavior the
previous prompt failed to elicit.

The remaining RuleKit misses show two distinct issues:

1. `cra_reinvestigation_timely` still depended on
   `fcra.additional_relevant_info_received_in_30_days`, which the model left
   `undetermined`. For cases where no later information is described and the
   narrative states ordinary timely reinvestigation, the Map/profile should
   close that atom as false rather than leaving it unresolved.

2. `furnisher_indirect_satisfied` is contaminated by direct-furnisher facts.
   The case says the furnisher failed to notify CRAs in the direct-dispute
   branch, but the separate CRA reinvestigation branch was otherwise timely and
   reasonable. The current atom set appears to reuse correction/reporting atoms
   across direct and indirect branches, making the Map vulnerable to branch
   leakage.

The direct prompt made the known `frivolous_termination_valid` not-invoked
mistake again, and it also treated the indirect furnisher branch as unresolved
because the narrative did not separately describe all indirect furnisher
actions.

## Takeaway

Prompt tightening improved local atom behavior but does not fully solve branch
scoping. The next architectural fix should separate direct-furnisher and
CRA-notice furnisher atoms, or add branch-scoped atom roles so that a direct
branch failure cannot automatically poison an indirect-branch determination.

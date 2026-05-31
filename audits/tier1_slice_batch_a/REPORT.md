# USCIS N-400 Expanded-Slice Batched Map Eval

Run date: 2026-05-31

Provider/model: `anthropic:claude-opus-4-7`

Purpose: make the RuleKit comparison fairer by expanding Map coverage from the
19 Tier 1 target atoms to the full DAG dependency slice for the 8 selected
determinations, while avoiding one LLM call per atom.

## Setup

- Cases: 10
- Determinations: 8
- Reachable atoms in selected determination slice: 116
- Batch size: 8 atoms per governed Map binding call
- LLM calls: 160 total
  - 10 source-inventory calls
  - 150 batched atom-binding calls

Without batching, the same slice would require about 1,170 calls: one source
inventory call plus 116 atom calls per case. Batching covered about 6x more
atoms than the prior 19-atom run while reducing call count from 200 to 160.

Artifacts:

- Aggregate summary: `summary.json`
- Provider summary: `anthropic_claude-opus-4-7/summary.json`
- Map records: `anthropic_claude-opus-4-7/map_records.json`
- Validation reports: `anthropic_claude-opus-4-7/map_validation_reports.json`
- Dispositions: `anthropic_claude-opus-4-7/dispositions.json`
- Prompt artifacts: `anthropic_claude-opus-4-7/prompts/`

## Cost And Latency

The run used configured pricing of `$15` input / `$75` output per million
tokens for Anthropic Opus. Token counts are estimated from character length.

| Metric | Expanded Batched Map | Prior 19-Atom Map | Direct LLM |
|---|---:|---:|---:|
| LLM calls | 160 | 200 | 10 |
| Selected atoms | 116 | 19 | n/a |
| Estimated input tokens | 374,981 | 197,290 | 12,323 |
| Estimated output tokens | 123,007 | 30,703 | 5,442 |
| Estimated total tokens | 497,988 | 227,993 | 17,765 |
| Estimated cost | $14.85024 | $5.262075 | $0.592995 |
| Total LLM latency | 1,917.28s | 748.18s | 92.34s |
| Average LLM call latency | 11.98s | 3.74s | 9.23s |

The expanded batched run is much more expensive than direct prompting, but the
cost profile is structurally different: it buys atom-level evidence, basis,
source IDs, validation, and deterministic engine traces. The result also shows
that batching reduces call count but does not automatically reduce total cost,
because larger prompts carry much more atom specification text.

## Binding Quality

Expected-binding benchmark:

| Metric | Expanded Batched Map | Prior 19-Atom Map |
|---|---:|---:|
| Expected bindings checked | 29 | 29 |
| Status matches | 29/29 | 27/29 |
| Value matches | 26/26 | 25/26 |
| Basis matches | 7/8 | 7/8 |

The expanded batched Map improved the controlled atom-binding checks. It
resolved the prior status/value misses, including the missing-travel-dates and
travel-conflict cases. Basis taxonomy remains slightly loose.

Basis counts:

| Basis | Count |
|---|---:|
| `open_world_absence` | 864 |
| `not_found` | 416 |
| `inferred_from_record` | 42 |
| `closed_world_absence` | 30 |
| `explicit_positive` | 24 |
| `explicit_negative` | 10 |
| `conflicting_evidence` | 8 |
| `computed` | 6 |

The volume of `open_world_absence` is the most important signal in this run.
The prompt is correctly refusing to convert narrative silence into negative
facts, but the policy DAG contains many negative bar and exception atoms. A
real deployment needs richer source-scope policy, structured forms, or
deterministic prefill rules so that broad official checks can support safe
negative bindings where appropriate.

## Disposition Changes From Prior RuleKit Run

The expanded run changed 12 of 80 dispositions compared with the prior
19-atom run:

| Change | Count |
|---|---:|
| `undetermined` -> `false` | 7 |
| `undetermined` -> `true` | 3 |
| `true` -> `undetermined` | 1 |
| `false` -> `undetermined` | 1 |

Useful improvements:

- `tier1_travel_conflict_six_month_absence`: continuous residence and physical
  presence moved from `undetermined` to `false`.
- `tier1_one_year_absence_no_exception`: continuous residence moved from
  `undetermined` to `false`.
- `tier1_physical_presence_short_by_worksheet`: physical presence moved from
  `undetermined` to `false`.
- `tier1_missing_travel_dates`: continuous residence and physical presence
  moved from `undetermined` to `false`.
- Clean case English/civics moved to `true`.

Regressions or still-open issues:

- Clean case `human_review_required` moved from `true` to `undetermined`, which
  is closer than the prior false-positive but still not the intended `false`.
- Some cases remain `undetermined` because negative bars, exceptions, and
  review-trigger atoms are still open-world absent rather than closed-world
  resolved.

## Comparison With Direct LLM

Direct LLM reference: `audits/tier1_direct_a`

Agreement with direct baseline:

| Metric | Result |
|---|---:|
| Compared dispositions | 80 |
| Agreements | 55 |
| Disagreements | 25 |
| Agreement rate | 68.75% |

Disagreement patterns:

| RuleKit outcome | Direct outcome | Count |
|---|---|---:|
| `undetermined` | `true` | 17 |
| `false` | `undetermined` | 6 |
| `undetermined` | `false` | 2 |

The comparison improved only slightly from the prior 19-atom run
(`54/80` to `55/80`). That is an important finding: expanding coverage helps,
but coverage alone is not enough. The next bottleneck is epistemic architecture:
when is an absent bad fact safely false, when is it undetermined, and when does
it trigger human review?

## Readout

This run supports the larger design direction:

1. One call per atom is overkill for runtime. Batched governed Map works and
   preserves the same evidence-basis contract.
2. Determination-slice coverage is better than manually selecting a few atoms.
3. Direct prompting remains much cheaper and more decisive, but it collapses
   evidence extraction and policy disposition into a single opaque judgment.
4. RuleKit's current conservative Map semantics are good for safety, but too
   conservative for clean positive cases unless the case packet has strong
   closed-world source scopes for negative bars and review triggers.

Recommended next implementation steps:

- Add source-scope profiles for common packet sources such as FBI checks,
  docket searches, N-400 travel tables, test records, oath worksheets, and
  interview worksheets.
- Add atom groups so one prompt can bind a coherent family, for example
  "GMC criminal bars", "travel/continuous residence", or "English/civics".
- Add deterministic prefill rules for atoms that can be derived from structured
  source completeness, instead of asking the LLM to infer every negative bar.
- Add load-bearing human-review semantics: missing/conflicting facts should
  trigger review when they affect the requested disposition, not merely because
  a non-load-bearing detail is absent.
- Rerun direct-vs-RuleKit after these source-scope and load-bearing changes.

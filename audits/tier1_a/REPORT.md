# USCIS N-400 Tier 1 Broad Map Eval

Run date: 2026-05-31

Provider/model: `anthropic:claude-opus-4-7`

Scope:

- 10 synthetic but policy-realistic evidence packets
- 19 target atoms across residence, travel, physical presence, state residence,
  English/civics, disability exception, oath/attachment, GMC, and review flags
- 8 determinations exercised downstream
- 200 live LLM calls: one source inventory call and 19 atom-binding calls per case

Artifacts:

- Aggregate summary: `summary.json`
- Provider summary: `anthropic_claude-opus-4-7/summary.json`
- Map records: `anthropic_claude-opus-4-7/map_records.json`
- Validation reports: `anthropic_claude-opus-4-7/map_validation_reports.json`
- Prompts and raw responses: `anthropic_claude-opus-4-7/prompts/`

## Cost And Latency

The run used configured pricing of `$15` input / `$75` output per million
tokens for Anthropic Opus. Token counts are estimated from character length
until provider wrappers expose exact usage metadata.

- LLM calls: 200
- Estimated input tokens: 197,290
- Estimated output tokens: 30,703
- Estimated total tokens: 227,993
- Estimated cost: `$5.262075`
- Total LLM latency: 748.18 seconds
- Average LLM call latency: 3.74 seconds

## Quality Summary

All 1,400 validated atom bindings were accepted by the Map validator after
sanitization. Most of those are default `not_found` bindings for atoms outside
the selected evidence scope.

Expected-binding benchmark:

- Expected bindings checked: 29
- Status matches: 27 / 29
- Value matches: 25 / 26
- Basis matches: 7 / 8

The important governance invariant held: there were no observed
false-from-open-world-silence failures and no overbroad closed-world absence
failures in this run.

## Notable Differences

1. `tier1_travel_conflict_six_month_absence`

   Expected `n400.days_absent_trip_1` to bind to `198`, but the model returned
   `undetermined` with `conflicting_evidence`. This is arguably safer than the
   expectation because the packet intentionally contains a conflict between the
   travel table and passport stamps. The benchmark expectation should likely be
   revised to prefer conflict preservation for the raw day-count atom, while a
   separate review flag carries the inconsistency.

2. `tier1_travel_conflict_six_month_absence`

   Expected `n400.absence_6_to_12_months` basis `inferred_from_record`; the
   model returned `computed`. The value and status were correct. This is a
   harmless basis taxonomy mismatch unless we want to distinguish record
   inference from arithmetic computation more strictly.

3. `tier1_missing_travel_dates`

   Expected `n400.absence_6_to_12_months` to be `undetermined`, but the model
   bound it `true` from an explicit packet statement that the absence was "about
   7 months." This exposes a useful design issue: if a policy atom depends on
   exact date arithmetic, approximate duration language should probably be
   insufficient for the duration atom and should instead bind only a separate
   "evidence missing critical dates" atom.

## Readout

This run is encouraging. The governed Map prompt is handling a larger atom
surface without collapsing into direct adjudication, and the validator accepted
the outputs. The failures are not random JSON/schema problems; they are
architecture-relevant questions about benchmark semantics:

- Preserve conflicts before computing load-bearing arithmetic.
- Separate approximate narrative facts from exact arithmetic facts.
- Tighten basis taxonomy for computed versus inferred bindings.

Recommended next step: add deterministic post-Map validators for numeric atoms
that require exact dates, then rerun this same suite across Anthropic, OpenAI,
and Gemini when all three keys are available in the environment.

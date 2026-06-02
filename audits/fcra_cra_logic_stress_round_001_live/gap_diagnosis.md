# FCRA CRA Logic Stress Gap Diagnosis

Date: 2026-06-02

This diagnosis uses the existing `fcra_cra_logic_stress_round_001_live`
artifacts. No fresh LLM calls were made.

## Executive Finding

The main governed RuleKit gap is not the deterministic engine. It is the Map
layer's current inability to reliably convert compact narrative case language
into enough atom bindings for a large, branchy policy.

The direct LLM comparison is strong because the direct prompt can reason
holistically over phrases such as "valid dispute", "reasonable reinvestigation",
"no branch applies", and "timely results notice". The governed path asks the
model to bind many low-level atoms independently. That is more governable, but
the current implementation loses information through output truncation, strict
open-world binding rules, incomplete profile/default coverage, and ambiguous
determination semantics.

## Current Scores

| Approach | Split | Matches | Total | Accuracy |
|---|---|---:|---:|---:|
| Governed LLM Map + engine | repair | 36 | 60 | 60.00% |
| Governed LLM Map + engine | validation | 31 | 60 | 51.67% |
| Direct LLM disposition | repair | 56 | 60 | 93.33% |
| Direct LLM disposition | validation | 55 | 60 | 91.67% |
| Profile-only baseline | repair | 22 | 60 | 36.67% |
| Profile-only baseline | validation | 25 | 60 | 41.67% |
| Candidate profile repair | repair | 43 | 60 | 71.67% |
| Candidate profile repair | validation | 28 | 60 | 46.67% |

The candidate profile repair improved the profile-only baseline but is still
below the promotion threshold. Its promotion gate is correctly
`hold_for_review`.

## Failure Shape

Governed validation has 29 mismatches:

| Direction | Count |
|---|---:|
| `undetermined->true` | 26 |
| `undetermined->false` | 2 |
| `false->true` | 1 |

Most governed misses are conservative unknowns. This is exactly the failure
distribution we want in a regulated setting, but the rate is too high.

Direct validation has 5 mismatches:

| Direction | Count |
|---|---:|
| `true->false` | 4 |
| `false->undetermined` | 1 |

Four of the five direct misses are on `fcra.frivolous_termination_valid`, where
the direct prompt treats "no frivolous termination occurred" as
not-applicable/satisfied, while the benchmark labels this event-validity
determination `false` unless an actual frivolous termination occurred.

## Root Causes

### 1. Single-map output truncation and parse failure

The governed single-map call often attempted to bind roughly 80 to 100 atoms in
one response, each with value, basis, evidence, explanation, confidence, and
source ids. Several raw responses are visibly truncated mid-JSON. The parser
then reports `single-map response was not a JSON object` or recovers only a
partial payload.

This is not merely a prompt-quality problem. The output contract is too large
for one unconstrained text response at the current token budget.

Observed examples:

- `cra_logic_direct_furnisher_public_record_exception`: single-map response
  ended mid-binding around `business_days_to_notify_furnisher`.
- `cra_logic_late_results_notice_after_timely_reinvestigation`: response ended
  mid-binding around `notice_included_all_relevant_info`.
- `cra_logic_consumer_statement_not_carried_forward`: response ended mid-field.

The repair call recovers some atoms, but it is capped and reactive. It cannot
fully compensate for a failed initial Map.

### 2. Atom-level mapping is stricter than real narrative language

Cases often state legally meaningful compound facts:

- "valid direct dispute"
- "timely and reasonable reinvestigation"
- "verified the item and recorded current status"
- "no reseller, reinsertion, or consumer-statement branch applies"
- "material date conflict and conflicting documents"

The DAG needs many lower-level atoms for those concepts. The Map layer currently
does not have enough profile guidance to expand these compound phrases
consistently into atom bundles.

Example: `cra_logic_direct_furnisher_public_record_exception` says the CRA side
had a valid direct dispute, notified the furnisher timely, completed a
reasonable reinvestigation in 24 days, verified the item, recorded current
status, and sent a timely results notice. Governed Map still leaves many atoms
undetermined, producing 10 mismatches.

### 3. Branch non-applicability is not fully formalized

Several determinations are explicitly "satisfied or not applicable":

- `fcra.reinsertion_satisfied`
- `fcra.reseller_satisfied`
- `fcra.direct_furnisher_satisfied`
- `fcra.consumer_statement_satisfied`
- `fcra.furnisher_indirect_satisfied`

The engine DAG supports this pattern through OR branches such as "not
reinserted OR reinsertion package satisfied". But the Map layer must bind the
branch trigger false when the narrative establishes non-applicability. If it
does not, the OR cannot collapse to true.

The profile repair added some branch-not-applicable rules and improved repair
split accuracy, but validation remains weak because the cues are still narrow
and hand-shaped.

### 4. Event-validity determinations are mixed with satisfaction determinations

`fcra.frivolous_termination_valid` is different from the other branch
determinations. It asks whether an actual frivolous/irrelevant termination, if
made, was valid. The current expected labels treat "no frivolous termination
occurred" as `false`, not as `true` or not-applicable.

Direct LLM repeatedly answered this as `true` because it interpreted the
question as "no violation on the frivolous branch." That is understandable from
the wording and is evidence that the determination taxonomy needs to be made
explicit.

Recommended resolution: split or annotate determination kinds:

- `event_validity`: false when the event did not occur unless explicitly modeled
  as not-applicable.
- `satisfied_or_not_applicable`: true when the branch trigger is false.
- `routing`: true/false over meta triggers, with missing handled by routing
  defaults.

### 5. Routing cues are undercovered

`human_review_required` is now a routing determination, but Map coverage is
still incomplete. The validation conflict case says "material date conflict and
conflicting documents"; the governed result was false because the relevant
routing atoms were not bound true.

This is a profile cue problem, not a DAG problem. Existing profile guidance
includes similar phrases such as "inconsistent dates", but did not cover this
case language reliably enough.

### 6. Numeric non-applicability remains awkward

For numeric atoms, the LLM sometimes returns boolean `false` to mean "not
applicable". `_binding_from_payload` correctly rejects boolean values for
numeric atoms and converts them to undetermined. That is type-safe, but it can
leave numeric comparison nodes unresolved.

The right fix is not to let numeric atoms hold `false`. The right fix is to
ensure the branch trigger is bound so the numeric comparison is not load-bearing
when the branch does not apply.

### 7. The repair loop targets the right layer but lacks enough validation logic

The new Map-profile repair correctly targets `map_profile.default_rules`.
However, the generated rules are still heuristic and sometimes too broad. The
validation gate now prevents promotion, but the loop needs sharper mismatch
classification before it can safely author profile changes.

## Case-Level Diagnosis

### `cra_logic_direct_furnisher_public_record_exception`

Governed validation mismatches: 10.

Primary gap: compound CRA-side success facts were not decomposed into enough
atoms. The narrative says the CRA side separately had a valid direct dispute,
timely furnisher notice, reasonable reinvestigation in 24 days, verification,
current status, and timely results notice. Map still leaves many corresponding
atoms undetermined.

Secondary gap: direct-furnisher branch is a public-record-only exception. The
system needs clearer profile guidance that this makes the direct-furnisher
branch satisfied/not-applicable, while the separate CRA branch still proceeds.

### `cra_logic_clean_conflict_pending_manual_review`

Governed validation mismatches: 4.

Primary gap: routing atoms did not bind true from "material date conflict and
conflicting documents." This caused `human_review_required=false` when expected
true.

Secondary gap: non-applicable reseller/reinsertion branches remained
undetermined despite explicit "no branch applies" language.

### `cra_logic_late_results_notice_after_timely_reinvestigation`

Governed validation mismatches: 7.

Primary gap: Map failed to bind many ordinary successful reinvestigation atoms
from compact narrative language. It also failed to bind the numeric late-results
notice fact strongly enough for `results_notice_satisfied=false`.

This case is important because it tests a common regulated-adjudication shape:
most duties are satisfied, but one timing element fails. The governed Map must
preserve that mixed result.

### `cra_logic_consumer_statement_not_carried_forward`

Governed validation mismatches: 8.

Primary gap: "otherwise timely and reasonable reinvestigation" was not expanded
into the atoms needed for the base CRA duties. The consumer-statement failure
itself is not the only issue; the Map also leaves surrounding ordinary duties
unknown.

## Highest-Value Fixes

1. Replace unconstrained one-call Map with structured, bounded mapping.

   Options:

   - Use provider-native structured output or tool calling when available.
   - Split Map into bounded chunks and validate each chunk's JSON before moving
     on.
   - Increase output budget only as a temporary mitigation; it does not solve
     reliability.

2. Add incremental sufficiency mapping.

   Flow:

   - Apply prebound/profile defaults.
   - Run engine.
   - Select unresolved load-bearing atoms only.
   - Ask the LLM for a small bounded set.
   - Validate JSON and atom types.
   - Re-run engine.
   - Repeat until determinations are resolved or no evidence-supported binding
     can be added.

   This preserves the governance benefit while avoiding 80 to 100 atom payloads.

3. Add Map-profile macro entailments.

   The profile should allow policy-authored macro rules such as:

   - "valid direct CRA dispute" entails intake atoms.
   - "reasonable reinvestigation" entails review/consideration atoms.
   - "verified and recorded current status" entails item-treatment atoms.
   - "no reseller branch applies" binds reseller trigger false.
   - "material date conflict and conflicting documents" binds routing triggers
     true.

   These must be authored as policy artifacts, not Python domain modules.

4. Make determination semantics explicit.

   Add first-class metadata for:

   - `event_validity`
   - `satisfied_or_not_applicable`
   - `routing`

   Then use that metadata in direct prompts, reports, and repair classification.

5. Improve repair classification before generating rules.

   Candidate profile rules should be classified as:

   - branch non-applicability
   - compound affirmative entailment
   - routing trigger
   - timing/numeric extraction
   - event-validity semantic ambiguity
   - ground-truth review needed

   Only the first four should generate profile patches automatically, and only
   when validation improves enough.

## Bottom Line

RuleKit's governed approach is failing conservatively, which is desirable, but
it is under-mapping the FCRA policy. The largest immediate gap is not policy
logic; it is the Map contract. The current one-call Map is too large and too
fragile. The next implementation should focus on structured bounded Map calls,
incremental sufficiency, and policy-authored profile macro entailments.


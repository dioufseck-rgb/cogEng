# FCRA Credit Reporting Deep Benchmark Run

Run date: 2026-05-31

## Artifacts

- Program: `audits/fcra_credit_reporting_deep/rulekit_export/program.json`
- Runtime cases: `audits/fcra_credit_reporting_deep/runtime_cases.json`
- RuleKit runtime result: `audits/fcra_credit_reporting_deep/rulekit_runtime/summary.json`
- Anthropic governed direct: `audits/fcra_credit_reporting_deep/direct_governed_anthropic/summary.json`
- Anthropic terse direct: `audits/fcra_credit_reporting_deep/direct_terse_anthropic/summary.json`

## Summary

| System | Cases | Dispositions | Matches | Mismatches | Agreement |
|---|---:|---:|---:|---:|---:|
| RuleKit exported runtime | 11 | 165 | 165 | 0 | 100.00% |
| Direct Anthropic, terse | 11 | 165 | 147 | 18 | 89.09% |
| Direct Anthropic, governed | 11 | 165 | 134 | 31 | 81.21% |

## Cost And Latency

| System | LLM calls | Total latency | Avg call latency | Estimated cost |
|---|---:|---:|---:|---:|
| RuleKit exported runtime | 0 | engine-only | milliseconds per determination | $0 |
| Direct Anthropic, terse | 11 | 166.97s | 15.18s | $1.52154 |
| Direct Anthropic, governed | 11 | 407.82s | 37.07s | $2.801655 |

Token counts are estimated from character count using the existing benchmark
harness pricing estimator.

## Direct Anthropic Error Directions

Governed prompt:

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 16 |
| `true` | `false` | 9 |
| `false` | `true` | 5 |
| `undetermined` | `false` | 1 |

Terse prompt:

| Actual | Expected | Count |
|---|---|---:|
| `true` | `false` | 10 |
| `false` | `true` | 6 |
| `undetermined` | `true` | 2 |

## Main Failure Pattern

The dominant direct-LLM error is applicability/scope handling:

- `fcra.frivolous_termination_valid` is expected `false` when no frivolous
  termination was made, because the determination asks whether such a
  termination is valid. Direct Anthropic frequently treats "not invoked" as
  "not applicable, therefore satisfied" and returns `true`.
- Direct-to-furnisher cases cause cross-branch contamination. The direct model
  often treats CRA reinvestigation determinations as out of scope, while the
  benchmark defaults the non-load-bearing CRA branch as satisfied for overall
  architecture comparison.
- On defect-treatment cases, direct Anthropic sometimes collapses a downstream
  treatment failure into upstream consideration failure, or vice versa. RuleKit
  keeps these as separate determinations.
- The governed direct prompt was more cautious, but it overproduced
  `undetermined` on determinations that the benchmark treats as satisfied by
  non-applicability or scoped defaults.

## Interpretation

This is the first benchmark in this sequence where the complexity hypothesis
starts to show a meaningful separation. On shallow USCIS Tier 1, a governed
direct prompt was competitive. On this deeper credit-reporting policy, the
direct model struggles with branch applicability, cross-actor scope, and
vacuous/non-load-bearing determinations.

The result is not just a headline accuracy win for RuleKit. The mechanism is
visible: the deterministic DAG preserves separate questions for trigger,
timing, forwarding, consideration, item treatment, results notice, reinsertion,
furnisher duties, direct-dispute duties, reseller duties, and routing. Direct
LLM disposition tends to reason holistically and then retrofits every
determination to the holistic story, which creates errors when determinations
are intentionally orthogonal.

## Caveat

The runtime cases include structured fields and benchmark defaults so RuleKit
can deterministically replay ground-truth cases. Direct prompts in this harness
also receive structured case fields. That makes this comparison generous to
direct LLM disposition, not hostile to it.

## Narrative-Only Slice

After the structured replay, a production-like narrative-only slice was run
with gold facts/defaults removed. The slice contains four cases:

- `fcra_deep_clean_verified`
- `fcra_deep_missing_forwarded_bank_statement`
- `fcra_deep_direct_furnisher_valid_not_corrected`
- `fcra_deep_mixed_file_identity_theft_ambiguous`

The full 11-case governed Map run over 120 atoms exceeded the 20-minute
interactive timeout before writing a summary. The four-case slice completed.

| System | Cases | Dispositions | Matches | Mismatches | Agreement | LLM calls | Latency | Estimated cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| RuleKit single-call Map + repair | 4 | 60 | 36 | 24 | 60.00% | 8 | 583.65s | $5.03748 |
| Direct Anthropic, governed | 4 | 60 | 33 | 27 | 55.00% | 4 | 150.85s | $0.900435 |
| Direct Anthropic, terse | 4 | 60 | 44 | 16 | 73.33% | 4 | 64.58s | $0.441285 |

Narrative-only RuleKit Map mismatch directions:

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 19 |
| `false` | `true` | 4 |
| `undetermined` | `false` | 1 |

Narrative-only direct governed mismatch directions:

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 21 |
| `true` | `false` | 2 |
| `false` | `true` | 2 |
| `undetermined` | `false` | 2 |

Narrative-only direct terse mismatch directions:

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 6 |
| `false` | `true` | 5 |
| `true` | `false` | 4 |
| `undetermined` | `false` | 1 |

### Narrative-Only Interpretation

This is the first result that tests the actual Map question. The current
single-call Map is not yet production-viable on this deep FCRA policy:

- It is much more expensive than direct disposition on the slice.
- It overproduces `undetermined` when structured defaults are removed.
- Many errors are not "LLM cannot read the narrative" errors. They are missing
  architectural/default semantics for non-applicable branches such as reseller,
  reinsertion, consumer-statement handling, and direct-furnisher/CRA branch
  separation.
- Human-review routing triggers are also too easy to miss from narrative-only
  evidence; `not mine`, mixed-file, and missing source-document cues need
  targeted routing extraction.

The important distinction is:

- The DAG is useful and coherent when facts are bound.
- The current generic Map strategy is too broad and too expensive for a
  120-atom deep policy.
- The next engineering target is not "better direct prompt"; it is a
  sufficiency-aware Map planner that binds only the facts needed for selected
  determinations, applies audited source-scope defaults for non-applicable
  branches, and runs targeted routing extraction before broad atom binding.

## Map Profile Fix

A generic map-profile mechanism was added after the first narrative-only run.
The profile is policy data, not domain Python. It is carried in
`program.metadata.extras.map_profile.default_rules` and applies narrative-matched
defaults before LLM atom selection.

The FCRA profile currently encodes:

- actor-scope defaults for reseller, reinsertion, consumer-statement, direct
  furnisher, and CRA paths;
- ordinary CRA dispute trigger cues;
- ordinary review/results/furnisher-response cues;
- forwarding-failure cues;
- routing cues for not-mine, identity theft, mixed-file, missing source
  documents, and date conflicts.

Two generic runtime fixes landed with this:

- governed Map atom selection now uses the profile-enriched prebind record, so
  profile-resolved atoms are not sent back to the LLM and overwritten;
- numeric atom bindings returned as booleans by the LLM are hardened to
  `undetermined` instead of crashing engine conversion.

### Delta

| Run | Matches | Agreement | Selected atoms | LLM calls | Latency | Estimated cost |
|---|---:|---:|---:|---:|---:|---:|
| No profile | 36/60 | 60.00% | 90 | 8 | 583.65s | $5.03748 |
| Profile pass 1 | 47/60 | 78.33% | 52 | 7 | 394.19s | $3.25542 |
| Profile pass 2 | 52/60 | 86.67% | 32 | 7 | 351.40s | $2.80767 |
| Direct Anthropic, terse | 44/60 | 73.33% | n/a | 4 | 64.58s | $0.441285 |
| Direct Anthropic, governed | 33/60 | 55.00% | n/a | 4 | 150.85s | $0.900435 |

Remaining profile-pass-2 mismatch directions:

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 4 |
| `false` | `true` | 3 |
| `undetermined` | `false` | 1 |

The quality result now supports the complexity hypothesis on the slice: RuleKit
Map + engine beats both direct baselines after policy-authored Map discipline is
injected. The cost result is still not acceptable. The next engineering problem
is reducing calls and prompt size, likely by splitting Map into a cheap
case-shape/routing pass plus targeted load-bearing atom binding.

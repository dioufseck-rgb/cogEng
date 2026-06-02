# FCRA CRA Logic-Stress Findings

Run date: 2026-06-02

## Purpose

This run tests the next complexity tier: epistemically clean narratives with
more difficult logic. The cases avoid typos, noisy documents, and ambiguous
fact extraction. Instead, they stress:

- conditional 30/45-day deadline logic;
- late or incomplete downstream notices;
- valid and invalid frivolous-termination branches;
- reinsertion safeguards;
- reseller own-error and source-CRA forwarding paths;
- consumer-statement carry-forward;
- direct-furnisher exception and correction paths;
- expedited deletion;
- unresolved conflict and human-review routing.

The final holdout stayed locked.

## Split Discipline

| Split | Cases | Dispositions | Ran? |
|---|---:|---:|---|
| Repair | 4 | 60 | yes |
| Validation | 4 | 60 | yes |
| Final holdout | 4 | 60 | no |

Each split contains four different `split_group` labels, so no single failure
mode dominates a slice.

## Results

| System | Split | Matches | Mismatches | Accuracy | LLM calls | Estimated tokens |
|---|---|---:|---:|---:|---:|---:|
| Governed Map + engine | repair | 36 | 24 | 60.00% | 8 | 146,057 |
| Governed Map + engine | validation | 31 | 29 | 51.67% | 8 | 157,341 |
| Direct LLM, profiled | repair | 56 | 4 | 93.33% | 4 | 36,408 |
| Direct LLM, profiled | validation | 55 | 5 | 91.67% | 4 | 35,714 |

## Mismatch Direction

Governed repair:

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 14 |
| `undetermined` | `false` | 7 |
| `false` | `true` | 3 |

Governed validation:

| Actual | Expected | Count |
|---|---|---:|
| `undetermined` | `true` | 26 |
| `undetermined` | `false` | 2 |
| `false` | `true` | 1 |

Direct repair:

| Actual | Expected | Count |
|---|---|---:|
| `true` | `false` | 3 |
| `undetermined` | `true` | 1 |

Direct validation:

| Actual | Expected | Count |
|---|---|---:|
| `true` | `false` | 4 |
| `false` | `undetermined` | 1 |

## Interpretation

This result is intentionally uncomfortable and useful.

The direct profiled prompt performs very well on clean logical cases. The
cases are harder than the bank-perspective set, but the facts are explicit and
the direct prompt receives the policy profile. A strong LLM can often read the
whole fact pattern and infer the correct branch-level disposition.

The governed result is not a DAG failure. It is mostly a Map/profile coverage
failure. The dominant governed mismatch is `undetermined -> true`, especially
for determinations that should be satisfied by scoped non-applicability or by
ordinary-process defaults. In other words, the engine is being conservative
because the full-policy Map profile does not yet bind enough branch-default
and ordinary-process atoms from these new narrative phrasings.

The direct result has a different failure shape. Its main error is
`true -> false`, concentrated around `fcra.frivolous_termination_valid`. That
is the same structural issue seen before: the model tends to treat "no
frivolous termination was made" as "the frivolous termination determination is
satisfied." The DAG keeps that determination separate.

## What This Teaches

The complexity hypothesis is not simply "harder logic makes RuleKit win." It is
more precise:

1. RuleKit wins only after the Map/profile layer binds the policy's branch
   semantics with enough coverage.
2. When the Map profile is underbuilt, the symbolic engine preserves uncertainty
   rather than hallucinating satisfaction.
3. Direct LLM can be strong on clean logical narratives, but still shows a
   systematic branch-applicability overclaim pattern.

This benchmark is a good repair target because the narratives are clean. The
remaining governed misses should be fixable with general policy-pack profile
rules rather than case-specific hacks.

## Highest-Value Next Fix

Use only the repair split to extend the full CRA map profile with generic rules:

- ordinary valid CRA intake when account, field, basis, and direct CRA receipt
  are stated in different words;
- ordinary timely completion and results notice phrases;
- non-applicable direct-furnisher, reseller, reinsertion, and consumer-statement
  branch defaults when the narrative explicitly says the branch does not apply;
- valid-frivolous and invalid-frivolous extraction rules that distinguish
  "termination made" from "termination absent";
- expedited-deletion rules that bind the furnisher-notice shortcut;
- reseller forwarding failure rules for late conveyance or missing reconveyance.

Then rerun the repair split, check the validation split without using it for
patch authoring, and keep the final holdout locked.

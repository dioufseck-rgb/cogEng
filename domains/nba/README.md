# NBA Domain

This directory holds artifacts for adjudicating NBA Collective Bargaining Agreement (CBA) cases under RuleKit. It is exercised by the RuleArena benchmark (ACL 2025), which provides annotated NBA CBA cases at three complexity levels.

## Fragments

`fragments/` contains hand-authored typed DAGs that exercise specific rule families from the CBA. Each fragment exposes:

- `build_fragment()` — returns a dict of named engine nodes ready to evaluate against a `FactBundle`
- `cases()` — returns a list of `(label, bundle, expected)` tuples, where `expected` is a dict of `{node_name: Kleene}` assertions

The four fragments target the rule families with the worst per-rule precision in the Opus 4.7 RuleArena Level 3 baseline (May 2026):

| Fragment | Rule family | Opus 4.7 precision | What it demonstrates |
|---|---|---|---|
| `mle_selection.py` | Mid-Level Exception flavors | 0.50–1.0 across MLE rules | Mutually-exclusive bracket-gating predicates structurally prevent flavor confusion |
| `max_salary_by_yos.py` | Article II Section 7(a) maximum annual salary | P=0.083 on Higher Max criterion | Conjunctive gating with `is_5th_year_eligible` prevents over-firing |
| `sign_and_trade.py` | Section 8(e)(1) + Section 2(e)(4) hard cap | Case-0 misattribution | Constraints wired per actor (signer vs acquirer); trace pinpoints problematic team-role |
| `trade_matching.py` | Section 6(j) Traded Player Exception | P=0.0 on aggregated TPE | Multi-player aggregation delegated to Map (single derived numeric atom); engine does inequality bridge |

## CBA constants used by the fragments

These come from the 2024-25 Salary Cap Year and are encoded as engine `Constant` nodes:

- Salary Cap: $140,588,000
- First Apron Level: $178,132,000
- Second Apron Level: $188,931,000
- Non-Taxpayer MLE percentage: 9.12% of cap
- Taxpayer MLE / Room MLE percentage: 5.68% of cap (approximation; CBA encoded amounts differ slightly)
- Max-salary percentages by YOS bracket: 25% (<7 YOS), 30% (7-9), 35% (10+)
- Higher Max boost: 30% for `is_5th_year_eligible AND has_higher_max_criteria`
- Designated Veteran boost: 35% for 8-9 YOS with continuous tenure + Higher Max
- Trade Player Exception allowance: $250,000 (or $0 if post-trade salary exceeds First Apron)

## Status

The fragments are hand-bound: a `make_bundle()` helper in each module constructs `FactBundle` instances directly. The next step for NBA is wiring `domains/nba/fragments/*` together via an adapter that:

1. Reads RuleArena case JSON
2. Instantiates per-operation atom IDs (e.g., `team_A_salary_pre_op_A`, `team_A_salary_pre_op_B`)
3. Invokes `rulekit.map.typed.TypedNarrativeLLMSubstrate` against the case description to bind values
4. Evaluates the fragments' top-level nodes
5. Un-maps results to RuleArena's expected output format
6. Scores against ground truth

This adapter doesn't exist yet. The fragments validate that the typed engine *can* express the reasoning shape correctly; the adapter is what makes them run end-to-end on real cases.

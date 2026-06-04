# Final Mixed Live Comparison Round 001

Date: 2026-06-03

Purpose: compare RuleKit total-atom Map + deterministic engine against direct
profiled LLM disposition on a mixed set of realistic and edge FCRA CRA cases.
The primary score is case-level final disposition. Determination-level agreement
is reported separately as trace fidelity.

Models:

- Frontier: `anthropic:claude-opus-4-7`
- Lower-cost: `anthropic:claude-sonnet-4-6`

Cases:

- `cra_logic_reseller_own_error_corrected_timely`
- `cra_logic_direct_furnisher_public_record_exception`
- `cra_logic_consumer_statement_not_carried_forward`
- `cra_logic_expedited_deletion_short_circuits_furnisher_notice`

Scoring:

- Final disposition: `fcra.dispute_resolution_compliant`
- Routing disposition: `fcra.human_review_required`
- Determination fidelity: all 15 expected determinations

## Headline

| Approach | Model | Final disposition | Routing | Final + routing | Determinations | Est. cost | LLM latency |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RuleKit total-map | Opus | 2/4 | 4/4 | 2/4 | 46/60 | $3.449670 | 514.45s |
| RuleKit total-map | Sonnet | 1/4 | 4/4 | 1/4 | 44/60 | $0.870174 | 658.74s |
| Direct profiled | Opus | 3/4 | 4/4 | 3/4 | 51/60 | $1.061880 | 138.42s |
| Direct profiled | Sonnet | 4/4 | 4/4 | 4/4 | 56/60 | $0.344841 | 259.61s |

On this suite, direct profiled Sonnet is the strongest result: it gets every
final disposition and routing disposition correct, with 56/60 determination
agreement. RuleKit total-map continues to underperform because the full atom
matrix leaves many support atoms unresolved or branch-contaminated.

## Final Disposition By Case

### RuleKit Total-Map Opus

- `cra_logic_reseller_own_error_corrected_timely`: got `false`, expected `true`
- `cra_logic_consumer_statement_not_carried_forward`: got `false`, expected `false`
- `cra_logic_direct_furnisher_public_record_exception`: got `true`, expected `true`
- `cra_logic_expedited_deletion_short_circuits_furnisher_notice`: got `undetermined`, expected `true`

### RuleKit Total-Map Sonnet

- `cra_logic_reseller_own_error_corrected_timely`: got `undetermined`, expected `true`
- `cra_logic_consumer_statement_not_carried_forward`: got `false`, expected `false`
- `cra_logic_direct_furnisher_public_record_exception`: got `undetermined`, expected `true`
- `cra_logic_expedited_deletion_short_circuits_furnisher_notice`: got `false`, expected `true`

### Direct Profiled Opus

- `cra_logic_reseller_own_error_corrected_timely`: got `true`, expected `true`
- `cra_logic_consumer_statement_not_carried_forward`: got `false`, expected `false`
- `cra_logic_direct_furnisher_public_record_exception`: got `true`, expected `true`
- `cra_logic_expedited_deletion_short_circuits_furnisher_notice`: got `false`, expected `true`

### Direct Profiled Sonnet

- `cra_logic_reseller_own_error_corrected_timely`: got `true`, expected `true`
- `cra_logic_consumer_statement_not_carried_forward`: got `false`, expected `false`
- `cra_logic_direct_furnisher_public_record_exception`: got `true`, expected `true`
- `cra_logic_expedited_deletion_short_circuits_furnisher_notice`: got `true`, expected `true`

## Determination Mismatch Pattern

RuleKit total-map misses are concentrated in support determinations that should
close as satisfied or not applicable:

- `cra_consideration_satisfied`
- `cra_furnisher_notice_satisfied`
- `cra_reinvestigation_timely`
- `results_notice_satisfied`
- `furnisher_indirect_satisfied`
- `item_treatment_satisfied`

This pattern means the full atom matrix is not reliably closing branch support
facts from realistic narrative phrases such as "otherwise timely,"
"reasonable," "no branch applies," or "expedited deletion."

Direct profiled misses are different. Opus mostly misses:

- `frivolous_termination_valid`, by treating "not invoked" as satisfied;
- expedited deletion final compliance, by over-penalizing lack of furnisher
  notice/results notice.

Sonnet's only determination-level misses are the recurring
`frivolous_termination_valid` not-invoked semantics. Its final dispositions
remain correct.

## Interpretation

This suite does not support the current full-total-map design as a production
runtime strategy. It is too expensive, too slow, and less accurate on both
final disposition and determination fidelity.

The lower-model hypothesis is only partly supported:

- A lower model can perform well on direct profiled disposition for these cases.
- A lower model does not rescue the current 120-atom total-map prompt; Sonnet is
  cheaper than Opus but produces slightly worse total-map accuracy and more
  output tokens.

The better architectural direction is not "one giant atom matrix with a cheaper
model." It is likely:

- determination-sliced atom mapping rather than all 120 atoms;
- branch-scoped atoms or branch roles to prevent direct/indirect contamination;
- compact structured output, especially emitting only changed/bound/relevant
  atoms plus explicit not-applicable branch closures;
- final-disposition-first reporting, with determination and atom traces treated
  as audit fidelity rather than headline case accuracy.

## Artifact Paths

- RuleKit Opus: `audits/final_mixed_live_compare_round_001/rulekit_total_map_opus`
- RuleKit Sonnet: `audits/final_mixed_live_compare_round_001/rulekit_total_map_sonnet`
- Direct profiled: `audits/final_mixed_live_compare_round_001/direct_profiled`

# Branch Findings Mixed Round 001

Date: 2026-06-03

Purpose: test the revised hypothesis that RuleKit should ask the LLM for
branch-level policy findings, not microscopic atom matrices, and then compose
the final disposition deterministically.

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

## Architecture Tested

The branch-findings harness does not ask the LLM to decide the final
disposition directly. It asks for branch findings:

- `applicable`
- `satisfied`
- `outcome`
- `blocks_final`
- rationale and critical facts

Then the harness composes final compliance deterministically:

- if any branch has `blocks_final=true`, final is `false`;
- else if any branch has `blocks_final=undetermined`, final is `undetermined`;
- else final is `true`.

Routing is parsed separately and not treated as a substantive final blocker.

## Headline Comparison

| Approach | Model | Final disposition | Routing | Determinations | Est. cost | LLM latency |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Branch findings | Opus | 3/4 | 4/4 | 48/60 | $0.834060 | 92.94s |
| Branch findings | Sonnet | 4/4 | 4/4 | 59/60 | $0.211617 | 131.91s |
| Direct profiled | Opus | 3/4 | 4/4 | 51/60 | $1.061880 | 138.42s |
| Direct profiled | Sonnet | 4/4 | 4/4 | 56/60 | $0.344841 | 259.61s |
| Total atom map | Opus | 2/4 | 4/4 | 46/60 | $3.449670 | 514.45s |
| Total atom map | Sonnet | 1/4 | 4/4 | 44/60 | $0.870174 | 658.74s |

Branch-findings Sonnet is the best result in this round. It matches all final
dispositions and routing determinations, gets 59/60 determinations, costs less
than direct Sonnet, and is much cheaper than total atom mapping.

## Branch Sonnet Error

Branch Sonnet's only mismatch:

- `cra_logic_reseller_own_error_corrected_timely`
  - `fcra.frivolous_termination_valid`: got `true`, expected `false`

This is the same not-invoked semantics issue seen in direct prompting. It does
not affect final disposition because branch findings set non-invoked frivolous
termination as non-blocking.

## Branch Opus Error Pattern

Branch Opus performed worse because it treated many not-applicable reseller-case
branches as false rather than satisfied/not applicable:

- CRA reinvestigation trigger/required/timely;
- furnisher notice;
- direct-furnisher duties;
- indirect-furnisher duties;
- results notice;
- consumer statement;
- reinsertion.

That produced one incorrect final disposition on the reseller-own-error case.
It also left expedited-deletion results notice undetermined, producing an
undetermined final disposition.

## Interpretation

This round supports the revised hypothesis:

The LLM should operate at a coherent legal-semantic branch level, while RuleKit
should perform deterministic composition, routing separation, and trace capture.

It does not support the microscopic total-atom runtime approach. The total atom
matrix is too broad, too expensive, and too brittle. But branch-level findings
appear to preserve much of the governance benefit while avoiding the worst
representation burden.

The lower-model hypothesis also looks stronger at branch level. Sonnet did not
rescue the 120-atom map, but it performed very well on branch findings.

## Next Architectural Move

Build a first-class branch-finding contract:

- branch ids and branch roles in the DeterminationProgram;
- branch applicability and satisfaction as structured findings;
- deterministic final-composition rules;
- branch-specific appeal/repair;
- optional atom traces only for the material facts supporting each branch.

This keeps RuleKit from becoming direct adjudication, but stops forcing the LLM
below the semantic level where policy concepts remain coherent.

## Artifact Paths

- Branch findings: `audits/branch_findings_mixed_round_001`
- Direct comparison: `audits/final_mixed_live_compare_round_001/direct_profiled`
- Total-map comparison: `audits/final_mixed_live_compare_round_001/rulekit_total_map_opus`
  and `audits/final_mixed_live_compare_round_001/rulekit_total_map_sonnet`

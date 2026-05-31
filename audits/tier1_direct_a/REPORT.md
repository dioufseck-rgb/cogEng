# USCIS N-400 Tier 1 Direct-LLM Baseline

Run date: 2026-05-31

Provider/model: `anthropic:claude-opus-4-7`

Purpose: compare a reasonable direct-disposition prompt against the governed
RuleKit Map + deterministic engine run on the same Tier 1 evidence packets.

Important limitation: the Tier 1 evidence suite was designed primarily for
atom-binding evaluation. It does not provide independent ground-truth expected
outcomes for all final determinations. The comparison below is therefore
agreement with the prior RuleKit run, not independent accuracy.

## Setup

- Cases: 10
- Direct LLM calls: 10, one call per case
- Determinations per case: 8
- Compared dispositions: 80
- Reference: `audits/tier1_a/anthropic_claude-opus-4-7/dispositions.json`
- Prompt inputs: USCIS benchmark policy summary, selected determination
  descriptions, and the full case packet

Artifacts:

- Aggregate summary: `summary.json`
- Provider summary: `anthropic_claude-opus-4-7/summary.json`
- Direct dispositions: `anthropic_claude-opus-4-7/dispositions.json`
- Prompts and raw responses: `anthropic_claude-opus-4-7/prompts/`

## Cost And Latency

The run used configured pricing of `$15` input / `$75` output per million
tokens for Anthropic Opus. Token counts are estimated from character length.

| Metric | Direct LLM | Governed Map Eval |
|---|---:|---:|
| LLM calls | 10 | 200 |
| Estimated input tokens | 12,323 | 197,290 |
| Estimated output tokens | 5,442 | 30,703 |
| Estimated total tokens | 17,765 | 227,993 |
| Estimated cost | $0.592995 | $5.262075 |
| Total LLM latency | 92.34s | 748.18s |
| Average call latency | 9.23s | 3.74s |

Direct prompting is much cheaper here because it makes one large call per case,
while governed Map makes one source-inventory call plus one call per selected
atom. The governed approach buys traceable atom-level evidence and deterministic
engine execution at materially higher inference cost.

## Agreement With RuleKit Reference

| Metric | Result |
|---|---:|
| Compared dispositions | 80 |
| Agreements | 54 |
| Disagreements | 26 |
| Agreement rate | 67.5% |

Disagreement patterns:

| RuleKit outcome | Direct outcome | Count |
|---|---|---:|
| `undetermined` | `true` | 20 |
| `undetermined` | `false` | 3 |
| `false` | `undetermined` | 2 |
| `true` | `false` | 1 |

The dominant pattern is direct prompting turning RuleKit's `undetermined` into
`true`. In this specific run, that often reflects the fact that the governed
Map evaluation selected only 19 atoms. Unselected atoms were intentionally left
`not_found`, so many full determinations stayed `undetermined` even when the
case narrative was enough for a human-like direct disposition.

## Direct Outcomes

| Case | Continuous | Physical | State | English | Civics | Oath | GMC | Human Review |
|---|---|---|---|---|---|---|---|---|
| clean general track | true | true | true | true | true | true | true | false |
| travel conflict | undetermined | undetermined | undetermined | undetermined | undetermined | undetermined | undetermined | true |
| one-year absence | false | undetermined | undetermined | undetermined | undetermined | undetermined | undetermined | true |
| short physical presence | undetermined | false | undetermined | undetermined | undetermined | undetermined | undetermined | true |
| short state residence | undetermined | undetermined | false | undetermined | undetermined | undetermined | undetermined | true |
| English failed, civics passed | undetermined | undetermined | undetermined | false | true | undetermined | undetermined | true |
| disability exception approved | undetermined | undetermined | undetermined | true | true | undetermined | undetermined | true |
| oath refusal | undetermined | undetermined | undetermined | undetermined | undetermined | false | undetermined | true |
| pending charge | true | true | true | true | true | true | undetermined | true |
| missing travel dates | undetermined | undetermined | undetermined | undetermined | undetermined | undetermined | undetermined | true |

## Readout

The direct baseline behaved plausibly and often gave more case-level finality
than the partial governed Map run. That is exactly the architectural tension:
direct prompting can collapse evidence interpretation and disposition into one
cheap step, but the result is less auditable and does not explain which atom
bindings the engine consumed.

The next fairer comparison should run governed Map over the full load-bearing
atom set for these 8 determinations, not just the 19 Tier 1 target atoms. Then
the comparison will separate real reasoning disagreements from intentional
coverage gaps in the partial Map eval.

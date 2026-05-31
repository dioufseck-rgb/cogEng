# Map Governance

RuleKit Map is an evidence-to-atom binding layer. It should not adjudicate
policy conclusions such as eligibility, approval, or good moral character.
Instead, Map proposes atom bindings with an epistemic basis, then a
deterministic validator decides whether those bindings are acceptable for the
atom before the engine consumes them.

## Binding Basis

Each `AtomBindingRecord` may now carry:

- `basis`: why the value was bound
- `source_ids`: evidence sources supporting the binding
- `explanation`: short rationale for the basis
- `evidence`: quoted or summarized evidence

Supported basis values:

- `explicit_positive`
- `explicit_negative`
- `closed_world_absence`
- `open_world_absence`
- `inferred_from_record`
- `conflicting_evidence`
- `computed`
- `looked_up`
- `not_found`

The critical rule is that `false` from open-world silence is not the same as
`false` from a closed-world source. For example, a narrative that does not
mention convictions should not bind a conviction atom to `false`. An official
criminal-history check with the right scope may.

## Atom Binding Policy

Atoms can declare `binding_policy`:

```json
{
  "allowed_bases_for_false": ["closed_world_absence", "explicit_negative"],
  "required_source_types_for_false": ["criminal_history_check"],
  "open_world_absence_behavior": "undetermined",
  "conflicting_evidence_behavior": "human_review",
  "invalid_binding_behavior": "undetermined"
}
```

The validator enforces this after Map returns. Invalid bindings are sanitized
to `undetermined`, marked for human review, or treated as errors depending on
the atom policy.

## Prompt Strategy

The governed LLM Map step uses two stages:

1. Source inventory: classify sources, dates, closed-world scopes, and
   limitations.
2. Atom binding: bind one atom at a time using the source inventory, atom
   policy, case narrative, and relevant evidence.

The atom prompt explicitly instructs the model not to bind `false` from mere
open-world silence and to preserve conflicts instead of resolving them.

## Multi-Provider Harness

Run the same evidence-packet suite through multiple providers:

```powershell
rulekit-orchestrator map-eval `
  --program review_bundle/program.json `
  --cases evidence_packet_cases.json `
  --model anthropic:claude-opus-4-7 `
  --model openai:gpt-5 `
  --model gemini:gemini-2.5-pro `
  --price anthropic:claude-opus-4-7=15,75 `
  --atom-scope determination-slice `
  --batch-size 8 `
  --determination n400.selected_n400_requirements_satisfied `
  --atom n400.aggravated_felony_after_1990 `
  --out audits/map_governance_n400 `
  --json
```

The harness writes, per provider/model:

- `summary.json`
- `results.json`
- `map_records.json`
- `map_validation_reports.json`
- `dispositions.json`
- `prompts/<case>/source_inventory_prompt.txt`
- `prompts/<case>/source_inventory_raw.txt`
- `prompts/<case>/source_inventory_parsed.json`
- `prompts/<case>/atoms/<atom>.prompt.txt`
- `prompts/<case>/atoms/<atom>.raw.txt`
- `prompts/<case>/atoms/<atom>.parsed.json`

Those files are the evidence needed to compare models: valid binding rate,
invalid-binding rejection, false-from-silence failures, conflict preservation,
schema failures, and downstream disposition effects.

## Cost And Latency Tracking

Governed Map records now include per-call and per-case cost metrics:

- estimated input tokens
- estimated output tokens
- estimated total tokens
- estimated cost in USD when a `--price` entry is provided
- per-call latency
- aggregate LLM latency per case and per run

Pricing is supplied explicitly as USD per million input/output tokens:

```powershell
--price provider:model=input_usd_per_million,output_usd_per_million
```

Token counts are currently estimated from character length. They are useful for
provider/model comparisons and budget planning, but should be replaced with
exact SDK usage metadata when provider wrappers expose it consistently.

## Atom Scope And Batching

The governed Map eval can now bind more than one atom per LLM call:

```powershell
--batch-size 8
```

When explicit `--atom` values are omitted, `--atom-scope` controls coverage:

- `all`: bind every atom in the program.
- `determination-slice`: bind only atoms reachable from the selected
  determinations' DAG roots.

`determination-slice` is the preferred comparison mode for direct-LLM
baselines because it gives RuleKit coverage over the whole relevant policy
surface without binding unrelated atoms.

## Case-Packet Defaults

Evidence packets may include `structured_fields.default_bindings` or
`structured_fields.default_binding_groups`. These are audited bindings supplied
by the packet, not Python domain logic. They apply after stochastic Map when an
atom is missing, undetermined, `not_found`, or `open_world_absence`, unless the
packet explicitly sets `apply_when: "always"`.

The intended use is source-scope/default semantics: non-load-bearing scope
facts and absent review triggers can be resolved from the packet when the packet
itself establishes that they are not relevant. Defaults still pass through the
same deterministic Map validation layer before the engine consumes them.

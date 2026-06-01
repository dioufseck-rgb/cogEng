# Tomorrow Work: Co-Authored Determination Packs

Last updated: 2026-06-01

## Where We Are

The FCRA deep benchmark confirmed an important architecture point: the generic
builder/factory path, the test workflow, and the runtime engine all converge on
the same `DeterminationProgram` object.

The current FCRA artifact has:

- 120 atoms
- 169 DAG nodes
- 15 determinations
- 14 adjudication determinations
- 1 routing determination
- 24 Map profile default rules
- 165/165 structured replay matches

The DAG used in tests is not separate from the builder artifact. The direct
factory output and the workflow/test output have the same node IDs, node kinds,
determination roots, atom counts, and validation result.

This means RuleKit is close to a co-authored determination pack. The remaining
work is primarily the authoring, review, packaging, and promotion layer.

## Main Goal

Turn the current seed/factory workflow into an explicit co-authored
determination pack workflow:

```text
policy material
  -> Builder agent draft
  -> human review and edits
  -> validated DeterminationProgram
  -> Map profile
  -> benchmark cases
  -> approval record
  -> deployed runtime package
```

## Priority 1: Formalize The Pack Boundary

Define the deployable unit as a `RuleKitDeterminationPack`.

Minimum package contents:

- `program.json`
- `source_manifest.json`
- `map_profile.json` or embedded `program.metadata.extras.map_profile`
- `benchmark_cases.json`
- `validation_report.json`
- `build_report.md`
- `approval_record.json`

The pack should make it clear what the engine consumes directly and what exists
for governance, review, testing, and deployment.

## Priority 2: Builder Agent Draft Output

Add a draft contract for Builder-generated proposals.

The Builder should produce proposals for:

- atoms
- typed nodes
- determinations
- routing logic
- Map profile concepts/defaults
- source-scope rules
- benchmark cases
- expected outcomes

Each proposed item should carry:

- source span
- rationale
- confidence
- risk level
- reviewer status
- tests that exercise it

## Priority 3: Map Profile v2

Move from keyword/default rules toward concept-aware profile rules.

Needed concepts include:

- case shape
- actor path
- source inventory
- closed-world scope
- non-applicable branches
- routing triggers
- implied facts
- adversarial/confounding cues

The profile should support hard rules, soft rules, and LLM-classified concepts.
Every profile-applied binding must remain visible in the trace.

## Priority 4: UI Review Workflow

The Builder UI should make the pack reviewable without requiring YAML editing.

Near-term UI surfaces:

- DAG view by determination
- atom catalog with source spans
- Map profile/default review
- routing trigger review
- test case list
- case narrative and expected outcomes
- benchmark result table
- mismatch trace inspection
- natural-language reviewer hints

The first useful UI milestone is not free-form editing of everything. It is a
review surface that lets a human approve, reject, or annotate generated pack
parts.

## Priority 5: Empirical Next Runs

Run evidence that tells us whether the architecture scales.

Immediate runs:

- FCRA full 11-case narrative-only Map with profile enabled
- FCRA direct terse and governed baselines for the same 11 cases
- Anthropic, OpenAI, and Gemini comparison on the same FCRA setup
- failure direction report by determination and branch
- cost and latency report by case and call type

Next domain:

- build a realistic prior authorization determination pack
- include arithmetic thresholds, documentation requirements, exceptions,
  contraindications, appeal evidence, and human-review triggers

## Priority 6: Fix Runtime Friction

Small but important engineering tasks:

- make workflow persistence robust on nested/long Windows paths
- write incremental benchmark outputs so long LLM runs are resumable
- reduce prompt size by selecting only load-bearing unresolved atoms
- add CLI commands for pack build, pack validate, pack export, and pack run
- ensure current Map profile metadata is present in exported audit programs

## Definition Of Done For The Next Milestone

The next milestone is reached when a user can:

1. start from a policy source and a target determination list;
2. let the Builder draft a determination pack;
3. review the DAG, atoms, routing, Map profile, and test cases in the UI;
4. run benchmark cases across one or more LLM providers;
5. inspect mismatches, traces, and costs;
6. approve a versioned pack;
7. run new case packets through the same exported artifact in the CLI/runtime.


# Tomorrow Work: Co-Authored Determination Packs

Last updated: 2026-06-02

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
  -> perspective and actor role
  -> Builder agent draft
  -> human review and edits
  -> validated DeterminationProgram
  -> Map profile
  -> benchmark cases
  -> approval record
  -> deployed runtime package
```

The policy is not a single neutral object in practice. It is a
multi-perspective source. A bank, CRA, consumer, regulator, and reviewer can
read the same legal material but need different role-scoped determinations,
evidence duties, defaults, and routing triggers.

RuleKit should therefore support perspective-scoped determination packs:

```text
policy source
  -> perspective
  -> role-scoped determinations
  -> role-scoped DAG projection
  -> role-scoped Map profile and evidence duties
  -> runtime disposition
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

Perspective support is now part of the pack boundary. A single source policy
may declare several views, such as:

- bank as furnisher/direct-dispute recipient
- CRA as reinvestigation actor
- consumer as appellant/requester
- regulator as auditor/enforcement reviewer

The first implementation slice declares FCRA perspectives in policy metadata
and can project the bank/furnisher view into a smaller valid
`DeterminationProgram` without creating domain-specific Python.

## Priority 2: Builder Agent Draft Output

Add a draft contract for Builder-generated proposals.

The Builder should produce proposals for:

- perspectives and actor roles
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

- perspective selector
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

## Priority 6: Split-Based Calibration And Repair Loop

Policy packs should come with labeled calibration cases. These cases must be
used with explicit split discipline. Splits should be seeded and stratified so
the same scenario family or failure mode is not overrepresented in repair,
validation, or final holdout:

```text
X labeled cases
  -> repair slices used to discover artifact gaps
  -> rolling validation slices used to reject overfitted repairs
  -> locked final holdout used once after the artifact is frozen
```

The Builder may use LLMs to propose changes, but accepted changes must become
explicit, versioned policy-pack artifacts: DAG nodes, perspective overrides,
Map profile rules, routing semantics, atoms, and regression cases. Runtime
disposition must not silently improvise new legal branches.

Near-term command shape:

```text
rulekit-orchestrator calibration-eval \
  --program program.json \
  --cases labeled_cases.yaml \
  --out audits/policy/calibration_round_001 \
  --repair-count 20 \
  --validation-count 20 \
  --final-holdout-count 80 \
  --model anthropic:claude-opus-4-7 \
  --single-map-call \
  --repair-unresolved
```

The command should:

- create deterministic or seeded case splits;
- scramble/stratify cases by explicit `split_group` metadata when present,
  and by generic scenario labels when metadata is absent;
- tag every case as `repair`, `validation`, or `final_holdout`;
- run governed Map + engine only on allowed slices;
- optionally run direct LLM comparison on allowed slices;
- classify mismatches by direction and likely failure type;
- replay candidate artifact repairs before spending new LLM calls;
- reject repairs that regress validation cases;
- preserve the final holdout as untouched until a `--final` run;
- write `repair_report.md`, `split_manifest.json`, `candidate_patches.json`,
  `replay_before_after.json`, `regression_summary.json`, and
  `open_design_questions.md`.

This is the empirical discipline for co-authored determination packs. It also
becomes a product workflow: customers can provide labeled seed cases, iterate
with the Builder on the repair/calibration split, and receive an honest final
holdout report at pack approval time.

## Priority 7: Fix Runtime Friction

Small but important engineering tasks:

- expose perspective list/export in CLI and eventually UI
- ensure perspective projections preserve validation, routing triggers, and Map metadata
- make workflow persistence robust on nested/long Windows paths
- write incremental benchmark outputs so long LLM runs are resumable
- reduce prompt size by selecting only load-bearing unresolved atoms
- add CLI commands for pack build, pack validate, pack export, and pack run
- ensure current Map profile metadata is present in exported audit programs

## Definition Of Done For The Next Milestone

The next milestone is reached when a user can:

1. start from a policy source and a target determination list;
2. choose or define the operating perspective;
3. let the Builder draft a determination pack;
4. review the DAG, atoms, routing, Map profile, and test cases in the UI;
5. run benchmark cases across one or more LLM providers;
6. inspect mismatches, traces, and costs;
7. approve a versioned pack;
8. run new case packets through the same exported artifact in the CLI/runtime.

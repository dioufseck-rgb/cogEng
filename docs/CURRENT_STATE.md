# RuleKit Current State

Last updated: 2026-05-31

RuleKit is evolving into a governed policy-reasoning toolkit for regulated
agentic execution. Its central design commitment is that LLMs should not make
case dispositions directly. LLMs may help build policy artifacts and may bind
case evidence to typed atoms, but deterministic RuleKit artifacts should decide
the policy outcome through an auditable DAG.

## Core Architecture

The current architecture has four main layers:

1. **Build**
   Converts policy material into a `DeterminationProgram`: atoms, typed nodes,
   determinations, constants, source spans, and case expectations.

2. **Map**
   Converts a case packet into atom bindings. This is where LLMs may be used,
   but only as constrained evidence extractors. Map records each binding with
   value, status, evidence, source, confidence, and now epistemic basis.

3. **Engine**
   Evaluates the `DeterminationProgram` deterministically using Kleene logic
   and typed numeric/arithmetic nodes. The engine consumes the same artifact
   that the builder exports.

4. **Runtime / Governance**
   Runs cases through Map and the engine, emits dispositions, traces,
   Map records, validation reports, and review artifacts suitable for audit or
   appeal.

The intended deployment shape is:

```text
policy source
  -> DeterminationProgram
  -> Map contract and atom binding policies
  -> evidence packet
  -> governed Map
  -> deterministic engine
  -> traced disposition
```

## What Exists Now

### Determination Contract

The main deployable artifact is `DeterminationProgram`. It contains:

- program metadata
- atom catalog
- typed DAG nodes
- determinations
- constants
- case input schema
- optional test cases
- production record

The engine supports:

- boolean atoms
- numeric atoms
- `and`
- `or`
- `not`
- `at_least`
- numeric constants
- comparisons
- unary arithmetic
- binary arithmetic
- variadic arithmetic
- conditional numeric selection
- named quantities

This is enough to model real policy logic with both Boolean structure and
quantitative thresholds.

### Generic Builder / Orchestrator

The orchestrator can ingest generic policy seeds and produce workspaces,
candidate programs, trajectories, reports, diagnostics, dispositions, and
review bundles. Importantly, new domains should enter as policy artifacts,
not as new Python modules.

The packaged USCIS benchmark is now a JSON seed artifact, not a domain-specific
Python adapter:

```text
rulekit/orchestrator/example_seeds/uscis_n400_selected.json
```

The CLI can write it with:

```powershell
rulekit-orchestrator template uscis_n400.json --example uscis-n400 --json
```

### Runtime Runner

The runtime runner consumes exported `program.json` artifacts and case files:

```powershell
rulekit-orchestrator adjudicate `
  --program review_bundle/program.json `
  --cases runtime_cases.json `
  --determination some.determination `
  --out runtime_results `
  --json
```

It writes:

- `summary.json`
- `map_records.json`
- `map_validation_reports.json`
- `dispositions.json`
- `results.json`

### Builder UI

The Builder UI can show:

- workspace overview
- cases and results
- DAG view
- Map record summaries
- basis counts
- validation summary
- timeline
- reports
- branches
- reviewer hints and added cases

This is still a static/exported UI plus optional API server. It is useful for
inspection, but not yet a polished end-user product.

## Map Governance

The most important recent addition is evidence-aware Map governance.

The system now distinguishes the value of a binding from the reason the value
was bound. A Map binding can carry a `basis`:

- `explicit_positive`
- `explicit_negative`
- `closed_world_absence`
- `open_world_absence`
- `inferred_from_record`
- `conflicting_evidence`
- `computed`
- `looked_up`
- `not_found`

Atoms can declare `binding_policy`, including:

- allowed bases for `true`
- allowed bases for `false`
- required source types for `true`
- required source types for `false`
- behavior for open-world absence
- behavior for conflicting evidence
- behavior for invalid bindings

This matters because many regulated cases require negative facts. For example,
the case narrative may not mention an aggravated felony, but that silence does
not justify:

```text
n400.aggravated_felony_after_1990 = false
```

A false binding may require a closed-world source, such as an official criminal
history check or court clearance.

The validator sits after Map and before the engine. It can sanitize invalid
bindings to `undetermined`, mark human review, or report an error depending on
the atom policy.

## Live Multi-Provider Map Eval

A live evidence-packet eval has been added under:

```text
audits/map_governance_eval/live_n400_gmc
```

It tests selected USCIS N-400 good moral character atoms across Anthropic,
OpenAI, and Gemini. The suite focuses on:

- open-world silence
- closed-world absence
- explicit positive evidence
- conflicting evidence
- incomplete source scope

The tested atoms were:

- `n400.aggravated_felony_after_1990`
- `n400.murder_conviction`
- `n400.pending_criminal_charge`
- `n400.false_testimony_for_immigration_benefit`

Initial results:

| Provider | Status Match | Basis Match | Value Match | False-from-silence failures | Overbroad closed-world failures |
|---|---:|---:|---:|---:|---:|
| Anthropic `claude-opus-4-7` | 9/9 | 8/9 | 5/5 | 0 | 0 |
| OpenAI `gpt-5` | 9/9 | 7/9 | 5/5 | 0 | 0 |
| Gemini `gemini-2.5-pro` | 9/9 | 9/9 | 5/5 | 0 | 0 |

The encouraging finding is that all three models avoided the major failure:
none bound `false` from open-world silence.

The useful differences were in basis selection:

- OpenAI sometimes used `inferred_from_record` where Anthropic/Gemini used
  `explicit_positive`.
- Anthropic/OpenAI used `open_world_absence` for incomplete state-only source
  scope, while Gemini used `not_found`.
- OpenAI returned `status=undetermined` but `value=false` in one open-world
  silence case. The validator accepted the binding because status was
  undetermined, but this payload is internally inconsistent and should be
  normalized or flagged.

One architectural issue was exposed and has now been addressed in the runtime:

- In the conflict case, models returned `status=undetermined` with
  `basis=conflicting_evidence`.
- The governed evaluator now preserves unresolved relevant evidence when a
  false engine result is not stable, and conflict-bearing atoms can force the
  disposition back to `undetermined` instead of collapsing to false.
- `human_review_required` can now be declared as routing logic over trigger
  atoms, so missing trigger facts default to no route while conflicts/errors
  can route to review.

A broader Tier 1 USCIS eval has also been added under:

```text
audits/tier1_a
```

It exercises 10 cases and 19 atoms across residence, travel, physical
presence, state residence, English/civics, disability exceptions,
oath/attachment, good moral character, and review flags. The first live run
used Anthropic only because only `ANTHROPIC_API_KEY` was present in this
environment.

Tier 1 Anthropic results:

| Metric | Result |
|---|---:|
| Live LLM calls | 200 |
| Expected status matches | 27/29 |
| Expected value matches | 25/26 |
| Expected basis matches | 7/8 |
| Estimated total tokens | 227,993 |
| Estimated cost | $5.262075 |
| Total LLM latency | 748.18s |
| Average call latency | 3.74s |

The main finding is that broader Map quality is not failing at JSON shape or
basic evidence extraction. The misses are semantic: preserving conflicts
before computing arithmetic, treating approximate durations differently from
exact date arithmetic, and tightening `computed` versus `inferred_from_record`
basis taxonomy.

The Tier 1 ground-truth replay now shows the value of the governed runtime
layer: saved Anthropic Map records plus case defaults and routing/conflict
handling score `72/80` (`90.00%`) versus direct Anthropic's `67/80`
(`83.75%`). The remaining RuleKit misses are conservative `undetermined`
outcomes.

## Current Strengths

- The engine is deterministic and typed.
- The deployable program artifact is clear and engine-compatible.
- The runtime runner consumes the same object the builder exports.
- Numeric/arithmetic reasoning is supported by the engine, not delegated to
  LLM free-form reasoning.
- The Map layer now has the vocabulary needed for governed negative facts.
- Routing determinations can be represented in the generic contract instead
  of being encoded as ordinary adjudication determinations.
- Evidence-aware evaluation preserves traceability while preventing conflict
  cases from collapsing to unsupported false outcomes.
- The multi-provider eval harness saves prompts, raw responses, parsed
  bindings, validation reports, and dispositions.
- Initial live results support the core prompt strategy.

## Current Gaps

### Build Automation

The benchmark USCIS program is an artifact, not a domain Python module, which
is the right direction. But the fully automated build process from raw policy
text to high-quality typed DAG is still incomplete. The library can represent
the target artifacts, but the automated builder still needs stronger typed
decomposition, source coverage, review workflows, and edit ergonomics.

### Map Validation Semantics

One refinement remains:

- `status=undetermined` with concrete `value=true/false` should be normalized
  or flagged.

### Evidence Packet Model

The evidence packet shape is emerging, but still basic. We likely need a
first-class case packet schema with:

- source IDs
- source types
- source dates
- source scope
- closed-world claims
- limitations
- document text or excerpts
- structured facts
- external-check metadata

### Eval Harness Hygiene

The live report produced very long file paths for prompt artifacts. On Windows,
this caused checkout problems unless long paths are enabled. The harness should
write shorter paths or bundle prompt artifacts into JSONL files.

### UI

The UI can show the current artifacts, but it is not yet a strong interactive
builder. It still needs better workflows for:

- evidence packet inspection
- atom binding basis review
- validation failures
- natural-language reviewer hints
- re-running Map with hints
- editing atom policies and DAG nodes
- comparing provider eval results

## Near-Term Priorities

1. Tighten source-scope/default semantics:
   - extend clean-packet negative-bar defaults where official sources cover
     the relevant factual universe
   - add explicit scope facts for failed tests, oath refusal, short presence,
     and state-residence shortfall cases

2. Normalize contradictory undetermined payloads:
   - reject or normalize `status=undetermined` with concrete true/false values

3. Shorten or bundle live eval artifact paths.

4. Add a report analyzer for `map-eval` outputs:
   - model comparison table
   - failure-mode table
   - basis confusion matrix
   - raw examples for disagreements

5. Extend the evidence-packet suite:
   - more domains
   - more atom types
   - more ambiguous source-scope cases
   - reviewer-hint reruns

6. Improve Builder UI around Map governance:
   - basis and source display
   - invalid binding review
   - human-review trigger surfacing
   - provider comparison view

7. Continue toward v1 policy package:

```text
RuleKitPolicyPackage
  program: DeterminationProgram
  map_contract / atom policies
  case packet schema
  test and eval suites
  governance assumptions
  known limits
```

## Bottom Line

RuleKit is no longer just a typed rule engine. It now has the outline of a
governed policy disposition architecture:

- LLMs extract and characterize evidence.
- Map records why each atom was bound.
- Deterministic validation checks whether that binding is epistemically
  acceptable.
- The engine composes trusted atoms through a typed DAG.
- The runtime emits artifacts that can be reviewed, appealed, and compared
  across model providers.

The next hard problem is not whether the engine can evaluate a DAG. It can.
The hard problem is making Map consistently produce defensible atom bindings
from realistic evidence packets. The first live eval suggests the approach is
promising, but the validator and harness need tightening before larger
cross-domain evaluations.

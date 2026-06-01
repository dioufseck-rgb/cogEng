# RuleKit: Governed Neurosymbolic Policy Reasoning for Agentic Execution

## Abstract

Many high-stakes institutions apply written policies to individual cases:
health plans adjudicate prior authorizations, consumer reporting agencies handle
credit disputes, immigration agencies adjudicate eligibility, tax authorities
evaluate audit issues, and lenders resolve credit or compliance decisions. Large
language models can read policy text and case narratives, which makes them
tempting as direct adjudicators. But direct LLM disposition is difficult to
govern: the model may reach a plausible answer without a stable trace of which
policy requirements were satisfied, which evidence supported them, which facts
were missing, and which assumptions were made.

RuleKit proposes a different architecture. LLMs may help build policy artifacts
and may bind case evidence to declared policy atoms, but they do not make the
final policy disposition. A deterministic typed engine evaluates a versioned
policy DAG over validated case facts and emits a traced disposition. This is a
neurosymbolic design: neural models handle language-heavy interpretation and
evidence extraction, while symbolic artifacts handle logical composition,
arithmetic, propagation of uncertainty, routing, and auditability.

The current implementation demonstrates the feasibility of this architecture,
but also exposes the hardest remaining problem: governed Map. The engine can
evaluate a policy artifact reliably once facts are bound. The builder can
represent substantial policies as deployable artifacts. The open question is
whether the Map layer can bind realistic, messy case packets to policy atoms
with acceptable accuracy, cost, latency, and trace quality. Recent USCIS and
FCRA experiments show both the promise and the gap. On a deep credit-reporting
benchmark, adding policy-authored Map profile rules improved RuleKit narrative
Map accuracy from 60.00% to 86.67% on a four-case slice and surpassed direct
LLM baselines, but cost remained significantly higher than direct prompting.

This paper introduces the purpose of RuleKit, the current gaps in direct LLM
adjudication, the proposed build-run architecture, implementation details,
use cases, empirical evidence, and the near-term roadmap.

## Reader Orientation

This paper assumes no prior knowledge of RuleKit.

The core idea is that a policy should become an executable artifact before it
is used in production. That artifact should be inspectable, testable, versioned,
and deployable. A runtime agent should then apply the artifact to a case, rather
than asking an LLM to improvise the policy decision each time.

Three terms recur throughout the paper:

- **DeterminationProgram**: the policy artifact RuleKit exports and the engine
  consumes. It contains atoms, typed DAG nodes, determinations, constants,
  metadata, and optional benchmark cases.
- **Map**: the process that converts a case packet into atom bindings. Map can
  use structured data, deterministic extractors, or LLMs, but its output is a
  structured binding record rather than a final disposition.
- **Engine**: the deterministic evaluator that consumes the
  `DeterminationProgram` and Map bindings, then emits outcomes and traces.

RuleKit therefore produces two kinds of durable output:

- a **policy package** built and approved at build time;
- a **case disposition package** produced at run time, including bindings,
  validation reports, traces, and final determinations.

This distinction is the heart of the project. The policy package is meant to be
the same object used by the Builder, the tests, the CLI runner, the UI, and the
agent runtime.

## 1. Purpose

RuleKit exists to support governed agentic execution in domains where a case
must be resolved under an explicit policy and where the outcome must be
traceable.

The motivating pattern is simple:

```text
written policy + case facts -> disposition + explanation
```

Examples include:

- whether a prior authorization request should be approved, denied, or routed
  to human review;
- whether a credit-reporting dispute was handled in compliance with FCRA
  obligations;
- whether a naturalization applicant satisfies selected N-400 eligibility
  requirements;
- whether a tax audit issue is resolved, unsupported, or requires additional
  documentation;
- whether a consumer complaint, benefit claim, or regulatory filing satisfies
  a policy-defined process.

In these settings, the goal is not only to produce a correct final label. The
institution also needs to know why the label was produced. The system should be
able to show:

- which policy determinations were evaluated;
- which atomic facts were bound true, false, or undetermined;
- which evidence supported each binding;
- which bindings were invalid, conflicted, or missing;
- how Boolean, arithmetic, and routing nodes propagated those bindings;
- which facts were load-bearing for the result;
- why the case was approved, denied, undetermined, or routed to human review.

Direct LLM adjudication can sound convincing, but it does not naturally produce
this governed trace. RuleKit's purpose is to make the trace the primary product
of the system, not an afterthought.

## 2. The Gap

Direct LLM disposition has an attractive surface:

```text
Prompt: Here is the policy and the case. Decide.
Output: Approved, denied, or review required.
```

This can work surprisingly well on shallow cases. A strong model can read a
policy, identify the main issue, and produce a plausible determination. But
regulated adjudication is not just question answering. It requires governed
failure modes.

The main gaps are:

### 2.1 Traceability

A direct LLM answer usually does not expose the actual computation by which the
answer was reached. It may cite some facts and omit others. It may use a
holistic story that is hard to audit against the policy's formal structure.

For appealable decisions, this is a serious defect. A patient, consumer,
applicant, or regulator may ask:

```text
Which policy condition failed?
Which evidence was considered?
Which missing document would change the result?
Why did this case route to review instead of denial?
```

RuleKit treats these questions as runtime outputs.

### 2.2 Cross-Branch Contamination

Deep policies often have multiple actor paths, exceptions, and procedural
branches. A direct LLM may reason from the overall story and then retrofit each
determination to that story.

In the FCRA benchmark, direct LLMs frequently confused:

- CRA reinvestigation obligations;
- furnisher indirect-dispute obligations;
- furnisher direct-dispute obligations;
- reseller duties;
- reinsertion safeguards;
- consumer statement handling;
- human-review routing.

These determinations are related, but they are intentionally distinct. The
same case may fail one branch while another branch is not applicable or already
satisfied.

### 2.3 Negative Facts and Source Scope

Many policies depend on the absence of a fact:

```text
no aggravated felony
no reseller involvement
no reinsertion
no pending charge
no contraindication
no conflicting record
```

But "not mentioned" is not the same as false. A medical record, police check,
court docket, payment ledger, or agency log may support absence only within a
specific source scope. Direct LLMs are weak at maintaining this distinction
unless heavily prompted, and heavy prompting can increase cost and introduce
over-cautious `undetermined` outcomes.

RuleKit gives Map bindings an epistemic basis, such as:

```text
explicit_positive
explicit_negative
closed_world_absence
open_world_absence
inferred_from_record
conflicting_evidence
computed
looked_up
not_found
```

This lets the runtime distinguish "false because an official closed-world
source excludes it" from "false because the narrative did not mention it."

### 2.4 Arithmetic and Temporal Logic

Policies often contain thresholds, date windows, counts, or conditional numeric
logic:

- days to complete reinvestigation;
- months of physical presence;
- days absent from the United States;
- income thresholds;
- therapy duration;
- filing deadlines;
- aggregate balances or payment amounts.

Direct LLM arithmetic is brittle. RuleKit represents arithmetic as typed engine
nodes: numeric atoms, constants, comparisons, unary arithmetic, binary
arithmetic, variadic arithmetic, conditional numeric nodes, and named
quantities.

### 2.5 Governed Failure Modes

In regulated workflows, not all errors have equal cost. A system that defaults
to unsupported approvals may be institutionally dangerous even if its headline
accuracy is high. A system that fails conservatively to human review may be
less efficient but more governable.

RuleKit's design favors explicit uncertainty:

```text
missing load-bearing fact -> undetermined
conflicting load-bearing evidence -> undetermined or review
routing trigger -> human review
non-load-bearing missing fact -> should not pollute the whole determination
```

Getting these semantics right is the central engineering challenge.

## 3. Proposal

RuleKit separates policy modeling from case execution, and separates LLM work
from deterministic reasoning.

The proposal has two phases:

```text
Build time:
  policy text + declared determinations
  -> atoms + DAG + arithmetic nodes + Map profile + test suite
  -> versioned DeterminationProgram

Run time:
  case packet
  -> governed Map bindings
  -> validation
  -> deterministic engine
  -> traced disposition
```

The LLM's role is constrained:

- assist in building the policy artifact;
- assist in binding evidence to atoms;
- assist in repairing unresolved bindings when guided by engine traces.

The LLM does not own the final disposition.

The symbolic engine's role is fixed:

- evaluate the DAG;
- propagate three-valued logic;
- compute typed numeric/arithmetic nodes;
- preserve trace;
- keep routing determinations distinct from substantive adjudication.

The human expert's role is governance:

- declare determinations;
- review the generated DAG;
- approve or revise Map profile rules;
- validate benchmark cases;
- decide which defaults are safe;
- decide when human review must be triggered.

This is not a scheme where a user hand-authors a new Python module for each
domain. The target is co-authoring by a Builder agent and a domain expert:

```text
policy expert provides policy material and review judgment
builder agent drafts the artifact
expert edits/approves
RuleKit tests and exports
runtime agents consume
```

## 4. The Build-Run Model

### 4.1 Build

The build process creates a deployable policy artifact. In the current system,
that artifact is a `DeterminationProgram`. It contains:

- program metadata;
- atom catalog;
- typed DAG node registry;
- determinations;
- constants;
- routing logic;
- Map binding policies and profile rules;
- case input schema;
- optional benchmark cases;
- production metadata.

Atoms are small claims about a case:

```text
The consumer disputed an item.
The CRA completed the reinvestigation.
The number of calendar days to completion is 24.
The applicant has a pending criminal charge.
The member completed six weeks of conservative therapy.
```

Nodes compose these atoms:

```text
AND
OR
NOT
AT_LEAST
COMPARISON
CONDITIONAL_NUMERIC
ARITHMETIC
```

Determinations point to root nodes:

```text
fcra.cra_reinvestigation_timely
fcra.results_notice_satisfied
n400.good_moral_character_satisfied
prior_auth.treatment_medically_necessary
```

The Builder agent should eventually draft all of this from policy text and
declared target determinations, then ask targeted questions where the policy
requires human judgment.

### 4.2 Map

Map converts case evidence into atom bindings.

A binding is not just a value. It includes:

```text
atom_id
atom_type
value
status
basis
source_ids
evidence
explanation
confidence
metadata
```

Example:

```json
{
  "atom_id": "fcra.primary_documents_forwarded",
  "value": false,
  "status": "bound",
  "basis": "explicit_negative",
  "evidence": "The processing log says document images were not sent or made available.",
  "source_ids": ["cra_log"]
}
```

Map may use structured facts, deterministic extraction, LLM extraction, or a
hybrid. The current governed Map can use:

- prebound structured facts;
- case-level defaults;
- program-level Map profile defaults;
- LLM single-call or batched binding;
- trace-guided repair for unresolved load-bearing atoms.

### 4.3 Map Profile

The Map profile is a policy-authored layer that teaches the generic Map how to
interpret case shape.

It is not per-case YAML. It is authored once per policy version, ideally by the
Builder agent with expert review.

For FCRA, profile rules currently encode concepts such as:

- no reseller branch mentioned;
- no reinsertion branch mentioned;
- no consumer statement filed;
- direct furnisher path active;
- ordinary CRA dispute trigger;
- primary documents not forwarded;
- `not mine` as a routing cue;
- mixed-file, identity-theft, source-gap, and date-conflict cues.

The profile is used before LLM atom selection:

```text
case narrative
  -> prebound facts
  -> program map profile defaults
  -> engine sufficiency check
  -> select unresolved load-bearing atoms
  -> LLM binds selected atoms
  -> validation
  -> engine
```

This matters because real narratives rarely say:

```text
No reseller was involved.
No reinsertion occurred.
No consumer statement was filed.
```

But those absences may be needed to prevent non-applicable branches from
turning into global uncertainty.

Profiles can mislead, so they must be governed:

- versioned;
- trace-visible;
- tested against adversarial cases;
- separated into hard and soft rules;
- tied to source-scope assumptions;
- reviewed by domain experts.

The next version should move beyond keyword rules into concept extraction:

```text
tenant screening company forwarded the dispute
  -> reseller_path_active

account reappeared after deletion
  -> reinsertion_event_present

similar name/address
  -> mixed_file_risk
```

### 4.4 Validate

Map validation checks whether a binding is acceptable under the atom's binding
policy.

For example, an atom might allow:

```text
true: explicit_positive, inferred_from_record
false: closed_world_absence only
```

If an LLM binds `false` from open-world silence, validation can sanitize the
binding to `undetermined` or route to review.

### 4.5 Engine

The engine consumes the same `DeterminationProgram` the builder exports. It
evaluates the typed DAG over a fact bundle.

Boolean nodes use Kleene three-valued logic:

```text
true
false
undetermined
```

Numeric nodes carry typed numeric values and support comparisons and arithmetic.

The engine returns:

- outcome;
- trace;
- load-bearing path;
- engine latency;
- metadata;
- evidence uncertainty overrides where needed.

### 4.6 Runtime Output

The runtime writes:

- `summary.json`;
- `map_records.json`;
- `map_validation_reports.json`;
- `dispositions.json`;
- `results.json`;
- prompt artifacts for LLM Map and direct comparisons;
- review bundles for the Builder UI.

These artifacts support audit, appeal, debugging, and empirical comparison.

## 5. Neurosymbolic Promise

RuleKit is neurosymbolic in a pragmatic sense.

Neural components are used where language understanding is valuable:

- reading policy text;
- proposing atoms and decompositions;
- identifying evidence sources;
- binding narrative evidence to atoms;
- classifying case shape;
- proposing repairs from trace-guided hints.

Symbolic components are used where governance requires determinism:

- policy DAG;
- Boolean logic;
- arithmetic;
- source-scope validation;
- routing logic;
- trace generation;
- replay;
- regression tests.

This division of labor gives a path to systems that are more governable than
direct LLM agents and more adaptable than hand-coded rule engines.

The promise is not that LLMs disappear. The promise is that their outputs are
placed behind contracts:

```text
LLM output -> structured binding -> validation -> deterministic reasoning
```

That makes LLM errors visible, local, repairable, and testable.

## 6. Architecture

The current architecture has four main layers.

### 6.1 Builder

The Builder produces policy artifacts.

Current state:

- generic policy seeds can produce `DeterminationProgram` artifacts;
- USCIS and FCRA examples are artifact-based, not domain Python;
- typed nodes support Boolean, numeric, arithmetic, and routing logic;
- the CLI exports review bundles and static UI assets.

Target state:

- Builder agent co-authors policy artifacts from raw policy text;
- human reviewers approve determinations, DAG, Map profile, routing, and tests;
- the UI supports interactive graph inspection, edits, hints, benchmark runs,
  and provider comparisons.

### 6.2 Map

Map binds cases to atoms.

Current state:

- prebound structured facts;
- governed LLM evidence Map;
- basis-aware binding records;
- source-scope validation;
- single-call and batched modes;
- trace-guided repair;
- program-level Map profile defaults.

Target state:

- cheap case-shape classifier;
- concept-based profile rules;
- source inventory with closed-world scopes;
- sufficiency-aware incremental binding;
- durable resumable runs;
- lower cost and latency.

### 6.3 Engine

The engine evaluates.

Current state:

- deterministic typed engine;
- Kleene logic;
- arithmetic and comparisons;
- conditional numeric nodes;
- routing determinations;
- load-bearing traces;
- safe runtime boundary.

Target state:

- stronger counterfactual explanation;
- margin analysis;
- richer trace visualization;
- deployment adapters for agent orchestration frameworks.

### 6.4 Runtime and Governance

Runtime packages the outputs.

Current state:

- CLI runner;
- exported `program.json`;
- runtime case files;
- dispositions and traces;
- Map validation reports;
- direct LLM comparison harness;
- multi-provider evaluation harness;
- static Builder UI.

Target state:

- production API;
- versioned policy packages;
- case packet schema;
- reviewer workflow;
- appeal packet generation;
- monitoring of model drift and profile failure modes.

## 7. Implementation

Important implementation elements include:

- `rulekit.contract`: the `DeterminationProgram` contract and typed node
  schemas.
- `rulekit.engine`: deterministic Boolean and typed evaluation.
- `rulekit.orchestrator`: builder workflows, cases, Map steps, reports,
  review bundles, CLI, and UI export.
- `rulekit.orchestrator.governed_map`: evidence-aware LLM Map with profile
  defaults and repair.
- `rulekit.runtime`: exported program runner used by agent runtimes.
- `rulekit.orchestrator.example_seeds`: artifact-style example policies,
  including USCIS N-400 and FCRA credit reporting.

The most recent implementation work added generic Map profiles:

```text
program.metadata.extras.map_profile.default_rules
```

The runtime now:

1. applies prebound facts;
2. applies program Map profile defaults;
3. evaluates the profile-enriched partial bundle;
4. selects unresolved load-bearing atoms;
5. invokes LLM Map only for selected atoms;
6. validates the resulting bindings;
7. evaluates the engine.

Two practical bugs were fixed during the FCRA run:

- profile defaults were previously applied but atom selection still used the
  pre-profile record, allowing the LLM to overwrite profile-resolved atoms;
- numeric atoms could crash conversion if the LLM returned a Boolean payload;
  those are now hardened to `undetermined`.

## 8. Use Cases

### 8.1 Prior Authorization

A health plan receives a request for a treatment. The policy describes
indications, contraindications, prior interventions, documentation
requirements, step therapy exceptions, and human-review triggers. RuleKit can
model:

- medical necessity criteria;
- conservative therapy duration;
- diagnosis confirmation;
- failed prior interventions;
- imaging or lab thresholds;
- contraindications;
- appeal evidence;
- review routing.

### 8.2 USCIS Naturalization Eligibility

An N-400 packet includes residence history, travel history, test results,
criminal history, oath/attachment facts, and good moral character evidence.
RuleKit can model:

- continuous residence;
- physical presence;
- state residence;
- English/civics;
- disability exceptions;
- oath attachment;
- good moral character;
- human-review triggers.

### 8.3 Credit Reporting Disputes

An FCRA dispute may involve a CRA, furnisher, direct furnisher dispute,
reseller, reinsertion, consumer statement, source conflicts, or identity-theft
claims. RuleKit can model:

- dispute trigger validity;
- reinvestigation timeliness;
- furnisher notice;
- forwarding of relevant information;
- consideration of primary evidence;
- correction/deletion duties;
- results notice contents;
- reinsertion certification;
- furnisher duties;
- direct-dispute duties;
- reseller duties;
- human-review routing.

### 8.4 Tax Audits

A taxpayer's case may involve deadlines, document sufficiency, income
categories, deductions, credits, exceptions, burdens of proof, and audit
escalation triggers. RuleKit can model:

- threshold calculations;
- documentary support;
- time windows;
- missing or conflicting records;
- issue-specific determinations;
- review routing.

### 8.5 Agentic Policy Runtime

In an agent system, RuleKit can serve as the policy reasoning component:

```text
agent receives case
agent gathers evidence
RuleKit Map binds evidence
RuleKit engine emits disposition and trace
agent communicates, requests missing evidence, or routes review
```

This keeps the agent from making direct, ungoverned adjudications.

## 9. Empirical Evidence

The empirical evidence so far is preliminary but useful. It shows where
RuleKit works, where direct LLMs fail, and where RuleKit's Map remains costly.
The results should be read as engineering evidence from synthetic benchmarks,
not as production validation. The most important findings are about failure
shape, branch handling, source-scope semantics, traceability, and cost.

### 9.1 USCIS N-400 Tier 1

The USCIS Tier 1 benchmark has 10 synthetic case packets and 8 determinations,
for 80 dispositions.

Ground-truth replay:

| System | Compared | Matches | Mismatches | Accuracy |
|---|---:|---:|---:|---:|
| RuleKit expanded batched | 80 | 61 | 19 | 76.25% |
| RuleKit with case defaults | 80 | 80 | 0 | 100.00% |
| Direct Anthropic terse | 80 | 67 | 13 | 83.75% |

The initial RuleKit errors exposed missing source-scope/default semantics. After
adding scoped packet binding directives, evidence-aware routing, and conflict
handling, deterministic replay reached 80/80.

A stronger governed direct prompt later reached 75/80, or 93.75%, but the
remaining errors were mostly over-routing substantive failures into human
review. This showed that prompt discipline can improve direct LLMs on shallow
benchmarks, but it does not remove the need for explicit routing semantics.

Key lesson:

```text
On shallow cases, direct LLMs can be competitive.
RuleKit's advantage should be tested on policy depth, branch scope, arithmetic,
conflict handling, and traceability.
```

### 9.2 FCRA Credit Reporting Deep Benchmark: Structured Replay

The FCRA deep benchmark contains:

```text
120 atoms
169 nodes
15 determinations
11 cases
165 dispositions
```

Structured replay results:

| System | Cases | Dispositions | Matches | Mismatches | Agreement |
|---|---:|---:|---:|---:|---:|
| RuleKit exported runtime | 11 | 165 | 165 | 0 | 100.00% |
| Direct Anthropic terse | 11 | 165 | 147 | 18 | 89.09% |
| Direct Anthropic governed | 11 | 165 | 134 | 31 | 81.21% |

This replay used structured facts/defaults in the case packets. It proves the
DAG and engine artifact are coherent, but it does not prove that Map can bind
facts from raw narrative.

The direct LLM failure pattern was revealing:

- applicability/scope confusion;
- treating "not invoked" as "satisfied";
- cross-branch contamination between CRA, furnisher, direct furnisher, reseller,
  reinsertion, and consumer statement branches;
- collapsing distinct determinations into one holistic compliance story.

### 9.3 FCRA Narrative-Only Slice

To test the actual Map problem, structured gold facts/defaults were removed
from four FCRA cases. The four-case slice includes:

- clean verified dispute;
- missing forwarded bank statement/settlement evidence;
- direct furnisher dispute not corrected to CRAs;
- mixed-file/identity-theft ambiguity.

Initial narrative-only results:

| System | Cases | Dispositions | Matches | Agreement | LLM calls | Latency | Cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| RuleKit single-call Map + repair | 4 | 60 | 36 | 60.00% | 8 | 583.65s | $5.03748 |
| Direct Anthropic governed | 4 | 60 | 33 | 55.00% | 4 | 150.85s | $0.900435 |
| Direct Anthropic terse | 4 | 60 | 44 | 73.33% | 4 | 64.58s | $0.441285 |

This was a bad result for current Map. The generic Map was too broad, too
expensive, and overproduced `undetermined`.

After adding generic program-level Map profiles and FCRA-specific profile
rules:

| Run | Matches | Agreement | Selected atoms | LLM calls | Latency | Cost |
|---|---:|---:|---:|---:|---:|---:|
| No profile | 36/60 | 60.00% | 90 | 8 | 583.65s | $5.03748 |
| Profile pass 1 | 47/60 | 78.33% | 52 | 7 | 394.19s | $3.25542 |
| Profile pass 2 | 52/60 | 86.67% | 32 | 7 | 351.40s | $2.80767 |
| Direct Anthropic terse | 44/60 | 73.33% | n/a | 4 | 64.58s | $0.441285 |
| Direct Anthropic governed | 33/60 | 55.00% | n/a | 4 | 150.85s | $0.900435 |

The profile-enabled RuleKit pipeline now beats both direct baselines on quality
for the slice. But it remains much more expensive. The quality hypothesis is
encouraging; the cost and latency story is not yet production-ready.

### 9.4 Interpretation

The evidence supports a nuanced claim:

1. Direct LLMs can perform well on shallow cases and can improve with stronger
   prompts.
2. As policy depth increases, direct LLMs struggle with branch applicability,
   actor scope, and orthogonal determinations.
3. RuleKit's deterministic DAG and engine provide real value once facts are
   bound.
4. Governed Map is the critical bottleneck.
5. Policy-authored Map profiles are a promising generic mechanism for improving
   Map accuracy and reducing atom workload.
6. The next frontier is cost: case-shape classification, concept extraction,
   sufficiency-aware binding, and resumable incremental Map.

What the evidence does not yet prove:

- that the current Map is production-ready;
- that the FCRA gains hold across the full 11-case narrative-only benchmark;
- that the profile-enabled approach holds across OpenAI, Gemini, and Anthropic
  on the deep FCRA benchmark;
- that a Builder agent can reliably co-author high-quality policy artifacts
  without expert review;
- that synthetic cases capture the noise, incompleteness, and procedural
  disorder of real institutional case files.

Those are the right next tests.

## 10. Current Gaps

### 10.1 Builder Co-Authoring

The Builder agent should draft the domain artifact, including:

- determinations;
- atoms;
- DAG nodes;
- arithmetic nodes;
- Map profile concepts;
- source-scope rules;
- routing triggers;
- benchmark cases.

The human should review and approve, not hand-author the YAML from scratch.

### 10.2 Map Profile Risk

Profiles can mislead. They can create false absence, overbroad triggers, wrong
source-scope defaults, branch masking, or policy drift. Profiles need:

- provenance;
- risk levels;
- hard/soft rule distinctions;
- test coverage;
- trace visibility;
- review workflows.

### 10.3 Concept Extraction

Keyword rules are brittle. Many facts are implied rather than named:

```text
tenant screening company -> reseller path
account reappeared -> reinsertion
similar name/address -> mixed-file risk
bank dispute department -> direct furnisher path
```

The next Map profile should define concepts, cues, and LLM classification
instructions rather than simple keyword defaults.

### 10.4 Cost and Latency

The improved FCRA Map slice still cost about $2.81 for four cases and took
about 351 seconds. That is not acceptable for production at scale.

The likely fix is:

```text
cheap case-shape/routing pass
  -> profile/default application
  -> engine sufficiency check
  -> bind only unresolved load-bearing atoms
  -> repair only decisive conflicts
```

### 10.5 Evidence Packet Schema

Production needs a first-class evidence packet schema:

- sources;
- source types;
- dates;
- closed-world scopes;
- limitations;
- excerpts;
- structured fields;
- document attachments;
- source provenance.

### 10.6 UI and Review Workflow

The UI can inspect artifacts, but the Builder should become an interactive
policy workbench:

- graph editing;
- atom review;
- Map profile review;
- source-scope validation;
- benchmark replay;
- provider comparison;
- natural-language reviewer hints;
- branch and version management.

### 10.7 Full Cross-Provider Evidence

USCIS good moral character has multi-provider Map evidence. FCRA deep does not
yet have full cross-provider narrative Map evidence. Running OpenAI and Gemini
through the same FCRA profile-enabled pipeline is a necessary next step.

## 11. Roadmap

Near-term:

1. Split FCRA artifacts into policy package and benchmark suite.
2. Add Map Profile v2 with concept extraction.
3. Add case-shape classification before atom binding.
4. Make Map evaluation resumable and write per-case results incrementally.
5. Reduce prompt size by binding only selected determinations and load-bearing
   atoms.
6. Run FCRA profile-enabled narrative Map across the full 11-case suite.
7. Run Anthropic, OpenAI, and Gemini on the same benchmark.
8. Add UI review for Map profile rules and profile-applied bindings.

Medium-term:

1. Build prior authorization as a second deep domain.
2. Add appeal packet workflows.
3. Add counterfactual/missing-evidence explanations.
4. Add deployment adapters for agent frameworks.
5. Package `RuleKitPolicyPackage` as the versioned deployable unit.

Long-term:

1. Evaluate across regulated domains.
2. Measure false-positive approval rates, conservative review rates, cost, and
   trace quality.
3. Develop governance methodology for profile rule approval.
4. Publish the architecture and empirical evidence as a neurosymbolic policy
   reasoning framework.

## 12. Conclusion

RuleKit is an attempt to make agentic policy execution governable.

The thesis is not that LLMs should be removed from policy reasoning. The thesis
is that LLMs should be placed where their language ability is useful and bounded
by symbolic contracts where institutional reliability is required.

The architecture is:

```text
LLM-assisted build
  -> versioned policy DAG
  -> governed Map
  -> validation
  -> deterministic typed engine
  -> traced disposition
```

The empirical evidence is early but instructive. On shallow USCIS cases, direct
LLMs can be competitive. On deeper FCRA cases, direct LLMs struggle with
applicability and branch scope. RuleKit's DAG and engine preserve the policy
structure, and profile-enabled Map can surpass direct baselines on quality. But
Map cost and latency remain too high.

The next decisive work is therefore not the engine. The engine is already doing
what it should. The decisive work is the Builder and Map layer: co-authoring
policy artifacts, extracting case shape, applying governed source-scope
defaults, and binding only the facts that matter.

If that work succeeds, RuleKit can become the policy reasoning component inside
agentic systems: not a model that opines about regulated cases, but a governed
runtime that applies policies, preserves uncertainty, routes review, and emits
appealable traces.

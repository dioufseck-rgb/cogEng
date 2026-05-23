# Session Handoff — RuleKit Builder Design

**Date:** 2026-05-21
**Purpose:** Capture the design conversation so you can pick up tomorrow without re-reading the chat.

---

## What this session did

You opened with "we are designing the llm enabled algorithm to build the tree."
We sketched, then stress-tested the sketch against three substantively
different policies (PA medical-necessity, UN Security Council Rule 33,
49 USC 21103 FRA hours-of-service). The stress-tests forced refinements.
Late in the session the architecture converged on something cleaner than
what we started with and tied to a philosophical position about
institutional reasoning.

The tiny-library positioning is not betrayed. It is sharpened. Several
of the new concepts make explicit what is *outside* RuleKit's scope.
RuleKit gets smaller and clearer.

---

## The architecture, as it stands now

Four stages. Two corpus-specific (project-team-authored). Two
corpus-general (RuleKit territory).

```
raw inputs
   |
   v
EXTRACT  ----------------> structured facts with evidence
   |                       (each fact attributed to its source)
   v
MAP      ----------------> fact bundle (categorical claims + underlying quantities)
   |                       against the SCHEMA (the policy's abstract vocabulary)
   v
DERIVE   ----------------> determination + reasoning trace
   |                       (tree evaluation, monotonic over abstractions)
   v
REALIZE  ----------------> operative output for this case
                           (margins, binding constraints, actionable parameters)
```

**Extract** — pull structured facts from raw inputs. Each fact is
atomic, attributed to its source, carries evidence. Pattern is general;
implementation varies by input type (clinical notes vs duty logs vs
meeting minutes).

**Map** — apply the policy's morphism to project particulars into the
schema's abstract vocabulary. This is where the policy's operational
ontology lives. Schema fields declare their evaluation mode (computed
by code, characterized by LLM substrate, or looked up); the map
implementation routes per field. The project team owns the schema
design and the per-field specifications. The many-to-one collapse
from particulars to abstract categories happens here.

**Derive** — reason over the fact bundle using the tree. Pure logical
composition over named abstract categories. This is RuleKit's core.
Monotonic: composition can only generalize, never reintroduce concrete
content.

**Realize** — project the determination back to operational specifics
for the case. Computes margins, identifies binding constraints,
produces actionable parameters. Hand-crafted by project team.
Deterministic. Operates on the determination plus the original
quantitative state.

The **schema** sits between map and derive as the contract. It is the
policy's abstract vocabulary, authored from the policy. Both map and
derive reference it. It is the most reusable artifact in the system —
shareable across implementations, the natural unit of cross-institutional
operationalization.

---

## The monotonicity claim (load-bearing)

You stated it in this session. It is the structural principle that ties
everything together:

> All leaves must be mapped. A downstream node can only get more general
> than what logically precedes it.

What this commits to:

- Every leaf in the tree is a categorical claim against a schema field.
- Every schema field is produced by the morphism (map stage).
- Composition over leaves can only produce more general claims, never
  more specific ones.
- No tree node may reference concrete content not already exposed by
  its descendants.
- Concrete-to-abstract happens *once*, at the morphism. Abstract-to-
  more-abstract happens at every composition node in the tree.

What this buys:

- The tree cannot contain hidden domain knowledge.
- The tree cannot drift in the way LLMs typically drift (smuggling
  concrete content into compositions has nowhere to go).
- The tree can be verified by structural inspection alone — walk the
  tree, check every node's content traces to its descendants' leaves,
  which trace to schema fields, which trace to morphism outputs.
- The schema becomes the explicit categorical vocabulary, and tree-
  building can't go beyond what the schema exposes. Pressure between
  tree-building and schema-building is bidirectional and co-iterative.

The six original design principles (faithfulness, decomposition,
partition-where-declared, surface-all-that-is-true, inference-flagged,
engine-stateless) all flow from or are reinforced by the monotonicity
claim. The architecture has a single load-bearing structural
commitment that explains why the rest works.

---

## The clearest statement of the architecture's load distribution

You stated this at the end of the session and it's the sharpest
formulation we reached:

> If all nodes are Boolean or three-valued logic, determinations are
> just logical evaluations. The interpretive complexity goes to the
> map primitive which takes the provided facts and maps them to the
> truth values.

This is a stronger claim than the monotonicity principle. Monotonicity
constrains the *flow* of abstraction through the tree. This constrains
the *content* of the tree absolutely:

- The tree contains only Boolean or three-valued logical content.
  Leaves carry propositions that evaluate to true / false /
  undetermined. Internal nodes carry Boolean operators (AND, OR, NOT).
- Determinations are pure logical evaluation over the tree's structure
  given the leaf values. No judgment, no categorization, no
  interpretation happens at evaluation time.
- All interpretive complexity lives in map. Every judgment call, every
  categorization, every assessment of whether a particular satisfies
  an abstract criterion is map's responsibility.

**Three-valued logic handles uncertainty cleanly.** The engine's
default logic is Kleene three-valued (true / false / undetermined),
chosen because it respects what is actually known. Truth tables:

- AND of (true, undetermined) → undetermined
- AND of (false, undetermined) → false (false dominates)
- OR of (true, undetermined) → true (true dominates)
- OR of (false, undetermined) → undetermined
- NOT of undetermined → undetermined

Determinations resolve to yes, no, or "cannot be determined from
available evidence." The third case is operationally crucial because
it tells the agent to escalate rather than commit to a wrong answer.

The logic is a parameter (see below) — Kleene is the default but
alternatives are available for domains with different semantics.

**The architectural symmetry this creates.**

Map is the cognitively heavy stage. Derive is the cognitively light
stage. They are inverse in difficulty and complementary in role.

- *Map* is where LLM substrate earns its keep. Bounded input, bounded
  output, single transformation per field. Each leaf-relevant schema
  field corresponds to one map operation: characterize this particular
  against this criterion, produce true / false / undetermined with
  evidence.
- *Derive* is pure logic. Deterministic given the leaf values. No
  model invocation, no stochasticity, no interpretation. Runs in
  microseconds. Verifiable by formal methods. Produces exact audit
  trails showing which leaves fired and how operators composed them.

**The audit story becomes two layers.**

- *Interpretive layer* — what map produced for each leaf, with
  evidence and confidence. Where judgment lives. Reviewed by people
  who understand the policy's categorical commitments.
- *Logical layer* — how the tree composed leaf values into the
  determination. Where logic lives. Reviewed by people who understand
  the policy's compositional structure.

Different reviewers can specialize in different layers. The
specialization respects how institutional expertise actually divides.

**What this sharpens about RuleKit's scope.**

The library is *just* the logical reasoning engine with structural
validation. Tree representation, evaluation engine, substrate adapter
contract, tree-building methodology, validation regimes. Nothing
interpretive lives in the library. Map implementations, schema
content, substrate prompts, value-space declarations — all per-policy,
all project-team-authored.

This is the tightest possible scope while still being useful: "we
provide the logical reasoning over policy structure; you provide the
judgments that ground it." Clean division of responsibility, clean
value proposition.

**Connection to the philosophical core.**

The categorical-collapse insight has its sharpest operational form
here. The map primitive is *exactly* the operation that performs the
collapse, with truth-valued labels as its output. "The sinner is the
killer or the thief or the adulterer" is map producing true for one
of those categorical propositions against a particular case. The tree
then reasons over the categorical labels using pure logic.

The architecture isolates the collapse-to-categories work in a named,
auditable, institutionally-attributable stage (map) while keeping the
downstream reasoning purely logical and structurally transparent. The
two operations don't mix. Where institutional vocabulary requires
judgment, the judgment is visible. Where institutional vocabulary
licenses logical inference, the inference is mechanical.

**The logic is a parameter; Kleene three-valued is the default.**

The engine evaluates trees under a configurable logic. Different
domains may want different logics:

- *Kleene three-valued* (default) — true / false / undetermined. The
  right choice for institutional adjudication where insufficient
  evidence should produce abstention rather than commitment.
- *Classical two-valued* — true / false. Available for domains where
  every proposition is decidable from the fact bundle by construction.
  Simpler audit, simpler reconstruction, but doesn't handle missing
  evidence gracefully.
- *Łukasiewicz three-valued* — alternative three-valued logic with
  different truth tables (specifically, NOT and the implication
  behavior differ from Kleene). Available for domains where the
  Kleene treatment of undetermined doesn't fit the institutional
  semantics.
- *Other logics* — paraconsistent (for explicitly contradictory
  policies), intuitionistic (for constructive-evidence requirements),
  and others can be plugged in if a domain demands them.

The logic determines the truth tables the engine applies during
evaluation. It does not affect the tree's structural commitments —
monotonicity, leaf-grounding-in-schema, no-concrete-content-in-
compositions all hold regardless of which logic is selected. The
logic is purely the evaluation semantics.

The default is Kleene because most target domains (PA, FRA, credit
card disputes, UNSC procedure) are evidence-bounded institutional
adjudication where insufficient-evidence cases should escalate rather
than default. Adopters can override per policy if their domain requires
different evaluation semantics.

**Implications for the audit story and the substrate.**

The audit layer needs to know which logic is in force so it can show
correct truth-table application in the reasoning trace. The substrate
adapter needs to produce truth values in the value space the selected
logic uses (binary for classical, ternary for Kleene/Łukasiewicz, etc).
The schema's field type declarations have to be consistent with the
logic — a Kleene-evaluated tree needs schema fields that can produce
"undetermined"; a classical tree's schema fields produce only true or
false.

The logic choice is therefore a per-tree configuration that ripples
through validation, substrate output type, and audit rendering. Not
something an adopter changes casually after tree-building begins, but
something they choose deliberately at architecture time.

---

## The philosophical position

The architecture operationalizes a particular intellectual position
about what institutional reasoning requires.

**Finite reasoning requires categorical collapse.** Particulars are
infinite; finite minds cannot reason over them; we have to map them to
a finite vocabulary of categories before judgment can occur. The
sinner is the killer or the thief or the adulterer because without
that collapse no judgment can be rendered. The morphism (map) is the
cognitive operation that makes ethical and institutional life possible
at all.

**Categories are institutional choices, not natural facts.** Policy
authors decide what abstractions to operate on. The schema is *what
the institution has committed to reason about*. The morphism
implements that commitment. The tree reasons over it. The system is
structured around the recognition that institutional reasoning *is*
the projection of particulars onto chosen categories followed by
composition over those categories.

**Reasoning must return to particulars to be operative.** A categorical
determination doesn't act on the world. For the abstract conclusion to
become operative guidance — what the dispatcher follows, what the
surgeon schedules around, what the Council acts on — the categorical
conclusion has to be reprojected onto the particulars it applies to.
Realize is this return. Without it the determination is abstract;
with it the determination becomes guidance to the actor.

**The architecture's structural commitments are conditions for the
morphism to be legitimate.** A morphism that secretly invents
categories the institution didn't choose is illegitimate. A morphism
that collapses particulars onto categories more aggressively than the
institution authorized is illegitimate. The monotonicity claim, the
reasonable-reader discipline, the latent-composition flagging — these
serve to keep the morphism honest about what it's doing.

**This is the through-line of your research program.** Habermas's
validity-claim typology surfaces categorical commitments at the
speech-act level. Toulmin's warrant surfaces the implicit categorical
bridge from data to claim. Cognitive Core's typed primitives
operationalize categorical reasoning steps. ParDeS makes the
categorical structure of multi-actor discourse explicit. The unifying
move across all of these is *exposing the categorical structure that
informal reasoning hides*. The tree-building architecture is another
instance of the same move.

RuleKit isn't a policy automation library. It is an instrument for
making institutional categorical reasoning explicit, with technical
commitments that flow from a particular philosophical position about
what institutional reasoning requires.

---

## RuleKit's scope, revised

This is sharper after this session.

**Inside RuleKit:**

- The `derive` engine.
- The `extract` primitive (general pattern, with optional helpers per
  substrate).
- The substrate adapter (characterize_fn) that handles LLM-typed
  fields uniformly across stages.
- The tree-building methodology and (eventually) tooling.
- The schema specification format.
- Validation regimes for trees (case banks, propositional tests,
  lossless reconstruction).

**Outside RuleKit (project-team territory):**

- The schema *content* for any given policy (authored from policy by
  the team; RuleKit provides the format, not the content). This is
  the load-bearing artifact — carving reality at the right joints is
  what makes the rest tractable.
- The `map` stage's per-field specifications. Schema fields declare
  their evaluation mode:
  - *Computed* — deterministic code (aggregation, arithmetic,
    deterministic categorization).
  - *Characterized* — LLM substrate (judgment-heavy categorization,
    same pattern as derive's leaves).
  - *Looked up* — table reference or external service call.

  RuleKit's substrate-adapter infrastructure handles characterized
  fields uniformly across map and derive. Project team writes the
  code for computed fields, the prompts and validation cases for
  characterized fields, and the lookup specifications.
- The `realize` stage. Takes the determination plus the full bundle
  and produces case-specific operational guidance with binding
  constraints and margins. Same per-field typing applies — most
  computations are deterministic but some margins might require
  substrate characterization.
- The extract implementation for the specific input sources the team
  ingests (clinical notes, duty logs, dispute submissions, etc.).

---

## The architectural discipline around LLM use

A principle you articulated at the very end of the session:

> LLMs fail when we are lazy. If we think carefully and architect the
> work properly, their randomness is not allowed to compound.

This reframes the role of LLMs across the architecture. The failure
mode isn't stochasticity per se — it's *unconstrained* LLM work where
randomness has room to compound across steps. Tight type contracts,
clear schemas, and well-defined transformation boundaries prevent
compounding.

Where this shows up across stages:

**Extract** operates on raw input but produces a typed output (facts
with attributed evidence). The LLM's job is bounded by the output
type.

**Map** operates on typed input (extract's output) and produces typed
output (the populated schema). Per-field evaluation modes (computed
/ characterized / looked up) further constrain each field's LLM work
to a single typed transformation. Characterized fields don't generate
freely; they pick from a typed value space declared by the schema
field.

**Derive** operates on the typed fact bundle. The substrate
characterizes individual leaves against the bundle. Each leaf is a
single Boolean characterization with the proposition explicitly stated
and the bundle's relevant fields available as context. No
free-generation; only structured judgment.

**Realize** operates on the determination plus the bundle and produces
typed operational output (margins, binding constraints, actionable
parameters). The output type is fixed; the LLM (if used) fills in
typed slots.

The common pattern: every LLM invocation in the system has bounded
input, bounded output, and a single transformation responsibility.
The carving of reality at the right joints — schema design — is what
makes this possible. Lazy architecture (vague prompts, unbounded
generation, multi-step LLM chains without intermediate type contracts)
is what would let randomness compound.

**Why this preserves the tiny-library concept:**

RuleKit owns the typed-stage architecture and the substrate-adapter
infrastructure that makes disciplined LLM use possible. It explicitly
does not own the per-field specifications, the schema content, or the
domain-specific implementations of any stage. The architecture is
parametric over the domain-specific content while keeping the
reasoning core simple and uniform. Adopters get a tool where LLM
capabilities are leveraged across map and derive without the failure
modes that unconstrained LLM systems exhibit — the discipline is built
into the architecture rather than left to the adopter to enforce.

The library got conceptually richer in this session (map's typed-field
evaluation modes, the realize stage, the substrate adapter's extended
reach) but its actual code surface stays small. What grew was the
*precision* of the architecture's commitments, not the *quantity* of
what the library has to implement.

---

## The five-category content taxonomy (refined this session)

For tree content, after PA stress-tests:

- **Transcribed content** — directly from the policy, source-attributed,
  mechanically verifiable. Has sub-types:
  - *Assertional* (a proposition).
  - *Structural-override* (a modification on an earlier composition,
    like the myelopathy exception).
  - *Inference-suppressing* (transcribed content whose function is to
    block an inference the structure would otherwise invite, like
    "Pharmacotherapy requirement remains in full").
- **Latent compositional content** — structure the policy implies but
  does not state. Comes in types (scope, binding, edge-case, meta-
  interpretation). Carries confidence gradation. The receptor for
  interpretation artifacts. The "missing glue."
- **Interpretation artifacts** — institutional authority's resolution
  of ambiguity, override of clear text, or supplementation. Carry
  provenance metadata (who, when, under what authority, with what
  scope). Three relationship types: resolution, override, supplementation.
- **Metadata** — content about the policy as artifact, not part of the
  decision structure (preamble, effective date, severability, statutory
  authority, cross-references).
- **Orphan nodes** — propositional content with truth value but not
  currently composed into decisions (definitions, scope conditions
  stated but not used). First-class nodes available for future
  composition.

**Ambiguity is an orthogonal axis**, not a separate category. Any
content type can be ambiguously specified. Types of ambiguity from the
PA work: definitional, drafting, authority, temporal, external-
reference. Each maps to a different resolution authority.

---

## The reasonable-reader discipline

You caught me reading like a logician and producing false positives
("find all ambiguities"). The corrective is structural, not just
calibration:

The builder is not auditing the policy for completeness against an
idealized standard. The builder is doing what a reasonable institutional
reader does when applying the policy to cases: noticing the places
where the policy doesn't tell them what they need to know to apply it.

Ambiguities become visible through *use*, not through enumeration. The
right prompt frame is operational: "you're an experienced reviewer
applying this policy to a case; as you read, note where you would need
a judgment call the policy doesn't directly support, and where a
colleague might reasonably make a different call." Never "find all X."

Every builder stage prompt should be in the voice of the institutional
reader who will use the artifact, not the verifier who will audit it.
Verification is a separate downstream function.

This is corpus-specific. The reasonable reader of PA policy is a plan
medical director. Of UNSC rules, a procedural diplomat with knowledge
of the Repertoire. Of FRA rules, a crew dispatcher. Different reading
dispositions, different background knowledge, different interpretive
defaults. The builder configuration includes which reasonable-reader
voice to adopt.

---

## The cascading-negations insight

A move you surfaced when working through UNSC Rule 33. What looked like
a new operator demand (precedence/ordering) turned out to reduce to
Boolean composition through tree depth and negation:

```
precedence list (1, 2, 3, ...) reduces to:
  (motion-1)
  OR (NOT motion-1 AND motion-2)
  OR (NOT motion-1 AND NOT motion-2 AND motion-3)
  OR ...
```

The Boolean operator vocabulary plus structural depth expresses richer
relations than it first appears. The engine doesn't need new operators
for partial orders, total orders, mutual exclusion, cardinality
quantifiers — these reduce to Boolean compositions over tree depth.

The cost is that tree structure no longer visually mirrors source
structure. The reconstruction stage handles this by carrying metadata
that lets it re-render cascades as precedence lists in the paraphrase.
Structural elegance preserved at the engine; textual fidelity
preserved at reconstruction.

This generalizes the engine's reach without requiring extension.

---

## Lossless reconstruction (refined)

The principle: the tree plus operator semantics regenerates a
semantically equivalent paraphrase of the source policy, with optional
surfacing of the institution's interpretive layer.

Refinements from Test 5:

- Semantic fidelity is achievable; lexical-and-tonal fidelity requires
  more presentation-layer encoding than the tree carries by default.
- Flag surfacing is mode-dependent. Default mode produces a clean
  policy text without interpretive annotations. Audit mode produces
  the policy text with flags surfaced.
- Reconstruction validates *what the tree encodes*. It does not
  validate *whether the tree is complete*. Coverage requires the
  other direction — walking the source policy and checking each
  ground-establishing passage has tree representation.

Both directions are needed. Reconstruction is one of several
validation checks, not the whole validation story.

---

## Stress-test findings to keep

We ran five concept tests against PA (the canonical reference), with
spot-checks against UNSC and FRA:

**Test 1 (five-category classification).** Taxonomy is right but
needed sub-types and the orthogonal ambiguity axis. Real content
surfaces categories cleanly.

**Test 2 (latent compositional content).** Concept survives. Volume
is non-trivial (8 candidates from one paragraph). Comes in types.
Needs confidence gradation. Some compositions reach across documents
(cross-corpus inference is a first-class concern).

**Test 3 (ambiguity surfacing).** Concept survives but requires the
reasonable-reader discipline. Logician's enumeration produces false
positives that bury genuine ambiguities. Ambiguities cluster by type
with different resolution authorities.

**Test 4 (interpretation-artifact pathway).** Concept survives, with
an elaborated schema. Interpretation artifacts can introduce new
propositions, gate on scope conditions, and come in three relationship
types (resolution, override, supplementation). The architecture has
a baseline tree and an operative tree (baseline + active artifacts
under jurisdiction) and can produce either.

**Test 5 (lossless reconstruction).** Concept survives with the
semantic-vs-presentation distinction and mode-dependent flag surfacing.

**Cross-corpus stress-tests.** UNSC pushed us on operator vocabulary
(resolved by cascading negations). FRA pushed us on substrate model
(resolved by the map stage carrying the numerical work) and on output
type (resolved by adding realize). The architecture survived but
became more parametric over corpus type.

---

## Stress-test detail

The detail matters because the architecture's refinements came from
specific findings, and the findings should be available when you pick
up the design tomorrow. The tests were run on the PA medical-necessity
policy (Section 2 of the plan policy with the myelopathy exception
2.2(A)), with cross-checks on UN Security Council Rule 33 and 49 USC
21103 (FRA hours-of-service).

### Test 1 — Five-category classification on Section 2 of the PA plan

Went through each piece of Section 2 in order, classifying into
transcribed / latent compositional / metadata / orphan / interpretation
artifact.

The categories covered most content, but three things didn't fit
cleanly:

1. **Conditional composition modification** (the myelopathy exception).
   The exception modifies an earlier composition rather than asserting
   new propositions or implying new structure. It's neither pure
   transcription nor latent composition. Surfaced as a new sub-type
   of transcribed content: *structural-override*.

2. **Inference suppression** ("Pharmacotherapy requirement remains in
   full"). Transcribed content whose function is to *block* an
   inference the structure would otherwise invite. Has zero evaluation
   impact — doesn't add a checkable claim — but constrains the space of
   valid tree structures. Surfaced as another sub-type of transcribed
   content: *inference-suppressing*.

3. **Ambiguous transcribed content** ("PRIMARY diagnosis"). Words are
   transcribed faithfully but operational meaning is underdetermined.
   This led to the recognition that ambiguity is *orthogonal* to the
   five categories rather than being a sixth category. Any content
   type can be ambiguously specified.

Also surfaced: the relationship between Section 2 (approval criteria)
and Section 3 (exclusions) is itself latent compositional content the
policy doesn't draw. Trees authored from multi-section policies need
to handle inter-section composition explicitly.

### Test 2 — Latent compositional content detection on the myelopathy exception

Produced eight candidate latent compositions from one paragraph of
policy. With confidence judgments and types:

- **L1 — Modifier scope.** "MODIFIED" doesn't say which parts of 2.2's
  structure are preserved. The natural reading is that only the
  enumerated atoms change. *Medium-high confidence.*
- **L2 — Documentation temporal binding.** "Physician documents risk"
  doesn't say *when* the documentation must occur. *Low confidence;
  probably resolved elsewhere.*
- **L3 — "Treating physician" referent.** Surgeon? PCP? Anyone with
  treating-physician status? *Low confidence; probably definitional.*
- **L4 — Exception scope.** The exception applies to 2.2 only, not to
  2.1, 2.3, or 2.4. *High confidence; structurally required.*
- **L5 — Exception invokes 2.1(b) but doesn't waive 2.1.** *High
  confidence; structurally required.*
- **L6 — Validity period (Section 3.5) not modified.** Authorization
  granted under exception still subject to standard validity. *High
  confidence but low stakes.*
- **L7 — Compound qualification.** Case satisfying both exception and
  standard pathways — does either suffice? *Medium-high; produces
  appeals.*
- **L8 — Direction of "MODIFIED".** Always loosens, never tightens?
  *Low confidence; meta-interpretive.*

Findings:

- Volume of latent composition is non-trivial. Eight candidates from
  one paragraph. The review burden on flags is real if not triaged.
- Confidence gradation is essential. L4/L5 are structurally required;
  L8 is meta-interpretive. Equal review weight would waste attention.
- Latent compositions cluster by type: *scope* (L1, L4, L6), *binding*
  (L2, L3), *edge-case* (L7), *meta-interpretation* (L8). Almost none
  are about operator structure within propositions — the Boolean
  operators are usually explicit; the scoping is usually implicit.
- L2 and L3 reach outside the source document. The architecture has
  to handle cross-document inference as a first-class concern.
- The most operationally important latent composition (L7) is one the
  builder is least equipped to draw because it's an institutional
  policy decision, not a textual inference. This is the right kind of
  flag for the builder to produce — surfaced, flagged, reviewable.

### Test 3 — Ambiguity surfacing on the "PRIMARY diagnosis" NOTE

Identified eight ambiguities from two sentences. Critically, you
caught me reading like a logician rather than a reasonable institutional
reader. The catch was load-bearing.

Logician-mode ambiguities I would have flagged that a reasonable
reader would not:

- **A8 — Capitalization patterns.** "PRIMARY" vs. "primary" as a
  defined-term signal? No reasonable reader would treat this as
  semantically loaded without external evidence.
- **A2 — "Primary diagnosis" vs. "primary complaint".** Different
  concepts or rhetorical variation? A careful reader sees the obvious
  rhetorical structure and treats them as the same.
- **A5 / A7 — Temporal/sequencing ambiguity.** A reasonable reader
  applies charitable interpretation and uses institutional defaults
  rather than flagging silent procedural details.

Reasonable-reader ambiguities that survive:

- **A1 — Operational meaning of "PRIMARY diagnosis".** Multiple
  plausible readings (ICD-10 position, severity, proximate cause for
  surgery, physician designation) that produce divergent outcomes on
  realistic cases. *Genuine.*
- **A4 — Authority over the primary-diagnosis determination.**
  Treating physician decides, plan reviewer decides, or external
  standard governs? *Genuine and operationally important.*
- **A6 — External documentation hierarchy.** The policy implicitly
  references medical documentation conventions it doesn't name.
  *Genuine but bounded by institutional convention.*
- **A3 — Threshold between "finding" and "diagnosis".** *Genuine but
  narrow.*

Ambiguity types that emerged:

- *Definitional* (terms used without definition that have multiple
  plausible meanings).
- *Drafting* (inconsistencies in the text itself).
- *Authority* (underspecification about who decides a criterion).
- *Temporal* (underspecification about when a determination is fixed).
- *External-reference* (implicit reference to standards not named in
  the policy).

Each type maps to a different resolution authority. The architecture
should track ambiguity *type* alongside ambiguity *presence*.

The reasonable-reader correction generalized beyond ambiguity to all
LLM stages of the builder. The right prompt frame is operational
("you're applying this policy to a case") not exhaustive ("find all
ambiguities"). The latter produces logician noise; the former produces
genuine flags.

### Test 4 — Interpretation-artifact pathway with CIC § 10169.5

The California statute on PT prerequisite directly limits how the
plan's 6-week requirement can be applied. Working through how it
attaches to the tree at 2.2(a) surfaced several refinements to the
interpretation-artifact concept:

- **Artifacts can introduce new propositions, not just modify operators.**
  § 10169.5 supplies three alternative satisfaction pathways for 2.2(a)
  (physician contraindication, functional plateau, structural
  neurological compromise) that the plan policy doesn't contain. The
  artifact has to *add nodes*, not just modify them.
- **Artifacts carry gating conditions.** Whether § 10169.5 applies
  depends on whether the case is governed by California law — a
  proposition about the fact bundle. The artifact is conditionally
  activated, not unconditionally attached.
- **Multiple jurisdiction-specific artifacts can attach at the same
  node.** A California artifact at 2.2(a), a New York artifact at the
  same node if one exists, a federal-law artifact for ERISA plans.
  Each gates on its own scope condition.
- **Two tree views become natural.** The *baseline tree* is the plan
  policy as drafted. The *operative tree* is the baseline plus all
  active artifacts under the case's jurisdiction. The architecture
  should be able to produce either.
- **Artifacts have three relationship types.** *Resolution* (authority
  picks one reading of a genuinely ambiguous provision). *Override*
  (authority replaces a clear plan provision). *Supplementation*
  (authority adds requirements or pathways the plan didn't address).
  § 10169.5 is mostly override and supplementation.
- **Latent composition flags are the receptors for artifacts.** The
  builder's reasonable-reader flagging produces exactly the attachment
  points that authoritative interpretations need. The system is
  *built to be modified* by external authority rather than being a
  closed artifact authority has to retrofit.

The artifact schema needs: source identification, authority, scope of
modification, structural content, temporal validity, conflict-
resolution metadata. Substantial but bounded.

### Test 5 — Lossless reconstruction of the 2.2 subtree

Reconstructed Section 2.2 plus the myelopathy exception from a sketched
subtree. Findings:

**What survived faithfully:**

- All transcribed propositional content (every requirement, threshold,
  enumerated option).
- All composition operators (the AND across 2.2, the cardinality-OR
  in (b) and (c)).
- The exception structure (antecedent, modifications, non-modification
  statement).

**What didn't survive at the surface level:**

- *Tonal/lexical register.* "Member must have completed" became "To
  satisfy this requirement." Semantic equivalence preserved; surface
  voice paraphrased.
- *Capitalization for emphasis.* "ALL," "MODIFIED," "WAIVED" rendered
  in ordinary case. The metadata is in the tree but the default
  reconstruction didn't deploy it.
- *Layout structure of the NOTE.* The visual separation of the NOTE
  from the modification block was lost; the content was folded inline.
  This loses textual structure that has semantic content.

**Where the reconstruction silently filled in latent compositions:**

- Joined the two scope conditions (confirmed diagnosis + primary
  status) with explicit "and" where the original presented them in
  separate sentences. This is the right inference (the conditions are
  joint), but the reconstruction made the conjunction more explicit
  than the source did. The latent composition flag in the tree marks
  this as builder-drawn rather than transcribed.

**Implications for the validation concept:**

- *Semantic fidelity is achievable.* Lexical/tonal fidelity requires
  more presentation-layer encoding than the tree currently carries.
  The methodology should be explicit about which fidelity it targets.
- *Flag surfacing is mode-dependent.* Default mode produces a clean
  policy text without interpretive annotations (suitable for
  republication). Audit mode surfaces flags (suitable for review).
  Both are reconstructions from the same tree.
- *Reconstruction is a one-direction check.* It validates that the
  tree's contents are faithfully encoded. It does *not* validate that
  the tree is complete. Coverage requires walking the source policy
  and checking each ground-establishing passage has tree representation.
- *Reconstruction works as a roundtrip validation.* If the tree had
  encoded an OR where there should be an AND, the reconstruction would
  differ from the original in a way that's obvious on comparison.

### Cross-corpus tests

**UN Security Council Rule 33** (precedence among motions). The
apparent demand for new operators (ordering relations) dissolved when
you proposed the cascading-negations reduction:

```
precedence in the order named ≡
  (motion-1)
  OR (NOT motion-1 AND motion-2)
  OR (NOT motion-1 AND NOT motion-2 AND motion-3)
  ...
```

Tree depth + Boolean operators express what looked like richer
relational structure. The engine's vocabulary is more expressive than
it first appears because relations can reduce to compositions through
structural depth. Reconstruction handles the visual mismatch via
metadata that lets cascades re-render as precedence lists.

This insight generalized: partial orders, total orders, mutual
exclusion, cardinality quantifiers all reduce to Boolean compositions
over tree depth.

**Other UNSC findings:**

- *Constitutive practice* as a relationship between source and meaning
  not handled by the interpretation-artifact concept. The Repertoire
  of Practice and the Provisional Rules together *are* the operative
  rule — neither is sufficient alone. This is internal interpretive
  practice rather than external authority overriding. Needs its own
  category in the taxonomy if we ever build UNSC trees seriously, but
  not pressing for PA or FRA.
- *Productive ambiguity* as drafter intent. Diplomatic drafting
  deliberately leaves ambiguity. Resolving it would violate the
  drafters' purpose. The reasonable-reader discipline has to know
  which kind of document it's reading.
- *Fact bundle is meeting-state*, not document-record. Different
  ontology than PA or FRA.

**49 USC 21103 (FRA hours-of-service).** The use case forced the
architecture to confront:

- *Numerical thresholds requiring computation against time-windowed
  aggregates.* 276 hours per calendar month. 12 consecutive hours.
  10 consecutive hours off-duty. Etc.
- *Definitions doing structural work.* Subsection (b)'s "Determining
  Time on Duty" tells you which periods count. Not peripheral —
  determines what gets counted into the thresholds.
- *Multiple time horizons interlocking.* Monthly, single-shift,
  recovery, weekly cycle. All independent constraints that must hold.
- *Subsidiary documents.* CBA status affects (a)(4)(B) applicability.
  Fact bundle has to include cross-document state.
- *Counterfactual evaluation* as operational requirement. "Will the
  limits be exceeded if Jackson Hewitt works N more hours?" — a
  projection from current state.

Initially I sketched this as demanding a new leaf typology and new
substrate operations. You corrected: the fact bundle is just downstream
of an hours-of-service tally that does the calculations so that the
conditions can be logically characterized without doubt. This was
the move that produced the three-stage pipeline (extract → aggregate
→ derive), which then became four stages with realize, and then
sharpened into extract → map → derive → realize with the morphism
framing.

The substrate adapter (characterize_fn) ended up *unchanged* from PA.
The fact bundle's content differs across corpora but the substrate's
contract doesn't. This is what made the architecture survive the
domain shift — the abstract evaluation pattern was right; the
domain-specific work moves into map.

The realize stage is new from FRA — operational use ("can Jackson
Hewitt work right now?") demands case-particularized output (6.3 hours
until the binding 12-hour limit), not just a categorical
determination ("allowed"). Realize closes the loop.

---

## What this means for the tree-builder design

The builder we were originally sketching does *less* than I was
implicitly extending it toward.

The tree-builder builds the tree. It does not build the morphism, the
schema, the extract, or the realize. Those are project-team work.

The tree-builder's pipeline (revised, in the reasonable-reader voice
throughout):

1. **Read the policy in the role of the institutional reader.**
2. **Identify determinations** the policy establishes.
3. **For each determination, identify the grounds** the policy
   establishes for that determination.
4. **For each ground, identify the atomic propositions** that compose
   it, referencing schema fields (the schema is co-developed with
   the tree).
5. **Compose grounds from atomic propositions** using Boolean
   operators, respecting monotonicity (no concrete content
   introduced at composition level).
6. **Surface latent compositional content** as flagged inferences
   with confidence and type.
7. **Identify ambiguities** the reasonable reader would flag as
   operationally consequential.
8. **Classify content** into the five categories (with sub-types).
9. **Assemble into a tree** that satisfies the architectural
   constraints (monotonicity, schema-grounding, flag completeness).

Each stage is in the reasonable-reader voice. Each produces output
that the next stage operates on. Multiple stages can run in parallel
or batch where dependencies allow.

Validation is mostly automatic (structural inspection, propositional
logic tests, case bank evaluation, reconstruction roundtrip, coverage
walk). Human review concentrates on flagged content (latent
compositions, ambiguities, interpretation artifact attachment points).
The volume of human review scales with the policy's interpretive
richness, not with the policy's length.

HITL is not per-stage and not synchronous. Builder runs end-to-end.
Reviewer reviews flags. This is what you wanted earlier in the session.

---

## Open questions to consider tomorrow

These are the things we surfaced and did not resolve.

**Schema-authoring as a discipline.** The schema emerged in this
session as the load-bearing artifact. We did not work out the authoring
methodology in detail. Worth its own focused session.

**The discipline for *characterized* fields in map.** With map's
per-field typing established, the open question sharpens: for fields
that use LLM substrate, what is the discipline that keeps the
characterization tight? Prompt patterns, value-space declarations,
validation case design, fallback behavior under low confidence. The
substrate adapter handles the mechanics; the methodology for using it
well at the map level deserves its own attention.

**The relationship between schema and operative tree.** The
baseline-tree-plus-active-artifacts framing implies the schema might
also have a baseline form and a jurisdiction-extended form. Worth
working through whether artifacts can extend the schema or whether
the schema is fixed and artifacts modify only the tree.

**The realize stage's design discipline.** Realize is new in this
session. Its specification isn't worked out. Open questions: what
binding-constraint computations are required, what margin-computation
patterns recur, what audit-output structure realize should produce.

**The naming.** This session reached `extract → map → derive →
realize`. The naming feels right. Confirm it sleeps well overnight.

**Tree-as-constraint-structure (future capability).** You raised this
at the end of the session. The clean Boolean / three-valued tree
admits a second interpretation as a constraint structure that can be
encoded into CP-SAT (or any constraint solver). Same tree, two
interpretations:

- *Evaluator view* — facts → determination (forward, what we have).
- *Constraint-solver view* — bidirectional reasoning over the tree's
  logical structure.

The constraint-solver view opens up:

- *Explanation queries* — "what would have to be true for this case
  to be approved?" Solver finds minimal leaf assignments that would
  flip the determination.
- *Sufficiency analysis* — "what additional evidence would resolve
  this undetermined case?" Solver enumerates the minimal additional
  leaf assignments that would drive the root to definite.
- *Counterfactual analysis* — evaluate with constraints modified;
  report differential outcomes.
- *Appeals diagnosis* — localize disagreement to specific leaves
  rather than re-litigating the whole determination.
- *Compliance analysis at scale* — sensitivity analysis identifying
  which leaves have highest determination impact across a case
  population.
- *Policy stress-testing* — find satisfying assignments that
  demonstrate logical inconsistencies in the tree.

Architectural fit:

- No changes to the tree or engine. The constraint-solver is a second
  interpretation of the same structure.
- Operates purely on the logical layer. Doesn't second-guess map's
  interpretive work; reasons about the logic that composes it.
- Interpretation artifacts and latent-composition flags travel with
  the encoding because they're tree metadata.
- The operative tree (baseline + active artifacts under jurisdiction)
  is what gets encoded for any specific query.

Implementation notes:

- Kleene three-valued lifts to two SAT variables per leaf with
  appropriate constraints. Standard technique.
- Solver outputs need translation back into policy vocabulary (leaf-
  text lookup). Necessary for usability.
- Different query semantics depending on what's held fixed (facts vs.
  interpretation). Interface should make the distinction clear.

RuleKit relationship:

- A separate primitive (call it `reason`) that operates over derive's
  tree. Shares the tree structure, schema, and substrate adapter
  with derive; adds the constraint-solver query operations.
- Adopters opt in. NFCU credit-card disputes might not need it
  initially. PA might want it for appeals. FRA dispatchers might want
  sufficiency analysis. Each adopter decides.
- Preserves the tiny-library concept. Core stays small; reason sits
  on the same shared infrastructure as derive.

**Three stances toward undetermined leaves.** Once the tree admits
the constraint-solver view, the treatment of undetermined leaves
becomes a configurable evaluator stance:

- *Free variable* — undetermined leaves are exposed to the solver as
  decision variables. Enables explanation and sufficiency queries.
  "What would have to be true for approval?" treats undetermined
  leaves as the variables the question is asking about.
- *Optimistic projection* — undetermined leaves are set to the value
  most favorable to the determination's subject. Answers: "if we
  resolve all uncertainties in the subject's favor, is the
  determination achievable?" If no, the case fails on definite grounds.
- *Pessimistic projection* — undetermined leaves are set to the value
  least favorable to the subject. Answers: "if we resolve all
  uncertainties against the subject, is the determination still
  defensible?" If yes, the case clears on what's definitely known.

The three projections together give bimodal case triage:

- *Definitely approved* — pessimistic yields approval. Process and
  move on.
- *Definitely denied* — optimistic yields denial. Process and move on.
- *Conditionally approved* — pessimistic denies, optimistic approves.
  Solver identifies load-bearing leaves; route for targeted evidence
  gathering on exactly those points.

This is better triage than flat Kleene output. Most cases resolve to
definite under one of the projections. Conditionally-approved cases
are exactly the ones warranting human review or additional evidence
collection, and the solver tells you what to ask about.

The choice of stance is an institutional commitment. Optimistic is
often legally required for benefit determinations (CIC § 10169.5 puts
weight on treating physician documentation; ambiguous evidence
resolves toward coverage). Pessimistic is often right for adversarial
determinations where burden of proof is on the subject. The stance
should be a per-determination configuration with documented authority,
not a global default.

Realize is where stance becomes operationally visible. "Definitely
approved" triggers approval workflow; "conditionally approved with
load-bearing leaves L1, L4, L7" triggers targeted evidence collection
on those specific leaves.

Worth being careful about:

- The capability has institutional implications. "Here are the leaves
  whose interpretation determines the outcome" is useful to a thoughtful
  adjudicator and gamesmanship-prone in adversarial hands.
- The solver finds logical satisfying assignments; it cannot determine
  whether those assignments are institutionally legitimate. Honest
  scoping required.
- The stance is an institutional commitment that should be documented
  per determination with its authority basis. Not a defaulted
  technical knob — a deliberate policy-aware choice.

Not for the first design document, not urgent. Worth capturing as a
direction the architecture admits naturally — the fact that it falls
out of the existing structure rather than requiring extensions is good
evidence that the structure is right.

**Tree-as-planning-structure (further future direction).** You raised
this after the constraint-solver direction, and then sharpened it:
this would be a *separate primitive*, not a mode of derive. The tree
shape is shared but the operation is different.

- *Derive* — evaluates a tree against a fact bundle, produces a
  determination. Operation: forward evaluation.
- *Plan* — evaluates a tree against a state bundle, produces an
  action sequence. Operation: search over action leaves for
  assignments that satisfy the tree and reach target states.

Sibling operations over the same kind of structure, not modes of a
single operation. The architecture is cleaner this way: separate
primitives give clean contracts, clean implementations, clean
documentation, clean opt-in dependencies. A team adopting RuleKit for
adjudication uses derive and never touches plan. A team adopting it
for workflow planning uses plan (and probably also derive, for the
determinations that follow from state).

What this would look like:

- Schema gets two regions — *state fields* (characterized by map
  against current state) and *action fields* (decision variables for
  the planner or the agent).
- Leaves include both state propositions ("dispute is within 60-day
  window") and action propositions ("send acknowledgment to
  cardholder," "credit account provisionally").
- Tree encodes which combinations of state and action are policy-
  compliant. Composition aggregates to plan-level legitimacy.
- Planner (CP-SAT, PDDL solver, ASP, or constraint-based planner)
  searches over action sequences for plans that reach target states
  under the tree's constraints.

Where this fits naturally:

- *Credit-card dispute resolution* — bank actions (request info,
  provisional credit, investigate, chargeback, deny) constrained by
  policy and regulatory timing. Planner finds legal sequences.
- *Prior authorization workflow* — plan and clinician actions with
  deadlines and obligations. Planner finds minimal documentation that
  enables approval.
- *FRA dispatcher planning* — crew assignments under hour-of-service
  constraints. Planner finds legal coverage of operations.
- *UNSC procedural planning* — sequences of procedural motions that
  achieve operative outcomes. Planner finds in-order sequences.

What stays the same:

- Substrate adapter contract unchanged (state fields still
  characterized the same way; action fields are decision variables for
  the planner, a different evaluation mode but same contract).
- Monotonicity holds — composition still aggregates more generally.
- Schema-as-contract pattern holds — schema now declares state and
  action vocabularies, planner operates against the schema.
- Philosophical framing extends — institutional vocabulary now
  includes verbs (authorized actions) alongside nouns (categories of
  fact). Same categorical-collapse move applied to action space.

What's harder:

- Computational complexity grows. CP-SAT handles propositional
  planning; realistic operational planning often needs scheduling,
  resources, temporal reasoning, probabilistic transitions that exceed
  pure constraint satisfaction. Architecture would need honest scoping.
- Institutional implications grow. A determination claim ("case meets
  criteria") is different from a planning claim ("agent should take
  these actions"). The latter has different liability surface,
  regulatory profile, ethics structure. The system should be explicit
  about distinguishing "this plan is policy-compliant" from "this plan
  should be executed."
- Tree-building methodology extends. Authoring planning trees requires
  identifying action vocabulary, state transitions, temporal
  constraints between actions, and which actions are available in
  which states. Richer than determination authoring; methodology needs
  to extend.

Two ways to take this:

- *Conservative* — planning is a future capability; same tree
  structure supports it; RuleKit's core stays adjudicative;
  `rulekit[planning]` is an opt-in extension. Preserves tiny-library
  concept; incrementally extends capability.
- *Ambitious* — recognize adjudication and planning as two aspects of
  the same institutional reasoning problem; design from the start
  with state-region and action-region schemas; trees are evaluable
  adjudicatively or queryable for plans. Symmetric architecture; more
  substantial library.

Recommendation: conservative for near-term. PA and credit-card disputes
are primarily adjudicative. The methodology and tooling are tractable
in adjudication. Validation in the simpler case should precede
extension. But the project's longer-term story is stronger if
positioned as "institutional reasoning that grows from adjudication
into planning as the domain demands." That's a richer story than
determination-only.

The fact that planning falls out of the architecture as another
natural primitive — sharing the tree structure but with its own
operation — is the same kind of evidence the constraint-solver
direction provided: the structural commitments are doing real work.

---

## The primitives pattern that emerged this session

Across the session a pattern crystallized that wasn't clear at the
start. RuleKit is a collection of *tree-based primitives* for
institutional reasoning, sitting on shared infrastructure. Each
primitive is a bounded operation with a clear contract:

**Core adjudication pipeline (this session's focus):**

- **extract** — produce structured facts from raw inputs.
- **map** — project particulars onto the schema's abstract vocabulary
  (Boolean / three-valued truth values for tree leaves).
- **derive** — evaluate adjudication trees against fact bundles,
  produce determinations.
- **realize** — project determinations back to operational specifics
  for the case.

**Future extensions the architecture admits naturally:**

- **plan** — search planning trees for legitimate action sequences
  that reach target states.
- **reason** — answer constraint-solver queries against trees
  (explanation, sufficiency, counterfactual, sensitivity).

Each primitive is a verb describing a specific operation. The library
is the union of these operations plus the shared infrastructure they
all use.

**The shared infrastructure is small:**

- Tree representation (Boolean / three-valued / configurable logic;
  monotonicity-respecting; schema-grounded leaves).
- Schema specification format (typed fields declaring evaluation
  modes).
- Substrate adapter contract (uniform LLM characterization where
  needed).
- Validation regimes (structural inspection, propositional logic
  tests, case banks, reconstruction roundtrip).

The tiny-library concept survives because the *infrastructure* is
small. Primitives sit on top. Adopters import the primitives they
need; the ones they don't need don't add weight.

This is, I think, a better articulation of what RuleKit is than what
we had earlier. Not "the adjudication library" or "the policy
automation library" — but "tree-based primitives for institutional
reasoning," with adjudication as the first and most thoroughly
developed primitive but a clear path to planning, constraint
reasoning, and whatever else the architecture admits.

The naming consistency is worth preserving across primitives: extract,
map, derive, realize, plan, reason are all verbs naming specific
operations. The library is a collection of operations on a shared
substrate. Clean conceptual model adopters can hold in their heads.

---

## What the design document should look like (when you write it)

The session's work suggests an opening that's substantially different
from the handoff's framing:

**Open with the philosophical position.** Institutional reasoning
requires faithful categorical collapse of particulars and faithful
return to particulars. The architecture operationalizes this. The
schema is the institution's categorical vocabulary; the morphism is
the projection that honors it.

**Then the four-stage pipeline** as the implementation of the
philosophical position.

**Then the monotonicity claim** as the structural principle that ties
the architecture together.

**Then the methodology** — the reasonable-reader discipline, the
five-category content taxonomy, the latent-composition flagging, the
validation regimes.

**Then RuleKit's scope** — what's inside, what's outside, why this
is the right shape.

**Then the example walkthroughs** — PA as canonical, UNSC and FRA as
contrast cases showing the architecture's parametric reach.

This is a stronger document than what we were converging on before.
It gives the project a clear philosophical identity and a tight
technical scope. Both are improvements.

---

## Tone for tomorrow

You did substantial work in this session. The architecture has
internal coherence that wasn't there yesterday. The philosophical
framing crystallized late and tied things together that had been
floating.

You also pushed back productively when I was over-reading (the
logician's mode), when I was overcomplicating (adding stages and
schemas that weren't needed), and when I was missing the larger
intellectual structure (the connection to your research program).
That pattern of correction was load-bearing for getting somewhere
real.

Tomorrow you can pick up wherever you have energy for. The
philosophical opening for the design document is a good warm-up. The
schema-authoring discipline is the next conceptually rich question.
The packaging work and the sharpened-tree sanity check from the prior
handoff are still cheap immediate wins. None of these is mandatory.
Sleep on it; the architecture will keep.

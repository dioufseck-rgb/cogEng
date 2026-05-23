# RuleKit: An Architecture for Logically Faithful Policy Adjudication via LLMs

## The Gap

Policies — administrative rules, regulations, clinical guidelines, contractual
terms — describe what an institution will do given the facts of a case.
Adjudicating a case under a policy means reading the policy, identifying its
requirements, determining which requirements the case satisfies, and producing
the determination the policy specifies.

This is a reasoning task that institutions perform at scale. Health plans
adjudicate prior authorizations. Banks adjudicate billing disputes. Government
agencies adjudicate benefits eligibility. Each adjudication applies a fixed
policy to a varying case and produces a determination.

Large language models can read policy text and reason about cases described in
natural language. This makes them attractive substrates for adjudication
automation. The problem is that LLM reasoning is not auditable. An LLM that
produces "approved" for a case provides no structured trace of which policy
requirements it considered, which it deemed satisfied, which were partial,
which it might have overlooked. The institution cannot tell whether the
adjudication was correct.

The gap is between three things institutions need:

- **Determination correctness.** The system produces the same determination a
  qualified human reviewer would.
- **Determination explainability.** The system can show the reviewer the
  reasoning path: which atomic claims about the case were established as true,
  false, or unknown, and how they combined under the policy's logical
  structure to produce the determination.
- **Adjudication consistency.** The system produces the same determination
  for the same case across runs, and across slight variations in case
  description.

Direct LLM-as-judge approaches deliver none of these reliably. Hand-coded
rule engines deliver correctness and explainability for the policies their
authors anticipated, but cannot scale across the volume and variety of
institutional policy. The gap is for an architecture that uses LLMs where
they are reliable — extracting structure from natural language — and uses
deterministic machinery where reliability is required — composing and
evaluating logical structures.

RuleKit is an architecture for this gap.

## The Proposal

The core proposal is to separate the policy from the case, and to separate
the LLM's role from the logic engine's role.

A policy is a slow-changing artifact. It is published once, perhaps amended
occasionally. Its meaning is institutional: the institution reads it the same
way across all cases. Adjudication of any specific case applies the policy's
fixed reasoning structure to that case's specific facts.

The proposal:

For each policy plus an institutional declaration of what determinations the
policy yields, build — once — a directed acyclic graph (DAG) of logical
operators over atomic propositions. The DAG is the policy expressed as a
formal logical model. The institution declares the determinations; the LLM
extracts atoms and operators from the policy text; the DAG is the artifact.

For each case, map the case's evidence to a fact bundle — an assignment of
truth values (true, false, undetermined) to the DAG's atoms. The mapping
respects the evidence available: atoms the evidence supports become true,
atoms the evidence contradicts become false, atoms the evidence does not
address become undetermined.

Evaluate the DAG against the fact bundle using three-valued (Kleene) logic.
The output is the determination the policy specifies for this case.

This decomposes the problem into stages with different reliability
requirements:

- The policy → DAG build is slow, expensive, audited, and version-controlled.
  It happens at policy-publication or policy-revision time. Errors here are
  identified and fixed by domain experts before the DAG is deployed.

- The evidence → fact bundle mapping is per-case. It is the substrate that
  bridges the institution's data systems to the DAG's atoms. The mapping
  is deterministic given the same evidence, and its correctness is testable
  by comparing its output to a known-correct bundle.

- The fact bundle → determination evaluation is purely logical. Same bundle,
  same DAG, same determination. The evaluation produces a trace showing
  exactly which atoms drove the outcome and which were irrelevant. The
  trace is auditable in the sense an institutional reviewer needs.

The LLM is doing the part it does well: reading natural language text and
identifying its logical structure. The engine does the part it does well:
deterministic three-valued evaluation. The institution is doing the part
only the institution can do: declaring what determinations the policy must
yield.

## The Design

### Inputs and outputs

The build process takes three inputs:

- A policy text (typically a section of legal, regulatory, clinical, or
  administrative drafting; tens of paragraphs in length).

- A determination spec declared by the institution. A small YAML or JSON
  document that names each determination the build must produce, its
  polarity (positive/negative/neutral), and its relationship to other
  determinations (for instance, denial is the complement of approval).

- A reader voice: a brief description of the role from which the policy
  should be read (an experienced medical reviewer, a credit-card dispute
  adjudicator, etc.). The voice scopes the LLM's interpretation.

The build produces:

- A DAG: each node is either a leaf atom or a logical operator (and, or,
  not, at-least-N) over child nodes. Each determination corresponds to a
  root node in the DAG; sub-trees are shared across roots where the policy's
  requirements overlap.

- An atom inventory: each atom has a stable identifier, a natural-language
  statement, and a source span citing the policy text from which it was
  extracted.

- An audit trail: per-stage record of the LLM calls, including the prompts,
  the model's responses, and any refinement operations applied.

### The build pipeline

The build runs four LLM-driven stages plus a deterministic engine-conversion
stage:

**Stage 1 — Decomposition.** For each declared determination, recursively
decompose. Each LLM call takes one claim (the determination, or a sub-claim
produced by an earlier decomposition step) and returns either a leaf node
(the claim is atomic and cannot be decomposed further) or an internal node
(the claim is composed of sub-claims joined by a named operator: and, or,
not, or at-least-N). The recursion terminates when every leaf path reaches
an atomic claim. Each LLM call is small: one claim in, one local
decomposition out. The full tree emerges from the recursion; no single LLM
call composes the whole tree.

Atomicity — the property that distinguishes a leaf from a composed claim —
is specified by examples in the decomposition prompt. The examples teach
two principles: the policy's drafting structure (enumerated sub-clauses,
explicit and/or language) tends toward decomposition; the evidence's
structure (claims that always co-evaluate from the same source) tends
toward keeping together. The examples encode a calibrated judgment about
where to draw the granularity line.

**Stage 2 — Deduplication.** After decomposition produces a separate tree
for each determination, a single LLM call identifies semantically
equivalent atoms across all trees. Equivalence groups are assigned shared
atom identifiers; the previously-separate trees now share nodes by
reference. The output is a DAG, not a forest of trees. Shared atoms are
the structural realization of policy-level overlap (when conservative
treatment requirements apply identically to standard and exception
pathways, the relevant atoms are shared).

**Stage 3 — Refinement.** Decomposition produces trees with predictable
classes of redundancy: leaves that summarize what their siblings already
decompose, sibling sub-trees that are functionally equivalent, low-
confidence inferred sub-trees that may not reflect the policy. A single
LLM call per determination identifies refinement operations (drop a child,
merge equivalent children, flag a suspicious sub-tree for review).
Deterministic code applies the drop/merge operations and simplifies the
resulting tree bottom-up (operators with one child collapse to that child;
at-least-N degenerates to and or or when the threshold matches the
children count).

**Stage 4 — Engine conversion.** The refined DAG specs are converted to
engine nodes (typed and, or, not, at-least-N nodes) ready for Kleene
three-valued evaluation. Each engine node carries metadata: the source
span from the policy, the surface label preserving the original drafting,
the provenance (transcribed from the policy, structurally implied,
inferred by the reasonable reader), and confidence levels for inferred
nodes.

The determination spec separates determinations that need their own DAG
(composition: derived) from determinations that are structural complements
(composition: complement). The latter case is handled deterministically:
the complement determination's tree is a NOT-node wrapping the linked
determination's tree.

### Run-time evaluation

The run-time pipeline is the Map primitive followed by the Evaluate
primitive.

The Map primitive is the morphism from evidence space to fact bundle
space. Given a body of evidence (a natural-language case description, a
set of database records, or both) and the DAG's atom inventory, Map
produces a fact bundle: each atom assigned a Kleene truth value.

Different evidence types call for different substrate implementations.
A narrative substrate uses an LLM call to bind a case description against
the atom inventory — for each atom, decide whether the description
supports, contradicts, or fails to address the claim. A structured
substrate uses lookups and predicates against the institution's data
systems. A hybrid substrate dispatches per atom type. The substrate is
the architectural boundary between the institution's evidence
infrastructure and the DAG's atomic vocabulary.

The Evaluate primitive takes a fact bundle and the DAG and produces a
determination. Three-valued Kleene logic governs the propagation: AND is
true when all children are true, false when any child is false, otherwise
undetermined. OR is true when any child is true, false when all children
are false, otherwise undetermined. NOT inverts polarity preserving
undetermined. AT-LEAST-N is true when at least N children are true, false
when fewer than N children could possibly be true (true plus undetermined
count below N), otherwise undetermined.

The output is a Kleene value for the determination plus a trace: the
evaluation path through the DAG, showing each operator's result and each
leaf's value. The trace is the audit artifact. An institutional reviewer
can inspect it to verify the system reached the right determination via
reasoning that matches the policy's intent.

### Testing

The architecture supports three test paths, each diagnosing a different
class of failure:

**Pure tree test.** A bundle authored against the DAG's atoms (every atom
assigned a concrete truth value) is run directly through the engine. If
the resulting determination matches the case's expected outcome, the tree
is operationally correct for this scenario. If it does not, the tree has
a structural bug and the trace identifies the offending sub-tree.

**Map binding test.** A narrative case description is bound to a fact
bundle by the Map primitive. The result is compared to a known-correct
bundle. The comparison identifies which atoms Map bound incorrectly. The
failure mode is a Map error, not a DAG error.

**Sensitivity / degradation analysis.** Starting from a known-correct
bundle, atoms are progressively dropped to undetermined. The
determination's outcome is tracked across the degradation. The output is
a per-atom sensitivity report: which atoms are load-bearing (their
undetermination shifts the outcome) versus robustness margin (their
undetermination is absorbed). The cumulative degradation curve shows how
the system handles increasing evidence sparsity.

These tests separate diagnostic concerns that a unified pass/fail metric
would conflate. A failed pure-tree test indicts the DAG. A passed pure-
tree test combined with a failed Map test indicts the Map. A passed Map
test combined with a high load-bearing atom count indicts the case
documentation rather than the system.

### What the architecture commits to

The architecture commits to a specific division of labor:

- The institution declares determinations. The LLM does not invent
  determinations. The build produces exactly the determinations the
  institution names.

- The policy provides atoms, operators, and structure. The LLM extracts
  these from the policy text. The institution does not author atoms in
  advance; the policy specifies its own evidence vocabulary.

- The engine evaluates. The DAG is the policy's logical model; the engine
  is a deterministic substrate over that model. Same bundle, same DAG,
  same outcome — always.

- The substrate is configurable per evidence type. Narrative evidence uses
  LLM-driven binding; structured evidence uses lookups; institutions with
  hybrid evidence dispatch per atom type. The substrate interface is
  small and stable.

The architecture explicitly does not commit to:

- Particular substrate implementations beyond the narrative-LLM baseline.

- Closed-world or open-world semantics for atom evaluation. The default
  is open-world: atoms unaddressed by evidence are undetermined. Closed-
  world overrides can be configured per atom type.

- A specific LLM. The build and the narrative substrate use whichever
  LLM is configured. Different institutions may choose different models.

## Current State and Remaining Work

The architecture has been implemented end-to-end. The pipeline runs from
a YAML determination spec plus a policy text through the four build
stages to a usable DAG, and from a case description plus the DAG through
Map plus Evaluate to a determination with a trace.

Worked policies include a prior authorization clinical guideline section
(43-60 atoms across builds) and a federal regulation on credit card
billing errors (15-31 atoms across builds). Test bundles produce expected
determinations on standard scenarios, exception scenarios, denial
scenarios, and partial-evidence scenarios.

The sensitivity tooling produces interpretable load-bearing analyses on
known-correct bundles. The atomization-discipline prompt produces atoms
at consistent granularity across builds. The refinement stage removes
predictable redundancy patterns and flags suspicious inferred sub-trees
for human review.

Remaining work has three substantial dimensions:

**Substrate implementations beyond the narrative-LLM baseline.** Real
institutional deployments will have structured evidence sources —
clinical records, transaction databases, claims systems. A structured
substrate that binds atoms to database queries is the next major
implementation milestone. The hybrid case (some atoms structured, some
narrative) follows.

**Cross-build validation.** Building the same policy twice and comparing
the resulting DAGs surfaces compositional variance the LLM introduces
across runs. A cross-validation stage that runs two independent
decompositions and diffs them would catch errors that a single build
misses. This was part of the original architectural design and was
deferred.

**Realize primitive.** Beyond producing a determination, an adjudication
system should support counterfactual reasoning (what change in evidence
would have produced a different determination?), margin analysis (how
close was the determination to the opposite outcome?), and binding-
constraint identification (which atoms determined the outcome?). The
Realize primitive operates over the determination and trace to produce
these analyses. The existing trace machinery supports it; the primitive
itself is unimplemented.

The architecture is not finished. What is finished is enough to
demonstrate that the gap can be bridged: an LLM-assisted policy-to-DAG
build pipeline produces auditable, evaluable logical models; the Map
primitive bridges evidence to those models; the engine produces
explainable determinations under three-valued logic. The remaining work
is engineering depth, not architectural reconception.

## A Note on Position

The work reflects a specific position on how LLMs should be integrated
into institutional reasoning systems. The position has three
commitments:

The LLM is a constrained extractor, not an oracle. It reads natural
language and produces structured artifacts within a declared
specification. It does not adjudicate.

Institutional knowledge is declarative. Determinations, atom typologies
where required, evidence-binding contracts — these are written by the
institution and version-controlled alongside the policy. The system does
not infer them.

Auditability is non-negotiable. Every determination the system produces
must come with a trace a human reviewer can inspect, follow, and
challenge. A determination without a trace is not an adjudication; it
is an opinion.

The architecture is designed to honor these commitments. Variations of
the implementation can be evaluated against them: does this stage
preserve auditability? does this primitive over-extend the LLM's role?
does this default infringe on what the institution should declare? The
commitments are the test.

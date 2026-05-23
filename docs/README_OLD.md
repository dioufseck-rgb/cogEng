# RuleKit — Session Package 2026-05-21

This package contains the design work, working code, and handoff document
from the design session of 2026-05-21. It is a snapshot of the project at
the end of that session, packaged so the work can be resumed without
re-reading the full conversation.

## What's in here

```
rulekit_session_2026_05_21/
├── README.md                       (this file)
├── SESSION_HANDOFF_2026-05-21.md   (the design conversation's output)
├── rulekit/                        (the engine — RuleKit's core library)
│   ├── __init__.py
│   ├── engine.py                   (Kleene three-valued cardinality semantics)
│   └── schema.py                   (typed field declarations)
├── policies/                       (two policies built as RuleKit trees)
│   ├── pa_section2.py              (PA medical-necessity with myelopathy exception)
│   └── fcba_1026_13a.py            (FCBA billing-error definition)
├── run_cases.py                    (test fact bundles + evaluation runner)
└── evaluation_output.txt           (full reasoning traces from the runner)
```

## How to run

From this directory:

```bash
python run_cases.py
```

This evaluates eight test cases (four PA, four FCBA) against the two
policy trees and prints the full reasoning trace for each. The output is
also saved as `evaluation_output.txt`.

Requirements: Python 3.10+ (uses dataclasses, type unions, and enums).
No external dependencies. Pure Python.

## What the package demonstrates

Two policy trees, built per the architecture from the design session, with
working evaluation:

- **PA Section 2** (HealthFirst CC-SPINE-2024 — cervical spinal surgery
  authorization). Includes the myelopathy exception (2.2A) as an
  alternative compositional pathway with a NOT-gated standard pathway
  enforcing mutual exclusion. Roughly 35 atoms after the atomicity
  discipline is applied; tree depth reaches 5 levels at the deepest
  branch.
- **FCBA § 1026.13(a)** (federal billing-error definition). Seven
  enumerated categories composed under OR; the unauthorized-charge
  category uses a De Morgan transformation flagged as an inferred
  operator. About 18 atoms.

Same engine evaluates both. The engine's operator vocabulary is just
AT-LEAST-N (with N as a parameter; AND is N=k, OR is N=1) and NOT.
All composition uses these two primitives.

## Test cases and expected outcomes

| Case | Description | Result |
|------|-------------|--------|
| PA-1 | Standard pathway — radiculopathy with full conservative treatment | TRUE |
| PA-2 | Exception pathway — primary myelopathy with 4-week PT and waived interventional | TRUE |
| PA-3 | Insufficient evidence — partial documentation | UNDETERMINED |
| PA-4 | Clear denial — no qualifying diagnosis | FALSE (D1), TRUE (D2) |
| FCBA-1 | Unauthorized charge — (a)(1) | TRUE |
| FCBA-2 | Undelivered services — (a)(3) | TRUE |
| FCBA-3 | Valid authorized charge | FALSE |
| FCBA-4 | Alleged unauthorized, evidence partial | UNDETERMINED |

Each result includes a full reasoning trace showing t/f/u counts at every
cardinality node, provenance metadata at every operator, and evidence
attribution at every leaf with available evidence.

## Architectural commitments demonstrated

The code embodies the design commitments from the session:

- **Monotonicity** — internal nodes carry only operators and children
  references; no concrete content introduced at composition.
- **Anonymous internal nodes** — composition nodes have no names; surface
  labels live as metadata; policy reference language lives on edges.
- **Provenance metadata** — every operator is marked transcribed,
  structural, or inferred. Inferred operators carry confidence and
  latent-composition type.
- **Three-valued logic at the leaf interface** — every leaf produces
  TRUE, FALSE, or UNDETERMINED. The Kleene cardinality semantics
  propagates correctly through the tree, surfacing undetermined results
  when evidence is genuinely insufficient.
- **Schema-as-contract** — the schema declares typed fields per atom
  with evaluation modes (computed / characterized / looked up). For the
  tested cases all atoms use characterized mode since they require
  substrate judgment, but the design accommodates the other modes for
  domains like FRA where numerical computation belongs.

## What's not in here (and where to find it in the handoff)

The session worked through a great deal of design that didn't go into the
code:

- **Decomposition / refinement / composition / schema-building** as stages
  of the tree-builder pipeline. The trees in this package were
  hand-constructed following those disciplines, but the automated builder
  itself wasn't implemented. The handoff documents the stage designs.
- **Constraint-solver primitive** (`reason`) — discussed as a future
  capability via SMT with Z3 Optimize. Not implemented in this build.
- **Planning primitive** (`plan`) — discussed as a separate future
  primitive sharing the tree infrastructure. Not implemented.
- **Realize stage** — discussed for projecting determinations back to
  case-specific operational guidance. The current code produces
  determinations with traces; realize would add margin computation and
  binding-constraint identification.
- **Validation regimes** beyond the evaluation runner — case banks,
  propositional logic tests, lossless reconstruction. The current runner
  is a manual smoke test; the validation discipline is documented in
  the handoff.

## The philosophical position (one-paragraph summary from the handoff)

Finite reasoning requires categorical collapse of particulars to abstract
categories. Categories are institutional choices, not natural facts. The
architecture operationalizes this: extract pulls structured facts from
raw inputs; map projects particulars onto the schema's abstract vocabulary
(producing three-valued truth values); derive composes the truth values
through pure logic over the tree; realize projects the determination back
to operational specifics. The schema is the institution's categorical
vocabulary, authored from the policy. The tree is pure logic — every node
is Boolean or three-valued, every internal node anonymous, no
interpretation at composition time. All interpretive complexity lives in
map; the tree does only logic.

## Where to start next session

The handoff document's "Open questions to consider tomorrow" section
lists the natural next moves:

1. Schema-authoring as a discipline (the next conceptually rich question).
2. The methodology for *characterized* fields in map (LLM-substrate
   discipline at the field level).
3. The relationship between schema and operative tree under
   jurisdiction-specific interpretation artifacts.
4. The realize stage's design discipline.
5. Naming confirmation (extract → map → derive → realize).

The handoff also notes the tree-builder algorithm is sketched (decomposition,
refinement, composition, schema-building stages) but not implemented.
Implementing the builder pipeline would let the next set of policies be
authored automatically rather than by hand.

## License and provenance

This is personal-time work by Mamadou Seck, conducted against public
sources only:

- PA policy: synthetic medical-necessity policy modeled on common health
  plan drafting conventions for the spinal surgery authorization domain.
  Used for design and methodology testing, not derived from any specific
  plan's internal documentation.
- FCBA policy: 12 CFR § 1026.13(a) — public federal regulation, retrieved
  from eCFR.

No employer materials used. License intent: open-source release through
appropriate channels once the architecture is mature and IP review
confirms no employer claims.

---

End of README.

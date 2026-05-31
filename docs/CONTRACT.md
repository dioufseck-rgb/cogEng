# RuleKit Spec Contract

**Status:** Draft for review.
**Purpose:** The contract that sits between a producer of determination
programs (build-time agent, hand author, config translator, UI editor)
and a consumer of them (the engine plus Map). The contract is
domain-agnostic. It does not know that a determination program was
derived from a policy, nor how it was derived.

---

## Why this exists

The handoff sentence is: *a policy extractor agent at build time
produces a DAG and a Map spec that are compatible with the engine. At
runtime, the engine evaluates the DAG against atoms that Map extracts
from each case.*

For "compatible with the engine" to mean anything, it has to be a
concrete shape. Today the shape exists as Python dataclasses in
`rulekit/build/decomposer.py` — implicit, in-process, not serializable,
not versioned, not validatable from outside Python. This document
specifies a single Pydantic-based contract that replaces those
dataclasses. The migration is invasive (the 137 existing unit tests
will need to be updated) and deliberate: the library's external
surface matters more than the cost of porting tests written against
the prior shape.

The contract has four jobs:

1. Define what a producer must emit — every field, every constraint,
   every validation rule that an externally-produced program must
   satisfy before the engine will accept it.
2. Serialize. A program must round-trip through JSON without loss.
   This is what makes it portable, diffable, version-controllable,
   and reviewable by humans who don't run Python.
3. Validate. Constraints that today are scattered across
   `__post_init__` methods, runtime errors in `spec_to_engine_node`,
   and tacit conventions become explicit Pydantic validators.
4. Carry audit metadata. Provenance, source spans, confidence, surface
   labels — everything an institutional reviewer needs to follow what
   the producer did.

The contract does **not** define:

- How a producer makes a program (prompts, dialogue patterns, state
  machines, hand-authoring conventions). That's the producer's design
  problem. For the LLM-driven build path, see `rulekit/build/` — the
  build module's `BuildSpec` describes what *that* producer needs as
  input (policy text, reader voice, declared determinations,
  constants). A `BuildSpec` is *not* a contract program; the build
  produces a contract program *from* a `BuildSpec` plus its inputs.
- How Map binds evidence to atoms (substrate implementations). That's
  per-deployment configuration.
- How the engine evaluates a DAG. That's `engine/boolean.py` and
  `engine/typed.py`, which are upstream of this contract.

---

## Architectural commitments encoded in the contract

These are decisions that constrain every field below. Stated up front
so the rationale for specific shapes is visible.

**C1. The DAG is a DAG, not a tree.** Sharing is explicit. The
contract defines an atom registry and a node registry; children
reference parents by ID, not by inline structure. Two determinations
that share a sub-tree reference the same node ID, not two copies.
This makes sharing visible to human reviewers, JSON diffs, and
producers' reasoning.

**C2. The Map spec is first-class.** Today the Map substrate reads
atoms at runtime with whatever extraction prompts the substrate's
author wrote. The contract pulls extraction guidance into the
program: per-atom evaluation mode, per-atom extraction template,
per-atom undetermined semantics. The substrate becomes a runtime
executor of the Map spec, not the place where extraction policy
lives.

**C3. Test cases are Map-input-shaped, not bundle-shaped.** A
`TestCase` carries the same shape Map will see at runtime — narrative
text, structured records, or both — paired with expected
determinations. This makes the test path end-to-end (case → Map →
bundle → engine → determination) rather than diagnostic-only
(pre-bound bundle → engine → determination). The pre-bound diagnostic
remains available as a separate operator-level tool, but it's not the
contract's test format.

**C4. Every engine node has a spec analog, and vice versa.** No
engine capability is reachable only by hand-authored Python. No spec
type compiles to nothing. Where the engine grew nodes the spec layer
hasn't caught up to (`ConditionalNumericNode`), this contract adds
them. Where the spec layer carries deprecated forms (`DerivedAtomSpec`
with `aggregate_sum` / `max_of` / `min_of`), this contract removes
them.

**C5. Audit metadata is mandatory, not optional.** Source spans,
provenance, surface labels, and confidence-for-inferred-nodes are
required on every non-leaf node. The library can't enforce that
producers write good labels, but it can enforce that the slot exists.
The interpretation of `source_span` is producer-defined — for a
policy-driven producer it cites policy text; for a hand-author it can
be any traceable reference. The contract treats it as an opaque
string.

**C6. The contract is the boundary, not the implementation.**
Pydantic models in this contract live in `rulekit/contract/` and have
no engine imports. Engine objects are produced by a converter
(`contract/convert.py`) that translates contract models to engine
nodes. This keeps the contract loadable in environments that don't
import the engine (e.g., a UI showing a DAG visualization, an
external validator).

**C7. The contract is domain-agnostic.** It does not assume that a
determination program was derived from a policy, that there is a
reader voice, that there is a source text, or that the producer is
an LLM. Domain-specific concerns (policy text, reader voice,
abbreviation conventions) live in the producer's spec, not the
contract.

---

## Module layout

```
rulekit/contract/
  __init__.py          public API
  base.py              shared primitives (Provenance, EvaluationMode, ID types)
  atoms.py             AtomSpec, BooleanAtom, NumericAtom
  boolean.py           BooleanNode, And/Or/Not/AtLeast specs
  numeric.py           NumericNode, leaves, constants, arithmetic, conditional
  comparison.py        ComparisonNode specs (eq/lt/leq/gt/geq)
  map.py               MapSpec (atom catalog + extraction policy)
  cases.py             CaseInputSchema, TestCase
  program.py           DeterminationProgram (the top-level object)
  convert.py           contract -> engine converter; engine -> contract dumper
  validators.py        cross-model validation (atom-ref integrity, DAG acyclicity)
```

The existing `rulekit/build/decomposer.py` dataclasses are deleted.
Their consumers (`spec_to_engine_node`, `build_from_spec`,
`load_spec_from_yaml`, the typed deduplicator) are rewritten to
operate on contract models.

`BuildSpec` and `DeterminationDeclaration` survive but move into
`rulekit/build/spec.py` and explicitly do not import from
`rulekit/contract/`. They are the *input* to the LLM-driven build
process; the contract program is its *output*. The build process is
the bridge.

The existing decomposer prompts (`typed_classify_prompt.py`,
`typed_numeric_decompose_prompt.py`) and their JSON output formats
are updated to emit contract-conformant JSON directly, eliminating
one layer of translation.

---

## Primitives

### Identifiers

Two kinds of IDs are used:

- `AtomId`: a string identifier for atoms. Must match
  `^[a-zA-Z][a-zA-Z0-9_.]*$`. Unique within a `DeterminationProgram`.
  Producers may use any naming convention — dotted prefixes
  (`fcba.x`), flat snake_case (`days_since_notice`), UUIDs, anything
  matching the regex.

- `NodeId`: same regex as AtomId. Unique within a program. Assigned
  by the producer. No semantic meaning beyond identity.
  Determination roots also use this scheme.

Both are `str` subclasses with regex validators in `base.py`.

### Provenance

```python
class Provenance(str, Enum):
    TRANSCRIBED = "transcribed"   # producer drew this node directly from source
    STRUCTURAL  = "structural"    # implied by structural decomposition
    INFERRED    = "inferred"      # producer's interpretation when source is silent
```

Required on every operator node. Inferred nodes additionally require
`confidence: float` (0..1) and `latent_type: str` (free-form
classifier for the kind of inference: scope / binding / edge-case /
meta-interpretation).

The producer's choice of provenance is producer-defined. The contract
just records it.

### Evaluation Mode

```python
class EvaluationMode(str, Enum):
    CHARACTERIZED = "characterized"  # bound by extraction (typically LLM Map)
    COMPUTED      = "computed"       # deterministic code (date math, arithmetic)
    LOOKED_UP     = "looked_up"      # table or external service
```

This mirrors the current `schema.EvalMode` but is required on every
`AtomSpec` rather than carried separately on a `SchemaField`.

### Source span

`source_span: str` is mandatory on every atom and every operator
node. Empty strings allowed only when provenance is `STRUCTURAL` or
`INFERRED` — `TRANSCRIBED` nodes with empty source spans are a
validation error. The contract does not specify what a source span
contains; it's an opaque string that traces the node back to whatever
the producer was working from.

---

## Atoms

```python
class AtomSpec(BaseModel):
    id: AtomId
    statement: str                    # the proposition in natural language
    source_span: str
    atom_type: Literal["boolean", "numeric"]
    evaluation_mode: EvaluationMode
    extraction_template: Optional[str] = None    # see Map spec
    undetermined_rule: str = ""        # when this atom is UND
    notes: str = ""
```

Two cross-cutting concerns:

- `atom_type` and `evaluation_mode` are not collapsed into a single
  field because they vary independently. A numeric atom may be
  `COMPUTED` (date diff) or `CHARACTERIZED` (Map extracts a stated
  dollar amount) or `LOOKED_UP` (table lookup). A boolean atom may be
  any of the three.

- `extraction_template` is `Optional` because not every atom needs
  one. `COMPUTED` atoms supply their computation rule in `notes` or
  a separate registry; `LOOKED_UP` atoms reference an external
  service. Only `CHARACTERIZED` atoms typically carry an extraction
  template — the prompt fragment Map's narrative substrate uses to
  decide TRUE/FALSE/UND.

Two convenience subclasses, mainly for documentation and IDE help:

```python
class BooleanAtom(AtomSpec):
    atom_type: Literal["boolean"] = "boolean"

class NumericAtom(AtomSpec):
    atom_type: Literal["numeric"] = "numeric"
    numeric_unit: Optional[str] = None    # "dollars", "days", "years"
```

`numeric_unit` is advisory — it doesn't affect engine behavior — but
it gives downstream consumers (a narrator, audit reports) a place to
read the unit from rather than inferring it from the statement.

---

## Boolean nodes

Every operator node carries the audit metadata: `node_id`,
`provenance`, `surface_label`, `source_span`, `confidence` (required
iff inferred), `latent_type` (required iff inferred).

```python
class BooleanNode(BaseModel):
    node_id: NodeId
    provenance: Provenance
    surface_label: str
    source_span: str
    confidence: Optional[float] = None
    latent_type: Optional[str] = None

class AtomRef(BooleanNode):
    """A boolean leaf — references a BooleanAtom by id."""
    kind: Literal["atom_ref"] = "atom_ref"
    atom_id: AtomId

class AndNodeSpec(BooleanNode):
    kind: Literal["and"] = "and"
    children: list[NodeRef]

class OrNodeSpec(BooleanNode):
    kind: Literal["or"] = "or"
    children: list[NodeRef]

class NotNodeSpec(BooleanNode):
    kind: Literal["not"] = "not"
    child: NodeRef

class AtLeastNodeSpec(BooleanNode):
    kind: Literal["at_least"] = "at_least"
    n: int = Field(ge=1)
    children: list[NodeRef]
```

`NodeRef` is just `NodeId` (a string). Children are by-reference. The
union of all node types is `AnyNodeSpec`. The node registry on the
program maps `NodeId -> AnyNodeSpec`.

`kind` is a discriminator field for Pydantic's tagged-union
deserialization. Every node type sets it as a `Literal`. JSON
deserialization picks the right class by inspecting `kind`.

---

## Numeric nodes

```python
class NumericNodeSpec(BaseModel):
    node_id: NodeId
    surface_label: str
    source_span: str
    provenance: Provenance
    confidence: Optional[float] = None
    latent_type: Optional[str] = None

class NumericAtomRef(NumericNodeSpec):
    kind: Literal["numeric_atom_ref"] = "numeric_atom_ref"
    atom_id: AtomId

class ConstantSpec(NumericNodeSpec):
    kind: Literal["constant"] = "constant"
    # Exactly one of literal_value or constant_label set
    literal_value: Optional[Decimal] = None
    constant_label: Optional[str] = None
    # Validated by model_validator: XOR of the two

class UnaryArithmeticSpec(NumericNodeSpec):
    kind: Literal["unary_arithmetic"] = "unary_arithmetic"
    operator: Literal[
        "times_const", "plus_const", "minus_const",
        "const_minus", "div_by_const", "const_div_by",
    ]
    # Exactly one of literal_constant or constant_label set
    literal_constant: Optional[Decimal] = None
    constant_label: Optional[str] = None
    child: NodeRef    # references another numeric node

class BinaryArithmeticSpec(NumericNodeSpec):
    kind: Literal["binary_arithmetic"] = "binary_arithmetic"
    operator: Literal["plus", "minus", "mul"]
    left: NodeRef
    right: NodeRef

class VariadicArithmeticSpec(NumericNodeSpec):
    kind: Literal["variadic_arithmetic"] = "variadic_arithmetic"
    operator: Literal["sum", "max", "min"]
    children: list[NodeRef] = Field(min_length=2)

class ConditionalNumericSpec(NumericNodeSpec):
    """IF condition THEN if_true ELSE if_false.

    condition is a NodeRef to a boolean-typed node (atom_ref or
    boolean op or comparison). if_true and if_false are NodeRefs to
    numeric nodes.

    UND-conservative: when condition is UND, result is UND.
    """
    kind: Literal["conditional_numeric"] = "conditional_numeric"
    condition: NodeRef
    if_true: NodeRef
    if_false: NodeRef

class NamedQuantitySpec(NumericNodeSpec):
    """A numeric quantity whose computation is delegated to Map.

    Replaces the legitimate remaining case of the old DerivedAtomSpec
    (computation_kind="named_quantity"). The deprecated cases —
    aggregate_sum, max_of, min_of — are now expressed via
    VariadicArithmeticSpec. The deprecated `conditional` case is now
    expressed via ConditionalNumericSpec.

    Used when the producer refers to a derived quantity that requires
    document-level interpretation outside the engine's arithmetic
    vocabulary, and the institution has implemented Map-side logic to
    compute it.
    """
    kind: Literal["named_quantity"] = "named_quantity"
    atom_id: AtomId
    # The atom this references must have evaluation_mode in
    # {COMPUTED, LOOKED_UP} — validated by validators.py.
```

Constant resolution: `constant_label` references the program's
`constants: dict[str, Decimal]`. Validation checks that every
referenced label exists.

---

## Comparison nodes (bridge from numeric to boolean)

```python
class ComparisonSpec(BooleanNode):
    kind: Literal["comparison"] = "comparison"
    operator: Literal["eq", "lt", "leq", "gt", "geq"]
    left: NodeRef     # numeric node
    right: NodeRef    # numeric node
```

Sits in the boolean tree (returns Kleene), takes numeric children.
Conversion produces `EqNode` / `LtNode` / `LeqNode` / `GtNode` /
`GeqNode`.

---

## Determinations

```python
class DeterminationSpec(BaseModel):
    id: AtomId
    description: str
    polarity: Literal["positive", "negative", "neutral"] = "neutral"
    source_span: str
    composition: Literal["derived", "complement"] = "derived"
    # If composition="derived": root_node points to a boolean node in the registry
    root_node: Optional[NodeRef] = None
    # If composition="complement": linked_to names another determination,
    # and this determination's root is NOT(linked_to.root_node)
    linked_to: Optional[AtomId] = None
    determination_kind: Literal["adjudication", "routing"] = "adjudication"
    routing: Optional[RoutingLogicSpec] = None
```

Cross-model validator: exactly one of `(root_node, linked_to)` set,
matching the `composition` field. If `determination_kind="routing"`,
`routing` must be present.

Routing determinations are not substantive policy adjudications. They are
runtime routing questions over validated trigger atoms, such as whether a case
requires human review:

```python
class RoutingLogicSpec(BaseModel):
    mode: Literal["any_true"] = "any_true"
    trigger_atoms: list[AtomId] = Field(default_factory=list)
    missing_behavior: Literal["false", "undetermined"] = "false"
    conflict_behavior: Literal["true", "undetermined"] = "true"
    error_behavior: Literal["true", "undetermined"] = "true"
```

---

## Map spec

```python
class MapSpec(BaseModel):
    """How Map binds evidence to atoms.

    Atom catalog plus per-atom extraction policy. The runtime Map
    substrate consumes this; it does not own its contents.
    """
    atoms: dict[AtomId, AtomSpec]
    # Optional defaults — used when an atom doesn't specify its own template
    default_extraction_template: Optional[str] = None
    # Per-evaluation-mode handler hints (advisory; substrate-specific)
    computed_handlers: dict[AtomId, str] = Field(default_factory=dict)
    lookup_handlers: dict[AtomId, str] = Field(default_factory=dict)
```

The atom catalog is part of the Map spec, not separate from it. The
extraction template and undetermined rule travel with the atom.

---

## Case input and test cases

```python
class CaseInputSchema(BaseModel):
    """Declares what shape Map will see for cases under this program.

    The schema is part of the program. Test cases must conform to it.
    At runtime, real cases must conform to it.
    """
    has_narrative: bool = True
    structured_fields: dict[str, Literal["string", "number", "date", "bool"]] = Field(
        default_factory=dict
    )
    # The narrative field is named "narrative" by convention if has_narrative=True

class CaseInput(BaseModel):
    """A single case, conforming to the program's CaseInputSchema."""
    case_id: str
    narrative: Optional[str] = None
    structured: dict[str, Any] = Field(default_factory=dict)
    # Validation: narrative present iff schema.has_narrative;
    # structured keys subset of schema.structured_fields.

class ExpectedOutcome(BaseModel):
    determination_id: AtomId
    expected_value: Literal["true", "false", "undetermined"]
    rationale: str = ""    # what makes this the expected outcome — for audit

class TestCase(BaseModel):
    case_id: str
    input: CaseInput
    expected_outcomes: list[ExpectedOutcome]
    # Optional: expected load-bearing atoms — for sensitivity validation
    expected_load_bearing_atoms: Optional[list[AtomId]] = None
    notes: str = ""
```

A narrative-only test case has `has_narrative=True`,
`structured_fields={}`, and each `TestCase.input` carries a narrative
string. A typed test case has both: narrative plus structured fields
like `team_salary: 145000000`, `player_years_of_service: 4`. The
producer's choice of schema is part of the program,
version-controlled with it.

---

## DeterminationProgram (the top-level object)

```python
class ProgramMetadata(BaseModel):
    name: str                       # human-readable program name
    version: str                    # producer-chosen versioning scheme
    description: str = ""           # free-form
    # Producer-defined free-form fields. The contract does not interpret these.
    extras: dict[str, Any] = Field(default_factory=dict)

class ProductionRecord(BaseModel):
    """Provenance for the program itself.

    Produced by whoever made the program — an agent, a human, a
    translator. Records what was decided, what was deferred, what was
    tested. A narrator or audit tool reads this.
    """
    produced_at: datetime = Field(default_factory=datetime.utcnow)
    produced_by: str = "unknown"   # agent id, human name, "manual"
    source_revision: str = ""      # producer-defined: a policy revision, a
                                   # config version, a git SHA, etc.
    decisions: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)
    tested: list[str] = Field(default_factory=list)

class DeterminationProgram(BaseModel):
    """The complete artifact a producer ships.

    Everything needed to adjudicate cases under one set of
    determinations: the DAG (as a registry of nodes referenced by
    determinations), the Map spec (atom catalog plus extraction
    policy), the case input schema, and the test suite.
    """
    contract_version: Literal["1.0"] = "1.0"
    metadata: ProgramMetadata
    constants: dict[str, Decimal] = Field(default_factory=dict)
    # The DAG: every node by ID, referenced by determinations and other nodes
    nodes: dict[NodeId, AnyNodeSpec]
    # Atom catalog plus extraction policy — every atom referenced by nodes
    map_spec: MapSpec
    # The determinations this program adjudicates
    determinations: dict[AtomId, DeterminationSpec]
    # Case input schema and test suite
    case_input_schema: CaseInputSchema
    test_cases: list[TestCase] = Field(default_factory=list)
    # How this program was produced
    production_record: ProductionRecord = Field(default_factory=ProductionRecord)
```

Nothing in this object references a policy, a source text, a reader
voice, or the build process that may have produced it. A program
might have been hand-authored, generated by an LLM-driven build,
translated from another format, or composed from fragments. The
contract treats them identically.

---

## Validation

`validators.py` runs cross-model checks not expressible as
single-model constraints:

1. **Atom-ref integrity.** Every `AtomRef.atom_id` and
   `NumericAtomRef.atom_id` names an atom present in
   `map_spec.atoms`. Every `ComparisonSpec.left` and `.right`
   references a numeric-returning node. Every
   `AndNodeSpec.children`, etc., references a boolean-returning
   node. Conditional and arithmetic respect their typed expectations.

2. **Node-ref integrity.** Every `NodeRef` in any node's children,
   child, left, right, condition, if_true, if_false, or
   determination root_node names a node present in `nodes`.

3. **DAG acyclicity.** No cycle exists in the node graph. (The
   in-process Python references of the old layer couldn't represent
   cycles; the registry-with-IDs shape can, so this has to be
   checked.)

4. **Constant-label resolution.** Every `constant_label` in any
   `ConstantSpec` or `UnaryArithmeticSpec` names a key in
   `constants`.

5. **Determination composition.** `composition="derived"` ⇒
   `root_node` set, `linked_to` unset. `composition="complement"` ⇒
   `linked_to` set to a sibling determination, `root_node` unset.

6. **Inferred provenance ⇒ confidence and latent_type set.**

7. **Transcribed provenance ⇒ source_span non-empty.**

8. **Test-case conformance.** Every `TestCase.input` conforms to
   `case_input_schema`. Every `ExpectedOutcome.determination_id`
   names a determination in `determinations`.

9. **ID uniqueness.** Every `AtomId` appears at most once across
   `map_spec.atoms` and `determinations`. Every `NodeId` appears at
   most once across `nodes`.

10. **Evaluation-mode coherence.** Atoms referenced by
    `NamedQuantitySpec` have `evaluation_mode ∈ {COMPUTED,
    LOOKED_UP}`. Atoms referenced by `NumericAtomRef` have
    `atom_type="numeric"`. Atoms referenced by `AtomRef` have
    `atom_type="boolean"`.

11. **No orphan nodes.** Every node in `nodes` is reachable from at
    least one determination's `root_node`. Producers may want to
    ship fragments that aren't reachable yet; if so, this becomes a
    warning rather than an error. For 1.0 it's an error and
    producers suppress with an explicit flag.

Validators run as part of `DeterminationProgram.model_validate`. A
program that fails validation does not reach the engine.

---

## Conversion to engine

`contract/convert.py` provides:

```python
def program_to_engine(program: DeterminationProgram) -> EngineRuntime:
    """Convert a validated DeterminationProgram to engine objects
    ready for evaluation.

    Returns an EngineRuntime: a small holder with:
      - atoms: dict[AtomId, engine.schema.Atom]
      - determinations: dict[AtomId, engine.Determination]
      - constants: dict[str, Decimal]
      - test_cases: list[TestCase]  (carried through for the runner)
    """
```

Memoization is by node_id during conversion, so a node referenced
from two parents becomes one engine object. This is where DAG
sharing becomes real (the engine has always supported it via shared
Python references; the contract has always represented it via shared
IDs).

The reverse — `engine_to_program` — exists for a narrower purpose:
dumping a hand-built engine DAG (like FCBA refined) back to a
DeterminationProgram so the contract's round-trip test is symmetric.
Generating canonical NodeIds for hand-built nodes is mechanical
(depth-first traversal, increment counter).

---

## What this replaces

| Today (`rulekit/build/decomposer.py`)            | Contract (`rulekit/contract/`)          |
|---|---|
| `LeafSpec`                                       | `AtomRef`                                |
| `OperatorSpec`                                   | `AndNodeSpec` / `OrNodeSpec` / `NotNodeSpec` / `AtLeastNodeSpec` |
| `ComparisonSpec`                                 | `ComparisonSpec` (similar shape)        |
| `NumericLeafSpec`                                | `NumericAtomRef`                         |
| `ConstantSpec`                                   | `ConstantSpec` (similar shape)          |
| `UnaryArithmeticSpec`                            | `UnaryArithmeticSpec` (similar shape)   |
| `PlusSpec` / `MinusSpec` / `MulSpec`             | `BinaryArithmeticSpec`                   |
| `SumSpec` / `MaxSpec` / `MinSpec`                | `VariadicArithmeticSpec`                 |
| `DerivedAtomSpec(named_quantity)`                | `NamedQuantitySpec`                      |
| `DerivedAtomSpec(conditional)`                   | `ConditionalNumericSpec` (new)           |
| `DerivedAtomSpec(aggregate_sum / max_of / min_of)` | `VariadicArithmeticSpec` (consolidated) |
| `DeterminationDeclaration`                       | `DeterminationSpec`                      |
| `BuildSpec.determinations` / `.constants`        | `DeterminationProgram.determinations` / `.constants` |
| `BuildSpec` (policy_name, source, voice, abbreviation) | *stays in `build/spec.py`; not part of contract* |
| `schema.Atom` + `SchemaField` + `Schema`         | `AtomSpec` (consolidated)                |
| (none)                                           | `MapSpec`                                |
| (none)                                           | `CaseInputSchema`                        |
| (none)                                           | `TestCase`                               |
| (none)                                           | `ProductionRecord`                       |
| (none)                                           | `ConditionalNumericSpec` (engine has node, no spec) |

The old build dataclasses are removed. Their consumers are rewritten
against contract models. `BuildSpec` and `DeterminationDeclaration`
stay in `rulekit/build/` because they describe what the *build
process* needs as input — policy text path, reader voice, declared
determinations, constants. The build process produces a
`DeterminationProgram` *from* a `BuildSpec` plus its inputs. The
contract is downstream of the build.

---

## Round-trip validation target

The contract is validated against one concrete scenario:

> The FCBA refined 71-node DAG, currently hand-authored in
> `bin/test_fcba_composite_refined.py`, is re-expressed as a
> `DeterminationProgram` (manually, by reading the Python and
> writing the JSON). The program passes `model_validate` without
> error. `program_to_engine` produces an equivalent engine DAG. The
> 13 test cases run against the converted DAG via Map produce the
> same 12/13 result the hand-authored version produced.

If this round-trip succeeds, the contract is empirically adequate
for at least one real determination program.

If it fails — if the contract can't express something FCBA refined
needs, or if conversion produces a non-equivalent DAG, or if the
12/13 result changes — the contract is revised before any agent work
begins.

The round-trip is the contract's first and most important test. It
is also the point at which the choice "Pydantic in place of
dataclasses, even if unit tests regress" is justified: the test that
matters is not that the old dataclasses' tests still pass, but that
the new contract expresses real determination work.

---

## What this document doesn't yet decide

These are decisions the writing of code will surface. Listed here so
they're not surprises:

- **JSON Schema export.** Pydantic v2 can emit JSON Schema, and the
  contract should expose it as a published artifact. Whether the
  schema is generated on demand or shipped as a fixed file alongside
  the code is a packaging decision, not a contract decision.

- **Versioning.** The contract carries
  `contract_version: Literal["1.0"]`. Future versions need a
  migration story (forward-only? reversible? per-program pin?). For
  1.0, just pin and revisit.

- **Production record granularity.** The fields above are
  placeholders. When richer producers exist (agents, UIs), they will
  produce richer production records — per-stage audit, per-atom
  rationale, per-decision evidence. Extending `ProductionRecord` is
  forward-compatible.

- **Map substrate registration.** The contract specifies what Map
  needs; it doesn't specify how a substrate registers itself with a
  program. That's a runtime concern — likely a separate
  `MapSubstrate` ABC in the Map module with a factory that takes a
  `MapSpec`.

---

## What happens after this document is approved

1. Implement `rulekit/contract/` per the module layout above.
   Pydantic v2. No engine imports inside the contract module;
   converter lives separately.

2. Move `BuildSpec`, `DeterminationDeclaration`, and the
   reader-voice / policy-source machinery from `decomposer.py` into
   `rulekit/build/spec.py`. They are the build's input shape, not
   the contract's content.

3. Rewrite `spec_to_engine_node`, `build_from_spec`, and
   `load_spec_from_yaml` to operate on contract models and emit
   `DeterminationProgram` from `BuildSpec` plus its inputs.

4. Update the prompts (`typed_classify_prompt.py`,
   `typed_numeric_decompose_prompt.py`) to emit contract-conformant
   JSON. The format is close to what they emit today; the migration
   is mostly field renames.

5. Hand-author the FCBA refined DeterminationProgram. Run the
   round-trip.

6. Update unit tests against contract models. Tests written against
   `LeafSpec` / `OperatorSpec` are rewritten against `AtomRef` /
   `AndNodeSpec`. Tests that pre-built engine DAGs by hand continue
   to work without changes — they're below the contract layer.

7. Ship.

Estimated effort: a session for the contract code, a session for
migration (including the build/contract split), a session for the
FCBA round-trip and test re-greening. Three sessions, not one. The
handoff's "~Day of focused work" estimate was honest about the
contract alone but didn't see the migration cost; this is the
better number.

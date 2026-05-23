# Typed Build Pipeline — Architectural Decisions and Evidence

**Date:** 2026-05-23
**Author:** RuleKit team
**Status:** Pieces 1, 2, 5, and 6 complete (Stage-1 classifier + numeric sub-decomposer + Stage-4 typed-engine conversion + typed atom deduplication in production). End-to-end NBA Build now runs from policy text to a runnable typed engine DAG with proper atom unification across multiple determinations. Piece 7 (end-to-end NBA section build) is the next architectural milestone.

This document records the architectural decisions made during the introduction of typed atoms and comparison nodes into the RuleKit Build pipeline. Each decision is grounded in evidence from live LLM evaluation (Opus 4.7 against hand-authored eval cases).

## Background

The RuleKit Build pipeline takes policy text plus declared determinations and produces a DAG that the engine evaluates against case bundles. Until this session, Build emitted only Boolean DAGs — atoms were opaque Kleene leaves, composed by AND, OR, NOT, AT_LEAST_N. This was adequate for policies like PA (prior authorization) and FCBA (billing-error resolution), where adjudication is structural rather than quantitative.

The NBA Collective Bargaining Agreement broke this assumption. Adjudicating "is this signing legal?" requires comparing contract salary against a percentage of the salary cap, comparing contract length against integer constants, and comparing team salary against named apron levels. Opaque Boolean leaves cannot express these comparisons; the engine cannot trace through arithmetic; the LLM becomes a black-box reasoner over numerics it does not show its work for.

A typed extension to the engine (`rulekit/engine/typed.py`, 13 new node types) and a typed Map substrate (`rulekit/map/typed.py`) were added in prior work. This session extended the Build pipeline to emit typed comparison nodes.

## Evidence summary

Two live LLM eval rounds, both against Opus 4.7:

**Round 1 — Stage-1 classifier on isolated claims (20 cases, no policy context):** 20/20 structural pass.
- 5 Boolean regression cases all preserved correct classification (atomic, AND, OR, NOT, AT_LEAST_N).
- 6 single-comparison cases correctly identified with correct operator, LHS kind, and RHS kind.
- 6 arithmetic-in-RHS cases correctly tagged the RHS as `arithmetic` rather than collapsing to `constant`.
- 2 adversarial cases (numeric-containing claims that are not comparisons) correctly classified as `leaf`.
- 1 bracket pattern correctly decomposed as AND-of-two before recursing.

**Round 2 — classifier on real CBA text with policy_text context (10 cases):** 7/10 structural pass, 10/10 parse success.
- 3 failures were eval-expectation errors, not classifier errors. Each represented a case where Opus made an architecturally sound call that did not match the eval author's preconception.

**Round 3 — Piece-2 numeric sub-decomposer (17 cases):** 17/17 structural pass on top-level spec_type, 14/14 substantive pass on operator/constant/child structure (3 numeric_leaf cases have no detail to check beyond type).
- Critically: all 3 `derived_atom` cases correctly routed (aggregate_sum, max_of, named_quantity) rather than being expanded into engine-node trees. This validates Decisions 4 and 5 live.
- The nested arithmetic case (`9.12% of (cap minus prior salary)`) decomposed to three levels correctly.
- The adversarial mistagging case (description was a bare constant, kind hint said "arithmetic") was overridden by Opus's judgment — produced a `constant` spec.
- Atom ID hints stable and consistent with hand-authored fragment conventions without explicit instruction.

The Round 2 failures are the load-bearing evidence for the decisions below.

## Decision 1 — Comparison is a first-class spec type

**Decision.** Introduce `ComparisonSpec` as a sibling of `LeafSpec` and `OperatorSpec` in the build pipeline's intermediate representation. The Stage-1 classifier may emit comparison nodes alongside Boolean composition operators.

**Evidence.** Round 1 showed Opus reliably distinguishes Boolean composition from numeric comparison given clear prompt instructions. Round 2 showed this distinction holds in real CBA text. No conflation observed in 30 cases.

**Implication.** Build now produces three kinds of nodes:
- `LeafSpec` — atomic Boolean claim
- `OperatorSpec` — Boolean composition (AND / OR / NOT / AT_LEAST_N)
- `ComparisonSpec` — numeric inequality or equality

The third is deferred-terminal at this stage: classified but not yet structurally decomposed.

## Decision 2 — Comparisons are deferred-terminal until LHS/RHS sub-decomposer ships

**Decision.** When the classifier emits a `ComparisonSpec`, the build pipeline captures the operator and the free-text LHS/RHS descriptions but does not recursively decompose them. The LHS/RHS structured sub-decomposition (turning `"9.12% of the salary cap"` into `TimesConstNode(0.0912, Constant(salary_cap))`) is deferred to Piece 2 of the typed Build pipeline.

**Evidence.** Building the sub-decomposer is a self-contained future piece requiring its own eval set and live validation. Deferring it now keeps today's work scoped and reviewable.

**Implication.** `spec_to_engine_node` raises `NotImplementedError` when it encounters a `ComparisonSpec`. The error message names the spec and points to the deferred pieces. Boolean-only policies (PA, FCBA) build cleanly; typed policies (NBA) halt at conversion with a clear, traceable error.

This is intentional. Silent degradation (treating comparisons as opaque leaves) would produce engine results without the typed reasoning that motivates the architecture. Loud halt is honest.

## Decision 3 — Opus inlines definitional references; the architecture does not require a separate inlining stage

**Decision.** When a claim references a named policy quantity defined elsewhere in the policy text ("Contract salary must not exceed the Non-Taxpayer MLE limit"), the classifier will inline the definition into the RHS description ("9.12% of the salary cap"). No separate inlining or named-derived-quantity resolution stage is required.

**Evidence.** Round 2 Case 3 (definitional reference) and Case 8 (gating predicate referencing First Apron Level) both showed Opus inlining the definition into the structured RHS description:

```json
{
  "rhs_description": "Non-Taxpayer Mid-Level Salary Exception limit (9.12% of the salary cap)",
  "rhs_kind": "arithmetic"
}
```

**Implication.** The Piece 2 LHS/RHS sub-decomposer will receive descriptions with the definitions already inlined. It does not need to maintain a symbol table of named CBA constants and dereference them. This is a significant simplification of the planned work.

Risk: this finding rests on 2 cases. The sub-decomposer's eval set must include several more definitional-reference cases to confirm the pattern holds across the CBA's named quantities (Salary Cap, First Apron, Second Apron, Tax Level, MLE variants, etc.).

## Decision 4 — Aggregates are arithmetic, not leaves

**Decision.** When a claim references an aggregate quantity ("the aggregate first-year salaries of all contracts signed under this exception"), the build pipeline treats the aggregate as `arithmetic` (a SUM operation), not as a single numeric leaf.

**Evidence.** Round 2 Cases 2 and 6 both showed Opus classifying aggregate LHS as `arithmetic`:

```json
{
  "lhs_description": "aggregate first-year Salaries and Unlikely Bonuses of Player Contracts signed/acquired under the Non-Taxpayer Mid-Level Salary Exception",
  "lhs_kind": "arithmetic"
}
```

**Implication.** The Piece 2 sub-decomposer must handle aggregate (SUM-style) arithmetic, not just unary arithmetic (TIMES_CONST, PLUS_CONST). Two architectural options:

- **Option A** — extend the typed engine with a `SumNode` operator
- **Option B** — have Build recognize the aggregate pattern and emit a Map-binding instruction that produces a single derived numeric atom (the sum), then have the engine see a `NumericLeaf` for that derived atom

The hand-authored NBA fragments already use Option B for analogous derived quantities (e.g., `max_salary_ceiling`). We commit to Option B for consistency: aggregate-of-multiple-instances arithmetic lives at the Map boundary, not in the engine. The engine sees one numeric leaf per aggregate. This keeps the engine's vocabulary small and bounded.

The Build pipeline must be taught to recognize aggregate-style descriptions and emit derived-atom Map bindings instead of attempting engine arithmetic nodes. This is part of Piece 3 (aggregate handling).

## Decision 5 — Max-of-formulas is a derived numeric atom, not an engine operator

**Decision.** When a claim references a `max(a, b)` or `greater of (x, y)` formula (e.g., "the greater of 25% of the Salary Cap or 105% of prior salary"), the build pipeline treats the formula as a single derived numeric atom that Map computes, not as an engine node tree.

**Evidence.** Round 2 Case 5 (max salary formula) showed Opus classifying the entire formula as a single `arithmetic` RHS:

```json
{
  "rhs_description": "the greater of 25% of the Salary Cap or 105% of the prior contract's final-season Salary",
  "rhs_kind": "arithmetic"
}
```

The typed engine has no `max` operator. Adding one would expand the engine's vocabulary beyond unary constant arithmetic. The hand-authored `max_salary_by_yos.py` fragment uses Option B (Map computes `max_salary_ceiling` as a derived atom). We commit to this convention.

**Implication.** Same as Decision 4: Build recognizes the max-of-formulas pattern and emits Map-binding instructions. The numeric sub-decomposer (Piece 2) must distinguish "this RHS is engine-expressible arithmetic" (TIMES_CONST, PLUS_CONST, etc.) from "this RHS is a derived numeric atom" (max, aggregate, conditional formulas) and route accordingly.

This decision keeps the engine small. The cost is a more elaborate Build pipeline.

## Decision 6 — Provenance calibration is preserved across context modes

**Decision.** The classifier's `provenance` field is meaningful and is preserved across the build pipeline for downstream refinement.

**Evidence.** Round 1 showed Opus marking 2-of-20 cases as `inferred` with `confidence < 1.0` and `latent_type` set. Round 2 (with real policy text) showed all 10 cases as `transcribed` — the presence of policy text grounded Opus to commit. Both behaviors are desirable: `inferred` signals where the refinement pass should look; `transcribed` signals high-confidence direct decomposition.

**Implication.** Build's refinement stage (which currently triggers on `inferred` provenance) will fire less frequently than Round 1 results suggested when run against real policy text. The refinement pass's role is reduced but still meaningful — it will catch the genuine ambiguity cases, not the easy ones.

## Risks and open questions

1. **Decision 3 (definitional inlining) rests on 2 cases.** The pattern may not hold for less-canonical named quantities. The sub-decomposer's eval set must probe this further.

2. **The Round 2 eval contained no AT_LEAST_N cases drawn from real CBA text.** The cardinality pattern in Article II Section 7 (Higher Max Criteria) was classified as OR, which is correct for the surface text but may need AT_LEAST_N treatment for the embedded "two of three seasons" sub-pattern. This will surface again in deeper decomposition.

3. **No eval data on table-driven constants.** The CBA has multiple tables (Transaction Restrictions Table, Taxpayer MLE amounts by year). Round 2 Case 4 touched this but treated `"Applicable Apron Level"` as an opaque constant. Real Build will need to dereference these tables per operation. This is a Map-substrate concern, not a classifier concern, but it has not been validated.

4. **Decision 2 (deferred-terminal) means NBA Build is not yet runnable end-to-end.** The next sessions must land Pieces 2 and 5 before the architectural scaling claim can be empirically demonstrated.

## What changed in code

**Piece 1 (Stage-1 classifier, completed in earlier session):**

- `rulekit/build/decomposer.py`:
  - Added `ComparisonSpec` dataclass
  - `NodeSpec` union expanded to include `ComparisonSpec`
  - `_build_spec_from_parsed` now handles `type=comparison` JSON output
  - `collect_leaves` treats `ComparisonSpec` as terminal (does not recurse)
  - The Stage-1 prompt is now sourced from `typed_classify_prompt.render_prompt()` instead of the old in-module `DECOMPOSE_PROMPT.format()` (the latter remains in the module for reference but is no longer invoked)

- `rulekit/build/typed_classify_prompt.py`:
  - Was previously a separate evaluation playground; now the active production prompt

- `rulekit/schema.py`:
  - `Atom.atom_type` field added with default `"boolean"`. Set to `"numeric"` for atoms produced by ComparisonSpec sub-decomposition.

**Piece 2 (numeric sub-decomposer, completed in earlier session):**

- `rulekit/build/decomposer.py`:
  - Added four new numeric spec dataclasses: `NumericLeafSpec`, `ConstantSpec`, `UnaryArithmeticSpec`, `DerivedAtomSpec`
  - `NumericSpec` union type defined over the four
  - `ComparisonSpec` extended with `lhs_spec: Optional[NumericSpec]` and `rhs_spec: Optional[NumericSpec]` fields
  - New function `decompose_numeric_expression(description, kind, state)` — invokes the sub-decomposer prompt and returns a NumericSpec
  - New function `_build_numeric_spec_from_parsed(parsed, state)` — recursive JSON parser for sub-decomposer responses
  - The comparison branch of `_build_spec_from_parsed` now immediately calls `decompose_numeric_expression` for LHS and RHS, returning a fully-expanded `ComparisonSpec`

- `rulekit/build/typed_numeric_decompose_prompt.py`:
  - New module with the validated sub-decomposer prompt
  - Used by `decompose_numeric_expression` at runtime

- `tests/eval_typed_decomposer/`:
  - `eval_cases_sub_decomposer.json` — 17 eval cases covering all four spec types
  - `eval_sub_decomposer.py` — eval runner with offline/live modes
  - `mock_responses_sub_decomposer.json` — 17/17 mock-pass validation of scoring logic
  - `sub_decomposer_responses.json` — live response artifacts from Opus 4.7 (17/17 architecturally sound)

**Piece 5 (Stage-4 typed-engine conversion, completed in earlier session):**

- `rulekit/build/decomposer.py`:
  - Added imports for typed engine nodes (NumericLeaf, Constant, all six arithmetic nodes, all five comparison nodes) and Decimal
  - New helper `_to_decimal_constant(value)` — converts JSON int/float/str to Decimal via `str()` to avoid float-binary representation errors (e.g. `Decimal(0.0912)` would yield `Decimal('0.0912000000000000058...')`; `Decimal(str(0.0912))` yields the clean `Decimal('0.0912')`). Also handles dollar signs and commas in string form.
  - New function `_numeric_spec_to_engine_node(spec, atoms, constants)` — recursive converter from NumericSpec to engine numeric node. Handles all four numeric spec types (NumericLeafSpec, ConstantSpec, UnaryArithmeticSpec, DerivedAtomSpec). DerivedAtomSpec records its `computation_kind` in the atom's `notes` field for Map to consult at extraction time.
  - `spec_to_engine_node` extended with optional `constants: dict[str, Decimal]` parameter. The ComparisonSpec branch now performs the full conversion: builds engine numeric subtrees for LHS and RHS via `_numeric_spec_to_engine_node`, then wraps in the corresponding comparison node (LeqNode, LtNode, GeqNode, GtNode, EqNode). Boolean policies (PA, FCBA) are unaffected — they pass an empty constants registry or omit it entirely.

- `tests/test_typed_engine_conversion.py`:
  - 69 unit tests covering: Decimal coercion, all four NumericSpec→engine paths, all six unary arithmetic operators, three-level nested arithmetic, all five comparison operators, integration with surrounding Boolean structure, end-to-end FactBundle evaluation producing TRUE/FALSE/UND, Boolean-only spec compatibility.

**Piece 6 (typed atom deduplication, completed in this session):**

- `rulekit/build/decomposer.py`:
  - New `NUMERIC_DEDUP_PROMPT` — analog of `DEDUP_PROMPT` specialized for numeric atom equivalence
  - New function `collect_numeric_specs(spec)` — walks a NodeSpec tree to find every `NumericLeafSpec` and `DerivedAtomSpec`. Recurses into `ComparisonSpec` LHS/RHS and into `UnaryArithmeticSpec` children. Does NOT collect `ConstantSpec` (constants are not atoms) or `LeafSpec` (Boolean dedup handles those separately).
  - New helper `_atom_class_key(spec)` — returns the dedup scoping key. NumericLeafSpec atoms get key `"numeric_leaf"`. DerivedAtomSpec atoms get key `"derived:{computation_kind}"` — different computation_kinds (aggregate_sum vs max_of vs named_quantity) NEVER merge.
  - New helper `_make_canonical_id(abbreviation, hint, taken)` — produces readable `{abbreviation}.{snake_case_hint}` atom IDs. On collision (same hint chosen for two distinct concepts), disambiguates with a numeric suffix.
  - New function `deduplicate_numeric_atoms(specs, llm, abbreviation)` — runs class-scoped LLM dedup. One call per class with multiple atoms; singleton classes skip the LLM entirely. Assigns canonical `atom_id` to every NumericLeafSpec and DerivedAtomSpec.
  - The `_numeric_spec_to_engine_node` already prefers `atom_id` over `atom_id_hint` (from Piece 5), so after this dedup pass, `spec_to_engine_node` produces engine `NumericLeaf` nodes that share canonical atom IDs across all comparisons in the DAG.

- `tests/test_typed_atom_dedup.py`:
  - 35 unit tests covering: tree walking through every spec type, class-key scoping (Boolean vs numeric vs computation_kind), canonical-id naming and collision handling, singleton-skip-LLM behavior, equivalence-group merging, non-equivalence preservation, and the load-bearing end-to-end test that confirms dedup + Stage-4 produce a single unified atom in the engine registry from two equivalent input atoms.

## What did not change

- The Boolean engine (`rulekit/engine/boolean.py`) is untouched.
- The typed engine (`rulekit/engine/typed.py`) is untouched.
- The Boolean Map substrate (`rulekit/map/boolean.py`) is untouched.
- The typed Map substrate (`rulekit/map/typed.py`) is untouched.
- The 137 unit tests covering the above all continue to pass.
- PA and FCBA Build pipelines continue to work end-to-end (they emit only Boolean nodes).

## Next pieces, in order

1. **Piece 7 — End-to-end NBA section build.** Run the full pipeline (Stage-1 + Sub-decomposer + Dedup + Stage-4) on a small CBA section (e.g., Article VII Section 6(e), Non-Taxpayer MLE) plus multiple determinations exercising the same atoms (so dedup actually fires). Compare the auto-built DAG to the hand-authored `mle_selection.py` fragment. The gap is the prompt-engineering work for subsequent sessions.

2. **Piece 8 — Full NBA build.** Same pipeline against Article VII Sections 6(d), 6(e), 6(f), and Section 8 — the four MLE flavors plus trade rules. Atom dedup carries cross-section equivalence (team_salary appears in many places).

3. **Piece 9 — NBA adapter runner.** The runner that takes a RuleArena case, calls Map to bind atoms, evaluates the DAG, and emits the standard answer/illegal_op/problematic_team tuple.

4. **Piece 10 — Benchmark measurement.** Run the adapter against RuleArena Levels 1, 2, 3. Compute Acc(t), per-rule precision. Compare RuleKit-typed vs direct-Opus baseline.

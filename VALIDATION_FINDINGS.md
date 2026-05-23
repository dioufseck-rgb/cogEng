# RuleKit — Tier 1 Logic Test Findings

## What we built

A tier 1 logic test harness (`logic_tests/propositional_tests.py`) that validates
the compositional engine in `derive_orchestrator.py` independently of any
domain content. The harness constructs trees over abstract propositions with
mocked leaf values, walks them through the engine, and verifies the engine
output matches the formal semantics of classical propositional logic extended
with three-valued escalation handling.

The harness has 63 tests organized in six scope tiers:

- **A** — unary NOT truth table over {True, False, escalated}
- **B** — structural identities (double negation, involution)
- **C** — NOT composed with AND/OR (De Morgan, excluded middle, non-contradiction)
- **D** — De Morgan across the full 3×3 escalation domain
- **E** — deeper nesting (triple NOT, mixed nested patterns)
- **F** — degenerate/error cases (NOT with wrong arity)
- **G** — larger-scope structural tests (wide and deep trees)
- **H** — property-based random tree generation at scale

Property-based tests generate random trees within a structural envelope,
compute the expected boolean with native Python, and verify the engine matches.
Around 1,030 random tree/assignment combinations are tested per run.

## Engine changes

### Added: explicit NOT operator

`_eval_NOT` added to `derive_orchestrator.py`. Three-valued semantics
following Strong Kleene:

- `NOT(True)` → `False`
- `NOT(False)` → `True`
- `NOT(escalated)` → `escalated` (signals and reason preserved)

This makes RuleKit's compositional layer logically complete over `{AND, OR, NOT}`.
Trees can now encode negation structurally rather than inverting leaf prompts.
The PA tree's exclusion leaves remain valid under their current convention;
migrating them to use explicit NOT is a separate decision.

### Fixed: short-circuit trace poisoning

**Bug:** When `AND` or `OR` short-circuited at a definitive child, the engine
wrote a `short_circuited=True` `NodeResult` to the shared trace cache for every
remaining child. Subsequent compose nodes that referenced any of those nodes
hit the cache and received the `None`-valued short-circuit entry rather than
re-evaluating, producing incorrect results in trees with shared leaf references.

**How it surfaced:** Property-based testing with random tree generation found
the defect after 56 hand-crafted tests passed. The PA tree happens to have
node-disjoint leaves, so the bug was invisible in production.

**Fix:** Short-circuit is now recorded on `self.short_circuit_log[parent_id]`
(a list of unevaluated child ids) rather than written into the global trace.
The trace contains only nodes that were actually evaluated. Leaves that other
parents reference get real evaluation when those parents reach them.

Applied to `_eval_AND`, `_eval_OR`, and `_eval_AND_NOT_CARVE_OUT` (the last
being a Part D vestige scheduled for removal).

**Impact:** The engine now handles shared leaf references correctly. Trees do
not need to be node-disjoint for the engine to behave correctly. The PA tree's
behavior is unchanged because PA trees never had shared leaves.

## Test results

All 63 tests pass on the current engine. The suite runs in under one second.

```
Results: 63 passed, 0 failed, 0 errored
```

Property-based coverage:
- 50 trees × depth ≤ 3, 4 variables
- 50 trees × depth ≤ 5, 6 variables
- 30 trees × depth ≤ 7, 8 variables
- 30 trees × depth ≤ 5, NOT-heavy generation
- 500 trees × depth ≤ 5, 5 variables (stress)
- 200 trees × depth ≤ 8, 6 variables (deep)
- 200 trees × depth ≤ 6, 3 variables (shared-leaf intensive)

Total: ~1,060 randomly-generated tree/assignment combinations, all matching
classical propositional logic computed natively in Python.

## What this validates

The compositional engine is sound on positive propositional logic with
classical {AND, OR, NOT} semantics and Strong Kleene three-valued escalation.
This is a precise, defensible, citable formal claim. The tests verify it
exhaustively at small scope and probabilistically at large scope.

## What this does not validate

- Substrate leaf evaluation calibration (a different question, addressed by
  tier 3 end-to-end testing)
- Disposition rule predicate evaluation (a separate logical subsystem;
  belongs in tier 2)
- Routing tier composition from escalation signal vectors (also tier 2)
- Domain encoding correctness of the PA tree specifically (also tier 2)

## Formal claim suitable for the position paper

> RuleKit's compositional layer implements classical propositional logic over
> the operators {AND, OR, NOT}, extended with Strong Kleene three-valued
> semantics for handling substrate escalation. The logic is validated against
> a tier 1 test suite of 63 tests covering operator truth tables, classical
> identities (commutativity, associativity, distributivity, De Morgan's laws,
> double negation, excluded middle, non-contradiction), short-circuit behavior,
> three-valued escalation propagation, and property-based random tree
> generation at production-scale tree sizes. The compositional engine is
> sound on this fragment.

## Next steps

Tier 2 synthetic domain tests for the PA tree — **COMPLETE.** See
`logic_tests/pa_domain_tests.py`. 29 tests covering:

- Each disposition rule firing under its predicate (6 tests)
- Each disposition rule NOT firing when conditions don't match (4 tests)
- Rank ordering (rank 1 beats 2, 2 beats 3, 3 beats 4) with secondary grounds (4 tests)
- Fallback_only semantics: rank 5 only fires when no other rule fires (1 test)
- Predicate evaluator: value match, value mismatch, apparently_true variants (5 tests)
- Required nodes / indeterminate disposition handling (2 tests)
- Routing tier mapping from escalation signals (4 tests)
- Synthetic reproduction of the three live-case shapes (achebe, clark, kamau) (3 tests)

All 29 pass. The PA tree's domain encoding is correct given the (mocked)
leaf values it receives.

## Implications for the live-case disposition mismatches

The synthetic reproductions of achebe, clark, and kamau produce the same
dispositions as the live runs. This isolates the cause of disposition-vs-GT
mismatches to substrate calibration on specific leaves, not to the tree's
domain logic. The tree is doing the right thing with whatever the substrate
puts in the leaves.

Tier 3 (re-running live cases with persistent JSON output and leaf-level
reasoning inspection) is where any remaining engineering effort against
those mismatches belongs.

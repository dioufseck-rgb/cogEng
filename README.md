# RuleKit

A typed Kleene engine for regulated adjudication. Neuro-symbolic policy reasoning where the LLM is a constrained extractor at the boundary and the engine handles structural composition over typed atoms.

## What it does

Regulated decisions — prior authorization, billing dispute adjudication, NBA roster moves, tax filings, mortgage underwriting — share a common reasoning shape: categorical determinations, conjunctive requirements, disjunctive pathways, and quantitative thresholds. RuleKit handles all four ingredients in a single architecture:

- **Build** turns policy text plus declared determinations into a DAG of typed atoms composed by AND, OR, NOT, AT-LEAST-N, comparison operators, and constant arithmetic
- **Map** binds case evidence to atom values via focused LLM extraction (one atom at a time, not free-form reasoning over the whole rule set)
- **Engine** evaluates the DAG deterministically, propagating Kleene three-valued logic (TRUE/FALSE/UNDETERMINED) through both Boolean and numeric layers

The engine is small and bounded. The architectural commitment is that LLMs do what they are good at (reading text, extracting values) while the engine does what it is good at (composing trusted operators with auditable traces).

## Package layout

```
rulekit/                      core package
  engine/
    boolean.py                Kleene-Boolean: AND/OR/NOT/AT-LEAST-N over Leaf atoms
    typed.py                  numeric atoms + constant arithmetic + comparison nodes
  schema.py                   atom typing declarations
  build/                      DAG construction pipeline
    extract.py                A1 atom extraction (the Extract primitive at policy level)
    decomposer.py             top-down DAG decomposition from declared determinations
    refinement.py             atom-level refinement pass

  map/                        evidence-to-atom binding
    boolean.py                NarrativeLLMSubstrate (Boolean atoms only)
    typed.py                  TypedNarrativeLLMSubstrate (Boolean + Numeric)

bin/                          workflow scripts
  build_dag.py                run the build pipeline against a determination spec
  run_cases.py                Map + Evaluate against case files
  inspect_built.py            introspection helper for built DAGs
  evaluate_built.py           end-to-end demonstration

domains/                      per-domain artifacts
  voices.py                   reader-voice registry
  pa/                         Prior Authorization (cervical spinal surgery)
  fcba/                       FCBA Section 1026.13 (billing-error disputes)
  nba/                        NBA CBA (Article II Section 7, Section 8(e), Section 6(j))
    fragments/                hand-authored typed DAGs validating the four worst Opus 4.7 failure modes

experiments/                  comparison-study machinery
  harness/                    multi-system comparison runner
  baselines/                  direct-LLM baselines
  tools/                      head-to-head utilities

tests/                        test suite
  test_engine_boolean.py      Boolean engine harness
  test_engine_typed.py        69 unit tests over the typed engine
  test_extract.py             A1 extraction test (offline LLM fixture)
  test_map_typed.py           31 unit tests over the typed Map substrate
  test_nba_fragments.py       37 NBA fragment cases across the four families
  fixtures/                   cached LLM responses for offline tests

docs/                         architecture and protocol documentation
```

## Quick start

```bash
# Run the typed-engine and substrate unit tests (no LLM required)
python tests/test_engine_typed.py
python tests/test_map_typed.py
python tests/test_nba_fragments.py

# Run the A1 extraction test (uses cached LLM fixture)
python tests/test_extract.py
```

## Build pipeline

The surviving build path is the top-down decomposer (`rulekit/build/decomposer.py`). The institution declares its determinations in a YAML spec; the decomposer recursively asks the LLM to decompose each declared determination against the policy text, then deduplicates equivalent atoms across determinations into a DAG.

```bash
python bin/build_dag.py domains/pa/determinations.yaml --out built_pa.pkl
python bin/run_cases.py built_pa.pkl domains/pa/cases/pa_*.yaml
```

## NBA fragments

`domains/nba/fragments/` contains four hand-authored DAGs that demonstrate the typed engine on the rule families where Opus 4.7 has the worst per-rule precision on RuleArena Level 3:

- `mle_selection.py` — Mid-Level Exception flavor selection (the canonical rule-confusion failure)
- `max_salary_by_yos.py` — Maximum Annual Salary by Years of Service with Higher Max gating (the Higher Max over-firing failure at P=0.083)
- `sign_and_trade.py` — Sign-and-Trade with team-role attribution (the case-0 misattribution failure)
- `trade_matching.py` — Traded Player Exception including aggregated TPE (the P=0.0 family)

Each fragment exposes `build_fragment()` and `cases()`. `tests/test_nba_fragments.py` runs all 37 cases across the four fragments.

## Documentation

- `docs/ARCHITECTURE.md` — the full architecture description
- `docs/PROTOCOL.md` — the comparison-study protocol
- `docs/README_OLD.md` — the pre-restructure README, kept for reference

## Status

The build pipeline (Path 2) and Boolean engine are stable. The typed-engine extension and typed Map substrate are recent (May 2026), validated via 137 unit tests plus 37 NBA fragment cases. The Build pipeline does not yet emit typed atoms; that's the next piece of work (Stage 1 decomposer learns to identify numeric atoms; Stage 4 engine conversion emits typed nodes).

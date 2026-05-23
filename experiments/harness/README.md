# Comparison Study — How to Apply the Protocol

This directory contains the harness for executing the RuleKit vs.
Direct-LLM comparison study specified in `PROTOCOL.md`.

The protocol is pre-registered. The harness is built to honor it. Do
not modify metrics, criteria, or analysis logic mid-study without
documenting an amendment in PROTOCOL.md Appendix C.

## Dependencies

```bash
# From the repo root:
pip install -r requirements.txt
```

That installs `anthropic` (the LLM SDK) and `PyYAML`. Everything else
is Python stdlib. Tested on Python 3.10+.

Set your API key before running anything that calls the LLM:

```bash
export ANTHROPIC_API_KEY=sk-...
```

## Order of operations

### 1. Freeze the source code (Protocol Section 2.1)

Commit the current state of:
- `rulekit/decomposer.py`
- `rulekit/refinement.py`
- `rulekit/map_primitive.py`
- `rulekit/engine.py`
- `baselines/direct_llm.py`
- `harness/run_study.py`
- `harness/analyze.py`

Record the git ref(s) in PROTOCOL.md Section 2.1.

### 2. Author the case bank (Protocol Section 3)

Cases live in `bank/policy1/`, `bank/policy2/`, `bank/policy3/` (and
`bank/validation/`).

Per policy:
- 20 main cases (2 per level, levels 1-10)
- 10 adversarial cases (5 RuleKit-targeting, 5 LLM-targeting)
- 5 validation cases (for prompt selection)

Total: 35 cases per policy × 3 policies = 105 cases.

Case YAML schema in `bank/_template.yaml`.

### 3. Select Policy 3 (Protocol Section 3.1)

Candidate criteria: nesting depth ≥4, at least one AT-LEAST-N with N≥3.
Add to `harness/policy_config.yaml` and to `policies/voices.py`.

### 4. Select the direct-LLM baseline prompt (Section 4)

```bash
python harness/select_prompt.py \
    --validation-dir bank/validation \
    --policy-config harness/policy_config.yaml
```

Produces `baselines/direct_llm_prompt.txt` (frozen).
Selection record at `baselines/direct_llm_prompt_selection.json`.

### 5. Pilot phase (Section 8)

```bash
python harness/run_study.py --phase build --pilot
python harness/run_study.py --phase run --pilot
python harness/analyze.py
```

This runs 1 policy, 1 build, 3 cases through both systems. Review
output. Verify all records validate. Fix any harness bugs before main.

### 6. Main experiment (Section 5)

```bash
python harness/run_study.py --phase build
python harness/run_study.py --phase run
```

This takes time: 3 builds × 3 policies = 9 RuleKit builds. Each build
runs ~150 LLM calls (~5 min). Then 3 policies × 30 cases × 3 runs =
270 RuleKit runs and 270 direct-LLM runs.

Total wall-clock: maybe 4-6 hours with serial execution; less with
parallelism.

Total LLM cost: ~$100-150 at Opus pricing.

Use `--resume` to continue from interruption. Records are immutable;
existing records are skipped.

### 7. Analyze (Section 6 & 7)

```bash
python harness/analyze.py
```

Produces:
- `analysis/tables/*.csv` — per-metric tables
- `analysis/criteria.json` — pre-registered criteria pass/fail
- `analysis/report.md` — readable summary

### 8. Traceability scoring (Section 6.4)

After main runs complete, the traceability matching judge scores each
record's load-bearing identification against case annotations:

```bash
python harness/score_traceability.py   # to be implemented
```

This populates the C4 criterion in `analysis/criteria.json`.

### 9. Manual validation of judge (Section 9.3)

Author manually reviews 10 randomly-sampled (case, system) pairs.
Computes Cohen's kappa against judge labels. If kappa < 0.6, judge
is replaced with manual scoring throughout.

## Pre-flight checks before main run

- [ ] Protocol committed at frozen git ref
- [ ] Case bank complete and second-reviewed
- [ ] Policy 3 sourced (or deviation documented)
- [ ] Validation cases authored (5 per policy)
- [ ] Baseline prompt selected and frozen
- [ ] Pilot phase passed (Section 8 acceptance criteria)
- [ ] LLM API key set in environment
- [ ] Disk space for ~1000 result JSON files

## What changes mid-experiment

Per Protocol Section 9 and Appendix C:

- Bug fixes to the harness: document in Appendix C, fix, restart
  affected runs.
- Metric/criterion modifications: not permitted. Reported as
  exploratory if added; pre-registered criteria stand regardless.
- Case modifications: not permitted. New cases would be a new study.
- Prompt modifications: not permitted within this study.

## What is OK to do post-hoc

- Additional analyses beyond Section 6, labeled clearly as
  exploratory.
- Additional cases as a follow-up study, with new protocol
  documentation.
- Sub-group analyses (by policy, by level, by case_class). The
  protocol-defined aggregate criteria still hold.

## Files

```
harness/
  timed_llm.py            — LLM caller wrapper with timing/tokens
  select_prompt.py        — Section 4 prompt selection
  run_study.py            — Section 5 main runner
  analyze.py              — Section 6/7 metrics and criteria
  policy_config.yaml      — policy declarations
  README.md               — this file

baselines/
  direct_llm.py           — direct-LLM baseline + 3 candidate prompts
  direct_llm_prompt.txt   — frozen winner (after select_prompt.py runs)
  direct_llm_prompt_selection.json — selection record

bank/
  _template.yaml          — case YAML template
  policy1/*.yaml          — PA cases
  policy2/*.yaml          — FCBA cases
  policy3/*.yaml          — Policy 3 cases (TBD)
  validation/*.yaml       — validation cases for prompt selection

results/
  builds/                 — pickled DAGs + build metadata
  runs/                   — per-evaluation JSON records
  _run_summary_*.json     — per-execution summaries

analysis/
  tables/*.csv            — per-metric tables
  criteria.json           — pre-registered criteria status
  report.md               — analysis report
```

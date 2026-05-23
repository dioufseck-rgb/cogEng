#!/usr/bin/env bash
#
# execute_study.sh — Orchestrates the full RuleKit comparison study per PROTOCOL.md.
#
# This script runs each protocol phase in order with explicit checkpoints.
# At each checkpoint the user must confirm before the next phase runs.
# This prevents an interrupted re-run from blowing through expensive phases
# (builds, main experiment) without inspection.
#
# Each phase logs to study_logs/<timestamp>/<phase>.log so a failed phase
# can be inspected without re-running.
#
# Usage:
#   ./execute_study.sh                  # run full protocol with checkpoints
#   ./execute_study.sh --auto           # run without checkpoints (CI mode)
#   ./execute_study.sh --from <phase>   # resume from a phase (skip earlier)
#   ./execute_study.sh --only <phase>   # run only one phase, then exit
#   ./execute_study.sh --pilot          # pilot only (1 policy, 1 build, 3 cases)
#   ./execute_study.sh --dry-run        # show what would run without running
#
# Phases (in order):
#   preflight       — verify prerequisites
#   select_prompt   — pick the direct-LLM baseline prompt (Section 4)
#   build           — generate k_build builds per policy (Section 5.1)
#   pilot           — small-N pilot verifying harness end-to-end (Section 8)
#   main            — main experimental runs (Section 5.2)
#   analyze         — compute metrics and criteria (Section 6/7)
#   traceability    — score traceability F1 (Section 6.4) [optional]
#   report          — render the final report

set -e
set -u
set -o pipefail

# -----------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PHASES=(preflight select_prompt build pilot main analyze traceability report)
LOG_ROOT="study_logs"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${LOG_ROOT}/${TIMESTAMP}"
mkdir -p "$LOG_DIR"

# Defaults
AUTO=0
PILOT_ONLY=0
DRY_RUN=0
FROM_PHASE=""
ONLY_PHASE=""

# -----------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------

usage() {
    grep '^#' "$0" | sed 's/^# \?//' | head -25
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --auto)        AUTO=1; shift ;;
        --pilot)       PILOT_ONLY=1; shift ;;
        --dry-run)     DRY_RUN=1; shift ;;
        --from)        FROM_PHASE="$2"; shift 2 ;;
        --only)        ONLY_PHASE="$2"; shift 2 ;;
        --help|-h)     usage ;;
        *) echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

c_blue()   { printf '\033[34m%s\033[0m' "$*"; }
c_green()  { printf '\033[32m%s\033[0m' "$*"; }
c_yellow() { printf '\033[33m%s\033[0m' "$*"; }
c_red()    { printf '\033[31m%s\033[0m' "$*"; }
c_bold()   { printf '\033[1m%s\033[0m' "$*"; }

header() {
    echo
    echo "================================================================"
    c_bold "  $1"; echo
    echo "================================================================"
}

checkpoint() {
    local prompt="$1"
    if [[ $AUTO -eq 1 ]]; then
        echo "[auto] proceeding past checkpoint: $prompt"
        return 0
    fi
    echo
    c_yellow "CHECKPOINT: $prompt"; echo
    read -r -p "  Continue? (y/N) " response
    case "$response" in
        y|Y|yes|YES) ;;
        *) c_red "Aborting at user request."; echo; exit 0 ;;
    esac
}

run_or_show() {
    local description="$1"; shift
    local cmd=("$@")
    echo
    c_blue ">>> ${description}"; echo
    echo "    $ ${cmd[*]}"
    if [[ $DRY_RUN -eq 1 ]]; then
        c_yellow "    [dry-run, not executing]"; echo
        return 0
    fi
    "${cmd[@]}"
}

# -----------------------------------------------------------------------
# Phase: preflight
# -----------------------------------------------------------------------

phase_preflight() {
    header "PHASE: preflight — verifying prerequisites"

    local fail=0

    # Source files frozen?
    if [[ ! -d .git ]]; then
        c_yellow "  WARNING: not a git repo; source freeze (Protocol Section 2.1) not verifiable"; echo
    else
        local head_ref
        head_ref=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
        echo "  Git HEAD: $head_ref"
        if ! git diff --quiet 2>/dev/null; then
            c_yellow "  WARNING: working tree has uncommitted changes; freeze before main run"; echo
        fi
    fi

    # Required files
    local required=(
        "PROTOCOL.md"
        "harness/run_study.py"
        "harness/analyze.py"
        "harness/select_prompt.py"
        "harness/timed_llm.py"
        "harness/policy_config.yaml"
        "baselines/direct_llm.py"
        "rulekit/decomposer.py"
        "rulekit/refinement.py"
        "rulekit/map_primitive.py"
        "rulekit/engine.py"
    )
    for f in "${required[@]}"; do
        if [[ ! -f "$f" ]]; then
            c_red "  MISSING: $f"; echo
            fail=1
        fi
    done

    # Case bank
    local n_validation
    n_validation=$(find bank/validation -name '*.yaml' 2>/dev/null | wc -l | tr -d ' ')
    local n_main
    n_main=$(find bank/policy1 bank/policy2 bank/policy3 -name '*.yaml' 2>/dev/null | wc -l | tr -d ' ')
    echo "  Validation cases: $n_validation (target: 15 for 3 policies)"
    echo "  Main + adversarial cases: $n_main (target: 90 for 3 policies)"

    if [[ $PILOT_ONLY -eq 1 ]]; then
        # Pilot tolerates empty validation set (uses P2 default) but needs
        # at least one main case to evaluate against.
        if [[ $n_main -lt 1 ]]; then
            c_red "  No main cases in bank/policy*/. Pilot needs at least one"; echo
            c_red "  case to evaluate against. Author one main case per the"; echo
            c_red "  Section 3.5 schema (template at bank/_template.yaml)."; echo
            fail=1
        fi
    else
        # Main experiment: validation set required for prompt selection,
        # full main bank required for the experiment itself.
        if [[ $n_validation -lt 5 ]]; then
            c_red "  Validation set must have ≥5 cases per Protocol Section 4"; echo
            c_red "  (used for direct-LLM prompt selection). You have $n_validation."; echo
            c_red "  Run with --pilot to skip this requirement, or author cases."; echo
            fail=1
        fi
        if [[ $n_main -lt 6 ]]; then
            c_red "  Main bank must have ≥6 cases (target: 90 across 3 policies)"; echo
            c_red "  per Protocol Section 3. You have $n_main."; echo
            c_red "  Run with --pilot to skip this requirement, or author cases."; echo
            fail=1
        fi
    fi

    # API key
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        c_red "  MISSING: ANTHROPIC_API_KEY environment variable not set"; echo
        fail=1
    else
        echo "  ANTHROPIC_API_KEY: set"
    fi

    # Disk space
    local avail_kb
    avail_kb=$(df -k . | awk 'NR==2 {print $4}')
    local avail_mb=$((avail_kb / 1024))
    echo "  Disk available: ${avail_mb} MB"
    if [[ $avail_mb -lt 500 ]]; then
        c_yellow "  WARNING: less than 500 MB available; results may not fit"; echo
    fi

    # Python deps
    if ! python -c "import yaml" 2>/dev/null; then
        c_red "  MISSING: PyYAML"; echo
        echo "           Install: pip install -r requirements.txt"
        fail=1
    fi
    if ! python -c "import anthropic" 2>/dev/null; then
        c_yellow "  WARNING: anthropic SDK not importable"; echo
        echo "           Install: pip install -r requirements.txt"
        echo "           (Only required for live LLM runs; offline tests work without it)"
    fi

    if [[ $fail -eq 1 ]]; then
        c_red "  preflight FAILED. Fix the issues above before continuing."; echo
        return 1
    fi

    c_green "  preflight OK"; echo
}

# -----------------------------------------------------------------------
# Phase: select_prompt
# -----------------------------------------------------------------------

phase_select_prompt() {
    header "PHASE: select_prompt — Section 4 baseline prompt selection"

    local n_validation
    n_validation=$(find bank/validation -name '*.yaml' 2>/dev/null | wc -l | tr -d ' ')

    if [[ $n_validation -lt 1 ]]; then
        if [[ $PILOT_ONLY -eq 1 ]]; then
            c_yellow "  No validation cases in bank/validation."; echo
            c_yellow "  Pilot will use default prompt (P2 structured)."; echo
            c_yellow "  For main experiment, author 5 validation cases per policy"; echo
            c_yellow "  and re-run: python harness/select_prompt.py"; echo
            return 0
        else
            c_red "  No validation cases in bank/validation."; echo
            c_red "  Main experiment requires the baseline prompt to be selected"; echo
            c_red "  from a validation set per Protocol Section 4. Author validation"; echo
            c_red "  cases (5 per policy) and re-run."; echo
            return 1
        fi
    fi

    if [[ -f baselines/direct_llm_prompt.txt ]]; then
        echo "  baselines/direct_llm_prompt.txt already exists."
        if [[ -f baselines/direct_llm_prompt_selection.json ]]; then
            echo "  Existing selection record:"
            python -c "import json; d=json.load(open('baselines/direct_llm_prompt_selection.json')); print(f'    selected: {d[\"selected_prompt\"]} at {d[\"timestamp_utc\"]}')"
        fi
        checkpoint "Re-run prompt selection? (will overwrite frozen prompt)"
    fi

    run_or_show "Selecting baseline prompt on validation set" \
        python harness/select_prompt.py \
            --validation-dir bank/validation \
            --policy-config harness/policy_config.yaml \
            --output-dir baselines/

    if [[ -f baselines/direct_llm_prompt_selection.json && $DRY_RUN -eq 0 ]]; then
        echo
        echo "  Selection record:"
        python -c "
import json
d = json.load(open('baselines/direct_llm_prompt_selection.json'))
print(f'    Winner: {d[\"selected_prompt\"]}')
for r in d['validation_results']:
    print(f'    {r[\"prompt_id\"]}: case_acc={r[\"case_accuracy\"]:.3f}, det_acc={r[\"det_accuracy\"]:.3f}')
"
    fi
}

# -----------------------------------------------------------------------
# Phase: build
# -----------------------------------------------------------------------

phase_build() {
    header "PHASE: build — Section 5.1 (k_build=3 per policy)"

    if [[ -d results/builds ]]; then
        local n_existing
        n_existing=$(find results/builds -name '*.pkl' 2>/dev/null | wc -l | tr -d ' ')
        if [[ $n_existing -gt 0 ]]; then
            echo "  Existing builds: $n_existing"
            checkpoint "Resume (skip existing builds) instead of rebuilding?"
            local resume_flag="--resume"
        else
            local resume_flag=""
        fi
    else
        local resume_flag=""
    fi

    local pilot_flag=""
    [[ $PILOT_ONLY -eq 1 ]] && pilot_flag="--pilot"

    run_or_show "Running builds (this can take ~5min per build × 3 builds × N policies)" \
        python harness/run_study.py --phase build $resume_flag $pilot_flag

    if [[ $DRY_RUN -eq 0 ]]; then
        echo
        echo "  Build summary:"
        for f in results/builds/*.meta.json; do
            [[ -f "$f" ]] || continue
            python -c "
import json
d = json.load(open('$f'))
print(f'    {d[\"policy_id\"]} build {d[\"build_n\"]}: '
      f'{d.get(\"n_atoms\",0)} atoms, {d.get(\"n_llm_calls\",0)} LLM calls, '
      f'{d.get(\"wall_clock_s\",0):.0f}s, \${d.get(\"cost_usd\",0):.2f}')
"
        done
    fi
}

# -----------------------------------------------------------------------
# Phase: pilot
# -----------------------------------------------------------------------

phase_pilot() {
    header "PHASE: pilot — Section 8 acceptance check"

    if [[ -d results/runs ]]; then
        local n_existing
        n_existing=$(find results/runs -name '*.json' ! -name '_*' 2>/dev/null | wc -l | tr -d ' ')
        if [[ $n_existing -gt 0 ]]; then
            c_yellow "  WARNING: results/runs already has $n_existing records."; echo
            checkpoint "Run pilot anyway (resume; existing records skipped)?"
        fi
    fi

    run_or_show "Pilot run (1 policy, 1 build, 3 cases × 2 systems × 3 runs)" \
        python harness/run_study.py --phase run --pilot --resume

    # Acceptance check
    if [[ $DRY_RUN -eq 0 ]]; then
        echo
        echo "  Pilot acceptance check:"
        local n_records
        n_records=$(find results/runs -name '*.json' ! -name '_*' 2>/dev/null | wc -l | tr -d ' ')
        echo "    Records written: $n_records (target: 18)"
        if [[ $n_records -lt 18 ]]; then
            c_red "    ACCEPTANCE FAILED: fewer than 18 pilot records"; echo
            return 1
        fi
        c_green "    Pilot record count OK"; echo

        # Try running analyze on pilot data to verify the pipeline
        echo
        c_blue "  Running analyze.py on pilot data..."; echo
        if python harness/analyze.py 2>&1 | tail -5; then
            c_green "    Analysis pipeline OK"; echo
        else
            c_red "    ACCEPTANCE FAILED: analyzer errored on pilot data"; echo
            return 1
        fi
    fi
}

# -----------------------------------------------------------------------
# Phase: main
# -----------------------------------------------------------------------

phase_main() {
    header "PHASE: main — Section 5.2 main experiment"

    c_yellow "  This phase runs the full matrix:"; echo
    echo "    3 policies × 3 builds × 30 cases × 3 runs (RuleKit) = 810 evaluations"
    echo "    3 policies × 30 cases × 3 runs (Direct LLM)        = 270 evaluations"
    echo "  Estimated wall-clock: 4-6 hours"
    echo "  Estimated LLM cost: \$100-150 at Opus pricing"

    checkpoint "Proceed with main experiment?"

    run_or_show "Main experiment (resume mode; skips completed records)" \
        python harness/run_study.py --phase run --resume

    if [[ $DRY_RUN -eq 0 ]]; then
        local n_records
        n_records=$(find results/runs -name '*.json' ! -name '_*' 2>/dev/null | wc -l | tr -d ' ')
        echo
        echo "  Total records after main: $n_records"
    fi
}

# -----------------------------------------------------------------------
# Phase: analyze
# -----------------------------------------------------------------------

phase_analyze() {
    header "PHASE: analyze — Section 6/7 metrics and criteria"

    run_or_show "Computing metrics and pre-registered criteria" \
        python harness/analyze.py

    if [[ $DRY_RUN -eq 0 && -f analysis/criteria.json ]]; then
        echo
        echo "  Criteria summary:"
        python -c "
import json
d = json.load(open('analysis/criteria.json'))
criteria = d['criteria']
for cid, c in criteria.items():
    if cid.startswith('_'):
        continue
    status = c.get('supported')
    sym = '✓' if status is True else '✗' if status is False else '?'
    print(f'    {sym} {cid}: supported={status}')
s = criteria.get('_summary', {})
print(f'    Summary: {s.get(\"n_supported\",0)}/{s.get(\"n_evaluated\",0)} criteria supported')
print(f'    Architecture supported: {s.get(\"architecture_supported\", False)}')
"
    fi
}

# -----------------------------------------------------------------------
# Phase: traceability (optional, separate)
# -----------------------------------------------------------------------

phase_traceability() {
    header "PHASE: traceability — Section 6.4 matching judge"

    if [[ ! -f harness/score_traceability.py ]]; then
        c_yellow "  harness/score_traceability.py not yet implemented; skipping."; echo
        c_yellow "  Per Protocol Section 6.4, C4 criterion remains deferred."; echo
        return 0
    fi

    run_or_show "Scoring traceability F1 across all records" \
        python harness/score_traceability.py
}

# -----------------------------------------------------------------------
# Phase: report
# -----------------------------------------------------------------------

phase_report() {
    header "PHASE: report — final outputs"

    if [[ -f analysis/report.md ]]; then
        echo "  Report at: analysis/report.md"
        if [[ $DRY_RUN -eq 0 ]]; then
            echo
            echo "  --- report.md (excerpt) ---"
            head -40 analysis/report.md
            echo "  --- (truncated) ---"
        fi
    else
        c_yellow "  No report yet. Run analyze first."; echo
    fi

    if [[ -d analysis/tables ]]; then
        echo
        echo "  Tables produced:"
        ls -1 analysis/tables/ 2>/dev/null | sed 's/^/    /'
    fi
}

# -----------------------------------------------------------------------
# Main dispatch
# -----------------------------------------------------------------------

# Validate from/only against known phases
validate_phase() {
    local p="$1"
    for known in "${PHASES[@]}"; do
        [[ "$p" == "$known" ]] && return 0
    done
    c_red "Unknown phase: $p"; echo
    echo "Known phases: ${PHASES[*]}"
    exit 1
}

[[ -n "$FROM_PHASE" ]] && validate_phase "$FROM_PHASE"
[[ -n "$ONLY_PHASE" ]] && validate_phase "$ONLY_PHASE"

# Build the phase list to actually execute
phases_to_run=()
if [[ -n "$ONLY_PHASE" ]]; then
    phases_to_run=("$ONLY_PHASE")
elif [[ -n "$FROM_PHASE" ]]; then
    found=0
    for p in "${PHASES[@]}"; do
        if [[ $found -eq 1 || "$p" == "$FROM_PHASE" ]]; then
            phases_to_run+=("$p")
            found=1
        fi
    done
else
    if [[ $PILOT_ONLY -eq 1 ]]; then
        phases_to_run=(preflight select_prompt build pilot analyze report)
    else
        phases_to_run=("${PHASES[@]}")
    fi
fi

# Report intent
header "EXECUTION PLAN"
echo "  Timestamp: $TIMESTAMP"
echo "  Log dir:   $LOG_DIR"
echo "  Mode:      $([[ $AUTO -eq 1 ]] && echo 'auto' || echo 'interactive')"
echo "  Pilot:     $([[ $PILOT_ONLY -eq 1 ]] && echo 'yes' || echo 'no')"
echo "  Dry run:   $([[ $DRY_RUN -eq 1 ]] && echo 'yes' || echo 'no')"
echo "  Phases:    ${phases_to_run[*]}"

if [[ $AUTO -eq 0 && $DRY_RUN -eq 0 ]]; then
    echo
    c_yellow "  Press Ctrl+C now to abort. Otherwise press Enter to begin."; echo
    read -r
fi

# Execute phases
overall_start=$(date +%s)
for phase in "${phases_to_run[@]}"; do
    phase_log="${LOG_DIR}/${phase}.log"
    echo
    c_bold "[$(date -u +%H:%M:%SZ)] Starting phase: $phase (log: $phase_log)"; echo

    # Tee output to phase log
    if "phase_${phase}" 2>&1 | tee "$phase_log"; then
        c_green "  phase $phase: OK"; echo
    else
        c_red "  phase $phase: FAILED (exit=$?)"; echo
        echo "  See log: $phase_log"
        exit 1
    fi
done

overall_end=$(date +%s)
overall_elapsed=$((overall_end - overall_start))
mins=$((overall_elapsed / 60))
secs=$((overall_elapsed % 60))

header "EXECUTION COMPLETE"
echo "  Elapsed: ${mins}m ${secs}s"
echo "  Logs:    $LOG_DIR"
echo "  Outputs:"
echo "    results/builds/      — pickled DAGs + metadata"
echo "    results/runs/        — per-evaluation JSON records"
echo "    analysis/tables/     — per-metric CSV tables"
echo "    analysis/criteria.json — pre-registered criteria pass/fail"
echo "    analysis/report.md   — narrative report"
echo
c_bold "Review the report before drawing conclusions."; echo

"""
analyze.py — Protocol Sections 6 (metrics) and 7 (criteria) implementation.

Reads all evaluation records from results/runs/, computes each metric
specified in Section 6, and reports each success criterion from Section 7
with its statistical test result.

Produces:
  - analysis/tables/*.csv: per-metric tables stratified per protocol
  - analysis/figures/*.png: optional plots
  - analysis/report.md: a markdown report integrating all results
  - analysis/criteria.json: machine-readable record of pass/fail per criterion

The analyzer is read-only with respect to results/; it does not mutate
any evaluation record.

Usage:
    python harness/analyze.py
    python harness/analyze.py --results-dir results/runs/ --output-dir analysis/
"""

from __future__ import annotations
import argparse
import sys
import os
import json
import csv
import glob
import math
from collections import defaultdict
from itertools import combinations

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)


# -----------------------------------------------------------------------
# Loading
# -----------------------------------------------------------------------

def load_records(results_dir: str) -> list[dict]:
    """Load all evaluation JSON records from results dir."""
    paths = sorted(glob.glob(os.path.join(results_dir, "*.json")))
    records = []
    for p in paths:
        # Skip non-record files (summaries, errors)
        fname = os.path.basename(p)
        if fname.startswith("_"):
            continue
        try:
            with open(p) as f:
                data = json.load(f)
            if "case_id" in data and "system" in data:
                records.append(data)
        except Exception as e:
            print(f"[WARN] could not load {p}: {e}")
    return records


def normalize_det(v) -> str:
    """Normalize a determination value to canonical string form."""
    if v is None:
        return "undetermined"
    s = str(v).strip().lower()
    if s in ("true", "t", "yes", "approved"):
        return "true"
    if s in ("false", "f", "no", "denied"):
        return "false"
    return "undetermined"


def case_fully_correct(record: dict) -> bool:
    """A record is 'fully correct' if every expected det matches actual."""
    expected = record.get("expected_outcomes", {})
    actual = record.get("determinations", {})
    for det_id, exp in expected.items():
        if normalize_det(actual.get(det_id)) != normalize_det(exp):
            return False
    return True


# -----------------------------------------------------------------------
# Section 6.1 — Correctness
# -----------------------------------------------------------------------

def correctness_per_case(records: list[dict]) -> dict:
    """
    For each (system, policy, case, difficulty) tuple, compute the mean
    correctness across runs and builds.
    """
    # Group: (system, policy, case_id) -> list of full-correctness booleans
    grouped = defaultdict(list)
    meta = {}  # carries difficulty_level and case_class
    for r in records:
        key = (r["system"], r["policy"], r["case_id"])
        grouped[key].append(case_fully_correct(r))
        meta[key] = {
            "difficulty_level": r.get("difficulty_level"),
            "case_class": r.get("case_class", "main"),
        }

    rows = []
    for key, correct_list in grouped.items():
        sys_, policy, case_id = key
        rows.append({
            "system": sys_,
            "policy": policy,
            "case_id": case_id,
            "difficulty_level": meta[key]["difficulty_level"],
            "case_class": meta[key]["case_class"],
            "n_runs": len(correct_list),
            "n_correct": sum(correct_list),
            "correctness": sum(correct_list) / len(correct_list) if correct_list else 0.0,
        })
    return rows


def correctness_by_strata(per_case_rows: list[dict]) -> dict:
    """Aggregate per-case correctness by (system, policy, level)."""
    by = defaultdict(list)
    for r in per_case_rows:
        if r["case_class"] != "main":
            continue
        key = (r["system"], r["policy"], r["difficulty_level"])
        by[key].append(r["correctness"])

    rows = []
    for key, vals in sorted(by.items()):
        rows.append({
            "system": key[0],
            "policy": key[1],
            "difficulty_level": key[2],
            "n_cases": len(vals),
            "mean_correctness": sum(vals) / len(vals) if vals else 0.0,
        })
    return rows


# -----------------------------------------------------------------------
# Section 6.2 — Consistency across runs
# -----------------------------------------------------------------------

def consistency_per_case(records: list[dict]) -> list[dict]:
    """
    For each (system, policy, case, build), compute the proportion of run
    pairs that agree on every determination.
    """
    # Group by (system, policy, case_id, build_id) -> list of determinations dicts
    grouped = defaultdict(list)
    meta = {}
    for r in records:
        key = (r["system"], r["policy"], r["case_id"], r.get("build_id"))
        grouped[key].append({did: normalize_det(v) for did, v in r["determinations"].items()})
        meta[key] = {"difficulty_level": r.get("difficulty_level"),
                     "case_class": r.get("case_class", "main")}

    rows = []
    for key, dets_list in grouped.items():
        if len(dets_list) < 2:
            continue
        pairs = list(combinations(dets_list, 2))
        agree = sum(1 for (a, b) in pairs if a == b)
        rows.append({
            "system": key[0],
            "policy": key[1],
            "case_id": key[2],
            "build_id": key[3],
            "difficulty_level": meta[key]["difficulty_level"],
            "case_class": meta[key]["case_class"],
            "n_pairs": len(pairs),
            "n_agreeing": agree,
            "agreement": agree / len(pairs) if pairs else 0.0,
        })
    return rows


# -----------------------------------------------------------------------
# Section 6.3 — Architectural stability across builds (RuleKit only)
# -----------------------------------------------------------------------

def stability_per_case(records: list[dict]) -> list[dict]:
    """
    For each (policy, case_id), compute across-build determination stability.
    Per protocol Section 6.3: for each pair of builds, compare modal
    determinations.
    """
    # Group by (policy, case_id) -> {build_id: [determinations]}
    grouped = defaultdict(lambda: defaultdict(list))
    meta = {}
    for r in records:
        if r["system"] != "rulekit":
            continue
        key = (r["policy"], r["case_id"])
        bid = r.get("build_id")
        grouped[key][bid].append({did: normalize_det(v) for did, v in r["determinations"].items()})
        meta[key] = {"difficulty_level": r.get("difficulty_level"),
                     "case_class": r.get("case_class", "main")}

    rows = []
    for key, by_build in grouped.items():
        builds = list(by_build.keys())
        if len(builds) < 2:
            continue
        # Compute modal determination per build
        modals = {}
        for bid, dets_list in by_build.items():
            modals[bid] = _modal_det(dets_list)
        # Count agreeing build pairs
        pairs = list(combinations(builds, 2))
        agree = sum(1 for (a, b) in pairs if modals[a] == modals[b])
        rows.append({
            "policy": key[0],
            "case_id": key[1],
            "difficulty_level": meta[key]["difficulty_level"],
            "case_class": meta[key]["case_class"],
            "n_builds": len(builds),
            "n_pairs": len(pairs),
            "n_agreeing": agree,
            "stability": agree / len(pairs) if pairs else 0.0,
            "modals": modals,
        })
    return rows


def _modal_det(dets_list: list[dict]) -> dict:
    """Return modal determination across runs (per det_id)."""
    if not dets_list:
        return {}
    det_ids = list(dets_list[0].keys())
    result = {}
    for did in det_ids:
        values = [d.get(did, "undetermined") for d in dets_list]
        # Mode: most common; ties broken by undetermined > false > true
        from collections import Counter
        c = Counter(values)
        max_count = max(c.values())
        candidates = [v for v, n in c.items() if n == max_count]
        if len(candidates) == 1:
            result[did] = candidates[0]
        else:
            # Tiebreak: prefer undetermined (most conservative)
            for pref in ("undetermined", "false", "true"):
                if pref in candidates:
                    result[did] = pref
                    break
    return result


# -----------------------------------------------------------------------
# Section 6.6 — Runtime and cost
# -----------------------------------------------------------------------

def runtime_aggregate(records: list[dict], builds_meta: list[dict]) -> dict:
    """Aggregate runtime metrics per protocol Section 6.6."""
    # Per-case latency by (system, level)
    by_strata = defaultdict(list)
    by_system = defaultdict(list)
    for r in records:
        if r.get("case_class") != "main":
            continue
        key = (r["system"], r.get("difficulty_level"))
        by_strata[key].append(r["wall_clock_seconds"])
        by_system[r["system"]].append({
            "wall_clock_seconds": r["wall_clock_seconds"],
            "total_input_tokens": r["total_input_tokens"],
            "total_output_tokens": r["total_output_tokens"],
            "cost_usd": r["cost_usd"],
        })

    strata_rows = []
    for key, lats in sorted(by_strata.items()):
        lats_sorted = sorted(lats)
        strata_rows.append({
            "system": key[0],
            "difficulty_level": key[1],
            "n": len(lats),
            "p50_latency_s": _percentile(lats_sorted, 50),
            "p95_latency_s": _percentile(lats_sorted, 95),
            "mean_latency_s": sum(lats) / len(lats) if lats else 0.0,
        })

    # Build cost / time totals (RuleKit only)
    rk_build_total_s = sum(b.get("wall_clock_s", 0) for b in builds_meta)
    rk_build_total_cost = sum(b.get("cost_usd", 0) for b in builds_meta)
    n_builds_total = len(builds_meta)
    mean_build_time_s = rk_build_total_s / n_builds_total if n_builds_total else 0.0
    mean_build_cost = rk_build_total_cost / n_builds_total if n_builds_total else 0.0

    # Mean per-case cost/time per system
    sys_stats = {}
    for sys_, cases in by_system.items():
        n = len(cases)
        sys_stats[sys_] = {
            "n_records": n,
            "mean_latency_s": sum(c["wall_clock_seconds"] for c in cases) / n if n else 0.0,
            "mean_cost_usd": sum(c["cost_usd"] for c in cases) / n if n else 0.0,
            "mean_input_tokens": sum(c["total_input_tokens"] for c in cases) / n if n else 0.0,
            "mean_output_tokens": sum(c["total_output_tokens"] for c in cases) / n if n else 0.0,
        }

    # Crossover analysis
    M = sys_stats.get("rulekit", {}).get("mean_latency_s", 0)
    D = sys_stats.get("direct_llm", {}).get("mean_latency_s", 0)
    rk_cost = sys_stats.get("rulekit", {}).get("mean_cost_usd", 0)
    llm_cost = sys_stats.get("direct_llm", {}).get("mean_cost_usd", 0)

    crossover_runtime = None
    if D > M and mean_build_time_s > 0:
        crossover_runtime = math.ceil(mean_build_time_s / (D - M))
    crossover_cost = None
    if llm_cost > rk_cost and mean_build_cost > 0:
        crossover_cost = math.ceil(mean_build_cost / (llm_cost - rk_cost))

    return {
        "by_strata": strata_rows,
        "by_system": sys_stats,
        "build_phase": {
            "n_builds": n_builds_total,
            "total_wall_s": rk_build_total_s,
            "mean_wall_s": mean_build_time_s,
            "total_cost_usd": rk_build_total_cost,
            "mean_cost_usd": mean_build_cost,
        },
        "crossover_runtime_n_cases": crossover_runtime,
        "crossover_cost_n_cases": crossover_cost,
    }


def _percentile(sorted_list: list[float], pct: float) -> float:
    if not sorted_list:
        return 0.0
    k = (len(sorted_list) - 1) * pct / 100
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_list[int(k)]
    return sorted_list[f] + (sorted_list[c] - sorted_list[f]) * (k - f)


# -----------------------------------------------------------------------
# Section 7 — Statistical tests
# -----------------------------------------------------------------------

def mcnemar_test(b: int, c: int) -> dict:
    """
    McNemar's test (continuity-corrected) on paired binary data.
    b = cases where system A is correct and B is wrong;
    c = cases where B is correct and A is wrong.
    """
    n = b + c
    if n == 0:
        return {"chi2": 0.0, "p": 1.0, "n_discordant": 0,
                "rationale": "no discordant pairs"}
    # Continuity-corrected statistic
    chi2 = (abs(b - c) - 1) ** 2 / n if n > 0 else 0.0
    p = _chi2_sf(chi2, df=1)
    return {"chi2": chi2, "p": p, "n_discordant": n, "b": b, "c": c}


def _chi2_sf(x: float, df: int = 1) -> float:
    """Approximate survival function of chi-squared with df=1."""
    # For df=1, P(X^2 > x) = 2 * P(Z > sqrt(x)) = erfc(sqrt(x/2))
    if df != 1 or x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2))


def wilcoxon_signed_rank(diffs: list[float]) -> dict:
    """
    Wilcoxon signed-rank on paired differences. Returns the test statistic
    W and an approximate p-value (normal approximation; exact for small N
    is omitted for simplicity).
    """
    nonzero = [d for d in diffs if d != 0]
    n = len(nonzero)
    if n == 0:
        return {"W": 0.0, "p": 1.0, "n": 0, "rationale": "all differences zero"}
    abs_sorted = sorted([(abs(d), i, d) for i, d in enumerate(nonzero)])
    # Average ranks for ties
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs_sorted[j + 1][0] == abs_sorted[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[abs_sorted[k][1]] = avg_rank
        i = j + 1
    W_plus = sum(r for r, (_, _, d) in zip(ranks, abs_sorted) if d > 0)
    W_minus = sum(r for r, (_, _, d) in zip(ranks, abs_sorted) if d < 0)
    W = min(W_plus, W_minus)
    # Normal approximation
    mean = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24
    z = (W - mean) / math.sqrt(var) if var > 0 else 0
    p = 2 * (1 - _phi(abs(z)))
    return {"W": W, "W_plus": W_plus, "W_minus": W_minus,
            "z": z, "p": p, "n": n}


def _phi(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def welch_t_test(a: list[float], b: list[float]) -> dict:
    """Welch's two-sample t-test. Returns t and approximate p."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return {"t": 0.0, "p": 1.0, "na": na, "nb": nb,
                "rationale": "insufficient sample size"}
    ma = sum(a) / na
    mb = sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    if va == 0 and vb == 0:
        return {"t": 0.0, "p": 1.0, "rationale": "no variance in either group"}
    se = math.sqrt(va / na + vb / nb)
    t = (ma - mb) / se if se > 0 else 0
    # Welch-Satterthwaite df
    if va == 0:
        df = nb - 1
    elif vb == 0:
        df = na - 1
    else:
        df = (va / na + vb / nb) ** 2 / (
            (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
        )
    # Approximate p via normal for large df (no exact t-CDF here)
    p = 2 * (1 - _phi(abs(t)))
    return {"t": t, "p": p, "df": df, "mean_a": ma, "mean_b": mb,
            "se": se}


# -----------------------------------------------------------------------
# Section 7 criteria evaluation
# -----------------------------------------------------------------------

def evaluate_criteria(per_case_correctness: list[dict],
                      consistency: list[dict],
                      stability: list[dict],
                      runtime: dict) -> dict:
    """
    Evaluate each of C1-C6 per Protocol Section 7 and report supported /
    not supported / ambiguous with rationale.
    """
    results = {}

    # C1 — Correctness, McNemar paired
    rk_by_case = {(r["policy"], r["case_id"]): r["correctness"]
                  for r in per_case_correctness
                  if r["system"] == "rulekit" and r["case_class"] == "main"}
    llm_by_case = {(r["policy"], r["case_id"]): r["correctness"]
                   for r in per_case_correctness
                   if r["system"] == "direct_llm" and r["case_class"] == "main"}
    paired_keys = set(rk_by_case) & set(llm_by_case)
    # Discordant pairs: per-case fully-correct vs not
    b = sum(1 for k in paired_keys if rk_by_case[k] >= 0.5 and llm_by_case[k] < 0.5)
    c = sum(1 for k in paired_keys if rk_by_case[k] < 0.5 and llm_by_case[k] >= 0.5)
    mcn = mcnemar_test(b, c)
    rk_acc = sum(rk_by_case[k] for k in paired_keys) / len(paired_keys) if paired_keys else 0
    llm_acc = sum(llm_by_case[k] for k in paired_keys) / len(paired_keys) if paired_keys else 0
    diff = rk_acc - llm_acc
    results["C1_correctness"] = {
        "rk_accuracy": rk_acc,
        "llm_accuracy": llm_acc,
        "difference": diff,
        "n_paired_cases": len(paired_keys),
        "mcnemar": mcn,
        "supported": diff > 0 and mcn["p"] < 0.05,
        "supported_rationale": (
            f"RuleKit acc {rk_acc:.3f} {'>' if diff > 0 else '≤'} "
            f"Direct-LLM acc {llm_acc:.3f}; McNemar p={mcn['p']:.4f}"
        ),
    }

    # C2 — Consistency, Wilcoxon paired
    rk_consistency = {(r["policy"], r["case_id"]): r["agreement"]
                      for r in consistency
                      if r["system"] == "rulekit" and r["case_class"] == "main"}
    llm_consistency = {(r["policy"], r["case_id"]): r["agreement"]
                       for r in consistency
                       if r["system"] == "direct_llm" and r["case_class"] == "main"}
    # Pair by case; if RuleKit has multiple builds per case, average them.
    rk_avg = defaultdict(list)
    for r in consistency:
        if r["system"] == "rulekit" and r["case_class"] == "main":
            rk_avg[(r["policy"], r["case_id"])].append(r["agreement"])
    rk_pair = {k: sum(v)/len(v) for k, v in rk_avg.items()}
    paired = set(rk_pair) & set(llm_consistency)
    diffs = [rk_pair[k] - llm_consistency[k] for k in paired]
    wsr = wilcoxon_signed_rank(diffs)
    mean_diff = sum(diffs) / len(diffs) if diffs else 0
    results["C2_consistency"] = {
        "rk_mean_agreement": sum(rk_pair[k] for k in paired) / len(paired) if paired else 0,
        "llm_mean_agreement": sum(llm_consistency[k] for k in paired) / len(paired) if paired else 0,
        "mean_difference": mean_diff,
        "n_paired_cases": len(paired),
        "wilcoxon": wsr,
        "supported": mean_diff > 0 and wsr["p"] < 0.05,
        "supported_rationale": (
            f"Mean diff {mean_diff:+.3f}; Wilcoxon p={wsr['p']:.4f}"
        ),
    }

    # C3 — Architectural stability ≥ 0.80, Welch vs Direct-LLM agreement
    rk_stab = [r["stability"] for r in stability if r["case_class"] == "main"]
    rk_stab_mean = sum(rk_stab) / len(rk_stab) if rk_stab else 0
    llm_agreement_vals = [r["agreement"] for r in consistency
                          if r["system"] == "direct_llm" and r["case_class"] == "main"]
    welch = welch_t_test(rk_stab, llm_agreement_vals)
    results["C3_stability"] = {
        "rk_mean_stability": rk_stab_mean,
        "llm_mean_agreement": welch.get("mean_b", 0),
        "n_rk_cases": len(rk_stab),
        "n_llm_cases": len(llm_agreement_vals),
        "welch": welch,
        "supported": (rk_stab_mean >= 0.80 and welch["p"] < 0.05
                       and welch.get("mean_a", 0) > welch.get("mean_b", 0)),
        "supported_rationale": (
            f"RuleKit stability {rk_stab_mean:.3f} (target ≥0.80); "
            f"Welch p={welch['p']:.4f}"
        ),
    }

    # C4 — Traceability ≥ 0.80, paired Wilcoxon
    # (Requires the matching judge; placeholder while traceability scoring
    # is not yet implemented at this stage.)
    results["C4_traceability"] = {
        "supported": None,
        "supported_rationale": (
            "Traceability scoring requires matching-judge implementation "
            "(harness/traceability.py, planned). Run after main experiment "
            "completes and run `python harness/score_traceability.py` to "
            "populate this criterion."
        ),
    }

    # C5 — Monotonicity (simple proxy: correlation between difficulty and correctness)
    rk_diff = [(r["difficulty_level"], r["correctness"])
               for r in per_case_correctness
               if r["system"] == "rulekit" and r["case_class"] == "main"
               and r["difficulty_level"] is not None]
    llm_diff = [(r["difficulty_level"], r["correctness"])
                for r in per_case_correctness
                if r["system"] == "direct_llm" and r["case_class"] == "main"
                and r["difficulty_level"] is not None]
    rk_slope = _linreg_slope(rk_diff)
    llm_slope = _linreg_slope(llm_diff)
    results["C5_monotonicity"] = {
        "rk_correctness_slope": rk_slope,
        "llm_correctness_slope": llm_slope,
        "supported": None,  # Requires full regression with CIs
        "supported_rationale": (
            f"RK slope={rk_slope['slope']:.4f}, LLM slope={llm_slope['slope']:.4f}; "
            f"95% CI computation requires full regression — see analysis/criteria.json."
        ),
    }

    # C6 — Amortization: runtime crossover < 100 cases
    runtime_crossover = runtime.get("crossover_runtime_n_cases")
    results["C6_amortization"] = {
        "runtime_crossover_n_cases": runtime_crossover,
        "cost_crossover_n_cases": runtime.get("crossover_cost_n_cases"),
        "supported": (runtime_crossover is not None and runtime_crossover < 100),
        "supported_rationale": (
            f"Runtime crossover at N={runtime_crossover}; "
            f"target N<100" if runtime_crossover is not None
            else "Direct LLM not slower than RuleKit; no crossover."
        ),
    }

    # Summary: number of supported criteria
    n_supported = sum(1 for k, v in results.items() if v.get("supported") is True)
    n_evaluated = sum(1 for k, v in results.items() if v.get("supported") is not None)
    results["_summary"] = {
        "n_supported": n_supported,
        "n_evaluated": n_evaluated,
        "architecture_supported": n_supported >= 5,
        "interpretation": (
            "≥5 of 6 criteria supported"
            if n_supported >= 5
            else "Architecture not fully supported by these criteria"
        ),
    }
    return results


def _linreg_slope(pairs: list[tuple]) -> dict:
    """Simple OLS slope of y on x with n, mean, slope, intercept."""
    if not pairs:
        return {"slope": 0.0, "intercept": 0.0, "n": 0}
    n = len(pairs)
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    num = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    den = sum((p[0] - mx) ** 2 for p in pairs)
    slope = num / den if den else 0
    intercept = my - slope * mx
    return {"slope": slope, "intercept": intercept, "n": n}


# -----------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------

def write_csv(path: str, rows: list[dict]):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Collect all keys observed
    keys = list({k for r in rows for k in r.keys() if not isinstance(r[k], (dict, list))})
    keys.sort()
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in keys})


def write_markdown_report(criteria: dict, runtime: dict, output_path: str):
    lines = ["# RuleKit vs Direct-LLM Comparison — Analysis Report\n"]
    lines.append("This report is generated by `harness/analyze.py` from raw\n"
                 "evaluation records. The criteria and tests are pre-registered\n"
                 "in `PROTOCOL.md`.\n")

    summary = criteria.get("_summary", {})
    lines.append(f"\n## Summary\n")
    lines.append(f"- Criteria supported: {summary.get('n_supported', 0)}/{summary.get('n_evaluated', 0)}\n")
    lines.append(f"- Architecture supported: **{summary.get('architecture_supported', False)}**\n")
    lines.append(f"- Interpretation: {summary.get('interpretation', '')}\n")

    lines.append("\n## Criteria Detail\n")
    for cid, c in criteria.items():
        if cid.startswith("_"):
            continue
        status = c.get("supported")
        status_str = ("SUPPORTED" if status is True
                      else "NOT SUPPORTED" if status is False
                      else "AMBIGUOUS / DEFERRED")
        lines.append(f"\n### {cid} — {status_str}\n")
        lines.append(f"{c.get('supported_rationale', '')}\n")

    lines.append("\n## Runtime Summary\n")
    bp = runtime.get("build_phase", {})
    lines.append(f"- Builds: n={bp.get('n_builds', 0)}, "
                 f"mean wall {bp.get('mean_wall_s', 0):.1f}s, "
                 f"mean cost ${bp.get('mean_cost_usd', 0):.3f}\n")
    by_sys = runtime.get("by_system", {})
    for sys_, stats in by_sys.items():
        lines.append(f"- {sys_}: mean latency {stats['mean_latency_s']:.1f}s, "
                     f"mean cost ${stats['mean_cost_usd']:.4f}\n")
    lines.append(f"- Runtime crossover: N={runtime.get('crossover_runtime_n_cases')}\n")
    lines.append(f"- Cost crossover: N={runtime.get('crossover_cost_n_cases')}\n")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.writelines(lines)


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze RuleKit comparison study results per PROTOCOL.md"
    )
    parser.add_argument("--results-dir", default="results/runs/")
    parser.add_argument("--builds-dir", default="results/builds/")
    parser.add_argument("--output-dir", default="analysis/")
    args = parser.parse_args()

    print(f"Loading records from {args.results_dir}...")
    records = load_records(args.results_dir)
    print(f"  Loaded {len(records)} evaluation records")

    builds_meta = []
    for p in sorted(glob.glob(os.path.join(args.builds_dir, "*.meta.json"))):
        with open(p) as f:
            builds_meta.append(json.load(f))
    print(f"  Loaded {len(builds_meta)} build metadata records")

    if not records:
        print("No records found — nothing to analyze.")
        return

    # Compute all per-case and aggregated metrics
    per_case_correctness = correctness_per_case(records)
    by_strata = correctness_by_strata(per_case_correctness)
    consistency = consistency_per_case(records)
    stability = stability_per_case(records)
    runtime = runtime_aggregate(records, builds_meta)

    # Tables
    tables_dir = os.path.join(args.output_dir, "tables")
    write_csv(os.path.join(tables_dir, "correctness_per_case.csv"), per_case_correctness)
    write_csv(os.path.join(tables_dir, "correctness_by_strata.csv"), by_strata)
    write_csv(os.path.join(tables_dir, "consistency_per_case.csv"), consistency)
    write_csv(os.path.join(tables_dir, "stability_per_case.csv"), stability)
    write_csv(os.path.join(tables_dir, "runtime_by_strata.csv"), runtime["by_strata"])

    # Criteria
    criteria = evaluate_criteria(per_case_correctness, consistency, stability, runtime)
    criteria_path = os.path.join(args.output_dir, "criteria.json")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(criteria_path, "w") as f:
        json.dump({"criteria": criteria, "runtime": runtime}, f, indent=2)

    # Markdown report
    report_path = os.path.join(args.output_dir, "report.md")
    write_markdown_report(criteria, runtime, report_path)

    print(f"\nAnalysis complete. Outputs:")
    print(f"  Tables: {tables_dir}")
    print(f"  Criteria: {criteria_path}")
    print(f"  Report: {report_path}")
    summary = criteria.get("_summary", {})
    print(f"\nSummary: {summary.get('n_supported', 0)}/{summary.get('n_evaluated', 0)} criteria supported")


if __name__ == "__main__":
    main()

"""
run_study.py — Protocol Section 5 implementation.

Orchestrates the full comparison study:

  1. Build phase (RuleKit only): k_build builds per policy, saved as
     pickle artifacts in results/builds/.

  2. Run phase: for each (policy, case, system, build_or_run_n, run_number),
     execute the system on the case and record a JSON evaluation record
     per protocol Section 5.3.

  3. Aggregate phase: walk the results/ directory and validate that
     every (policy, case, system, run) combination has a record. Report
     missing or errored records.

Usage:
    python harness/run_study.py --phase build
    python harness/run_study.py --phase run --pilot   # 1 policy, 3 cases, 1 build
    python harness/run_study.py --phase run           # full main experiment

Records are immutable. Each record is written exactly once. If the
runner crashes mid-way, it can be re-run with --resume; existing records
are not overwritten.
"""

from __future__ import annotations
import argparse
import sys
import os
import json
import time
import glob
import pickle
import socket
import platform
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(os.path.dirname(_HERE))  # nested → project root
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

import yaml

from rulekit.build.decomposer import LLMCaller, build_from_spec, BuildSpec, DeterminationDeclaration
from rulekit.engine import Kleene
from rulekit.map.boolean import NarrativeLLMSubstrate, map_case_to_bundle
from experiments.harness.timed_llm import TimedLLMCaller, compute_cost_usd
from experiments.baselines.direct_llm import run_direct_llm, load_frozen_prompt, _normalize_kleene_str
from domains.voices import VOICES


# -----------------------------------------------------------------------
# Constants per protocol
# -----------------------------------------------------------------------

K_BUILD = 3  # RuleKit builds per policy (Section 5.1)
K_RUN = 3    # Runs per (case, system, build) (Section 5.2)
MODEL = "claude-opus-4-7"  # Section 2.3


# -----------------------------------------------------------------------
# Policy config loading (shared with select_prompt.py)
# -----------------------------------------------------------------------

def load_policy_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_build_spec(policy_id: str, policy_config: dict) -> BuildSpec:
    """Reconstruct a BuildSpec from policy config."""
    p = policy_config["policies"][policy_id]
    dets = [
        DeterminationDeclaration(
            id=d["id"],
            description=d["description"],
            polarity=d.get("polarity", "positive"),
            composition=d.get("composition", "derived"),
            linked_to=d.get("linked_to"),
            source_span=d.get("source_span", ""),
        )
        for d in p["determinations"]
    ]
    return BuildSpec(
        policy_source=p["text_path"],
        abbreviation=policy_id,
        policy_name=p.get("name", policy_id),
        voice_key=p.get("voice_key", policy_id),
        determinations=dets,
    )


# -----------------------------------------------------------------------
# Build phase
# -----------------------------------------------------------------------

def run_build(policy_id: str, build_n: int, policy_config: dict,
              builds_dir: str, llm: LLMCaller) -> dict:
    """Run one build. Returns metadata; saves pickle to builds_dir."""
    spec = load_build_spec(policy_id, policy_config)
    if spec.voice_key not in VOICES:
        raise SystemExit(f"Unknown voice_key {spec.voice_key}")
    voice = VOICES[spec.voice_key]()

    print(f"  Building {policy_id} build #{build_n}...")
    timed = TimedLLMCaller(llm)
    start_wall = time.monotonic()
    result = build_from_spec(spec, voice, timed, refine=True)
    wall_clock = time.monotonic() - start_wall

    pickle_path = os.path.join(builds_dir, f"{policy_id}_build_{build_n}.pkl")
    with open(pickle_path, "wb") as f:
        pickle.dump(result, f)

    metadata = {
        "policy_id": policy_id,
        "build_n": build_n,
        "pickle_path": pickle_path,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": MODEL,
        "n_atoms": len(result.atoms),
        "n_determinations": len(result.determinations),
        "n_llm_calls": timed.n_calls,
        "wall_clock_s": wall_clock,
        "total_input_tokens": timed.total_input_tokens,
        "total_output_tokens": timed.total_output_tokens,
        "cost_usd": compute_cost_usd(timed.total_input_tokens, timed.total_output_tokens),
        "refinement_summary": {
            det_id: {
                "ops_applied": len(r.operations_applied),
                "flags": len(r.flags),
            }
            for det_id, r in (result.refinement_results or {}).items()
        },
    }
    meta_path = os.path.join(builds_dir, f"{policy_id}_build_{build_n}.meta.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"    Atoms: {metadata['n_atoms']}, "
          f"LLM calls: {metadata['n_llm_calls']}, "
          f"wall: {wall_clock:.1f}s, "
          f"cost: ${metadata['cost_usd']:.3f}")
    return metadata


def build_phase(policy_config: dict, builds_dir: str, llm: LLMCaller,
                resume: bool, policies_to_run: list[str] = None,
                pilot: bool = False) -> list[dict]:
    """Run all builds. Skips existing if --resume. In pilot mode: 1 build, first policy only."""
    os.makedirs(builds_dir, exist_ok=True)
    policies = policies_to_run or list(policy_config["policies"].keys())

    if pilot:
        policies = policies[:1]  # only first policy
        k_build_effective = 1
    else:
        k_build_effective = K_BUILD

    all_metadata = []
    n_attempted = 0
    n_errored = 0
    for policy_id in policies:
        print(f"\nPolicy: {policy_id}")
        for build_n in range(1, k_build_effective + 1):
            pickle_path = os.path.join(builds_dir, f"{policy_id}_build_{build_n}.pkl")
            meta_path = os.path.join(builds_dir, f"{policy_id}_build_{build_n}.meta.json")
            if resume and os.path.exists(pickle_path) and os.path.exists(meta_path):
                print(f"  Skipping {policy_id} build #{build_n} (already exists)")
                with open(meta_path) as f:
                    all_metadata.append(json.load(f))
                continue
            n_attempted += 1
            try:
                metadata = run_build(policy_id, build_n, policy_config, builds_dir, llm)
                all_metadata.append(metadata)
            except Exception as e:
                n_errored += 1
                print(f"  ERROR building {policy_id} #{build_n}: {e}")
                # Record the failure
                err_path = os.path.join(builds_dir, f"{policy_id}_build_{build_n}.error.json")
                with open(err_path, "w") as f:
                    json.dump({"error": str(e), "timestamp_utc":
                               time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)

    # If we attempted at least one build and every one failed, this is a
    # hard error: the orchestrator should not advance to the run phase.
    # (If n_attempted == 0, everything was satisfied from cache via --resume,
    # which is a legitimate success.)
    if n_attempted > 0 and n_errored == n_attempted:
        raise SystemExit(
            f"\nBUILD PHASE FAILED: {n_errored}/{n_attempted} attempted builds errored. "
            f"See {builds_dir}/*.error.json for details. "
            f"Aborting before downstream phases."
        )

    return all_metadata


# -----------------------------------------------------------------------
# Case loading
# -----------------------------------------------------------------------

def load_cases_for_policy(bank_dir: str, policy_id: str) -> list[dict]:
    """Load all main + adversarial cases for a policy."""
    patterns = [
        os.path.join(bank_dir, f"policy{_policy_index(policy_id)}", "*.yaml"),
        os.path.join(bank_dir, policy_id, "*.yaml"),  # alternative layout
    ]
    paths = []
    for pat in patterns:
        paths.extend(sorted(glob.glob(pat)))
    paths = sorted(set(paths))

    cases = []
    for path in paths:
        with open(path) as f:
            data = yaml.safe_load(f)
        if data.get("policy") != policy_id:
            continue
        if data.get("case_class") == "validation":
            continue  # validation set excluded from main
        if "case_id" not in data:
            data["case_id"] = os.path.basename(path).replace(".yaml", "")
        data["_path"] = path
        cases.append(data)
    return cases


def _policy_index(policy_id: str) -> int:
    """Map policy id to its index for the directory layout."""
    return {"pa": 1, "fcba": 2, "policy3": 3}.get(policy_id, 0)


# -----------------------------------------------------------------------
# RuleKit run on one case
# -----------------------------------------------------------------------

def run_rulekit_case(case: dict, build, policy_config: dict,
                     timed_llm: TimedLLMCaller) -> dict:
    """Run one case through RuleKit (System A): Map + Evaluate."""
    timed_llm.reset()
    substrate = NarrativeLLMSubstrate(timed_llm)

    wall_start = time.monotonic()
    bundle = map_case_to_bundle(case["description"], build.atoms, substrate)

    determinations = {}
    traces = {}
    for det_id, det in build.determinations.items():
        outcome, trace = det.evaluate(bundle)
        determinations[det_id] = str(outcome)
        traces[det_id] = _serialize_trace(trace)
    wall_clock = time.monotonic() - wall_start

    return {
        "determinations": determinations,
        "wall_clock_s": wall_clock,
        "llm_calls": timed_llm.calls.copy(),
        "total_input_tokens": timed_llm.total_input_tokens,
        "total_output_tokens": timed_llm.total_output_tokens,
        "cost_usd": compute_cost_usd(timed_llm.total_input_tokens, timed_llm.total_output_tokens),
        "bundle": {aid: str(v) for aid, v in bundle.values.items()},
        "traces": traces,
    }


def _serialize_trace(trace) -> dict:
    """Serialize an evaluation trace to a JSON-friendly dict."""
    if trace is None:
        return None
    # The trace is a dataclass-like object; rely on dict conversion via vars()
    # plus recursive handling of children. Defensive: dataclass-recursive walk.
    if hasattr(trace, "__dict__"):
        out = {}
        for k, v in trace.__dict__.items():
            if isinstance(v, list):
                out[k] = [_serialize_trace(x) for x in v]
            elif hasattr(v, "__dict__"):
                out[k] = _serialize_trace(v)
            else:
                out[k] = str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
        return out
    return str(trace)


# -----------------------------------------------------------------------
# Direct-LLM run on one case
# -----------------------------------------------------------------------

def run_direct_llm_case(case: dict, policy_config: dict,
                        timed_llm: TimedLLMCaller,
                        frozen_prompt: str) -> dict:
    """Run one case through Direct LLM (System B)."""
    policy_id = case["policy"]
    p = policy_config["policies"][policy_id]
    with open(p["text_path"]) as f:
        policy_text = f.read()

    timed_llm.reset()
    wall_start = time.monotonic()
    result = run_direct_llm(
        case=case,
        policy_text=policy_text,
        determination_specs=p["determinations"],
        voice_role=p["voice"],
        timed_llm=timed_llm,
        prompt_template=frozen_prompt,
    )
    wall_clock = time.monotonic() - wall_start

    return {
        "determinations": result["determinations"],
        "wall_clock_s": wall_clock,
        "llm_calls": timed_llm.calls.copy(),
        "total_input_tokens": timed_llm.total_input_tokens,
        "total_output_tokens": timed_llm.total_output_tokens,
        "cost_usd": compute_cost_usd(timed_llm.total_input_tokens, timed_llm.total_output_tokens),
        "explanation": result["explanation"],
        "parsed_ok": result["parsed_ok"],
        "parse_error": result["parse_error"],
        "raw_output": result["raw_output"],
    }


# -----------------------------------------------------------------------
# Record writing
# -----------------------------------------------------------------------

def make_record(case: dict, system: str, run_n: int, run_result: dict,
                build_n: int = None) -> dict:
    """Construct the protocol Section 5.3 record."""
    record = {
        "schema_version": "1.0",
        "case_id": case["case_id"],
        "policy": case["policy"],
        "difficulty_level": case.get("difficulty_level"),
        "case_class": case.get("case_class", "main"),
        "system": system,
        "build_id": f"{case['policy']}_build_{build_n}" if build_n else None,
        "run_number": run_n,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": MODEL,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "determinations": run_result["determinations"],
        "expected_outcomes": {
            k: _normalize_kleene_str(v) for k, v in case["expected_outcomes"].items()
        },
        "wall_clock_seconds": run_result["wall_clock_s"],
        "llm_calls": run_result["llm_calls"],
        "n_llm_calls": len(run_result["llm_calls"]),
        "total_input_tokens": run_result["total_input_tokens"],
        "total_output_tokens": run_result["total_output_tokens"],
        "cost_usd": run_result["cost_usd"],
    }
    # System-specific fields
    if system == "rulekit":
        record["bundle"] = run_result["bundle"]
        record["traces"] = run_result["traces"]
    else:
        record["explanation"] = run_result["explanation"]
        record["parsed_ok"] = run_result["parsed_ok"]
        record["parse_error"] = run_result["parse_error"]
        record["raw_output"] = run_result["raw_output"]
    return record


def record_path(results_dir: str, policy: str, system: str, case_id: str,
                run_n: int, build_n: int = None) -> str:
    """Path per protocol Section 5.3."""
    if system == "rulekit":
        fname = f"{policy}_rulekit_b{build_n}_{case_id}_run{run_n}.json"
    else:
        fname = f"{policy}_direct_llm_{case_id}_run{run_n}.json"
    return os.path.join(results_dir, fname)


# -----------------------------------------------------------------------
# Run phase
# -----------------------------------------------------------------------

def run_phase(policy_config: dict, bank_dir: str, builds_dir: str,
              results_dir: str, llm: LLMCaller, resume: bool,
              pilot: bool, policies_to_run: list[str] = None) -> dict:
    """Execute the run phase. Returns summary stats."""
    os.makedirs(results_dir, exist_ok=True)

    policies = policies_to_run or list(policy_config["policies"].keys())
    frozen_prompt = load_frozen_prompt(allow_default=pilot)

    if pilot:
        policies = policies[:1]  # only first policy
        k_build_effective = 1
        cases_per_policy_limit = 3
        run_levels = [1, 5, 8]  # pilot covers one of each protocol level group
    else:
        k_build_effective = K_BUILD
        cases_per_policy_limit = None
        run_levels = None

    summary = {
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pilot": pilot,
        "k_build_effective": k_build_effective,
        "k_run": K_RUN,
        "policies": policies,
        "n_records_written": 0,
        "n_records_skipped": 0,
        "n_records_errored": 0,
        "errors": [],
    }

    for policy_id in policies:
        cases = load_cases_for_policy(bank_dir, policy_id)
        if pilot and run_levels:
            # In pilot, filter to one case per requested level
            seen_levels = set()
            filtered = []
            for c in cases:
                lvl = c.get("difficulty_level")
                if lvl in run_levels and lvl not in seen_levels:
                    filtered.append(c)
                    seen_levels.add(lvl)
                if len(filtered) >= cases_per_policy_limit:
                    break
            cases = filtered

        if not cases:
            print(f"\n[WARN] No cases for {policy_id}")
            continue

        print(f"\n{'=' * 60}")
        print(f"Policy: {policy_id} ({len(cases)} cases)")
        print(f"{'=' * 60}")

        # System A: RuleKit
        for build_n in range(1, k_build_effective + 1):
            pickle_path = os.path.join(builds_dir, f"{policy_id}_build_{build_n}.pkl")
            if not os.path.exists(pickle_path):
                print(f"[ERROR] Build missing: {pickle_path}; skipping rulekit runs for it")
                summary["errors"].append(f"missing build: {pickle_path}")
                continue
            with open(pickle_path, "rb") as f:
                build = pickle.load(f)
            for case in cases:
                for run_n in range(1, K_RUN + 1):
                    rp = record_path(results_dir, policy_id, "rulekit",
                                     case["case_id"], run_n, build_n)
                    if resume and os.path.exists(rp):
                        summary["n_records_skipped"] += 1
                        continue
                    try:
                        timed = TimedLLMCaller(llm)
                        rr = run_rulekit_case(case, build, policy_config, timed)
                        record = make_record(case, "rulekit", run_n, rr, build_n=build_n)
                        with open(rp, "w") as f:
                            json.dump(record, f, indent=2)
                        summary["n_records_written"] += 1
                        print(f"  RuleKit b{build_n} {case['case_id']} r{run_n}: "
                              f"{record['determinations']} "
                              f"({record['wall_clock_seconds']:.1f}s)")
                    except Exception as e:
                        summary["n_records_errored"] += 1
                        summary["errors"].append(
                            f"rulekit {policy_id} b{build_n} {case['case_id']} r{run_n}: {e}"
                        )
                        print(f"  [ERROR] {case['case_id']}: {e}")

        # System B: Direct LLM
        for case in cases:
            for run_n in range(1, K_RUN + 1):
                rp = record_path(results_dir, policy_id, "direct_llm",
                                 case["case_id"], run_n)
                if resume and os.path.exists(rp):
                    summary["n_records_skipped"] += 1
                    continue
                try:
                    timed = TimedLLMCaller(llm)
                    rr = run_direct_llm_case(case, policy_config, timed, frozen_prompt)
                    record = make_record(case, "direct_llm", run_n, rr)
                    with open(rp, "w") as f:
                        json.dump(record, f, indent=2)
                    summary["n_records_written"] += 1
                    print(f"  DirectLLM {case['case_id']} r{run_n}: "
                          f"{record['determinations']} "
                          f"({record['wall_clock_seconds']:.1f}s)")
                except Exception as e:
                    summary["n_records_errored"] += 1
                    summary["errors"].append(
                        f"direct_llm {policy_id} {case['case_id']} r{run_n}: {e}"
                    )
                    print(f"  [ERROR] {case['case_id']}: {e}")

    summary["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return summary


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Execute the RuleKit comparison study per PROTOCOL.md"
    )
    parser.add_argument("--phase", choices=["build", "run", "all"], default="all",
                        help="Which phase to execute")
    parser.add_argument("--policy-config", default="harness/policy_config.yaml")
    parser.add_argument("--bank-dir", default="bank/")
    parser.add_argument("--builds-dir", default="results/builds/")
    parser.add_argument("--results-dir", default="results/runs/")
    parser.add_argument("--resume", action="store_true",
                        help="Skip records/builds that already exist")
    parser.add_argument("--pilot", action="store_true",
                        help="Pilot run: 1 policy, 1 build, 3 cases (Section 8)")
    parser.add_argument("--policies", default=None,
                        help="Comma-separated policy ids to run (default: all in config)")
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()

    policy_config = load_policy_config(args.policy_config)
    llm = LLMCaller(model=args.model)
    policies_to_run = args.policies.split(",") if args.policies else None

    if args.phase in ("build", "all"):
        print(f"\n{'#' * 72}")
        print(f"# BUILD PHASE (k_build={K_BUILD if not args.pilot else 1})")
        print(f"{'#' * 72}")
        build_phase(policy_config, args.builds_dir, llm,
                    resume=args.resume, policies_to_run=policies_to_run,
                    pilot=args.pilot)

    if args.phase in ("run", "all"):
        print(f"\n{'#' * 72}")
        print(f"# RUN PHASE (k_run={K_RUN})")
        if args.pilot:
            print(f"#   PILOT MODE (Protocol Section 8)")
        print(f"{'#' * 72}")
        summary = run_phase(policy_config, args.bank_dir, args.builds_dir,
                            args.results_dir, llm,
                            resume=args.resume, pilot=args.pilot,
                            policies_to_run=policies_to_run)
        # Write summary
        summary_path = os.path.join(
            args.results_dir,
            f"_run_summary_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
        )
        os.makedirs(args.results_dir, exist_ok=True)
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\n{'=' * 72}")
        print(f"Records written: {summary['n_records_written']}")
        print(f"Records skipped: {summary['n_records_skipped']}")
        print(f"Records errored: {summary['n_records_errored']}")
        if summary["errors"]:
            print(f"\nErrors (first 10):")
            for e in summary["errors"][:10]:
                print(f"  {e}")
        print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    main()

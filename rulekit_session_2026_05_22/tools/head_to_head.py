"""
head_to_head.py — single-case comparison between RuleKit and direct-LLM.

The protocol harness runs a full matrix (k_build × k_run × N_cases × 2 systems);
this tool runs ONE case end-to-end, prints results to stdout as they arrive,
and reuses a cached build across invocations so per-case marginal cost is small.

Usage:

    # First time on a policy: build (one-time, ~5min, ~$3)
    python tools/head_to_head.py --build pa

    # Run a single case (uses cached build):
    python tools/head_to_head.py --case pa-adv-llm-001

    # List available cases:
    python tools/head_to_head.py --list

    # Discard cached build and rebuild:
    python tools/head_to_head.py --build pa --force

Cached builds live in `results/h2h_builds/<policy>.pkl` and are reused across
runs until you `--force` or delete them.
"""

from __future__ import annotations
import argparse
import glob
import json
import os
import pickle
import sys
import time
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

import yaml

from rulekit.decomposer import LLMCaller, build_from_spec
from rulekit.map_primitive import NarrativeLLMSubstrate, map_case_to_bundle
from harness.timed_llm import TimedLLMCaller, compute_cost_usd
from harness.run_study import load_policy_config, load_build_spec, VOICES
from baselines.direct_llm import run_direct_llm, CANDIDATE_PROMPTS, load_frozen_prompt


# ANSI for terminal output. Disabled if not a tty.
def _color(c: str, s: str) -> str:
    if not sys.stdout.isatty():
        return s
    codes = {"red": 31, "green": 32, "yellow": 33, "blue": 34,
             "magenta": 35, "cyan": 36, "bold": 1, "dim": 2}
    return f"\033[{codes[c]}m{s}\033[0m"


# -----------------------------------------------------------------------
# Build cache
# -----------------------------------------------------------------------

CACHE_DIR = os.path.join(_PKG, "results", "h2h_builds")
PROTOCOL_BUILDS_DIR = os.path.join(_PKG, "results", "builds")


def cache_path_for(policy_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{policy_id}.pkl")


def protocol_build_path_for(policy_id: str) -> str:
    """Path to the protocol harness's build #1 for a given policy."""
    return os.path.join(PROTOCOL_BUILDS_DIR, f"{policy_id}_build_1.pkl")


def build_one(policy_id: str, policy_config: dict, llm: LLMCaller,
              force: bool = False) -> object:
    """Build the policy (or load cached). Returns the build object.

    Resolution order:
      1. h2h cache at results/h2h_builds/<policy>.pkl  (unless --force)
      2. protocol harness's build #1 at results/builds/<policy>_build_1.pkl
         (unless --force) — lets us reuse expensive prior runs
      3. fresh build via LLM, saved to h2h cache
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    h2h_path = cache_path_for(policy_id)
    proto_path = protocol_build_path_for(policy_id)

    if not force:
        if os.path.exists(h2h_path):
            print(_color("dim", f"[cache] reusing h2h build at {h2h_path}"))
            with open(h2h_path, "rb") as f:
                return pickle.load(f)
        if os.path.exists(proto_path):
            print(_color("dim",
                f"[cache] reusing protocol build_1 at {proto_path}"))
            with open(proto_path, "rb") as f:
                return pickle.load(f)

    spec = load_build_spec(policy_id, policy_config)
    if spec.voice_key not in VOICES:
        raise SystemExit(f"Unknown voice_key {spec.voice_key}")
    voice = VOICES[spec.voice_key]()

    print(_color("cyan", f"Building {policy_id}... (~5 min, ~$3)"))
    timed = TimedLLMCaller(llm)
    start = time.monotonic()
    build = build_from_spec(spec, voice, timed, refine=True)
    elapsed = time.monotonic() - start

    cost = compute_cost_usd(timed.total_input_tokens, timed.total_output_tokens)
    print(_color("green",
        f"  built: {len(build.atoms)} atoms, "
        f"{timed.n_calls} LLM calls, {elapsed:.0f}s, ${cost:.2f}"))

    with open(h2h_path, "wb") as f:
        pickle.dump(build, f)
    print(_color("dim", f"  cached → {h2h_path}"))
    return build


# -----------------------------------------------------------------------
# Case loading
# -----------------------------------------------------------------------

def find_case(case_id: str) -> Optional[dict]:
    """Locate a case by id across the bank. Returns dict or None."""
    bank = os.path.join(_PKG, "bank")
    for path in glob.iglob(os.path.join(bank, "**", "*.yaml"), recursive=True):
        if os.path.basename(path) == "_template.yaml":
            continue
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            continue
        cid = data.get("case_id") or os.path.basename(path).replace(".yaml", "")
        # Allow either dashes or underscores when matching:
        if cid == case_id or cid.replace("-", "_") == case_id.replace("-", "_"):
            data["case_id"] = cid
            data["_path"] = path
            return data
    return None


def list_cases() -> list[dict]:
    """List all cases with a quick summary line."""
    bank = os.path.join(_PKG, "bank")
    out = []
    for path in sorted(glob.iglob(os.path.join(bank, "**", "*.yaml"), recursive=True)):
        if os.path.basename(path) == "_template.yaml":
            continue
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            continue
        out.append({
            "case_id": data.get("case_id") or os.path.basename(path).replace(".yaml", ""),
            "policy": data.get("policy"),
            "difficulty": data.get("difficulty_level"),
            "class": data.get("case_class"),
            "path": path,
        })
    return out


# -----------------------------------------------------------------------
# Verdict
# -----------------------------------------------------------------------

def verdict(determinations: dict, expected: dict) -> str:
    """Return 'CORRECT' if every expected det matches, else 'WRONG (...)'."""
    mismatches = []
    for det_id, exp in expected.items():
        got = determinations.get(det_id, "<missing>")
        if str(got).lower() != str(exp).lower():
            mismatches.append(f"{det_id}: got {got}, expected {exp}")
    if not mismatches:
        return "CORRECT"
    return "WRONG (" + "; ".join(mismatches) + ")"


def short_status(v: str) -> str:
    if v == "CORRECT":
        return _color("green", "✓ CORRECT")
    return _color("red", "✗ " + v)


# -----------------------------------------------------------------------
# Main entry
# -----------------------------------------------------------------------

def run_case_head_to_head(case_id: str, policy_config: dict, llm: LLMCaller,
                          show_trace: bool = False,
                          force_build: bool = False,
                          prompt_key: Optional[str] = None) -> None:
    case = find_case(case_id)
    if case is None:
        raise SystemExit(f"Case '{case_id}' not found in bank/.")

    policy_id = case["policy"]
    p = policy_config["policies"][policy_id]

    # Header
    print()
    print(_color("bold", f"Case: {case['case_id']}  "
                          f"(policy={policy_id}, "
                          f"level={case.get('difficulty_level')}, "
                          f"class={case.get('case_class')})"))
    print(_color("dim", f"  {case['_path']}"))
    print()
    print(_color("bold", "Expected:"))
    for k, v in case["expected_outcomes"].items():
        print(f"  {k} = {v}")
    print()

    # ---- 1. Build (cached) ----
    build = build_one(policy_id, policy_config, llm, force=force_build)
    print()

    # ---- 2. RuleKit ----
    print(_color("bold", "── RuleKit ──"))
    rk_timed = TimedLLMCaller(llm)
    substrate = NarrativeLLMSubstrate(rk_timed)
    t0 = time.monotonic()
    bundle = map_case_to_bundle(case["description"], build.atoms, substrate)
    rk_dets = {}
    rk_traces = {}
    for det_id, det in build.determinations.items():
        outcome, trace = det.evaluate(bundle)
        rk_dets[det_id] = str(outcome)
        rk_traces[det_id] = trace
    rk_elapsed = time.monotonic() - t0
    rk_cost = compute_cost_usd(rk_timed.total_input_tokens, rk_timed.total_output_tokens)

    for det_id, v in rk_dets.items():
        print(f"  {det_id} = {v}")
    rk_verdict = verdict(rk_dets, case["expected_outcomes"])
    print(f"  {short_status(rk_verdict)}")
    print(_color("dim",
        f"  {rk_timed.n_calls} LLM calls (Map), {rk_elapsed:.1f}s, ${rk_cost:.3f}"))
    print()

    # ---- 3. Direct LLM ----
    print(_color("bold", "── Direct LLM ──"))
    dl_timed = TimedLLMCaller(llm)
    with open(p["text_path"]) as f:
        policy_text = f.read()

    if prompt_key:
        prompt_template = CANDIDATE_PROMPTS[prompt_key]
        prompt_label = prompt_key
    else:
        try:
            prompt_template = load_frozen_prompt()
            prompt_label = "frozen"
        except FileNotFoundError:
            prompt_template = CANDIDATE_PROMPTS["P1"]
            prompt_label = "P1 (default — no frozen prompt found)"

    t0 = time.monotonic()
    dl_result = run_direct_llm(
        case=case,
        policy_text=policy_text,
        determination_specs=p["determinations"],
        voice_role=p["voice"],
        timed_llm=dl_timed,
        prompt_template=prompt_template,
    )
    dl_elapsed = time.monotonic() - t0
    dl_cost = compute_cost_usd(dl_timed.total_input_tokens, dl_timed.total_output_tokens)

    for det_id, v in dl_result["determinations"].items():
        print(f"  {det_id} = {v}")
    dl_verdict = verdict(dl_result["determinations"], case["expected_outcomes"])
    print(f"  {short_status(dl_verdict)}")
    print(_color("dim",
        f"  1 LLM call (prompt={prompt_label}), {dl_elapsed:.1f}s, ${dl_cost:.3f}"))
    if dl_result.get("explanation"):
        exp = dl_result["explanation"]
        if len(exp) > 300:
            exp = exp[:297] + "..."
        print(_color("dim", "  explanation: " + exp))
    print()

    # ---- 4. Head-to-head ----
    print(_color("bold", "── Head-to-head ──"))
    rk_ok = rk_verdict == "CORRECT"
    dl_ok = dl_verdict == "CORRECT"
    if rk_ok and dl_ok:
        summary = _color("yellow", "TIE: both systems correct")
    elif rk_ok and not dl_ok:
        summary = _color("green", "RULEKIT wins: direct LLM failed")
    elif dl_ok and not rk_ok:
        summary = _color("magenta", "DIRECT LLM wins: RuleKit failed")
    else:
        summary = _color("red", "BOTH WRONG")
    print(f"  {summary}")
    print()

    # ---- 5. Optional trace dump ----
    if show_trace:
        from rulekit.engine import format_trace, Kleene
        print(_color("bold", "── RuleKit trace (all determinations) ──"))
        for det_id, det in build.determinations.items():
            print()
            print(_color("bold", f"  {det_id}: {det.description.strip()}"))
            if getattr(det, "source_span", ""):
                print(_color("dim", f"    source_span: {det.source_span!r}"))
            print(f"    final value: {rk_dets[det_id]}")
            print()
            trace_text = format_trace(rk_traces[det_id], indent=2)
            print(trace_text)
        print()

        # Atom inventory — what each atom in the build means, and what
        # the case bound it to. This is the "source material" view the
        # narrator stage would consume.
        print(_color("bold", "── Atom bindings (full bundle) ──"))
        # Show atoms grouped by bound value, so it's easy to scan:
        groups = {"true": [], "false": [], "undetermined": []}
        for aid, atom in sorted(build.atoms.items()):
            v = str(bundle.values.get(aid, Kleene.UNDETERMINED)).lower()
            groups.setdefault(v, []).append((aid, atom))

        for label, color in [("true", "green"), ("false", "red"),
                              ("undetermined", "yellow")]:
            entries = groups.get(label, [])
            if not entries:
                continue
            print(_color(color, f"  {label.upper()} ({len(entries)})"))
            for aid, atom in entries:
                stmt = getattr(atom, "statement", str(atom))
                print(f"    {aid}: {stmt}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Run a single head-to-head case (RuleKit vs direct LLM).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--case", help="case_id to run")
    parser.add_argument("--list", action="store_true", help="list available cases and exit")
    parser.add_argument("--build", metavar="POLICY_ID",
                        help="(re)build the cached policy and exit (e.g. --build pa)")
    parser.add_argument("--force", action="store_true",
                        help="with --build, discard cached build first")
    parser.add_argument("--show-trace", action="store_true",
                        help="dump the RuleKit evaluation trace for D1")
    parser.add_argument("--prompt", choices=["P1", "P2", "P3"],
                        help="override frozen prompt with a candidate")
    parser.add_argument("--policy-config",
                        default=os.path.join(_PKG, "harness", "policy_config.yaml"))
    parser.add_argument("--model", default=None,
                        help="override the model (default: protocol default)")
    args = parser.parse_args()

    if args.list:
        cases = list_cases()
        if not cases:
            print("(no cases found)")
            return
        for c in cases:
            print(f"  {c['case_id']:30s}  policy={c['policy']:6s}  "
                  f"level={c['difficulty']}  class={c['class']}")
        return

    policy_config = load_policy_config(args.policy_config)
    llm = LLMCaller(model=args.model) if args.model else LLMCaller()

    if args.build:
        if args.build not in policy_config["policies"]:
            raise SystemExit(f"Unknown policy '{args.build}'. "
                             f"Choices: {list(policy_config['policies'].keys())}")
        if args.force and os.path.exists(cache_path_for(args.build)):
            os.remove(cache_path_for(args.build))
        build_one(args.build, policy_config, llm, force=args.force)
        return

    if not args.case:
        parser.print_help()
        sys.exit(2)

    run_case_head_to_head(
        case_id=args.case,
        policy_config=policy_config,
        llm=llm,
        show_trace=args.show_trace,
        prompt_key=args.prompt,
    )


if __name__ == "__main__":
    main()

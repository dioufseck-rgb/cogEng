"""
build_dag.py — top-down decomposition builder.

Takes a determination spec (YAML) as the primary input. The spec declares
the policy source and the determinations the build must produce. The LLM
decomposes each determination top-down against the policy text.

Usage:
    python build_dag.py SPEC.yaml [--out OUTPUT_PKL]
    python build_dag.py determinations/pa_section2.yaml --out built_pa_dag.pkl

The spec is the institution's declarative input. Determinations are not
discovered by the LLM — they're declared.
"""

import sys
import os
import pickle
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # bin/ → project root
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from rulekit.build.extract import ReaderVoice
from rulekit.build.decomposer import build_from_spec, load_spec_from_yaml, LLMCaller
from domains.voices import VOICES


def main():
    parser = argparse.ArgumentParser(
        description="Build a DAG by top-down decomposition from a declarative spec."
    )
    parser.add_argument("spec_file", help="YAML build spec")
    parser.add_argument("--out", default=None,
                        help="Output path for built DAG (default: <spec_name>.pkl)")
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--no-refine", action="store_true",
                        help="Skip the refinement stage (faster, less clean)")
    parser.add_argument("--state-dir", default=None,
                        help="Directory to stream per-determination decompose "
                             "results to. If specified, the Build can resume "
                             "from this directory if it crashes — existing "
                             "per-determination saves are reused, only "
                             "remaining determinations are decomposed.")
    args = parser.parse_args()

    # Load the spec. Pass the legacy voices registry so YAMLs that declare
    # `policy.voice: "pa"` (registry key) continue to work alongside YAMLs
    # that declare an inline `voice:` block (the library-native path).
    spec = load_spec_from_yaml(args.spec_file, voices_registry=VOICES)

    # If the spec still has voice_key set after loading, the registry didn't
    # resolve it — error out with a useful message.
    if spec.voice is None and spec.voice_key is not None:
        raise SystemExit(
            f"Spec uses legacy voice_key={spec.voice_key!r} but it is not "
            f"registered in domains.voices.VOICES. Either declare an inline "
            f"`voice:` block in the YAML, or register the voice in voices.py."
        )

    out_path = args.out or args.spec_file.replace(".yaml", ".pkl")

    print(f"\nBuilding DAG from {args.spec_file}")
    print(f"  Policy: {spec.policy_source}")
    print(f"  Voice: {spec.voice.role}")
    print(f"  Constants: {list(spec.constants.keys()) or '(none)'}")
    print(f"  Determinations declared: {[d.id for d in spec.determinations]}")
    print(f"  Refinement: {'OFF' if args.no_refine else 'ON'}")
    if args.state_dir:
        print(f"  State dir: {args.state_dir} (decompose results streamed; resume on crash)")
    print()

    llm = LLMCaller(model=args.model)
    result = build_from_spec(
        spec,
        llm=llm,
        refine=not args.no_refine,
        state_dir=args.state_dir,
    )

    total_llm_calls = sum(len(audit) for audit in result.audit.values())
    print(f"Build complete:")
    print(f"  Total LLM calls: {total_llm_calls}")
    print(f"  Atoms: {len(result.atoms)}")
    print(f"  Determinations: {len(result.determinations)}")

    if result.refinement_results:
        print(f"\nRefinement summary:")
        for det_id, ref in result.refinement_results.items():
            print(f"  {det_id}: {len(ref.operations_applied)} ops applied, "
                  f"{len(ref.flags)} flags for review")
            for op in ref.operations_applied:
                op_name = type(op).__name__
                reason = getattr(op, 'reason', '')
                print(f"    [{op_name}] {reason[:70]}")
            for flag in ref.flags:
                print(f"    [FLAG/{flag.severity}] {flag.reason[:70]}")

    print()
    with open(out_path, "wb") as f:
        pickle.dump(result, f)
    print(f"Saved built DAG to {out_path}")

    print("\nDeterminations built:")
    for did, det in result.determinations.items():
        print(f"  {did} ({det.polarity}): {det.description}")


if __name__ == "__main__":
    main()

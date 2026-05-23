"""
build.py — the RuleKit builder.

Takes a policy document (or several) as input and produces a runnable tree
that the engine can evaluate against fact bundles.

Usage:
    python build.py POLICY_FILE --voice VOICE [--abbreviation ABBR]
                    [--name NAME] [--out OUTPUT_FILE] [--offline DIR]

Example:
    python build.py policies/pa_section2.txt --voice pa --abbreviation pa \\
                    --name "PA Section 2" --out built_pa.pkl

The output is a pickle file containing a BuildResult with:
- atoms (the refined atom list)
- schema (typed fields per atom)
- determinations (the composed trees, ready to evaluate)
- audit (the full LLM call trail)

To use the built tree, load it and call evaluate() on any determination:

    import pickle
    from rulekit import FactBundle, Kleene, format_trace
    result = pickle.load(open("built_pa.pkl", "rb"))
    bundle = FactBundle(values={"pa.radic.diagnosis": Kleene.TRUE, ...})
    determination = result.determinations["pa.D1"]
    outcome, trace = determination.evaluate(bundle)
    print(outcome)
    print(format_trace(trace))
"""

import sys
import os
import json
import argparse
import pickle

# Make rulekit importable
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rulekit.builder import ReaderVoice
from rulekit.full_builder import build_from_policy, LLMCaller
from policies.voices import VOICES


def load_offline_responses(directory: str, policy_key: str) -> dict:
    """
    Load offline responses from a directory. The directory should contain:
    - a1_response_{key}.json           -> extract_atoms
    - revise_atoms_{key}.json          -> revise_atoms (optional)
    - extract_determinations_{key}.json -> extract_determinations
    - compose_{ABBR}.{DET_ID}.json     -> compose_<det_id>  (one per determination)
    - build_schema_{key}.json          -> build_schema
    """
    responses = {}

    # Atom extraction
    p = os.path.join(directory, f"a1_response_{policy_key}.json")
    if os.path.exists(p):
        responses["extract_atoms"] = open(p).read()

    # Atom revision
    p = os.path.join(directory, f"revise_atoms_{policy_key}.json")
    if os.path.exists(p):
        responses["revise_atoms"] = open(p).read()

    # Determination extraction
    p = os.path.join(directory, f"extract_determinations_{policy_key}.json")
    if os.path.exists(p):
        responses["extract_determinations"] = open(p).read()

    # Schema
    p = os.path.join(directory, f"build_schema_{policy_key}.json")
    if os.path.exists(p):
        responses["build_schema"] = open(p).read()

    # Compositions (one per determination — match prefix compose_{ABBR}.)
    # Filter by the policy's abbreviation so we don't pick up other policies' files.
    compose_prefix = f"compose_{policy_key}."
    for fname in os.listdir(directory):
        if fname.startswith(compose_prefix) and fname.endswith(".json"):
            stage_name = fname[:-len(".json")]
            responses[stage_name] = open(os.path.join(directory, fname)).read()

    return responses


def main():
    parser = argparse.ArgumentParser(description="Build a RuleKit tree from a policy document.")
    parser.add_argument("policy_file", help="Path to policy text file")
    parser.add_argument("--voice", choices=list(VOICES.keys()), required=True,
                        help="Reasonable-reader voice for the policy's drafting culture")
    parser.add_argument("--abbreviation", required=True,
                        help="Short prefix for atom IDs (e.g., 'pa', 'fcba')")
    parser.add_argument("--name", default=None,
                        help="Display name for the schema (default: filename)")
    parser.add_argument("--out", default=None,
                        help="Output path for built tree (default: <policy_file>.pkl)")
    parser.add_argument("--offline", default=None,
                        help="Directory containing offline responses (for testing without API)")
    parser.add_argument("--offline-key", default=None,
                        help="Key to use for offline response files (default: same as abbreviation)")
    parser.add_argument("--model", default="claude-opus-4-7",
                        help="Model ID for the LLM calls")
    args = parser.parse_args()

    with open(args.policy_file) as f:
        policy_text = f.read()

    voice = VOICES[args.voice]()
    name = args.name or os.path.basename(args.policy_file)
    out_path = args.out or args.policy_file + ".pkl"

    offline_responses = None
    if args.offline:
        key = args.offline_key or args.abbreviation
        offline_responses = load_offline_responses(args.offline, key)
        print(f"Loaded {len(offline_responses)} offline responses from {args.offline}")
        for stage in offline_responses:
            print(f"  - {stage}")

    llm = LLMCaller(model=args.model, offline_responses=offline_responses)

    print(f"\nBuilding tree from {args.policy_file}...")
    print(f"  Voice: {voice.role}")
    print(f"  Domain: {voice.domain}")
    print(f"  Abbreviation: {args.abbreviation}")
    print()

    result = build_from_policy(
        policy_text=policy_text,
        voice=voice,
        abbreviation=args.abbreviation,
        schema_name=name,
        llm=llm,
    )

    print(f"Build complete:")
    print(f"  Atoms: {len(result.atoms)}")
    print(f"  Determinations: {len(result.determinations)}")
    print(f"  Schema fields: {len(result.schema.fields)}")
    if result.atomicity_flags:
        print(f"  Remaining atomicity flags: {len(result.atomicity_flags)}")
        for aid, flags in result.atomicity_flags.items():
            print(f"    {aid}: {flags}")
    print(f"  Audit entries: {list(result.audit.keys())}")

    # Save the result
    with open(out_path, "wb") as f:
        pickle.dump(result, f)
    print(f"\nSaved built tree to {out_path}")

    # Print summary of determinations
    print("\nDeterminations built:")
    for did, det in result.determinations.items():
        polarity = det.polarity or "neutral"
        print(f"  {did} ({polarity}): {det.description}")


if __name__ == "__main__":
    main()

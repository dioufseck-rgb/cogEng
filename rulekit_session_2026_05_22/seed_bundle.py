"""
seed_bundle.py — seed a fact bundle JSON from a narrative case via Map.

Useful for bootstrapping a Level 0 bundle: instead of authoring every
atom's truth value by hand, run the Map primitive against a narrative
case description and let the LLM produce a starting bundle. Then audit
the bundle by hand, overriding values where Map got it wrong.

This is a construction tool, not a test tool. After seeding, evaluate
the bundle with eval_bundle.py to see whether the audited bundle
produces the expected determination.

Usage:
    python seed_bundle.py BUILD_PKL CASE_YAML --out BUNDLE_JSON

The narrative case file uses the same format as run_cases.py:
  case_id: ...
  description: |
    Multi-line natural language ...
  expected_outcomes:
    det.D1: true
    ...
"""

import sys
import os
import json
import pickle
import argparse
from collections import OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import yaml

from rulekit.engine import Kleene
from rulekit.decomposer import LLMCaller
from rulekit.map_primitive import NarrativeLLMSubstrate, map_case_to_bundle


def main():
    parser = argparse.ArgumentParser(
        description="Seed a fact bundle JSON from a narrative case via Map."
    )
    parser.add_argument("build_pkl", help="Built DAG pickle")
    parser.add_argument("case_yaml", help="Narrative case YAML file")
    parser.add_argument("--out", required=True, help="Output bundle JSON path")
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--batch-size", type=int, default=None)
    args = parser.parse_args()

    with open(args.case_yaml) as f:
        case = yaml.safe_load(f)
    if "description" not in case:
        raise SystemExit(f"Case missing 'description': {args.case_yaml}")
    if "expected_outcomes" not in case:
        raise SystemExit(f"Case missing 'expected_outcomes': {args.case_yaml}")
    if "case_id" not in case:
        case["case_id"] = os.path.basename(args.case_yaml).replace(".yaml", "")

    with open(args.build_pkl, "rb") as f:
        build = pickle.load(f)

    print(f"Seeding bundle from {args.case_yaml}")
    print(f"  Build: {args.build_pkl}")
    print(f"  Atoms in build: {len(build.atoms)}")
    print(f"  Case: {case['case_id']}")
    print()
    print("Calling Map (one LLM call)...")

    llm = LLMCaller(model=args.model)
    substrate = NarrativeLLMSubstrate(llm, batch_size=args.batch_size)
    bundle = map_case_to_bundle(case["description"], build.atoms, substrate)

    # Count results
    counts = {"true": 0, "false": 0, "undetermined": 0}
    for v in bundle.values.values():
        counts[str(v)] += 1
    print(f"  Map result: {counts['true']} TRUE / {counts['false']} FALSE / "
          f"{counts['undetermined']} UNDETERMINED")
    print()

    # Build the bundle JSON
    bundle_values = OrderedDict()
    atom_statements = OrderedDict()
    for aid in sorted(build.atoms.keys()):
        bundle_values[aid] = str(bundle.values[aid])
        atom = build.atoms[aid]
        atom_statements[aid] = {
            "statement": atom.statement,
            "source_span": atom.source_span,
        }

    expected_outcomes = {
        det_id: str(v) for det_id, v in case["expected_outcomes"].items()
    }

    doc = OrderedDict([
        ("case_id", case["case_id"]),
        ("description", case.get("description", "").strip().split("\n")[0][:120]),
        ("build_pkl", os.path.basename(args.build_pkl)),
        ("expected_outcomes", expected_outcomes),
        ("bundle", bundle_values),
        ("atom_statements", atom_statements),
        ("seeded_from", os.path.basename(args.case_yaml)),
        ("audit_note",
         "This bundle was seeded by Map from a narrative case. "
         "Review each atom's binding before treating as ground truth. "
         "Override values where Map got it wrong."),
    ])

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)

    print(f"Wrote seeded bundle to {args.out}")
    print()
    print("Next steps:")
    print(f"  1. Audit {args.out} — check each atom's binding against the case description")
    print(f"  2. Override any values Map got wrong")
    print(f"  3. Run: python eval_bundle.py {args.build_pkl} {args.out}")


if __name__ == "__main__":
    main()

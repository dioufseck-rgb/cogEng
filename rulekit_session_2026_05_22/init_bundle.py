"""
init_bundle.py — generate a starter fact bundle JSON from a built DAG.

Reads a build pickle, lists every atom, produces a JSON file with each
atom set to "undetermined" by default. The institution then edits the
JSON to assign "true" / "false" / "undetermined" to each atom based on
the case's intended facts.

This is build-aware case construction. The bundle is a 1:1 map onto the
build's atoms. No narrative; no LLM binding at test time.

Usage:
    python init_bundle.py BUILD_PKL --case-id ID --out PATH
    python init_bundle.py built_pa_dag.pkl --case-id pa-standard-approval \\
        --description "Radiculopathy + full conservative tx" \\
        --out bundles/pa_standard_approval.json
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


def main():
    parser = argparse.ArgumentParser(
        description="Generate a starter fact bundle JSON from a built DAG."
    )
    parser.add_argument("build_pkl", help="Built DAG pickle")
    parser.add_argument("--case-id", required=True, help="Identifier for this case")
    parser.add_argument("--description", default="",
                        help="One-line description of the scenario")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--default", default="undetermined",
                        choices=["true", "false", "undetermined"],
                        help="Default value to seed each atom with")
    args = parser.parse_args()

    with open(args.build_pkl, "rb") as f:
        build = pickle.load(f)

    # Build the bundle skeleton. Use a normal dict for the bundle (we'll
    # sort keys at JSON dump time for stability), and an OrderedDict for
    # the atom_statements section so the natural ordering of atoms in the
    # build is preserved (helps the human editor read context).
    bundle_values = {aid: args.default for aid in sorted(build.atoms.keys())}

    atom_statements = OrderedDict()
    for aid in sorted(build.atoms.keys()):
        atom = build.atoms[aid]
        atom_statements[aid] = {
            "statement": atom.statement,
            "source_span": atom.source_span,
        }

    # Expected outcomes — seed with each determination set to "undetermined"
    expected_outcomes = {
        det_id: "undetermined" for det_id in sorted(build.determinations.keys())
    }

    doc = OrderedDict([
        ("case_id", args.case_id),
        ("description", args.description or
            "Edit this with a one-line scenario description."),
        ("build_pkl", os.path.basename(args.build_pkl)),
        ("expected_outcomes", expected_outcomes),
        ("bundle", bundle_values),
        ("atom_statements", atom_statements),
    ])

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)

    print(f"Wrote starter bundle to {args.out}")
    print(f"  Atoms: {len(bundle_values)} (all defaulted to '{args.default}')")
    print(f"  Determinations: {list(expected_outcomes.keys())}")
    print()
    print("Next steps:")
    print(f"  1. Edit {args.out} — assign true/false/undetermined to each atom in 'bundle'")
    print(f"  2. Edit 'expected_outcomes' to declare what the build should produce")
    print(f"  3. Run: python eval_bundle.py {args.build_pkl} {args.out}")


if __name__ == "__main__":
    main()

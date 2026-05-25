"""
extract_und_atoms.py — pull the UND atoms from a full-DAG audit for
resolver-simulation purposes.

Prints each UND Boolean atom in the case, along with:
  - The atom statement (what Map was asked)
  - Which determination it's inside
  - Where it sits in the determination's trace (load-bearing?)

This is what a resolver would see: atom statement + case description.
The simulator (Claude in conversation) judges whether to flip it.

Usage:
    python bin/extract_und_atoms.py audits/full_dag_diagnostic/case_comp_0_1_op_A.json
"""
import json
import sys
import pickle
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


def main():
    if len(sys.argv) < 2:
        print("Usage: python bin/extract_und_atoms.py <audit-json> [built.pkl]")
        sys.exit(1)

    audit_path = sys.argv[1]
    pkl_path = sys.argv[2] if len(sys.argv) > 2 else "built_nba_v2.pkl"

    with open(audit_path, encoding="utf-8") as f:
        audit = json.load(f)
    with open(pkl_path, "rb") as f:
        build = pickle.load(f)

    print("=" * 70)
    print(f"CASE: {audit['case_id']}")
    print(f"Ground truth: is_illegal={audit['ground_truth']['is_illegal']}")
    print(f"RuleKit disposition: {audit['rulekit']['disposition']}")
    print("=" * 70)
    print()

    print("CASE DESCRIPTION:")
    print("-" * 70)
    print(audit.get("case_description", ""))
    print()

    print("=" * 70)
    print("PER-DETERMINATION RESULTS:")
    print("=" * 70)
    for did, k in audit["rulekit"]["per_determination_kleene"].items():
        print(f"  {did}: {k}")
    print()

    # For each UND determination, walk the trace and pull UND Boolean leaves
    print("=" * 70)
    print("UND BOOLEAN ATOMS BY DETERMINATION")
    print("=" * 70)

    bindings = audit.get("atom_bindings", {})
    atoms = build.atoms

    for did, trace in audit.get("per_determination_traces", {}).items():
        det_result = audit["rulekit"]["per_determination_kleene"].get(did)
        if det_result != "UNDETERMINED":
            continue

        print(f"\n--- {did} ---")
        und_atoms_in_det = set()

        def collect_und_leaves(entry):
            if not isinstance(entry, dict):
                return
            if entry.get("type") == "leaf":
                aid = entry.get("atom_id", "")
                val = entry.get("value", "")
                if val == "undetermined" and aid:
                    und_atoms_in_det.add(aid)
            if "children_trace" in entry:
                for c in entry["children_trace"]:
                    collect_und_leaves(c)
            for attr in ("left_trace", "right_trace", "child_trace"):
                if attr in entry:
                    items = entry[attr]
                    if isinstance(items, list):
                        for c in items:
                            collect_und_leaves(c)

        for entry in trace:
            collect_und_leaves(entry)

        for aid in sorted(und_atoms_in_det):
            atom = atoms.get(aid)
            stmt = atom.statement if atom else "(atom not in registry)"
            print(f"\n  [{aid}]")
            print(f"    Statement: {stmt}")


if __name__ == "__main__":
    main()
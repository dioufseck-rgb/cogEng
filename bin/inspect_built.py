"""
inspect_built.py — inspect a built tree to help write test cases against it.

Usage:
    python inspect_built.py BUILT_PKL [--atoms] [--tree DET_ID] [--starter]

Examples:
    python inspect_built.py built_pa.pkl --atoms
        # Lists all atoms with their statements

    python inspect_built.py built_pa.pkl --tree pa.D1
        # Shows the composed tree structure for D1

    python inspect_built.py built_pa.pkl --starter
        # Generates starter Python code with all atom IDs set to UNDETERMINED
"""

import sys
import os
import pickle
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # bin/ → project root
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from rulekit import Kleene, FactBundle, format_trace, CardinalityNode, NotNode, Leaf, AndNode, OrNode, AtLeastNode


def print_atoms(result):
    print(f"\n{len(result.atoms)} atoms in built tree:\n")
    for aid in sorted(result.atoms.keys()):
        atom = result.atoms[aid]
        print(f"  {aid}")
        print(f"    [{atom.source_span}]")
        print(f"    {atom.statement}")
        print()


def render_tree_structure(node, indent=0):
    """Render the tree structure without evaluation."""
    prefix = "  " * indent
    if isinstance(node, Leaf):
        return f"{prefix}LEAF: {node.atom_id}"
    if isinstance(node, NotNode):
        out = f"{prefix}NOT ({node.provenance.value})"
        out += "\n" + render_tree_structure(node.child, indent + 1)
        return out
    if isinstance(node, AndNode):
        label = node.surface_label or "AND"
        out = f"{prefix}{label} (AND, k={len(node.children)}, {node.provenance.value})"
        for child in node.children:
            out += "\n" + render_tree_structure(child, indent + 1)
        return out
    if isinstance(node, OrNode):
        label = node.surface_label or "OR"
        out = f"{prefix}{label} (OR, k={len(node.children)}, {node.provenance.value})"
        for child in node.children:
            out += "\n" + render_tree_structure(child, indent + 1)
        return out
    if isinstance(node, AtLeastNode):
        label = node.surface_label or f"AT-LEAST-{node.n}"
        out = f"{prefix}{label} (n={node.n}, k={len(node.children)}, {node.provenance.value})"
        for child in node.children:
            out += "\n" + render_tree_structure(child, indent + 1)
        return out
    return f"{prefix}?? unknown node type"


def print_tree(result, det_id):
    if det_id not in result.determinations:
        print(f"No such determination: {det_id}")
        print(f"Available: {list(result.determinations.keys())}")
        return
    det = result.determinations[det_id]
    print(f"\nTree for {det_id}:")
    print(f"Description: {det.description}\n")
    print(render_tree_structure(det.tree))


def print_starter_code(result, var_name="case"):
    print("\n# Starter code for a test case — every atom defaulted to UNDETERMINED.")
    print("# Edit each value to T, F, or U as your case requires.\n")
    print(f"{var_name} = {{")
    for aid in sorted(result.atoms.keys()):
        atom = result.atoms[aid]
        statement_preview = atom.statement[:60] + ("..." if len(atom.statement) > 60 else "")
        print(f"    '{aid}': U,  # {statement_preview}")
    print("}")
    print(f"\n# Evaluate:")
    print(f"# bundle = FactBundle(values={{aid: U for aid in result.atoms}})")
    print(f"# bundle.values.update({var_name})")
    print(f"# outcome, trace = result.determinations['DETERMINATION_ID'].evaluate(bundle)")


def main():
    parser = argparse.ArgumentParser(description="Inspect a built RuleKit tree.")
    parser.add_argument("built_pkl", help="Path to a .pkl produced by build.py")
    parser.add_argument("--atoms", action="store_true", help="List atoms with statements")
    parser.add_argument("--tree", default=None, help="Show tree structure for a determination")
    parser.add_argument("--starter", action="store_true", help="Generate starter test-case code")
    parser.add_argument("--all", action="store_true", help="Run all three views")
    args = parser.parse_args()

    with open(args.built_pkl, "rb") as f:
        result = pickle.load(f)

    print(f"Loaded build: {len(result.atoms)} atoms, {len(result.determinations)} determinations")
    print(f"Determinations: {list(result.determinations.keys())}")

    if args.atoms or args.all:
        print_atoms(result)
    if args.tree or args.all:
        det_id = args.tree or list(result.determinations.keys())[0]
        print_tree(result, det_id)
    if args.starter or args.all:
        print_starter_code(result)


if __name__ == "__main__":
    main()

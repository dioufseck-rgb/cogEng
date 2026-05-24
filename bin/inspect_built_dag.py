"""
inspect_built_dag.py — inspect a built DAG pickle from bin/build_dag.py.

Prints:
  - Per-determination tree shape (top-level structure)
  - Full atom registry with type and statement preview
  - Cross-determination atom usage (which atoms appear in which determinations)
  - Summary statistics

Cost: $0 (pure inspection; no LLM).

USAGE:
    python bin/inspect_built_dag.py built_nba_universal.pkl
"""
from __future__ import annotations
import os
import pickle
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.engine import (
    Leaf, AndNode, OrNode, NotNode, AtLeastNode, CardinalityNode,
)
from rulekit.engine.typed import (
    NumericLeaf, Constant, EqNode, LtNode, LeqNode, GtNode, GeqNode,
    TimesConstNode, PlusConstNode, MinusConstNode, ConstMinusNode,
    DivByConstNode, ConstDivByNode,
)


def collect_atom_ids_used(node, atoms_used=None) -> set[str]:
    """Walk an engine tree, collect all atom_ids referenced by Leaf/NumericLeaf."""
    if atoms_used is None:
        atoms_used = set()
    # Leaf-like nodes
    if isinstance(node, Leaf):
        atoms_used.add(node.atom_id)
        return atoms_used
    if isinstance(node, NumericLeaf):
        atoms_used.add(node.atom_id)
        return atoms_used
    # Constants don't reference atoms
    if isinstance(node, Constant):
        return atoms_used
    # Comparison nodes: left + right
    if isinstance(node, (EqNode, LtNode, LeqNode, GtNode, GeqNode)):
        collect_atom_ids_used(node.left, atoms_used)
        collect_atom_ids_used(node.right, atoms_used)
        return atoms_used
    # Unary arithmetic: child
    if isinstance(node, (TimesConstNode, PlusConstNode, MinusConstNode,
                         ConstMinusNode, DivByConstNode, ConstDivByNode)):
        collect_atom_ids_used(node.child, atoms_used)
        return atoms_used
    # NOT: child
    if isinstance(node, NotNode):
        collect_atom_ids_used(node.child, atoms_used)
        return atoms_used
    # Boolean composers: children
    if isinstance(node, (AndNode, OrNode, AtLeastNode, CardinalityNode)):
        for c in node.children:
            collect_atom_ids_used(c, atoms_used)
        return atoms_used
    return atoms_used


def describe_top_level(node, indent=0) -> str:
    """Single-level description of an engine node (top of a determination tree)."""
    t = type(node).__name__
    if hasattr(node, "children"):
        n_children = len(node.children)
        n_kw = f" n={node.n}" if hasattr(node, "n") and node.n is not None else ""
        return f"{t}({n_children} children{n_kw})"
    if hasattr(node, "left") and hasattr(node, "right"):
        l = type(node.left).__name__
        r = type(node.right).__name__
        return f"{t}({l} vs {r})"
    if hasattr(node, "child"):
        return f"{t}({type(node.child).__name__})"
    if hasattr(node, "atom_id"):
        return f"{t}({node.atom_id!r})"
    return t


def tree_depth(node) -> int:
    """Compute the depth of an engine tree."""
    if hasattr(node, "children"):
        if not node.children:
            return 1
        return 1 + max(tree_depth(c) for c in node.children)
    if hasattr(node, "left") and hasattr(node, "right"):
        return 1 + max(tree_depth(node.left), tree_depth(node.right))
    if hasattr(node, "child"):
        return 1 + tree_depth(node.child)
    return 1


def tree_node_count(node) -> int:
    """Total node count in an engine tree."""
    count = 1
    if hasattr(node, "children"):
        for c in node.children:
            count += tree_node_count(c)
    elif hasattr(node, "left") and hasattr(node, "right"):
        count += tree_node_count(node.left) + tree_node_count(node.right)
    elif hasattr(node, "child"):
        count += tree_node_count(node.child)
    return count


def main():
    if len(sys.argv) < 2:
        print("Usage: python inspect_built_dag.py BUILT.pkl")
        sys.exit(2)

    pkl_path = sys.argv[1]
    with open(pkl_path, "rb") as f:
        build = pickle.load(f)

    print("=" * 75)
    print(f"BUILT DAG: {pkl_path}")
    print("=" * 75)
    print(f"  Policy: {build.spec.policy_name}")
    print(f"  Abbreviation: {build.spec.abbreviation}")
    print(f"  Determinations: {len(build.determinations)}")
    print(f"  Total atoms registered: {len(build.atoms)}")
    print()

    # Per-determination summary
    print("-" * 75)
    print("DETERMINATIONS")
    print("-" * 75)
    det_to_atoms: dict[str, set[str]] = {}
    for det_id, det in build.determinations.items():
        atoms_used = collect_atom_ids_used(det.tree)
        det_to_atoms[det_id] = atoms_used
        print(f"\n  {det_id}")
        print(f"    Top-level: {describe_top_level(det.tree)}")
        print(f"    Tree depth: {tree_depth(det.tree)}")
        print(f"    Tree node count: {tree_node_count(det.tree)}")
        print(f"    Atoms referenced: {len(atoms_used)}")

    # Atom-usage cross-tabulation
    print()
    print("-" * 75)
    print("ATOM REGISTRY (sorted by reference count, then by id)")
    print("-" * 75)

    # Count how many determinations reference each atom
    atom_ref_count: dict[str, int] = {aid: 0 for aid in build.atoms}
    atom_dets: dict[str, list[str]] = {aid: [] for aid in build.atoms}
    for det_id, atoms_used in det_to_atoms.items():
        for aid in atoms_used:
            if aid in atom_ref_count:
                atom_ref_count[aid] += 1
                atom_dets[aid].append(det_id)

    # Atoms shared across 2+ determinations — the cross-determination dedup wins
    shared_atoms = [(aid, atom_ref_count[aid], atom_dets[aid])
                    for aid in build.atoms if atom_ref_count[aid] >= 2]
    shared_atoms.sort(key=lambda x: (-x[1], x[0]))

    single_atoms = [(aid, atom_dets[aid][0] if atom_dets[aid] else "(none)")
                    for aid in build.atoms if atom_ref_count[aid] == 1]
    single_atoms.sort()

    orphan_atoms = [aid for aid in build.atoms if atom_ref_count[aid] == 0]

    print(f"\n  Atoms shared across 2+ determinations: {len(shared_atoms)}")
    for aid, count, dets in shared_atoms:
        atom = build.atoms[aid]
        stmt = atom.statement[:70] if atom.statement else "(no statement)"
        print(f"    [{count}x] {aid} ({atom.atom_type})")
        print(f"           used in: {', '.join(dets)}")
        print(f"           statement: {stmt}")

    print(f"\n  Atoms used in exactly one determination: {len(single_atoms)}")
    boolean_singles = [(aid, det) for aid, det in single_atoms
                       if build.atoms[aid].atom_type == "boolean"]
    numeric_singles = [(aid, det) for aid, det in single_atoms
                       if build.atoms[aid].atom_type == "numeric"]
    print(f"    Boolean: {len(boolean_singles)} | Numeric: {len(numeric_singles)}")
    # Print numeric atoms (more interesting for Phase 2 Map design)
    print(f"\n    Numeric atoms (Map will need extraction prompts for each):")
    for aid, det in numeric_singles:
        atom = build.atoms[aid]
        stmt = atom.statement[:65] if atom.statement else "(no statement)"
        print(f"      {aid}  [{det}]")
        print(f"           {stmt}")

    if orphan_atoms:
        print(f"\n  Orphan atoms (registered but not referenced by any determination):")
        for aid in orphan_atoms:
            print(f"    {aid}")

    # Summary
    print()
    print("=" * 75)
    print("SUMMARY")
    print("=" * 75)
    print(f"  Total atoms: {len(build.atoms)}")
    print(f"  Shared atoms (cross-determination dedup wins): {len(shared_atoms)}")
    print(f"  Single-determination atoms: {len(single_atoms)}")
    if orphan_atoms:
        print(f"  ORPHAN atoms: {len(orphan_atoms)}  (should be 0 — investigate)")
    n_numeric = sum(1 for a in build.atoms.values() if a.atom_type == "numeric")
    n_boolean = sum(1 for a in build.atoms.values() if a.atom_type == "boolean")
    print(f"  By type: {n_boolean} Boolean, {n_numeric} numeric")


if __name__ == "__main__":
    main()

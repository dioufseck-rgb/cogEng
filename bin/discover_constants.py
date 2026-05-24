"""
discover_constants.py — inspect saved spec trees for constant references.

After build_from_spec has run decompose for one or more determinations
and streamed them to a state_dir, this script walks every saved spec
tree and collects all named constants referenced — comparing against
a YAML spec's `constants:` block.

Purpose: catch the failure mode where Stage-4 conversion crashes
mid-Build because a named constant has no value in the registry.
Running this script after decompose tells us EVERY missing constant
in one pass, instead of crash-fix-rerun-crash-fix-rerun cycles.

Cost: $0. Operates entirely on saved spec trees; no LLM calls.

USAGE:
    # After a partial or crashed Build that used --state-dir:
    python bin/discover_constants.py STATE_DIR SPEC.yaml

    # Example:
    python bin/discover_constants.py state/nba domains/nba/cba.yaml

Output:
    - List of every constant referenced in any spec tree
    - Which determination(s) reference each constant
    - Which constants are provided by the spec
    - Which constants are MISSING (would crash Stage-4)
"""
from __future__ import annotations
import os
import pickle
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.build.decomposer import (
    ConstantSpec, UnaryArithmeticSpec, ComparisonSpec, NumericLeafSpec,
    LeafSpec, OperatorSpec,
    load_spec_from_yaml,
)


def collect_constants(spec, refs=None) -> dict[str, int]:
    """Walk a NodeSpec tree and count every named constant referenced.

    Returns a dict of constant_label -> reference count.
    """
    if refs is None:
        refs = {}

    # ConstantSpec with a label is a named-constant reference
    if isinstance(spec, ConstantSpec):
        if spec.label is not None:
            refs[spec.label] = refs.get(spec.label, 0) + 1
        return refs

    # UnaryArithmeticSpec may have constant_label
    if isinstance(spec, UnaryArithmeticSpec):
        if spec.constant_label is not None:
            refs[spec.constant_label] = refs.get(spec.constant_label, 0) + 1
        collect_constants(spec.child, refs)
        return refs

    # ComparisonSpec walks both sides
    if isinstance(spec, ComparisonSpec):
        collect_constants(spec.lhs_spec, refs)
        collect_constants(spec.rhs_spec, refs)
        return refs

    # NumericLeafSpec and LeafSpec are terminal — no constants
    if isinstance(spec, (NumericLeafSpec, LeafSpec)):
        return refs

    # OperatorSpec walks children
    if isinstance(spec, OperatorSpec):
        for child in spec.children:
            collect_constants(child, refs)
        return refs

    return refs


def main():
    if len(sys.argv) < 3:
        print("Usage: python discover_constants.py STATE_DIR SPEC.yaml")
        sys.exit(2)

    state_dir = sys.argv[1]
    spec_path = sys.argv[2]

    if not os.path.isdir(state_dir):
        print(f"State directory not found: {state_dir}")
        sys.exit(2)

    if not os.path.isfile(spec_path):
        print(f"Spec file not found: {spec_path}")
        sys.exit(2)

    # Load the spec to compare against its constants block
    spec = load_spec_from_yaml(spec_path)
    provided = set(spec.constants.keys())

    print(f"Spec: {spec_path}")
    print(f"State dir: {state_dir}")
    print(f"Determinations declared: {len(spec.determinations)}")
    print()

    # Walk every decompose_*.pkl in the state dir
    files = sorted(f for f in os.listdir(state_dir)
                   if f.startswith("decompose_") and f.endswith(".pkl"))
    if not files:
        print(f"No decompose_*.pkl files found in {state_dir}")
        print("Run build_dag.py --state-dir first to populate.")
        sys.exit(1)

    print(f"Saved decompose results: {len(files)}")
    print()

    # Per-determination constant references
    all_refs: dict[str, int] = {}
    per_det_refs: dict[str, dict[str, int]] = {}

    for fname in files:
        det_id = fname[len("decompose_"):-len(".pkl")]
        path = os.path.join(state_dir, fname)
        try:
            with open(path, "rb") as f:
                saved = pickle.load(f)
        except Exception as e:
            print(f"WARN: could not load {fname}: {e}")
            continue
        tree = saved.get("spec")
        if tree is None:
            print(f"WARN: {fname} has no 'spec' key")
            continue

        det_refs = collect_constants(tree)
        per_det_refs[det_id] = det_refs
        for k, v in det_refs.items():
            all_refs[k] = all_refs.get(k, 0) + v

    # Report
    print("-" * 70)
    print("CONSTANTS REFERENCED ACROSS ALL DETERMINATIONS")
    print("-" * 70)
    if not all_refs:
        print("  (none — no spec tree references any named constant)")
    else:
        for label in sorted(all_refs.keys()):
            count = all_refs[label]
            provided_marker = "✓" if label in provided else "✗ MISSING"
            print(f"  [{provided_marker}] {label} (referenced {count}x)")

    print()
    print("-" * 70)
    print("CONSTANTS PROVIDED IN SPEC")
    print("-" * 70)
    for label in sorted(provided):
        count = all_refs.get(label, 0)
        used_marker = f"used {count}x" if count > 0 else "UNUSED"
        print(f"  {label} = {spec.constants[label]} ({used_marker})")

    # Per-determination cross-reference
    print()
    print("-" * 70)
    print("PER-DETERMINATION CONSTANT REFERENCES")
    print("-" * 70)
    for det_id in sorted(per_det_refs.keys()):
        refs = per_det_refs[det_id]
        if not refs:
            print(f"  {det_id}: (no constants)")
            continue
        print(f"  {det_id}:")
        for label in sorted(refs.keys()):
            marker = "✓" if label in provided else "✗"
            print(f"    [{marker}] {label} ({refs[label]}x)")

    # Missing summary
    missing = sorted(k for k in all_refs if k not in provided)
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Constants referenced: {len(all_refs)}")
    print(f"  Constants provided:   {len(provided)}")
    print(f"  Missing constants:    {len(missing)}")
    if missing:
        print()
        print("  These constants need to be added to the spec's constants:")
        print("  block before Stage-4 can succeed:")
        for label in missing:
            dets = [d for d, refs in per_det_refs.items() if label in refs]
            print(f"    - {label}")
            print(f"      referenced by: {', '.join(dets)}")
        print()
        print("  Add them to the YAML's `constants:` block, then re-run")
        print("  build_dag.py with --state-dir to resume from saved trees")
        print("  (no new LLM cost for the already-decomposed determinations).")
        sys.exit(1)

    print()
    print("  All referenced constants are provided. Stage-4 should not")
    print("  crash on missing constants.")


if __name__ == "__main__":
    main()

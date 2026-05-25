"""
diagnose_run2.py - inspect what happened during a Build run that produced
suspiciously few nodes. Tests two scenarios:

  A: Silent partial parse (parser caught a malformed LLM response and
     returned what it could without raising)
  B: Legitimate early stop (decomposer chose not to recurse further)

Look at:
  - Number of audit entries (LLM calls made)
  - Any error messages in the audit
  - Raw decomposition specs structure (vs final tree)
  - Atom count and statements

Usage:
    python bin/diagnose_run2.py [path/to/built_runN.pkl]
"""
import argparse
import json
import os
import pickle
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("path",
                   default="audits/decompose_stability/built_run2.pkl",
                   nargs="?")
    p.add_argument("--det", default="nba.cap_room")
    args = p.parse_args()

    with open(args.path, "rb") as f:
        b = pickle.load(f)

    print(f"=== Inspecting {args.path} ===")
    print()
    print(f"Top-level attrs: {sorted(vars(b).keys()) if hasattr(b, '__dict__') else dir(b)}")
    print()

    print("Determinations:")
    for did in b.determinations:
        det = b.determinations[did]
        print(f"  {did}: {type(det).__name__}")
    print()

    print("Atoms:")
    print(f"  Total: {len(b.atoms)}")
    for aid, atom in sorted(b.atoms.items())[:20]:
        atype = getattr(atom, 'atom_type', 'unknown')
        stmt = (getattr(atom, 'statement', '') or '')[:100]
        print(f"  [{atype}] {aid}: {stmt}")
    if len(b.atoms) > 20:
        print(f"  ...and {len(b.atoms) - 20} more")
    print()

    # Audit log: what LLM calls were made?
    print("Audit entries:")
    audit = getattr(b, 'audit', None)
    if audit is None:
        print("  (no audit attribute)")
    elif isinstance(audit, dict):
        for det_id, entries in audit.items():
            print(f"  --- {det_id} ---")
            if entries is None:
                print(f"    (no entries)")
                continue
            if isinstance(entries, list):
                print(f"    {len(entries)} entries:")
                for i, e in enumerate(entries):
                    stage = e.get('stage', '?') if isinstance(e, dict) else '?'
                    extra = ''
                    if isinstance(e, dict):
                        if 'error' in e:
                            extra = f"  ERROR: {e['error']}"
                        elif 'parse_error' in e:
                            extra = f"  PARSE_ERROR: {e['parse_error']}"
                        elif 'raw_response' in e:
                            raw = e['raw_response']
                            extra = f"  raw_response_len={len(raw) if raw else 0}"
                    print(f"    [{i}] stage={stage}{extra}")
            else:
                print(f"    {type(entries).__name__}: {str(entries)[:200]}")
    print()

    # Decomposition specs
    print("Decomposition specs:")
    dspecs = getattr(b, 'decomposition_specs', {})
    for did, spec in dspecs.items():
        print(f"  {did}: {type(spec).__name__}")
        # Try to see internal structure
        for attr in ['op', 'spec_type', 'children', 'atoms']:
            v = getattr(spec, attr, None)
            if v is not None:
                if isinstance(v, list):
                    print(f"    {attr}: list of {len(v)}")
                else:
                    print(f"    {attr}: {str(v)[:150]}")
    print()

    # If the state directory still exists, list it
    state_dir = args.path.replace('built_run', 'state_run').replace('.pkl', '')
    if os.path.isdir(state_dir):
        print(f"State directory {state_dir}:")
        for fname in sorted(os.listdir(state_dir)):
            fpath = os.path.join(state_dir, fname)
            size = os.path.getsize(fpath)
            print(f"  {fname}: {size} bytes")

    # Look at the determination's actual tree compared to specs
    print()
    print("=== Tree walk ===")
    det = b.determinations.get(args.det)
    if det:
        def walk(n, depth=0):
            if depth > 10:
                return
            label = ''
            for attr in ('surface_label', 'atom_id'):
                v = getattr(n, attr, None)
                if v:
                    label = str(v)
                    break
            print('  ' * depth + f"{type(n).__name__}: {label[:80]}")
            if hasattr(n, 'children') and isinstance(n.children, list):
                for c in n.children:
                    walk(c, depth + 1)
            for attr in ('left', 'right', 'child', 'tree'):
                if hasattr(n, attr):
                    c = getattr(n, attr)
                    if c is not None and not isinstance(c, (str, int, float)):
                        walk(c, depth + 1)
        walk(det)


if __name__ == "__main__":
    main()

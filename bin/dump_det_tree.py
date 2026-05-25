"""
dump_det_tree.py - dump a determination's tree structure to a file.

Avoids PowerShell stdout encoding issues by writing directly to disk.

Usage:
    python bin/dump_det_tree.py nba.sign_and_trade
    python bin/dump_det_tree.py nba.sign_and_trade --built built_nba_v2.pkl --out sat_tree.txt
"""
import argparse
import os
import pickle
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


def walk(node, lines, depth=0, max_depth=20):
    if depth > max_depth:
        lines.append("  " * depth + "... (truncated)")
        return
    name = type(node).__name__
    label = ""
    for attr in ("surface_label", "atom_id"):
        v = getattr(node, attr, None)
        if v:
            label = str(v)[:80]
            break
    # Show constant value if this is a Constant node
    extra = ""
    if name == "Constant":
        val = getattr(node, "value", None)
        lbl = getattr(node, "label", "")
        extra = f" value={val} label={lbl}"
    elif name in ("TimesConstNode", "PlusConstNode", "MinusConstNode",
                  "DivByConstNode", "ConstMinusNode", "ConstDivByNode"):
        c = getattr(node, "constant", None)
        extra = f" const={c}"
    lines.append("  " * depth + f"{name}: {label}{extra}")

    # Recurse into children, lists first
    if hasattr(node, "children") and isinstance(node.children, list):
        for c in node.children:
            walk(c, lines, depth + 1, max_depth)
    for attr in ("left", "right", "child", "tree"):
        if hasattr(node, attr):
            child = getattr(node, attr)
            if child is not None and not isinstance(child, (str, int, float)):
                walk(child, lines, depth + 1, max_depth)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("det_id", help="Determination id, e.g. nba.sign_and_trade")
    p.add_argument("--built", default="built_nba_v2.pkl")
    p.add_argument("--out", default=None,
                   help="Output file (default: <det_id>_tree.txt)")
    p.add_argument("--max-depth", type=int, default=20)
    args = p.parse_args()

    with open(args.built, "rb") as f:
        b = pickle.load(f)

    if args.det_id not in b.determinations:
        print(f"Determination {args.det_id} not found in build.")
        print(f"Available: {sorted(b.determinations.keys())}")
        sys.exit(1)

    det = b.determinations[args.det_id]
    lines = []
    lines.append(f"Determination: {args.det_id}")
    lines.append(f"Description: {det.description}")
    lines.append("=" * 70)
    walk(det, lines, max_depth=args.max_depth)

    out_path = args.out or f"{args.det_id.replace('.', '_')}_tree.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote tree to {out_path} ({len(lines)} lines)")


if __name__ == "__main__":
    main()

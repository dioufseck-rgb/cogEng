"""
inspect_audit.py - inspect a per-case audit JSON.

Usage:
    python bin/inspect_audit.py audits/cap_room_diagnostic/case_comp_0_60_op_A.json
"""
import json
import sys


def main():
    if len(sys.argv) != 2:
        print("Usage: python bin/inspect_audit.py <audit-json-path>")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        a = json.load(f)

    print("=" * 70)
    print("CASE DESCRIPTION")
    print("=" * 70)
    print(a.get("case_description", "")[:1500])
    print()

    print("=" * 70)
    print("GROUND TRUTH")
    print("=" * 70)
    gt = a.get("ground_truth", {})
    print(f"  is_illegal: {gt.get('is_illegal')}")
    print(f"  relevant_rules: {gt.get('relevant_rules', [])}")
    print()

    print("=" * 70)
    print("RULEKIT RESULT")
    print("=" * 70)
    rk = a.get("rulekit", {})
    print(f"  disposition: {rk.get('disposition')}")
    print(f"  per_determination:")
    for did, kl in rk.get("per_determination_kleene", {}).items():
        print(f"    {did}: {kl}")
    print()

    print("=" * 70)
    print("ATOM BINDINGS (non-UNDETERMINED only)")
    print("=" * 70)
    bound_count = 0
    und_count = 0
    for aid, v in sorted(a.get("atom_bindings", {}).items()):
        val = str(v.get("value", ""))
        if "UNDETERMINED" in val.upper() or val == "undetermined":
            und_count += 1
        else:
            bound_count += 1
            print(f"  {aid}: {v}")
    print()
    print(f"  Total bound to value: {bound_count}")
    print(f"  Total UNDETERMINED: {und_count}")
    print()

    print("=" * 70)
    print("DETERMINATION TRACES")
    print("=" * 70)
    for det_id, trace in a.get("per_determination_traces", {}).items():
        print(f"\n--- {det_id} ---")
        for entry in trace:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("type", "")
            label = (entry.get("surface_label", "")
                     or entry.get("atom_id", "")
                     or entry_type)
            result = entry.get("result", entry.get("value", ""))
            print(f"  [{entry_type}] {label}: {result}")
            # Show top-level child results for and/or nodes
            if entry_type in ("and", "or") and "children_trace" in entry:
                for child in entry["children_trace"]:
                    if not isinstance(child, dict):
                        continue
                    ctype = child.get("type", "")
                    clabel = (child.get("surface_label", "")
                              or child.get("atom_id", "")
                              or ctype)
                    cresult = child.get("result", child.get("value", ""))
                    print(f"    - [{ctype}] {clabel}: {cresult}")


if __name__ == "__main__":
    main()

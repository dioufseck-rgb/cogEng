"""
Create an experimental variant of the PA tree with sharpened prompts on
two borderline leaves: pharmacotherapy_requirement_met and
pt_contraindicated_or_futile.

This produces pa_appeal_tree_sharpened.json. The two prompts are rewritten
to add explicit decision criteria. All other tree content is unchanged.

The rewrites preserve the policy's underlying intent — they add specificity
without changing the underlying question or biasing the substrate toward
a particular value.

Usage:
    python3 sharpen_prompts.py
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Sharpened prompts.

SHARPENED = {
    "pharmacotherapy_requirement_met": (
        "Has the pharmacotherapy requirement been met? "
        "Requires trial of at least TWO distinct agent classes from this list, "
        "each trialed for a minimum of 4 cumulative weeks:\n"
        "- NSAIDs or COX-2 inhibitors\n"
        "- Muscle relaxants\n"
        "- Neuropathic agents (gabapentin, pregabalin, duloxetine, "
        "  tricyclic antidepressants)\n"
        "- Oral corticosteroids (note: brief dose packs of <2 weeks do NOT "
        "  count as 4-week trial of this class)\n\n"
        "Decision criteria — return TRUE only if BOTH of the following are met:\n"
        "  (1) Documentation shows at least 2 distinct classes were trialed.\n"
        "  (2) Each trialed class meets the 4-week cumulative-duration minimum, "
        "      with dose/frequency that would constitute a therapeutic trial "
        "      (not isolated single doses or sub-therapeutic dosing).\n\n"
        "Return FALSE if either condition is not met. Return FALSE if the "
        "documentation is ambiguous about duration or dose adequacy — the "
        "burden of demonstrating completion is on the requesting party.\n\n"
        "This requirement applies in full under both STANDARD and MYELOPATHY "
        "pathways — § 2.2A explicitly retains the pharmacotherapy requirement.\n\n"
        "Cite the specific medication records, pharmacy fills, or treating "
        "physician documentation that support the determination."
    ),
    "pt_contraindicated_or_futile": (
        "Has physical therapy been documented as contraindicated or futile, "
        "such that CIC § 10169.5 carve-out applies (PT requirement waived)?\n\n"
        "This is a discretionary clinical determination by the treating "
        "physician. The carve-out is intended for cases where PT genuinely "
        "cannot help or would be harmful — not for cases where PT was "
        "incomplete by member choice.\n\n"
        "Decision criteria — return TRUE only if at least ONE of the "
        "following is documented:\n"
        "  (a) Explicit contraindication: medical condition that makes PT "
        "      unsafe (e.g., acute instability, severe osteoporosis with "
        "      fracture risk, severe progressive neurological deficit).\n"
        "  (b) Documented functional plateau after substantive PT trial: "
        "      treating physician or PT clinician documents that the patient "
        "      has reached maximum medical improvement from PT and further "
        "      therapy is not expected to provide additional benefit.\n"
        "  (c) Documented progressive worsening despite PT: PT was attempted "
        "      and condition objectively worsened (e.g., progressive "
        "      neurological deficit during therapy).\n\n"
        "Return FALSE if PT was incomplete due to patient choice without "
        "documented contraindication, plateau, or worsening.\n\n"
        "Return FALSE if documentation is ambiguous — the carve-out requires "
        "affirmative documented evidence, not absence of evidence.\n\n"
        "Cite the specific clinical documentation supporting the determination."
    ),
}


def main():
    src = _HERE / "pa_appeal_tree.json"
    dst = _HERE / "pa_appeal_tree_sharpened.json"

    data = json.loads(src.read_text())
    tree = data["tree"]

    # Apply sharpening
    changed = []
    for nid, new_text in SHARPENED.items():
        if nid not in tree:
            raise SystemExit(f"Node {nid} not found in tree")
        old = tree[nid].get("condition_text", "")
        tree[nid]["condition_text"] = new_text
        changed.append((nid, len(old), len(new_text)))

    # Bump version to make the sharpened variant identifiable in artifacts
    data["tree_metadata"]["version"] = "1.1-sharpened"

    dst.write_text(json.dumps(data, indent=2))
    print(f"Wrote sharpened tree: {dst.name}")
    print()
    for nid, old_len, new_len in changed:
        print(f"  {nid}: {old_len} chars → {new_len} chars")
    print()
    print("Version bumped to 1.1-sharpened so runs are identifiable.")


if __name__ == "__main__":
    main()

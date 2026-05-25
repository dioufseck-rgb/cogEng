"""
identify_clusters.py - inspect tagging output to find candidate cluster
regions for cap_room.

Walks the consolidated tag output, surfaces:
  - All OBLIGATION sentences (cluster anchors)
  - For each OBLIGATION, the surrounding window of CONDITION/THRESHOLD/
    EXCEPTION sentences that probably belong to its cluster
  - Section markers (COMMENT-tagged sentences that look like headers)

Output is informational - helps us pick which cluster ranges to compose.

Usage:
    python bin/identify_clusters.py
    python bin/identify_clusters.py --tagging audits/tagging_stability/tagging_run1_consolidated.json
"""
import argparse
import json
import re


SECTION_PATTERNS = [
    (r"#\s+Article\s+(VII|II|I)", "ARTICLE_HEADER"),
    (r"^\(\w+\)\s+\"", "DEFINITION_ENTRY"),
    (r"^\([a-z]\)\s+", "SUBSECTION"),  # (a), (b), ...
    (r"^Section\s+6", "SECTION_6"),
    (r"Bi-annual\s+Exception", "BAE"),
    (r"Non-Taxpayer\s+Mid-Level", "NT_MLE"),
    (r"Taxpayer\s+Mid-Level", "T_MLE"),
    (r"Mid-Level\s+Salary\s+Exception\s+for\s+Room", "ROOM_MLE"),
    (r"Veteran\s+Free\s+Agent\s+Exception", "VFA"),
    (r"Minimum\s+Player\s+Salary\s+Exception", "MIN_PLAYER"),
    (r"Traded\s+Player\s+Exception", "TPE"),
]


def classify(text):
    """Return a list of structural markers found in the text."""
    markers = []
    for pat, name in SECTION_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            markers.append(name)
    return markers


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tagging",
                   default="audits/tagging_stability/tagging_run1_consolidated.json")
    args = p.parse_args()

    with open(args.tagging, encoding="utf-8") as f:
        tags = json.load(f)

    print(f"Loaded {len(tags)} tagged sentences\n")

    # First pass: find structural section markers
    print("=" * 70)
    print("STRUCTURAL MARKERS (section boundaries)")
    print("=" * 70)
    print()
    section_markers = []
    for t in tags:
        sid = t.get("sentence_id")
        text = t.get("text_snippet", "")
        tag = t.get("tag", "")
        markers = classify(text)
        if markers:
            section_markers.append((sid, markers, tag, text))
            print(f"  [{sid:>3}] {','.join(markers):<25} (tag={tag}) {text[:60]}")
    print()

    # Second pass: identify OBLIGATION anchors and their surrounding context
    print("=" * 70)
    print("OBLIGATION ANCHORS (potential cluster centers)")
    print("=" * 70)
    print()
    obligations = [(t["sentence_id"], t.get("text_snippet", ""))
                   for t in tags if t.get("tag") == "OBLIGATION"]
    print(f"Total OBLIGATION-tagged sentences: {len(obligations)}\n")
    for sid, text in obligations[:30]:
        print(f"  [{sid:>3}] {text[:80]}")
    if len(obligations) > 30:
        print(f"  ... and {len(obligations) - 30} more")
    print()

    # Third pass: surface candidate cluster regions around named exceptions
    print("=" * 70)
    print("CANDIDATE EXCEPTION-CLUSTER REGIONS")
    print("=" * 70)
    print()
    target_exceptions = ["BAE", "NT_MLE", "T_MLE", "ROOM_MLE",
                          "VFA", "MIN_PLAYER", "TPE"]
    for exc in target_exceptions:
        print(f"\n--- {exc} ---")
        # Find sentences mentioning this exception
        hits = []
        for t in tags:
            sid = t.get("sentence_id")
            text = t.get("text_snippet", "")
            if exc in classify(text):
                hits.append((sid, t.get("tag"), text))
        if not hits:
            print(f"  (no sentences match)")
            continue
        # Show first ~5 hits to identify the cluster's likely range
        for sid, tag, text in hits[:8]:
            print(f"  [{sid:>3}] {tag:<12} {text[:70]}")
        if len(hits) > 8:
            print(f"  ... and {len(hits)-8} more")
        # Suggested cluster range: first hit's sid through last hit's sid (capped)
        first_sid = hits[0][0]
        last_sid = hits[-1][0]
        range_size = last_sid - first_sid + 1
        if range_size <= 50:
            print(f"  -> Suggested cluster range: sentences [{first_sid}-{last_sid}] "
                  f"({range_size} sentences)")
        else:
            # The exception is mentioned across a wide range — needs careful curation
            print(f"  -> Wide range [{first_sid}-{last_sid}] ({range_size} sentences); "
                  f"cluster needs manual narrowing")

    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)
    print()
    print("Next step: pick 2-3 candidate clusters from the regions above.")
    print("For each, identify the sentence range that contains:")
    print("  - The exception's OBLIGATION/permission statement")
    print("  - Its CONDITIONs (eligibility requirements)")
    print("  - Its THRESHOLDs (amount limits)")
    print("Hand-extract these into tagged-unit JSON for the next composition probe.")


if __name__ == "__main__":
    main()

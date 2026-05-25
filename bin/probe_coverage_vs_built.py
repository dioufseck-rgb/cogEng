"""
probe_coverage_vs_built.py - test whether Phase 1 sentence-level tagging
preserves at least the operative content that monolithic decompose
extracted into built_nba_v2.pkl.

Method:
  - Load atoms from built_nba_v2.pkl
  - Load tagged sentences from audits/tagging_stability/tagging_run1_raw.json
  - For each atom, find tagged sentences whose text plausibly grounds it
  - Count matches with operative tags (OBLIGATION, THRESHOLD, EXCEPTION,
    CONDITION, DEFINITION) vs. non-operative tags (COMMENT, EXAMPLE)
  - Report unmatched atoms — these would represent content the tagging
    phase missed but monolithic decompose found

No LLM cost. Pure analytical comparison.

Usage:
    python bin/probe_coverage_vs_built.py
"""
import argparse
import json
import os
import pickle
import re
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


# Tags that preserve operative content
OPERATIVE_TAGS = {"OBLIGATION", "THRESHOLD", "EXCEPTION", "CONDITION", "DEFINITION"}
NON_OPERATIVE_TAGS = {"COMMENT", "EXAMPLE", "REFERENCE"}


def extract_key_terms(text, min_len=4):
    """Extract distinctive multi-character tokens from text.
    Used to find overlap between atom statements and tagged sentences."""
    # Strip punctuation, lowercase, split on whitespace
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = cleaned.split()
    # Filter to substantive terms
    stopwords = {
        "the", "and", "for", "this", "that", "with", "from", "into", "such",
        "than", "have", "been", "any", "all", "must", "may", "not", "are",
        "shall", "will", "team", "player", "salary",  # too common in NBA
        "section", "article", "subsection", "subsec", "paragraph",
        "above", "below", "such", "case", "year",
    }
    return {t for t in tokens if len(t) >= min_len and t not in stopwords}


def overlap_score(atom_terms, sentence_terms):
    """Jaccard-style overlap between atom and sentence."""
    if not atom_terms:
        return 0.0
    intersection = atom_terms & sentence_terms
    return len(intersection) / max(1, len(atom_terms))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--built", default="built_nba_v2.pkl")
    p.add_argument("--tagging", default="audits/tagging_stability/tagging_run1_raw.json")
    p.add_argument("--det", default="nba.cap_room",
                   help="Restrict to atoms used by this determination")
    p.add_argument("--threshold", type=float, default=0.3,
                   help="Minimum overlap score to count as a match (0-1)")
    p.add_argument("--top-k", type=int, default=3,
                   help="Show top K candidate sentences per atom")
    args = p.parse_args()

    # Load built DAG
    print(f"Loading {args.built}...")
    with open(args.built, "rb") as f:
        build = pickle.load(f)

    all_atoms = build.atoms
    print(f"  Total atoms in DAG: {len(all_atoms)}")

    # Restrict to atoms reachable from the target determination
    if args.det in build.determinations:
        det_tree = build.determinations[args.det]
        atom_ids_used = set()

        def collect(node):
            name = type(node).__name__
            if name in ("Leaf", "NumericLeaf") and hasattr(node, "atom_id"):
                aid = getattr(node, "atom_id", None)
                if aid:
                    atom_ids_used.add(aid)
            if hasattr(node, "children") and isinstance(node.children, list):
                for c in node.children:
                    collect(c)
            for attr in ("left", "right", "child", "tree"):
                if hasattr(node, attr):
                    c = getattr(node, attr)
                    if c is not None and not isinstance(c, (str, int, float)):
                        collect(c)

        collect(det_tree)
        atoms = {aid: a for aid, a in all_atoms.items() if aid in atom_ids_used}
        print(f"  Atoms used by {args.det}: {len(atoms)}")
    else:
        atoms = all_atoms
        print(f"  Determination {args.det} not found; using all atoms.")
    print()

    # Load tagged sentences
    print(f"Loading {args.tagging}...")
    with open(args.tagging, encoding="utf-8") as f:
        raw = f.read()
    # Handle partial JSON (truncated outputs from earlier probes)
    # Try to recover as much as possible
    try:
        tagged = json.loads(raw)
    except json.JSONDecodeError:
        # Truncated — find all complete entries
        matches = re.findall(
            r'\{[^{}]*"sentence_id"\s*:\s*\d+[^{}]*\}',
            raw
        )
        tagged = []
        for m in matches:
            try:
                tagged.append(json.loads(m))
            except json.JSONDecodeError:
                pass
        print(f"  Recovered {len(tagged)} tag entries from truncated JSON")

    print(f"  Total tagged sentences: {len(tagged)}")
    operative = [t for t in tagged if t.get("tag") in OPERATIVE_TAGS]
    non_operative = [t for t in tagged if t.get("tag") in NON_OPERATIVE_TAGS]
    print(f"  Operative tags: {len(operative)}")
    print(f"  Non-operative tags: {len(non_operative)}")
    print()

    # Pre-compute terms for tagged sentences
    sentence_data = []
    for t in tagged:
        text = t.get("text_snippet", "")
        sentence_data.append({
            "sentence_id": t.get("sentence_id"),
            "tag": t.get("tag"),
            "text": text,
            "terms": extract_key_terms(text),
        })

    # For each atom, find best-matching tagged sentences
    print("=" * 70)
    print("ATOM <-> TAGGED-SENTENCE MATCHING")
    print("=" * 70)
    print()

    results = []
    unmatched = []
    matched_operative = []
    matched_non_operative = []

    for aid, atom in sorted(atoms.items()):
        stmt = getattr(atom, "statement", "") or ""
        atom_terms = extract_key_terms(stmt)

        # Score all sentences
        scored = []
        for s in sentence_data:
            score = overlap_score(atom_terms, s["terms"])
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])

        top = scored[:args.top_k]
        best_score = top[0][0] if top else 0
        best_match = top[0][1] if top else None

        if best_score < args.threshold:
            unmatched.append({
                "atom_id": aid,
                "statement": stmt,
                "best_score": best_score,
                "best_match": best_match["text"][:80] if best_match else None,
            })
            continue

        if best_match["tag"] in OPERATIVE_TAGS:
            matched_operative.append({
                "atom_id": aid,
                "statement": stmt,
                "score": best_score,
                "match_tag": best_match["tag"],
                "match_text": best_match["text"][:80],
            })
        else:
            matched_non_operative.append({
                "atom_id": aid,
                "statement": stmt,
                "score": best_score,
                "match_tag": best_match["tag"],
                "match_text": best_match["text"][:80],
            })

        results.append({
            "atom_id": aid,
            "statement": stmt,
            "top_matches": [
                {
                    "score": round(score, 3),
                    "tag": s["tag"],
                    "text": s["text"][:80],
                }
                for score, s in top
            ],
        })

    # Summary
    total = len(atoms)
    print(f"Total atoms in determination: {total}")
    print(f"  Matched to OPERATIVE-tagged sentence (>= {args.threshold} overlap): "
          f"{len(matched_operative)} ({100*len(matched_operative)/max(1,total):.0f}%)")
    print(f"  Matched to NON-OPERATIVE-tagged sentence (>= {args.threshold} overlap): "
          f"{len(matched_non_operative)} ({100*len(matched_non_operative)/max(1,total):.0f}%)")
    print(f"  Unmatched (no good candidate): "
          f"{len(unmatched)} ({100*len(unmatched)/max(1,total):.0f}%)")
    print()

    # Show non-operative matches (these are atoms whose content was extracted
    # by decompose but tagged as non-operative by Phase 1 — potential coverage gap)
    if matched_non_operative:
        print("-" * 70)
        print("ATOMS MATCHED TO NON-OPERATIVE TAGS (potential coverage gap):")
        print("-" * 70)
        for m in matched_non_operative[:15]:
            print(f"\n  Atom: {m['atom_id']}")
            print(f"    Statement: {m['statement'][:100]}")
            print(f"    Best match (tag={m['match_tag']}, score={m['score']:.2f}):")
            print(f"      {m['match_text']}")
        if len(matched_non_operative) > 15:
            print(f"\n  ...and {len(matched_non_operative) - 15} more")
        print()

    # Show unmatched (these are atoms with no good candidate sentence — definite coverage gap)
    if unmatched:
        print("-" * 70)
        print("UNMATCHED ATOMS (no tagged sentence found above threshold):")
        print("-" * 70)
        for m in unmatched[:15]:
            print(f"\n  Atom: {m['atom_id']}")
            print(f"    Statement: {m['statement'][:100]}")
            print(f"    Best candidate score: {m['best_score']:.2f}")
            if m['best_match']:
                print(f"    Closest candidate: {m['best_match']}")
        if len(unmatched) > 15:
            print(f"\n  ...and {len(unmatched) - 15} more")
        print()

    # Distribution of matched-operative tags
    if matched_operative:
        print("-" * 70)
        print(f"OPERATIVE-MATCH TAG DISTRIBUTION:")
        tag_counts = Counter(m["match_tag"] for m in matched_operative)
        for tag, count in tag_counts.most_common():
            print(f"  {tag}: {count}")
        print()

    # Save detail
    out_path = "audits/coverage_vs_built.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "determination": args.det,
            "total_atoms": total,
            "matched_operative": len(matched_operative),
            "matched_non_operative": len(matched_non_operative),
            "unmatched": len(unmatched),
            "threshold": args.threshold,
            "details": results[:50],  # sample
            "non_operative_matches": matched_non_operative,
            "unmatched_atoms": unmatched,
        }, f, indent=2)
    print(f"Detail saved to {out_path}")
    print()

    # Interpretation
    print("=" * 70)
    print("INTERPRETATION")
    print("=" * 70)
    op_rate = len(matched_operative) / max(1, total)
    miss_rate = len(unmatched) / max(1, total)

    if op_rate >= 0.85 and miss_rate <= 0.05:
        print(f"GOOD COVERAGE.")
        print(f"  {op_rate:.0%} of atoms ground in operative-tagged sentences.")
        print(f"  Only {miss_rate:.0%} of atoms have no plausible source sentence.")
        print(f"  Phase 1 tagging is preserving the operative content that")
        print(f"  monolithic decompose extracted.")
    elif op_rate >= 0.70:
        print(f"MODERATE COVERAGE.")
        print(f"  {op_rate:.0%} of atoms ground in operative-tagged sentences.")
        print(f"  {len(matched_non_operative)} atoms match non-operative tags")
        print(f"  ({100*len(matched_non_operative)/max(1,total):.0f}%) — review these")
        print(f"  to see if they represent real content lost in tagging.")
        print(f"  {miss_rate:.0%} unmatched.")
    else:
        print(f"COVERAGE GAP IDENTIFIED.")
        print(f"  Only {op_rate:.0%} of atoms ground in operative-tagged sentences.")
        print(f"  Either Phase 1 is mis-tagging operative content,")
        print(f"  or monolithic decompose is extracting from sentences")
        print(f"  not in the truncated tagging output (the most likely")
        print(f"  explanation given Phase 1 only completed ~60/314 sentences).")
        print()
        print(f"  Recommend re-running Phase 1 with chunked processing")
        print(f"  to get tags for all 314 sentences before drawing conclusions.")


if __name__ == "__main__":
    main()

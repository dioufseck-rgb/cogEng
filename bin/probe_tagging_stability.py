"""
probe_tagging_stability.py — test whether sentence-level functional tagging
of policy text is stable across independent LLM runs.

Hypothesis: if forcing the LLM to commit to a tag per sentence produces
stable assignments, then compositional decomposition (every unit has a
typed role) is a viable alternative to monolithic decompose.

If tags are unstable, the latitude problem exists even at the unit level,
and compositional approach would inherit the same variance.

Method:
  - Extract the policy span for cap_room from cba.yaml's source_span
  - Split into sentences (simple period-based split, preserving structure)
  - Run an LLM tagging pass three times, structured-output JSON
  - Compare tag assignments across runs
  - Report stability metrics

Usage:
    python bin/probe_tagging_stability.py
    python bin/probe_tagging_stability.py --det nba.cap_room --n 3

Cost: ~$3-5 total (3 tagging passes on a ~3-page policy span).
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


TAG_VOCABULARY = """
You will tag sentences with EXACTLY ONE of these functional roles:

THRESHOLD  - sentence names a numeric limit, ceiling, floor, or comparison
             (e.g., "The Salary Cap is $140,588,000")
OBLIGATION - sentence states what MUST, MAY, or MAY NOT happen
             (e.g., "A Team's Team Salary may not exceed the Salary Cap")
EXCEPTION  - sentence names a carve-out, alternative path, or "unless" clause
             (e.g., "Notwithstanding the foregoing, a Team may exceed the Cap if...")
CONDITION  - sentence states an antecedent or precondition (typically "if X, then Y")
             that gates an obligation or exception
DEFINITION - sentence defines a term, formula, or named concept
             (e.g., "'Team Salary' means the sum of all Player Contracts...")
REFERENCE  - sentence's primary content is a cross-reference to another section
             (e.g., "subject to Article VII Section 6")
EXAMPLE    - illustrative content, not operative
             (e.g., "For example, if Team A...")
COMMENT    - descriptive, contextual, or transitional content with no operative force
             (e.g., section headings, explanatory preambles)
"""

TAGGING_PROMPT_TEMPLATE = """You are analyzing a policy text from a regulatory document.
Your task is structural classification: assign each sentence a single functional role.

{tag_vocabulary}

OUTPUT INSTRUCTIONS:
Return a JSON array. For each sentence, produce an object with:
  - "sentence_id": the sentence's index in the input (integer)
  - "text_snippet": first 80 characters of the sentence
  - "tag": exactly one of the tag names above
  - "confidence": "high" if the sentence clearly fits the tag, "low" if borderline

Produce one object per sentence in the input. Account for every sentence — do not skip.
Output ONLY the JSON array, no preamble or commentary.

POLICY TEXT (sentences numbered):
{numbered_text}
"""


def split_sentences(text):
    """Simple sentence splitter that preserves structure markers.
    Splits on period followed by whitespace+capital, but keeps section
    headings (lines that don't end with period) as separate units."""
    lines = text.strip().split("\n")
    sentences = []
    sid = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # If line doesn't end with period or has very few words, treat as single unit
        if not line.endswith(".") or len(line.split()) < 4:
            sentences.append((sid, line))
            sid += 1
            continue
        # Sentence-split on ". " followed by uppercase or digit
        parts = re.split(r'(?<=[.])\s+(?=[A-Z0-9])', line)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append((sid, part))
                sid += 1
    return sentences


def build_numbered_text(sentences):
    return "\n".join(f"[{sid}] {text}" for sid, text in sentences)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--det", default="nba.cap_room")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--spec", default="domains/nba/cba.yaml")
    p.add_argument("--out-dir", default="audits/tagging_stability")
    p.add_argument("--model", default="claude-opus-4-7")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    from rulekit.build.decomposer import load_spec_from_yaml, LLMCaller
    from domains.voices import VOICES

    spec = load_spec_from_yaml(args.spec, voices_registry=VOICES)

    # Find the determination's policy span
    det_decl = next((d for d in spec.determinations if d.id == args.det), None)
    if det_decl is None:
        print(f"ERROR: determination {args.det} not found")
        sys.exit(1)

    # Load the policy text from the source path. BuildSpec stores it as
    # a file path; build_from_spec reads it at Build time. We do the same.
    with open(spec.policy_source, encoding="utf-8") as f:
        policy_text = f.read()

    # Extract the source_span lines
    if det_decl.source_span and len(det_decl.source_span) == 2:
        start, end = det_decl.source_span
        lines = policy_text.split("\n")
        span_text = "\n".join(lines[start-1:end])
    else:
        span_text = policy_text

    print(f"Determination: {args.det}")
    print(f"Source span: lines {det_decl.source_span}")
    print(f"Span length: {len(span_text)} chars")
    print()

    # Split into sentences
    sentences = split_sentences(span_text)
    print(f"Sentences extracted: {len(sentences)}")
    print()
    # Show first few sentences as a sanity check
    for sid, text in sentences[:5]:
        print(f"  [{sid}] {text[:80]}")
    if len(sentences) > 5:
        print(f"  ... and {len(sentences) - 5} more")
    print()

    numbered = build_numbered_text(sentences)
    
    # Chunked tagging: process CHUNK_SIZE sentences per LLM call.
    # Each LLM response is short enough to avoid max_tokens truncation,
    # and we concatenate results across chunks.
    CHUNK_SIZE = 50
    chunks = []
    for chunk_start in range(0, len(sentences), CHUNK_SIZE):
        chunk_end = min(chunk_start + CHUNK_SIZE, len(sentences))
        chunk_sentences = sentences[chunk_start:chunk_end]
        chunks.append((chunk_start, chunk_end, chunk_sentences))

    print(f"Chunking {len(sentences)} sentences into {len(chunks)} chunks of up to {CHUNK_SIZE}.")
    print()

    llm = LLMCaller(model=args.model)

    # Run N tagging passes, each pass processing all chunks
    runs = []
    for i in range(args.n):
        print(f"=== Tagging Run {i+1}/{args.n} ===")
        all_tags = []
        run_elapsed = 0.0
        run_errors = 0

        for chunk_idx, (start, end, chunk_sentences) in enumerate(chunks):
            chunk_numbered = build_numbered_text(chunk_sentences)
            chunk_prompt = TAGGING_PROMPT_TEMPLATE.format(
                tag_vocabulary=TAG_VOCABULARY,
                numbered_text=chunk_numbered,
            )

            t0 = time.time()
            response = llm.call(
                f"tag_run_{i+1}_chunk_{chunk_idx+1}",
                chunk_prompt
            )
            elapsed = time.time() - t0
            run_elapsed += elapsed

            # Save raw chunk response
            raw_path = os.path.join(
                args.out_dir,
                f"tagging_run{i+1}_chunk{chunk_idx+1}_raw.json"
            )
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(response)

            # Parse this chunk's JSON
            try:
                cleaned = response.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
                    cleaned = re.sub(r"\n```\s*$", "", cleaned)
                chunk_tags = json.loads(cleaned)
                all_tags.extend(chunk_tags)
                print(f"  Chunk {chunk_idx+1}/{len(chunks)} "
                      f"(sentences {start}-{end-1}): "
                      f"{len(chunk_tags)} tags in {elapsed:.1f}s")
            except json.JSONDecodeError as e:
                print(f"  Chunk {chunk_idx+1}/{len(chunks)}: PARSE ERROR ({e})")
                run_errors += 1
                # Try to salvage individual entries
                matches = re.findall(
                    r'\{[^{}]*"sentence_id"\s*:\s*\d+[^{}]*\}',
                    response
                )
                salvaged = 0
                for m in matches:
                    try:
                        all_tags.append(json.loads(m))
                        salvaged += 1
                    except json.JSONDecodeError:
                        pass
                if salvaged:
                    print(f"    Salvaged {salvaged} tag entries")

        # Save consolidated tag list for this run
        consolidated_path = os.path.join(
            args.out_dir,
            f"tagging_run{i+1}_consolidated.json"
        )
        with open(consolidated_path, "w", encoding="utf-8") as f:
            json.dump(all_tags, f, indent=2)

        tag_dist = Counter(t.get("tag", "UNKNOWN") for t in all_tags)
        print(f"  TOTAL: {len(all_tags)} / {len(sentences)} tagged "
              f"in {run_elapsed:.1f}s ({run_errors} chunk errors)")
        print(f"  Tag distribution: {dict(tag_dist)}")
        print()

        runs.append({
            "run": i + 1,
            "tags": all_tags,
            "tag_distribution": dict(tag_dist),
            "elapsed_s": run_elapsed,
            "chunk_errors": run_errors,
        })

    # === Stability analysis ===
    print("=" * 70)
    print("TAGGING STABILITY ANALYSIS")
    print("=" * 70)
    print()

    # 1. Per-sentence tag agreement
    print("Per-sentence tag assignments across runs:")
    sentence_tags = {}  # sid -> list of tags from each run
    for r in runs:
        for t in r["tags"]:
            sid = t.get("sentence_id")
            if sid is not None:
                sentence_tags.setdefault(sid, [None] * args.n)
                if r["run"] - 1 < args.n:
                    sentence_tags[sid][r["run"] - 1] = t.get("tag")

    full_agreement = 0
    partial_agreement = 0
    full_disagreement = 0
    missing = 0
    for sid in sorted(sentence_tags.keys()):
        tags_for_sentence = sentence_tags[sid]
        non_none = [t for t in tags_for_sentence if t is not None]
        if len(non_none) < args.n:
            missing += 1
            continue
        unique_tags = set(non_none)
        if len(unique_tags) == 1:
            full_agreement += 1
        elif len(unique_tags) == args.n:
            full_disagreement += 1
        else:
            partial_agreement += 1

    total_evaluable = full_agreement + partial_agreement + full_disagreement
    print(f"  Total sentences evaluated: {total_evaluable}")
    print(f"  Full agreement (all {args.n} runs same tag): "
          f"{full_agreement} ({100 * full_agreement / max(1, total_evaluable):.0f}%)")
    print(f"  Partial agreement (2 of {args.n} match): "
          f"{partial_agreement} ({100 * partial_agreement / max(1, total_evaluable):.0f}%)")
    print(f"  Full disagreement (all {args.n} different): "
          f"{full_disagreement} ({100 * full_disagreement / max(1, total_evaluable):.0f}%)")
    if missing > 0:
        print(f"  Sentences missing from some runs: {missing}")
    print()

    # 2. Show disagreements
    if full_disagreement + partial_agreement > 0:
        print("Sentences with tag disagreement:")
        shown = 0
        for sid in sorted(sentence_tags.keys()):
            tags_for_sentence = sentence_tags[sid]
            non_none = [t for t in tags_for_sentence if t is not None]
            if len(set(non_none)) > 1:
                # Find the sentence text
                stext = next((t for s, t in sentences if s == sid), "(not found)")
                print(f"  [{sid}] {stext[:75]}")
                print(f"        runs: {tags_for_sentence}")
                shown += 1
                if shown >= 10:
                    print(f"  ... and {full_disagreement + partial_agreement - shown} more")
                    break
        print()

    # 3. Tag distribution stability
    print("Tag distributions across runs:")
    all_tags = sorted({tag for r in runs for tag in r["tag_distribution"]})
    print(f"  {'Tag':<12} " + " ".join(f"Run{r['run']}" for r in runs))
    for tag in all_tags:
        counts = [r["tag_distribution"].get(tag, 0) for r in runs]
        consistency = "stable" if len(set(counts)) == 1 else "VARIES"
        row = f"  {tag:<12} " + " ".join(f"{c:>4}" for c in counts) + f"   ({consistency})"
        print(row)
    print()

    # Save summary
    summary = {
        "determination": args.det,
        "model": args.model,
        "n_runs": args.n,
        "n_sentences": len(sentences),
        "stability": {
            "full_agreement": full_agreement,
            "partial_agreement": partial_agreement,
            "full_disagreement": full_disagreement,
            "missing": missing,
            "agreement_rate": full_agreement / max(1, total_evaluable),
        },
        "runs": runs,
    }
    summary_path = os.path.join(args.out_dir, "tagging_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"Summary written to {summary_path}")
    print()

    # Interpretation
    print("=" * 70)
    print("INTERPRETATION")
    print("=" * 70)
    rate = full_agreement / max(1, total_evaluable)
    if rate >= 0.85:
        print(f"HIGH STABILITY ({rate:.0%} full agreement).")
        print("Sentence-level functional tagging is consistent across runs.")
        print("Compositional approach has empirical traction. Decomposing into")
        print("typed units appears to remove much of the variance latitude.")
        print("Next step: explore building the parsing layer that combines tags.")
    elif rate >= 0.6:
        print(f"MODERATE STABILITY ({rate:.0%} full agreement).")
        print("Some agreement, but meaningful variance exists at the tag level.")
        print("Compositional approach would inherit some variance. Worth")
        print("inspecting disagreements: are they on borderline sentences")
        print("(where reasonable taggers might disagree) or on substantive")
        print("ones (genuine interpretive variance)?")
    else:
        print(f"LOW STABILITY ({rate:.0%} full agreement).")
        print("Tagging is highly variable even at the unit level.")
        print("Compositional approach unlikely to reduce variance much.")
        print("The latitude is in interpretation of each unit, not just")
        print("in composition. Need different intervention.")


if __name__ == "__main__":
    main()

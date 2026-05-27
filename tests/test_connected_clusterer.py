"""
test_connected_clusterer.py - tests for the connected-component
clusterer (Phase 2 with graph-construction semantics).
"""
from __future__ import annotations
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.build.clusterer import TaggedUnit
from rulekit.build.connected_clusterer import (
    extract_references,
    section_matches_reference,
    extract_defined_terms,
    find_term_references,
    build_section_contexts,
    find_connected_cluster,
    find_all_obligation_clusters,
    ADJACENCY,
    EXPLICIT_REFERENCE,
    TERM_REFERENCE,
)

passed = 0
failed = 0


def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


def mk(sid, tag, text="..."):
    return TaggedUnit(sentence_id=sid, text=text, tag=tag)


# ---------------------------------------------------------------------------
# Reference extraction
# ---------------------------------------------------------------------------
print("--- Reference extraction ---")

refs = extract_references("A Team's Salary may not exceed the Salary Cap "
                          "unless the Team is using an Exception under Article VII, Section 6.")
ref_kinds = {k for k, _ in refs}
check("article" in ref_kinds, "Detects Article reference")
check("section" in ref_kinds, "Detects Section reference")

refs = extract_references("Subject to Section 6(d) Bi-annual Exception.")
ref_values = {v for _, v in refs}
check("6(d)" in ref_values, "Detects Section 6(d)")

refs = extract_references("See §6(b) for Veteran Free Agent rules.")
check(any("6(b)" in v for _, v in refs), "Detects § symbol references")

refs = extract_references("This paragraph contains no references at all.")
check(len(refs) == 0, "No false positives in reference-free text")


# ---------------------------------------------------------------------------
# Section matching
# ---------------------------------------------------------------------------
print("--- Section matching ---")

check(
    section_matches_reference(
        "# Article VII, Section 6: Exceptions to the Salary Cap",
        "section", "6"
    ),
    "'Section 6' matches '# Article VII, Section 6'"
)
check(
    section_matches_reference("(d) Bi-annual Exception.", "section", "6(d)"),
    "'Section 6(d)' matches subsection '(d) Bi-annual Exception'"
)
check(
    section_matches_reference(
        "# Article VII, Section 6: Exceptions to the Salary Cap",
        "article", "VII"
    ),
    "'Article VII' matches matching section text"
)
check(
    not section_matches_reference("# Article II, Section 7", "section", "6"),
    "Article II Section 7 does NOT match Section 6"
)


# ---------------------------------------------------------------------------
# Defined-term extraction
# ---------------------------------------------------------------------------
print("--- Defined term extraction ---")

definitions = [
    mk(1, "DEFINITION", '(t) "Early Qualifying Veteran Free Agent" means a Veteran...'),
    mk(2, "DEFINITION", '(yy) "Qualifying Veteran Free Agent" means a Veteran...'),
    mk(3, "DEFINITION", '(hhhh) "Veteran Free Agent" means a Veteran...'),
]
terms = extract_defined_terms(definitions)
check("early qualifying veteran free agent" in terms, "Extracts 'Early Qualifying Veteran Free Agent'")
check("qualifying veteran free agent" in terms, "Extracts 'Qualifying Veteran Free Agent'")
check("veteran free agent" in terms, "Extracts 'Veteran Free Agent'")


# ---------------------------------------------------------------------------
# Find term references in text
# ---------------------------------------------------------------------------
print("--- Term references in text ---")

text = "A Qualifying Veteran Free Agent may sign with his Prior Team."
hits = find_term_references(text, terms)
hit_terms = {t for t, _ in hits}
check("qualifying veteran free agent" in hit_terms,
      "Finds 'Qualifying Veteran Free Agent' in obligation text")
# Note: "veteran free agent" is a substring of "qualifying veteran free agent",
# so it will also match. That's expected behavior — both terms genuinely
# appear in the text.
check("veteran free agent" in hit_terms,
      "Finds 'Veteran Free Agent' (as a substring)")


# ---------------------------------------------------------------------------
# Section context building
# ---------------------------------------------------------------------------
print("--- Section context building ---")

units = [
    mk(0, "COMMENT", "# Article I: Definitions"),
    mk(1, "DEFINITION", '(t) "Foo" means ...'),
    mk(2, "DEFINITION", '(u) "Bar" means ...'),
    mk(3, "COMMENT", "# Article VII, Section 6: Exceptions"),
    mk(4, "COMMENT", "(d) Bi-annual Exception."),
    mk(5, "OBLIGATION", "A Team may use the Bi-annual Exception..."),
]
contexts = build_section_contexts(units)
check(contexts[1] == "# Article I: Definitions",
      "Sentence 1 is in Article I")
# After the new hierarchical context: sid 5 carries both Section 6 and (d) Bi-annual
check("Article VII, Section 6" in contexts[5] and "Bi-annual" in contexts[5],
      "Sentence 5 has both section and subsection context")


# ---------------------------------------------------------------------------
# Connected cluster: adjacency only
# ---------------------------------------------------------------------------
print("--- Adjacency-only connection ---")

units = [
    mk(0, "OBLIGATION", "Team Salary may not exceed Cap."),
    mk(1, "THRESHOLD", "Cap is $140M."),
    mk(2, "CONDITION", "Unless...x."),
]
contexts = {0: "", 1: "", 2: ""}
c = find_connected_cluster(units[0], units, contexts)
check(c.anchor.sentence_id == 0, "Anchor is sentence 0")
check(c.n_units == 3, "Cluster has 3 units (anchor + 2 adjacent supports)")
adj_count = c.by_kind().get(ADJACENCY, 0)
check(adj_count == 2, "2 adjacency connections")


# ---------------------------------------------------------------------------
# Connected cluster: explicit reference connects across distance
# ---------------------------------------------------------------------------
print("--- Cross-section connection via explicit reference ---")

units = [
    mk(0, "COMMENT", "# Article VII, Section 2"),
    mk(1, "OBLIGATION", "A Team's Team Salary may not exceed the Salary Cap "
                        "unless the Team is using an Exception under Section 6."),
    mk(2, "COMMENT", "# Article VII, Section 6"),
    mk(3, "COMMENT", "(d) Bi-annual Exception."),
    mk(4, "OBLIGATION", "A Team may use the Bi-annual Exception..."),
    mk(5, "THRESHOLD", "(2) The term of a Contract signed pursuant to the BAE..."),
]
contexts = build_section_contexts(units)
c = find_connected_cluster(units[1], units, contexts)
# Should connect to sentence 4 (OBLIGATION in Section 6) and 5 (THRESHOLD in Section 6)
# via the explicit "Section 6" reference
connected_sids = {conn.unit.sentence_id for conn in c.connections}
check(4 in connected_sids,
      "Section-6 OBLIGATION connects via explicit reference")
check(5 in connected_sids,
      "Section-6 THRESHOLD also pulled in (same section context)")
ref_count = c.by_kind().get(EXPLICIT_REFERENCE, 0)
check(ref_count >= 2, "Two units connected via explicit reference")


# ---------------------------------------------------------------------------
# Connected cluster: term reference brings in DEFINITION
# ---------------------------------------------------------------------------
print("--- Term-reference connection ---")

units = [
    mk(0, "COMMENT", "# Article I: Definitions"),
    mk(1, "DEFINITION", '(hhhh) "Veteran Free Agent" means a Veteran who...'),
    mk(2, "COMMENT", "# Article VII, Section 6"),
    mk(3, "OBLIGATION", "A Qualifying Veteran Free Agent may sign with his Prior Team."),
]
contexts = build_section_contexts(units)
c = find_connected_cluster(units[3], units, contexts)
connected_sids = {conn.unit.sentence_id for conn in c.connections}
check(1 in connected_sids, "DEFINITION of 'Veteran Free Agent' pulled in")
term_count = c.by_kind().get(TERM_REFERENCE, 0)
check(term_count >= 1, "At least one term reference connection")


# ---------------------------------------------------------------------------
# find_all_obligation_clusters: end-to-end on small synthetic input
# ---------------------------------------------------------------------------
print("--- find_all_obligation_clusters ---")

units = [
    mk(0, "COMMENT", "# Article VII, Section 2"),
    mk(1, "OBLIGATION", "Salary may not exceed Cap unless using an Exception under Section 6."),
    mk(2, "COMMENT", "# Article VII, Section 6"),
    mk(3, "OBLIGATION", "A Team may use the Bi-annual Exception..."),
    mk(4, "THRESHOLD", "BAE is $4.5M."),
]
result = find_all_obligation_clusters(units)
check(len(result) == 2, "Two OBLIGATIONs -> two clusters")
# First cluster (anchor at sid=1) should connect to sentences 3 and 4
# via the Section 6 explicit reference
first = next(c for c in result if c.anchor.sentence_id == 1)
first_sids = {conn.unit.sentence_id for conn in first.connections}
check(3 in first_sids or 4 in first_sids,
      "First obligation connects to Section 6 content")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)
sys.exit(0 if failed == 0 else 1)

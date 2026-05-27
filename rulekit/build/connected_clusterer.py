"""
connected_clusterer.py - graph-construction approach to Phase 2.

Where the adjacency-based clusterer (clusterer.py) walks the document
linearly and partitions tagged units into contiguous clusters, this
clusterer treats the document as a graph and finds connected components
per OBLIGATION.

For a given anchor OBLIGATION, a unit U is "connected" if any of:

  1. EXPLICIT_REFERENCE: the anchor's text contains a citation pattern
     ("Section X", "Article Y", "§Z") that points to U's section.

  2. TERM_REFERENCE: the anchor's text uses a defined term whose
     DEFINITION is U (or U is in the section that defines the term).

  3. ADJACENCY: U is textually adjacent to the anchor AND has a
     supporting tag (CONDITION, THRESHOLD, EXCEPTION). This is the
     simple case the adjacency clusterer handles well.

The output preserves *why* each unit connected — connection provenance
is part of the audit story.

This is one-hop: we don't transitively follow connections. A unit
connected to the anchor is included; units connected to *that* unit
are not (unless they're independently connected to the anchor).
Transitive closure is a separate concern that may need different rules.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple
import re

from rulekit.build.clusterer import TaggedUnit


# Connection kinds — used as provenance in the output
ADJACENCY = "adjacency"
EXPLICIT_REFERENCE = "explicit_reference"
TERM_REFERENCE = "term_reference"
SECTION_CONTAINMENT = "section_containment"


# Patterns for detecting explicit cross-references in text.
# These are policy-agnostic — they match citation forms common to
# many regulatory documents.
REFERENCE_PATTERNS = [
    # "Section 6", "Section 6(b)", "Section 2(e)(2)"
    (re.compile(r"\bSection\s+(\d+(?:\([a-z0-9]+\))*)", re.IGNORECASE), "section"),
    # "Article VII", "Article VII Section 2"
    (re.compile(r"\bArticle\s+([IVXLC]+|\d+)", re.IGNORECASE), "article"),
    # "§6", "§ 6(d)"
    (re.compile(r"§\s*(\d+(?:\([a-z0-9]+\))*)", re.IGNORECASE), "section"),
    # "subsection (b)", "subsec. (d)"
    (re.compile(r"\bsubsec(?:tion)?\.?\s+\(([a-z])\)", re.IGNORECASE), "subsection"),
    # "(a)(1)", "(b)(3)(ii)" — bare structural references
    (re.compile(r"(?<!\w)\(([a-z])\)\(\s*(\d+)\s*\)", re.IGNORECASE), "structural"),
]


@dataclass
class Connection:
    """Records how a unit connects to the anchor."""
    unit: TaggedUnit
    kind: str  # ADJACENCY, EXPLICIT_REFERENCE, etc.
    evidence: str = ""  # e.g., the matched section reference

    def __repr__(self):
        return (f"Connection({self.kind}, sid={self.unit.sentence_id}, "
                f"tag={self.unit.tag}, evidence='{self.evidence[:30]}')")


@dataclass
class ConnectedCluster:
    """A cluster built by finding all units connected to an anchor."""
    anchor: TaggedUnit
    connections: List[Connection] = field(default_factory=list)
    # Optional: the determination this anchor serves (None if not mapped)
    determination_id: Optional[str] = None

    @property
    def all_units(self) -> List[TaggedUnit]:
        seen = {self.anchor.sentence_id}
        out = [self.anchor]
        for c in self.connections:
            if c.unit.sentence_id not in seen:
                seen.add(c.unit.sentence_id)
                out.append(c.unit)
        return out

    @property
    def n_units(self) -> int:
        return len(self.all_units)

    def by_kind(self) -> dict:
        """Count connections by kind."""
        d = {}
        for c in self.connections:
            d[c.kind] = d.get(c.kind, 0) + 1
        return d


def extract_references(text: str) -> List[Tuple[str, str]]:
    """Find all explicit cross-references in text.

    Returns list of (reference_kind, reference_value) pairs.
    e.g., [("section", "6"), ("section", "6(d)"), ("article", "VII")]
    """
    refs = []
    for pattern, kind in REFERENCE_PATTERNS:
        for m in pattern.finditer(text):
            # Combine groups into a single value if multiple
            value = "".join(g for g in m.groups() if g is not None)
            refs.append((kind, value))
    return refs


def section_matches_reference(section_text: str,
                              ref_kind: str,
                              ref_value: str) -> bool:
    """Check if a section context contains the given reference.

    Handles two cases that arise in practice:
    
    1. The section context contains the full reference:
       section_text = "# Article VII, Section 6: Exceptions"
       ref = ("section", "6") -> match

    2. The section context contains just the subsection part of a
       parenthesized reference. This happens when the COMMENT-based
       segmenter establishes section context at the subsection level
       (e.g., "(d) Bi-annual Exception") for content that lives under
       a higher-level section.
       section_text = "(d) Bi-annual Exception."
       ref = ("section", "6(d)") -> match (subsection (d) component matches)

    The matching is intentionally permissive: false positives produce
    extra units in a cluster that Phase 3 composition handles by simply
    ignoring irrelevant content. False negatives produce missing units
    that Phase 3 can't recover from.
    """
    if not section_text:
        return False
    section_lower = section_text.lower()
    ref_lower = ref_value.lower()

    if ref_kind == "section":
        # Case 1: full "Section X" appears in the context
        if f"section {ref_lower}" in section_lower:
            return True
        # Case 2: the reference has a subsection part — extract and
        # check whether the subsection marker appears in the context.
        # "6(d)" -> check for "(d)"
        # "2(e)(2)" -> check for "(e)" and "(2)"
        import re as _re
        subsection_parts = _re.findall(r"\(([a-z0-9]+)\)", ref_lower)
        if subsection_parts:
            # If ALL subsection parts appear in the section context, match.
            # This is conservative: requiring all parts means deeper
            # references need deeper context.
            if all(f"({p})" in section_lower for p in subsection_parts):
                return True
        # Case 3: bare section number (no subsection) just appears as
        # a substring with parens, e.g., "6(...)" in the section text
        if "(" in ref_lower and ref_lower in section_lower:
            return True
    elif ref_kind == "article":
        if f"article {ref_lower}" in section_lower:
            return True
    elif ref_kind == "subsection":
        # ref_value is just a letter like "b"
        if f"({ref_lower})" in section_lower:
            return True
    elif ref_kind == "structural":
        if ref_lower in section_lower:
            return True
    return False


def extract_defined_terms(definitions: List[TaggedUnit]) -> dict:
    """Build a map of defined term -> DEFINITION unit.
    
    Definitions in NBA-style CBA look like:
      (t) "Early Qualifying Veteran Free Agent" means a Veteran Free Agent...
      (hhhh) "Veteran Free Agent" means a Veteran who completed...
    
    Extract the quoted term as the key.
    """
    terms = {}
    for d in definitions:
        # Look for quoted terms in the definition text
        matches = re.findall(r'"([^"]+)"', d.text)
        for term in matches:
            # Use the term in lowercase as the key for matching
            # (case-insensitive lookup)
            terms[term.lower()] = d
    return terms


def find_term_references(text: str, defined_terms: dict) -> List[Tuple[str, TaggedUnit]]:
    """Find defined terms that appear in the text.

    Returns list of (term, DEFINITION_unit) pairs.
    """
    found = []
    text_lower = text.lower()
    for term, definition in defined_terms.items():
        # Match the term as a substring (case-insensitive).
        # We could use word boundaries but defined terms can be
        # multi-word with internal punctuation.
        if term in text_lower:
            found.append((term, definition))
    return found


def find_connected_cluster(
    anchor: TaggedUnit,
    all_units: List[TaggedUnit],
    section_contexts: dict,  # sentence_id -> section context text
    adjacency_window: int = 5,
) -> ConnectedCluster:
    """Find the connected sub-graph for a single anchor OBLIGATION.

    Args:
      anchor: the OBLIGATION sentence we're building the cluster around
      all_units: all tagged units in the document
      section_contexts: per-sentence-id section context (from segmenting
                        the document into sections via COMMENT markers)
      adjacency_window: how many sentences after the anchor count as
                        "adjacent" for the adjacency rule
    """
    cluster = ConnectedCluster(anchor=anchor)
    anchor_section = section_contexts.get(anchor.sentence_id, "")
    seen_sids: Set[int] = {anchor.sentence_id}

    # 1. ADJACENCY: supporting-tagged units immediately following the anchor,
    #    up to the next OBLIGATION or section break.
    sorted_units = sorted(all_units, key=lambda u: u.sentence_id)
    anchor_index = next(
        (i for i, u in enumerate(sorted_units) if u.sentence_id == anchor.sentence_id),
        None,
    )
    if anchor_index is not None:
        for i in range(anchor_index + 1, min(anchor_index + 1 + adjacency_window,
                                              len(sorted_units))):
            u = sorted_units[i]
            if u.tag == "OBLIGATION":
                break  # adjacency stops at next OBLIGATION
            if u.tag in ("COMMENT",) and u.text.strip().startswith("#"):
                break  # adjacency stops at major section header
            if u.tag in ("CONDITION", "THRESHOLD", "EXCEPTION",
                         "REFERENCE", "DEFINITION"):
                if u.sentence_id not in seen_sids:
                    cluster.connections.append(Connection(
                        unit=u,
                        kind=ADJACENCY,
                        evidence=f"sentence {u.sentence_id} immediately follows anchor",
                    ))
                    seen_sids.add(u.sentence_id)

    # 2. EXPLICIT_REFERENCE: extract references from anchor's text,
    #    find clusters whose section context matches.
    refs = extract_references(anchor.text)
    for ref_kind, ref_value in refs:
        for u in sorted_units:
            if u.sentence_id in seen_sids:
                continue
            u_section = section_contexts.get(u.sentence_id, "")
            if section_matches_reference(u_section, ref_kind, ref_value):
                # Only include operative units, not the section header itself
                if u.tag in ("OBLIGATION", "CONDITION", "THRESHOLD",
                              "EXCEPTION", "DEFINITION"):
                    cluster.connections.append(Connection(
                        unit=u,
                        kind=EXPLICIT_REFERENCE,
                        evidence=f"anchor references '{ref_kind} {ref_value}', "
                                 f"matches section '{u_section[:40]}'",
                    ))
                    seen_sids.add(u.sentence_id)

    # 3. TERM_REFERENCE: find defined terms in the anchor's text,
    #    add their DEFINITIONs.
    definitions = [u for u in all_units if u.tag == "DEFINITION"]
    defined_terms = extract_defined_terms(definitions)
    term_hits = find_term_references(anchor.text, defined_terms)
    for term, definition_unit in term_hits:
        if definition_unit.sentence_id in seen_sids:
            continue
        cluster.connections.append(Connection(
            unit=definition_unit,
            kind=TERM_REFERENCE,
            evidence=f"anchor uses defined term '{term}'",
        ))
        seen_sids.add(definition_unit.sentence_id)

    return cluster


def build_section_contexts(units: List[TaggedUnit]) -> dict:
    """Walk units in order, tracking section context for each sentence_id.

    Section context is hierarchical: we track both the major section
    (Article/Section header) AND the current subsection. Both are
    concatenated into a single context string so reference matching
    can find either.

    e.g., for a sentence inside "(d) Bi-annual Exception" under
    "# Article VII, Section 6: Exceptions", the context becomes:
        "# Article VII, Section 6: Exceptions || (d) Bi-annual Exception."

    Returns: {sentence_id: section_context_text}
    """
    contexts = {}
    current_section = ""
    current_subsection = ""
    for u in sorted(units, key=lambda x: x.sentence_id):
        if u.tag == "COMMENT":
            text_stripped = u.text.strip()
            # Major section headers start with '#'
            if text_stripped.startswith("#"):
                current_section = u.text
                # New major section resets subsection
                current_subsection = ""
            # Subsection labels like "(b) Operation of Salary Cap." update
            # subsection context without overriding section context
            elif re.match(r"\(\w+\)\s+", text_stripped):
                current_subsection = u.text
            # Other COMMENTs (table separators, structural setup) don't
            # update either context
        # Build combined context: section || subsection
        if current_section and current_subsection:
            contexts[u.sentence_id] = (
                f"{current_section} || {current_subsection}"
            )
        elif current_section:
            contexts[u.sentence_id] = current_section
        elif current_subsection:
            contexts[u.sentence_id] = current_subsection
        else:
            contexts[u.sentence_id] = ""
    return contexts


def find_all_obligation_clusters(units: List[TaggedUnit]) -> List[ConnectedCluster]:
    """Find connected clusters for every OBLIGATION in the document."""
    section_contexts = build_section_contexts(units)
    obligations = [u for u in units if u.tag == "OBLIGATION"]
    clusters = []
    for obl in sorted(obligations, key=lambda u: u.sentence_id):
        c = find_connected_cluster(obl, units, section_contexts)
        clusters.append(c)
    return clusters

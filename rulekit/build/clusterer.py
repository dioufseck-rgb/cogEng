"""
clusterer.py - Phase 2 of the compositional Build pipeline.

Takes Phase 1's tagged sentences and groups them into clusters. Each
cluster is one OBLIGATION (or DEFINITION) plus its supporting units.

The clustering rules are structural and domain-agnostic:

  1. An OBLIGATION starts a cluster. The cluster extends forward to
     include CONDITIONs, THRESHOLDs, EXCEPTIONs, REFERENCEs, and any
     supporting DEFINITIONs that appear before the next cluster anchor.

  2. A DEFINITION at top-level (not nested inside an OBLIGATION's
     extent) is its own one-unit cluster. Definitions are the
     vocabulary the policy uses; the rest of the policy references
     them.

  3. Section breaks (COMMENT-tagged section headers / subsection
     labels) terminate the current cluster. A new cluster begins at the
     next non-COMMENT unit.

  4. EXAMPLE units are skipped (not included in any cluster). They
     are illustrative, not operative.

  5. Stray operative units before any OBLIGATION (e.g., a THRESHOLD
     that opens a section, like a table header) attach to the next
     OBLIGATION's cluster.

These rules are intended to work on any regulatory text with explicit
normative force, not specifically NBA CBA text. The patterns of
OBLIGATION-with-supporting-units appear across regulatory domains.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


# Tag categories used by the clusterer
ANCHOR_TAGS = {"OBLIGATION"}
SUPPORTING_TAGS = {"CONDITION", "THRESHOLD", "EXCEPTION", "REFERENCE", "DEFINITION"}
SECTION_BREAK_TAGS = {"COMMENT"}
SKIP_TAGS = {"EXAMPLE"}


@dataclass
class TaggedUnit:
    """A single sentence with its functional tag from Phase 1."""
    sentence_id: int
    text: str
    tag: str
    confidence: str = "high"


@dataclass
class Cluster:
    """A group of TaggedUnits belonging to one logical structure."""
    cluster_id: str
    anchor: TaggedUnit  # the OBLIGATION or DEFINITION that starts the cluster
    supporting: List[TaggedUnit] = field(default_factory=list)
    section_context: str = ""  # nearest preceding COMMENT (section marker)

    @property
    def all_units(self) -> List[TaggedUnit]:
        """All units in this cluster, in source order."""
        return [self.anchor] + self.supporting

    @property
    def kind(self) -> str:
        """OBLIGATION-anchored or DEFINITION-anchored."""
        return self.anchor.tag

    @property
    def span(self) -> tuple:
        """(first_sentence_id, last_sentence_id)."""
        ids = [u.sentence_id for u in self.all_units]
        return (min(ids), max(ids))

    def __repr__(self):
        first, last = self.span
        return (f"Cluster({self.cluster_id}, {self.kind}, "
                f"sentences=[{first}-{last}], "
                f"units={len(self.all_units)})")


def cluster(units: List[TaggedUnit]) -> List[Cluster]:
    """Apply structural clustering rules to a list of tagged units.
    
    Returns a list of Cluster objects, one per OBLIGATION/DEFINITION
    anchor. Units that don't fit the rules (orphan THRESHOLDs etc.)
    are attached to the next anchor.
    """
    # Sort by sentence_id to ensure source order
    units = sorted(units, key=lambda u: u.sentence_id)

    clusters: List[Cluster] = []
    current_section: str = ""  # text of nearest preceding COMMENT
    pending_orphans: List[TaggedUnit] = []
    open_cluster: Optional[Cluster] = None
    cluster_counter = 0

    def start_cluster(anchor: TaggedUnit) -> Cluster:
        nonlocal cluster_counter
        cluster_counter += 1
        # Use sentence_id + tag for human-readable cluster ID
        cid = f"c{cluster_counter:03d}_{anchor.tag.lower()}_s{anchor.sentence_id}"
        c = Cluster(
            cluster_id=cid,
            anchor=anchor,
            section_context=current_section,
        )
        # Attach any pending orphans to this new cluster as supporting units
        if pending_orphans:
            c.supporting.extend(pending_orphans)
            pending_orphans.clear()
        return c

    for u in units:
        tag = u.tag

        if tag in SKIP_TAGS:
            # EXAMPLEs are not part of any cluster
            continue

        if tag in SECTION_BREAK_TAGS:
            # COMMENT closes the current cluster and updates section context
            if open_cluster is not None:
                clusters.append(open_cluster)
                open_cluster = None
            current_section = u.text
            # Pending orphans stay pending (will attach to next anchor)
            continue

        if tag in ANCHOR_TAGS:
            # OBLIGATION: close current, start new
            if open_cluster is not None:
                clusters.append(open_cluster)
            open_cluster = start_cluster(u)
            continue

        # tag is in SUPPORTING_TAGS or unrecognized
        if tag in SUPPORTING_TAGS:
            if open_cluster is not None:
                # Attach to current open cluster as supporting unit
                open_cluster.supporting.append(u)
            else:
                # No anchor yet: hold as orphan
                # Exception: a DEFINITION with no open cluster becomes
                # its own cluster (definitions are independently meaningful)
                if tag == "DEFINITION":
                    if open_cluster is not None:
                        clusters.append(open_cluster)
                    open_cluster = start_cluster(u)
                    # DEFINITION clusters are typically self-contained;
                    # close immediately
                    clusters.append(open_cluster)
                    open_cluster = None
                else:
                    pending_orphans.append(u)
            continue

        # Unrecognized tag: surface as orphan
        pending_orphans.append(u)

    # Close any open cluster at end of stream
    if open_cluster is not None:
        clusters.append(open_cluster)

    return clusters


def cluster_summary(clusters: List[Cluster]) -> dict:
    """Produce a summary of clustering results for inspection."""
    kinds = {}
    sizes = []
    for c in clusters:
        kinds[c.kind] = kinds.get(c.kind, 0) + 1
        sizes.append(len(c.all_units))
    return {
        "total_clusters": len(clusters),
        "by_kind": kinds,
        "size_min": min(sizes) if sizes else 0,
        "size_max": max(sizes) if sizes else 0,
        "size_mean": sum(sizes) / len(sizes) if sizes else 0,
        "singletons": sum(1 for s in sizes if s == 1),
    }


def units_from_tagging_output(tag_records: List[dict]) -> List[TaggedUnit]:
    """Convert Phase 1 JSON output to TaggedUnit objects."""
    units = []
    for r in tag_records:
        sid = r.get("sentence_id")
        if sid is None:
            continue
        units.append(TaggedUnit(
            sentence_id=sid,
            text=r.get("text_snippet", r.get("text", "")),
            tag=r.get("tag", "COMMENT"),
            confidence=r.get("confidence", "high"),
        ))
    return units

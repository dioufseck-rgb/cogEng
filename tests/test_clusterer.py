"""
test_clusterer.py - tests for the Phase 2 clusterer.

Exercises the clustering rules on synthetic inputs to verify the
structural behavior is correct.
"""
from __future__ import annotations
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from rulekit.build.clusterer import (
    TaggedUnit,
    cluster,
    cluster_summary,
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
# Basic: OBLIGATION + following CONDITION/THRESHOLD/EXCEPTION = one cluster
# ---------------------------------------------------------------------------
print("--- Basic OBLIGATION clustering ---")

units = [
    mk(0, "OBLIGATION", "Team Salary may not exceed cap."),
    mk(1, "THRESHOLD", "Cap is $140M."),
    mk(2, "EXCEPTION", "Unless using an Exception."),
    mk(3, "CONDITION", "Exception applies if X."),
]
result = cluster(units)
check(len(result) == 1, "Single OBLIGATION + 3 supporting = 1 cluster")
check(len(result[0].all_units) == 4, "Cluster has all 4 units")
check(result[0].anchor.sentence_id == 0, "Anchor is the OBLIGATION")
check(result[0].kind == "OBLIGATION", "Cluster kind is OBLIGATION")


# ---------------------------------------------------------------------------
# Two OBLIGATIONs = two clusters
# ---------------------------------------------------------------------------
print("--- Two OBLIGATIONs ---")

units = [
    mk(0, "OBLIGATION"),
    mk(1, "CONDITION"),
    mk(2, "OBLIGATION"),
    mk(3, "THRESHOLD"),
]
result = cluster(units)
check(len(result) == 2, "Two OBLIGATIONs = two clusters")
check(result[0].anchor.sentence_id == 0, "First cluster anchored at sentence 0")
check(result[1].anchor.sentence_id == 2, "Second cluster anchored at sentence 2")
check(len(result[0].all_units) == 2, "First cluster has 2 units")
check(len(result[1].all_units) == 2, "Second cluster has 2 units")


# ---------------------------------------------------------------------------
# COMMENT (section break) closes the current cluster
# ---------------------------------------------------------------------------
print("--- COMMENT section break ---")

units = [
    mk(0, "OBLIGATION"),
    mk(1, "THRESHOLD"),
    mk(2, "COMMENT", "# New Section Header"),
    mk(3, "OBLIGATION"),
    mk(4, "CONDITION"),
]
result = cluster(units)
check(len(result) == 2, "COMMENT separates two clusters")
check(len(result[0].all_units) == 2, "First cluster has OBLIGATION + THRESHOLD")
check(len(result[1].all_units) == 2, "Second cluster has OBLIGATION + CONDITION")
check(result[1].section_context.startswith("# New Section"),
      "Second cluster carries section context")


# ---------------------------------------------------------------------------
# DEFINITION before any OBLIGATION = its own cluster
# ---------------------------------------------------------------------------
print("--- Top-level DEFINITION ---")

units = [
    mk(0, "DEFINITION", '"Free Agent" means a player...'),
    mk(1, "DEFINITION", '"Veteran" means...'),
    mk(2, "OBLIGATION"),
    mk(3, "CONDITION"),
]
result = cluster(units)
check(len(result) == 3, "Two DEFINITIONs + OBLIGATION = 3 clusters")
check(result[0].kind == "DEFINITION", "First cluster is DEFINITION-anchored")
check(len(result[0].all_units) == 1, "DEFINITION cluster is singleton")
check(result[1].kind == "DEFINITION", "Second cluster is DEFINITION-anchored")
check(result[2].kind == "OBLIGATION", "Third cluster is OBLIGATION-anchored")


# ---------------------------------------------------------------------------
# EXAMPLE units are skipped
# ---------------------------------------------------------------------------
print("--- EXAMPLE skipped ---")

units = [
    mk(0, "OBLIGATION"),
    mk(1, "EXAMPLE", "For example, ..."),
    mk(2, "CONDITION"),
]
result = cluster(units)
check(len(result) == 1, "One cluster")
check(len(result[0].all_units) == 2, "EXAMPLE not included in cluster")
# Make sure the cluster has the right two units
unit_tags = [u.tag for u in result[0].all_units]
check(unit_tags == ["OBLIGATION", "CONDITION"], "EXAMPLE excluded, others kept")


# ---------------------------------------------------------------------------
# Orphan supporting unit before any OBLIGATION attaches to next anchor
# ---------------------------------------------------------------------------
print("--- Orphan supporting unit ---")

units = [
    mk(0, "THRESHOLD", "Higher Max Criteria table..."),
    mk(1, "OBLIGATION", "No contract may exceed..."),
    mk(2, "CONDITION"),
]
result = cluster(units)
check(len(result) == 1, "Orphan attaches to following OBLIGATION's cluster")
check(len(result[0].all_units) == 3, "All three units in one cluster")
check(result[0].anchor.sentence_id == 1, "OBLIGATION is anchor, not orphan THRESHOLD")
# THRESHOLD should appear in supporting
support_sids = [u.sentence_id for u in result[0].supporting]
check(0 in support_sids, "Orphan THRESHOLD is in supporting")


# ---------------------------------------------------------------------------
# Source-order preserved
# ---------------------------------------------------------------------------
print("--- Source order preserved ---")

# Pass units in scrambled order, expect them sorted by sentence_id
units = [
    mk(2, "CONDITION"),
    mk(0, "OBLIGATION"),
    mk(1, "THRESHOLD"),
]
result = cluster(units)
check(len(result) == 1, "One cluster from scrambled input")
ordered_sids = [u.sentence_id for u in result[0].all_units]
check(ordered_sids == [0, 1, 2], "Units in cluster ordered by sentence_id")


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------
print("--- Summary ---")
units = [
    mk(0, "DEFINITION"),
    mk(1, "OBLIGATION"),
    mk(2, "CONDITION"),
    mk(3, "OBLIGATION"),
    mk(4, "THRESHOLD"),
    mk(5, "EXCEPTION"),
]
result = cluster(units)
summary = cluster_summary(result)
check(summary["total_clusters"] == 3, "Summary: 3 clusters")
check(summary["by_kind"]["OBLIGATION"] == 2, "Summary: 2 OBLIGATION clusters")
check(summary["by_kind"]["DEFINITION"] == 1, "Summary: 1 DEFINITION cluster")
check(summary["singletons"] == 1, "Summary: 1 singleton (the DEFINITION)")


# ---------------------------------------------------------------------------
# Print result
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)
sys.exit(0 if failed == 0 else 1)

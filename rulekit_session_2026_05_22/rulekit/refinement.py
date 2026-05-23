"""
Refinement.

After top-down decomposition produces a NodeSpec tree, refinement walks
the tree and prunes structural redundancies that the LLM tends to introduce
during decomposition:

1. Redundant summary atoms: a leaf that summarizes what its siblings already
   decompose. E.g., AND(at_least_2_of_4(...with-duration...), "each agent
   trialed ≥4 weeks") — the leaf summarizes the at_least_2 sub-tree.

2. Duplicate sibling sub-trees: two children of the same operator that are
   semantically equivalent. Keep one.

3. Low-confidence inferred sub-trees: flagged for review, not dropped
   automatically. These need human attention.

The refinement design is two-phase: an LLM call identifies operations to
apply, then deterministic code rewrites the tree.

Refinement preserves semantics: a case that evaluates TRUE before refinement
should evaluate TRUE after (and same for FALSE). The refinement is about
removing structural noise, not changing the policy's logic.
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Optional, Union

from rulekit.decomposer import (
    LeafSpec, OperatorSpec, NodeSpec, LLMCaller, _parse_json_response,
    collect_leaves,
)


# ---------------------------------------------------------------------------
# Refinement operations
# ---------------------------------------------------------------------------

@dataclass
class DropChild:
    """Drop a child node at the given path."""
    parent_path: list[int]  # path from root to parent (each entry is a child index)
    child_index: int
    reason: str = ""


@dataclass
class MergeChildren:
    """Merge several children at the given parent path into one (keep_index)."""
    parent_path: list[int]
    child_indices: list[int]  # indices of children to merge
    keep_index: int  # which one to retain (the others are dropped)
    reason: str = ""


@dataclass
class FlagForReview:
    """Mark a sub-tree for human review without modifying it."""
    path: list[int]
    reason: str
    severity: str = "medium"  # low / medium / high


RefinementOp = Union[DropChild, MergeChildren, FlagForReview]


@dataclass
class RefinementResult:
    """Output of refinement: refined tree plus review flags."""
    tree: NodeSpec
    operations_applied: list[RefinementOp]
    flags: list[FlagForReview]


# ---------------------------------------------------------------------------
# Refinement prompt
# ---------------------------------------------------------------------------

REFINEMENT_PROMPT = """You are reviewing a decomposition tree produced by an
earlier extraction pass on a policy. The tree may contain three kinds of
structural redundancy that you should identify:

1. REDUNDANT SUMMARY ATOMS. A leaf claim that summarizes content already
   decomposed by its siblings. Example: an AND parent has children
   [decomposed sub-tree about agent + duration for each pharma category,
   leaf "each agent trialed for 4 weeks"]. The leaf summarizes what the
   sub-tree already establishes — drop the leaf.

2. DUPLICATE SIBLING SUB-TREES. Two children of the same operator that are
   semantically equivalent (same operator, same children referencing the
   same atoms, expressing the same proposition). Keep one of them — the
   policy's logic only needs to be expressed once.

3. LOW-CONFIDENCE INFERRED SUB-TREES that appear logically suspect. These
   are sub-trees marked with provenance "inferred" and a low confidence,
   especially when the sub-tree's structure makes a requirement vacuous
   (e.g., a branch that says "X is satisfied if X OR (not X)"). Flag these
   for review rather than dropping automatically.

TREE STRUCTURE
===============
The tree below uses path indices: the root is [], its first child is [0],
the second child of [0] is [0,1], and so on. When you identify an operation,
specify the parent_path (path to the operator whose children you're modifying)
and child_index (which child of that parent).

ATOMS REFERENCED IN THE TREE
=============================
{atom_listing}

TREE
=====
{tree_json}

OUTPUT FORMAT
==============
A JSON object with one field "operations" containing a list. Each operation
is one of:

DropChild:
{{
  "type": "drop_child",
  "parent_path": [<indices>],
  "child_index": <int>,
  "reason": "<one sentence>"
}}

MergeChildren (when multiple sibling children are equivalent — keep one,
drop the others):
{{
  "type": "merge_children",
  "parent_path": [<indices>],
  "child_indices": [<indices of equivalent children>],
  "keep_index": <which one to keep>,
  "reason": "<one sentence>"
}}

FlagForReview:
{{
  "type": "flag_for_review",
  "path": [<indices to the suspect node>],
  "reason": "<one sentence>",
  "severity": "low" | "medium" | "high"
}}

PRINCIPLES
============
- Be conservative. Only identify operations where the redundancy is clear.
- Do not drop a child if it adds genuinely new information.
- A leaf is redundant with a sub-tree only if the sub-tree FULLY encodes
  the leaf's content. Partial overlap is not enough.
- Two sub-trees are duplicates only if they reference the same atoms and
  have the same operator structure. Different surface labels are fine; the
  content matters.
- Flag suspicious inferred sub-trees rather than dropping them — humans
  should review.

Output ONLY the JSON object. No preamble, no commentary.
"""


# ---------------------------------------------------------------------------
# Tree serialization for LLM input
# ---------------------------------------------------------------------------

def serialize_node(node: NodeSpec, path: Optional[list[int]] = None) -> dict:
    """Serialize a NodeSpec tree to JSON-friendly dict with path annotations."""
    if path is None:
        path = []
    if isinstance(node, LeafSpec):
        return {
            "type": "leaf",
            "path": path,
            "atom_id": node.atom_id,
            "claim": node.claim,
            "source_span": node.source_span,
        }
    if isinstance(node, OperatorSpec):
        return {
            "type": node.operator,
            "path": path,
            "n": node.n,
            "surface_label": node.surface_label,
            "provenance": node.provenance,
            "confidence": node.confidence,
            "latent_type": node.latent_type,
            "children": [
                serialize_node(c, path + [i])
                for i, c in enumerate(node.children)
            ],
        }
    raise ValueError(f"Unknown node type: {type(node)}")


def format_atom_listing(tree: NodeSpec) -> str:
    """Build a listing of atoms referenced in the tree."""
    leaves = collect_leaves(tree)
    seen = {}
    for leaf in leaves:
        if leaf.atom_id and leaf.atom_id not in seen:
            seen[leaf.atom_id] = leaf.claim
    return "\n".join(
        f"  {aid}: {claim}"
        for aid, claim in sorted(seen.items())
    )


# ---------------------------------------------------------------------------
# Refinement: ask LLM for operations
# ---------------------------------------------------------------------------

def identify_refinements(tree: NodeSpec, det_id: str,
                         llm: LLMCaller) -> list[RefinementOp]:
    """Ask the LLM to identify refinement operations on a tree."""
    serialized = serialize_node(tree)
    tree_json = json.dumps(serialized, indent=2)
    atom_listing = format_atom_listing(tree)
    prompt = REFINEMENT_PROMPT.format(
        atom_listing=atom_listing,
        tree_json=tree_json,
    )
    raw = llm.call(f"refine_{det_id}", prompt)
    parsed = _parse_json_response(raw)
    return _parse_operations(parsed.get("operations", []))


def _parse_operations(op_dicts: list[dict]) -> list[RefinementOp]:
    """Parse the operations list from the LLM's JSON output."""
    ops = []
    for op in op_dicts:
        op_type = op.get("type")
        if op_type == "drop_child":
            ops.append(DropChild(
                parent_path=op["parent_path"],
                child_index=op["child_index"],
                reason=op.get("reason", ""),
            ))
        elif op_type == "merge_children":
            ops.append(MergeChildren(
                parent_path=op["parent_path"],
                child_indices=op["child_indices"],
                keep_index=op["keep_index"],
                reason=op.get("reason", ""),
            ))
        elif op_type == "flag_for_review":
            ops.append(FlagForReview(
                path=op["path"],
                reason=op["reason"],
                severity=op.get("severity", "medium"),
            ))
        # Unknown op types are silently skipped
    return ops


# ---------------------------------------------------------------------------
# Applying operations: deterministic tree rewriting
# ---------------------------------------------------------------------------

def _navigate(tree: NodeSpec, path: list[int]) -> NodeSpec:
    """Walk to the node at the given path."""
    node = tree
    for idx in path:
        if not isinstance(node, OperatorSpec):
            raise ValueError(f"Cannot navigate into leaf at path {path}")
        node = node.children[idx]
    return node


def _clone_tree(tree: NodeSpec) -> NodeSpec:
    """Deep-copy a NodeSpec tree."""
    if isinstance(tree, LeafSpec):
        return LeafSpec(
            claim=tree.claim,
            source_span=tree.source_span,
            atom_id=tree.atom_id,
        )
    if isinstance(tree, OperatorSpec):
        return OperatorSpec(
            operator=tree.operator,
            children=[_clone_tree(c) for c in tree.children],
            n=tree.n,
            surface_label=tree.surface_label,
            source_span=tree.source_span,
            provenance=tree.provenance,
            confidence=tree.confidence,
            latent_type=tree.latent_type,
        )
    raise ValueError(f"Unknown node type: {type(tree)}")


def _simplify_operator(node: OperatorSpec) -> NodeSpec:
    """
    After dropping children, an operator may degenerate:
    - AND/OR with 1 child collapses to that child.
    - AND/OR with 0 children is an error.
    - AT-LEAST-N with n > k after drop becomes unsatisfiable; raise an error.
    """
    if node.operator in ("and", "or"):
        if len(node.children) == 0:
            raise ValueError(f"Operator {node.operator} has no children after refinement")
        if len(node.children) == 1:
            return node.children[0]  # collapse degenerate operator
        return node
    if node.operator == "at_least":
        n = node.n
        k = len(node.children)
        if n is None:
            return node
        if k == 0:
            raise ValueError("at_least has no children after refinement")
        if n > k:
            raise ValueError(
                f"at_least n={n} > k={k} after refinement (unsatisfiable)"
            )
        if n == k:
            # Equivalent to AND
            return OperatorSpec(
                operator="and",
                children=node.children,
                n=None,
                surface_label=node.surface_label,
                source_span=node.source_span,
                provenance=node.provenance,
                confidence=node.confidence,
                latent_type=node.latent_type,
            )
        if n == 1:
            # Equivalent to OR
            return OperatorSpec(
                operator="or",
                children=node.children,
                n=None,
                surface_label=node.surface_label,
                source_span=node.source_span,
                provenance=node.provenance,
                confidence=node.confidence,
                latent_type=node.latent_type,
            )
        return node
    return node


def apply_operations(tree: NodeSpec,
                     ops: list[RefinementOp]) -> tuple[NodeSpec, list[RefinementOp], list[FlagForReview]]:
    """
    Apply a list of refinement operations to the tree.
    Returns (refined_tree, ops_actually_applied, flags).

    Operations are applied in order. After all drops/merges, operators are
    simplified bottom-up. Flag operations don't modify the tree.

    Operations applied to leaves (rather than operators), or to invalid
    paths, are silently skipped.
    """
    tree = _clone_tree(tree)
    applied = []
    flags = []

    # Sort drop/merge operations by depth (deepest first) so that paths
    # remain valid as we apply changes from the bottom up.
    drop_merge_ops = [op for op in ops if not isinstance(op, FlagForReview)]
    drop_merge_ops.sort(key=lambda op: -len(op.parent_path))

    # Track child indices to drop per parent path (so multiple operations
    # at the same parent don't invalidate each other's indices).
    drops_per_parent: dict[tuple, list[int]] = {}

    for op in drop_merge_ops:
        parent_key = tuple(op.parent_path)
        try:
            parent = _navigate(tree, op.parent_path)
        except (ValueError, IndexError):
            continue
        if not isinstance(parent, OperatorSpec):
            continue

        if isinstance(op, DropChild):
            if 0 <= op.child_index < len(parent.children):
                drops_per_parent.setdefault(parent_key, []).append(op.child_index)
                applied.append(op)
        elif isinstance(op, MergeChildren):
            for idx in op.child_indices:
                if idx == op.keep_index:
                    continue
                if 0 <= idx < len(parent.children):
                    drops_per_parent.setdefault(parent_key, []).append(idx)
            applied.append(op)

    # Now apply the drops per parent (deepest paths first remains valid because
    # we sorted, and we accumulate per-parent indices to drop them together).
    for parent_path, indices_to_drop in drops_per_parent.items():
        parent = _navigate(tree, list(parent_path))
        if not isinstance(parent, OperatorSpec):
            continue
        # Drop children in descending index order to preserve other indices
        kept = [
            c for i, c in enumerate(parent.children)
            if i not in set(indices_to_drop)
        ]
        parent.children = kept

    # Now simplify bottom-up
    tree = _simplify_bottom_up(tree)

    # Collect flag operations separately
    flags = [op for op in ops if isinstance(op, FlagForReview)]

    return tree, applied, flags


def _simplify_bottom_up(node: NodeSpec) -> NodeSpec:
    """Walk the tree bottom-up, simplifying degenerate operators."""
    if isinstance(node, LeafSpec):
        return node
    if isinstance(node, OperatorSpec):
        node.children = [_simplify_bottom_up(c) for c in node.children]
        return _simplify_operator(node)
    return node


# ---------------------------------------------------------------------------
# End-to-end refinement
# ---------------------------------------------------------------------------

def refine_tree(tree: NodeSpec, det_id: str, llm: LLMCaller) -> RefinementResult:
    """Identify refinements via LLM, apply them, return the refined tree."""
    ops = identify_refinements(tree, det_id, llm)
    refined, applied, flags = apply_operations(tree, ops)
    return RefinementResult(
        tree=refined,
        operations_applied=applied,
        flags=flags,
    )

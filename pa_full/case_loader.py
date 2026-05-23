"""
JSON loaders for the PA appeal pipeline.

The tree and case facts live as JSON files (data, not code). These
loaders read JSON and wrap it in the dataclass types the orchestrator
expects.

This is the only Python that touches domain content. Everything else
flows through the orchestrator (generic) and the JSON artifacts (data).
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DERIVE = _HERE.parent / "derive_design"
sys.path.insert(0, str(_DERIVE))

from derive_orchestrator import CaseFactBundle


def load_tree(json_path: str | Path):
    """Load a tree JSON file. Returns (tree, tree_metadata)."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    tree = data["tree"]
    tree_metadata = data["tree_metadata"]
    return tree, tree_metadata


def load_case_facts(json_path: str | Path) -> CaseFactBundle:
    """Load a case fact JSON file as a CaseFactBundle."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return CaseFactBundle(
        case_id=data["case_id"],
        retrieve_facts=data.get("retrieve_facts", {}),
        extract_facts=data.get("extract_facts", {}),
    )

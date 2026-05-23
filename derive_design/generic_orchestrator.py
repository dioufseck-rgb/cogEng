"""
Generic orchestrator. No domain knowledge.

Takes:
  - tree (data) — nodes carry disposition_role annotations
  - tree_metadata (data) — carries routing rules and default disposition
  - characterize_fn (substrate interface)

Produces a Determination by walking the tree and applying the
disposition router.

Adding a new domain means writing tree + tree_metadata only.
"""

import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from derive_orchestrator import DeriveOrchestrator as _BaseTreeWalker
from disposition_router import DispositionRouter


class GenericOrchestrator(_BaseTreeWalker):
    """Composes tree walking with declarative disposition routing."""

    def __init__(self, tree, tree_metadata, characterize_fn,
                 escalation_threshold=0.7):
        super().__init__(
            tree=tree,
            tree_metadata=tree_metadata,
            characterize_fn=characterize_fn,
            escalation_threshold=escalation_threshold,
        )
        self.router = DispositionRouter(
            tree=tree,
            tree_metadata=tree_metadata,
        )

    def _apply_routing(self):
        version = self.tree_metadata.get("version", "unknown")
        return self.router.derive_determination(
            trace=self.trace,
            tree_version=version,
        )

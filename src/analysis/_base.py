"""Base class for workspace-persisted state modules.

CatalystTracker and ThesisTracker share the same initialization pattern:
resolve workspace dir → create AtomicJSON store → load state from a named
JSON file. This base class eliminates that boilerplate.

Note: EdgeScorer does NOT extend this base — it supports stateless mode
(workspace_dir="") and uses list-based history storage. KnowledgeGraph
also manages its own persistence at the workspaces root level.
"""

from __future__ import annotations

import copy

from config.settings import WORKSPACES_DIR
from src.storage import AtomicJSON


class WorkspaceStateBase:
    """Base for modules that persist state as JSON in a workspace directory.

    Subclasses must set class attributes:
        _state_file: str — JSON filename (e.g. "thesis.json")
        _default_state: dict | list — default value when file is missing
    """

    _state_file: str
    _default_state: dict | list

    def __init__(self, workspace_dir: str):
        self.workspace = WORKSPACES_DIR / workspace_dir
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._store = AtomicJSON(self.workspace)
        # Deep-copy default to avoid shared mutable state across instances
        default = copy.deepcopy(self._default_state)
        self._data = self._store.load(self._state_file, default=default)

    def _save(self):
        self._store.save(self._state_file, self._data)

    def _load(self):
        """Re-read state from disk (useful for verifying persistence in tests)."""
        default = copy.deepcopy(self._default_state)
        self._data = self._store.load(self._state_file, default=default)
        return self._data

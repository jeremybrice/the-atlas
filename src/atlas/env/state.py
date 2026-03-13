"""Environment State Model — structured snapshot for prompt injection."""

from __future__ import annotations

import platform

from atlas.env.filesystem import FilesystemProvider


class EnvironmentStateModel:
    """Produces a token-efficient environment state snapshot."""

    def __init__(self, filesystem: FilesystemProvider):
        self._filesystem = filesystem

    def snapshot(self) -> dict:
        return {
            "workspace": self._workspace_summary(),
            "system": self._system_info(),
        }

    def _workspace_summary(self) -> dict:
        workspace = self._filesystem.workspace
        try:
            entries = self._filesystem.list_dir(workspace)
            return {
                "path": workspace,
                "entries": [e["name"] for e in entries[:50]],
                "total_entries": len(entries),
            }
        except Exception:
            return {"path": workspace, "entries": [], "error": "could not list"}

    def _system_info(self) -> dict:
        return {
            "os": platform.system(),
            "python": platform.python_version(),
        }

"""Filesystem Provider — file and directory operations."""

from __future__ import annotations

from pathlib import Path


class FilesystemProvider:
    """Wraps pathlib for file operations with workspace awareness."""

    def __init__(self, workspace: str = "."):
        self._workspace = Path(workspace).resolve()

    def read(self, path: str) -> str:
        p = Path(path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return p.read_text()

    def write(self, path: str, content: str) -> None:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def list_dir(self, path: str, recursive: bool = False) -> list[dict]:
        p = Path(path).resolve()
        if not p.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        entries = []
        items = p.rglob("*") if recursive else p.iterdir()
        for item in sorted(items):
            entries.append(
                {
                    "name": item.name,
                    "path": str(item),
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0,
                }
            )
        return entries

    def search(self, root: str, pattern: str) -> list[str]:
        p = Path(root).resolve()
        return [str(match) for match in sorted(p.glob(pattern))]

    @property
    def workspace(self) -> str:
        return str(self._workspace)

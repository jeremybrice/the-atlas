"""Seed Skills — the four built-in skills that ship with ATLAS Phase 1."""

from __future__ import annotations

from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.skills.registry import SkillRegistry


def register_seed_skills(
    registry: SkillRegistry,
    filesystem: FilesystemProvider,
    process: ProcessProvider,
) -> None:
    """Register the four Phase 1 seed skills."""

    async def file_read(params: dict) -> dict:
        content = filesystem.read(params["path"])
        return {"content": content}

    async def file_write(params: dict) -> dict:
        filesystem.write(params["path"], params["content"])
        return {"written": True, "path": params["path"]}

    async def file_search(params: dict) -> dict:
        matches = filesystem.search(
            params.get("root", filesystem.workspace),
            params["pattern"],
        )
        return {"matches": matches}

    async def shell_execute(params: dict) -> dict:
        result = await process.execute(
            params["command"],
            cwd=params.get("cwd"),
            timeout=params.get("timeout", 30),
        )
        return result

    registry.register(
        "file.read", "Read File",
        "Read the contents of a file at the given path",
        handler=file_read, risk_level="low",
        tags=["filesystem", "read"],
    )
    registry.register(
        "file.write", "Write File",
        "Write content to a file at the given path, creating directories if needed",
        handler=file_write, risk_level="medium",
        tags=["filesystem", "write"],
    )
    registry.register(
        "file.search", "Search Files",
        "Search for files matching a glob pattern in a directory tree",
        handler=file_search, risk_level="low",
        tags=["filesystem", "search"],
    )
    registry.register(
        "shell.execute", "Execute Shell Command",
        "Run a shell command and return stdout, stderr, and exit code",
        handler=shell_execute, risk_level="high",
        tags=["process", "shell"],
    )

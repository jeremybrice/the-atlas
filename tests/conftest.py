from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Provides a temporary ATLAS data directory."""
    data_dir = tmp_path / ".atlas"
    data_dir.mkdir()
    (data_dir / "config").mkdir()
    (data_dir / "data").mkdir()
    (data_dir / "logs").mkdir()
    (data_dir / "skills").mkdir()
    return data_dir


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Provides a temporary workspace directory with sample files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("print('hello')\n")
    return workspace

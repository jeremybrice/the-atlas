# tests/unit/env/test_filesystem.py
from pathlib import Path

import pytest

from atlas.env.filesystem import FilesystemProvider


@pytest.fixture
def fs(tmp_workspace: Path) -> FilesystemProvider:
    return FilesystemProvider(workspace=str(tmp_workspace))


def test_read_file(fs: FilesystemProvider, tmp_workspace: Path):
    result = fs.read(str(tmp_workspace / "src" / "main.py"))
    assert "hello" in result


def test_read_missing_file(fs: FilesystemProvider):
    with pytest.raises(FileNotFoundError):
        fs.read("/nonexistent/file.py")


def test_write_file(fs: FilesystemProvider, tmp_workspace: Path):
    path = str(tmp_workspace / "output.txt")
    fs.write(path, "test content")
    assert Path(path).read_text() == "test content"


def test_list_dir(fs: FilesystemProvider, tmp_workspace: Path):
    entries = fs.list_dir(str(tmp_workspace))
    names = [e["name"] for e in entries]
    assert "src" in names


def test_search_glob(fs: FilesystemProvider, tmp_workspace: Path):
    results = fs.search(str(tmp_workspace), pattern="**/*.py")
    assert len(results) >= 1
    assert any("main.py" in r for r in results)

# tests/unit/env/test_process.py
import pytest

from atlas.env.process import ProcessProvider


@pytest.fixture
def proc() -> ProcessProvider:
    return ProcessProvider()


async def test_execute_simple_command(proc: ProcessProvider):
    result = await proc.execute("echo hello")
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


async def test_execute_failing_command(proc: ProcessProvider):
    result = await proc.execute("false")
    assert result["exit_code"] != 0


async def test_execute_with_timeout(proc: ProcessProvider):
    result = await proc.execute("sleep 10", timeout=1)
    assert result["exit_code"] != 0
    assert "timeout" in result.get("error", "").lower() or result["exit_code"] == -1


async def test_execute_captures_stderr(proc: ProcessProvider):
    result = await proc.execute("echo error >&2")
    assert "error" in result["stderr"]

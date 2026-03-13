import asyncio
from pathlib import Path

import pytest

from atlas.contracts.types import AuditEntry, PolicyDecision
from atlas.control.audit import AuditLogger


@pytest.fixture
async def audit_logger(tmp_path: Path):
    db_path = tmp_path / "test.db"
    logger = AuditLogger(db_path=str(db_path))
    await logger.initialize()
    yield logger
    await logger.close()


async def test_log_and_query(audit_logger: AuditLogger):
    entry = AuditEntry(
        actor="core",
        action_type="filesystem_read",
        action_details={"path": "/tmp/test.txt"},
        policy_decision=PolicyDecision.ALLOW,
        outcome="success",
        correlation_id="corr-1",
    )
    await audit_logger.log(entry)
    entries = await audit_logger.query(limit=10)
    assert len(entries) == 1
    assert entries[0]["actor"] == "core"
    assert entries[0]["correlation_id"] == "corr-1"


async def test_log_multiple_and_query_recent(audit_logger: AuditLogger):
    for i in range(5):
        entry = AuditEntry(
            actor=f"actor-{i}",
            action_type="test",
            outcome="success",
        )
        await audit_logger.log(entry)
    entries = await audit_logger.query(limit=3)
    assert len(entries) == 3


async def test_query_empty_log(audit_logger: AuditLogger):
    entries = await audit_logger.query(limit=10)
    assert entries == []

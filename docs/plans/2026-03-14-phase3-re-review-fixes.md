# Phase 3 Stage A — Re-Review Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 7 issues (scoring 75+) from the second code review of PR #3.

**Architecture:** Targeted fixes across vault (remove sync constructor), config (remove dead code), trust (single-save atomicity, contract alignment), MCP handler (exception hygiene), and test isolation. Each fix is independent and testable.

**Tech Stack:** Python 3.12+, asyncio, aiosqlite, cryptography, pytest

---

## Issue Summary

| # | Title | Score | Task |
|---|-------|-------|------|
| 1 | `__init__` vs `create()` salt incompatibility | 85 | 2 |
| 2 | `MCPServerEntry` dead code | 100 | 1 |
| 3 | `ctx` accepted but never used | 75 | 6 |
| 4 | `test_vault_list` uses real `~/.atlas` | 75 | 7 |
| 5 | Double `_save_record` atomicity risk | 75 | 3 |
| 6 | Handler raises ConnectorError vs dict protocol | 75 | 5 |
| 7 | `TrustRecord` missing `recent_outcomes` field | 75 | 4 |

---

### Task 1: Remove `MCPServerEntry` dead code

**Issue:** #2 — `MCPServerEntry` dataclass is defined but never used. `MCPConfig.servers` is `list[dict]`.

**Files:**
- Modify: `src/atlas/config.py:47-52`

**Step 1: Remove the dead dataclass**

In `src/atlas/config.py`, delete lines 47–53 (the `MCPServerEntry` class and its blank line):

```python
@dataclass
class MCPServerEntry:
    name: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
```

**Step 2: Run tests to verify nothing breaks**

Run: `source .venv/bin/activate && pytest tests/unit/test_config.py -v`
Expected: All config tests pass.

**Step 3: Commit**

```bash
git add src/atlas/config.py
git commit -m "fix: remove unused MCPServerEntry dataclass"
```

---

### Task 2: Remove sync `__init__`, make `create()` the only vault constructor

**Issue:** #1 — `__init__` uses a fixed salt while `create()` uses a random salt. They are silently incompatible on the same database.

**Files:**
- Modify: `src/atlas/integrations/vault.py:29-35`
- Modify: `tests/unit/integrations/test_vault.py`
- Modify: `tests/integration/test_trust_vault_integration.py`

**Step 1: Write a test that verifies `create()` is the only way to construct**

Add to `tests/unit/integrations/test_vault.py`:

```python
def test_credential_vault_has_no_sync_constructor():
    """CredentialVault should only be constructed via create() to ensure correct salt usage."""
    assert hasattr(CredentialVault, 'create')
    # Verify that direct instantiation is not the intended path
    # by checking create is a classmethod
    assert isinstance(CredentialVault.__dict__['create'], classmethod)
```

**Step 2: Remove the sync `__init__`**

In `src/atlas/integrations/vault.py`, replace `__init__` with a private init that `create()` uses internally:

```python
class CredentialVault:
    """Encrypted credential storage backed by SQLite. Use CredentialVault.create() to construct."""

    def __init__(self, db: DatabaseStore, fernet: Fernet):
        """Internal constructor. Use CredentialVault.create() instead."""
        self._db = db
        self._fernet = fernet

    @classmethod
    async def create(cls, db: DatabaseStore, passphrase: str) -> "CredentialVault":
        """Create a CredentialVault with a per-database random salt."""
        salt = await cls._get_or_create_salt(db)
        fernet = Fernet(_derive_key(passphrase, salt))
        return cls(db=db, fernet=fernet)
```

**Step 3: Update all tests that use the sync constructor**

In `tests/unit/integrations/test_vault.py`, update `test_get_with_wrong_passphrase_raises_credential_error`:

```python
async def test_get_with_wrong_passphrase_raises_credential_error(db):
    vault1 = await CredentialVault.create(db=db, passphrase="correct-pass")
    await vault1.store("github", "token", "secret123")

    vault2 = await CredentialVault.create(db=db, passphrase="wrong-pass")
    with pytest.raises(CredentialError, match="Decryption failed"):
        await vault2.get("github", "token")
```

Check all other test files for any remaining `CredentialVault(db=..., passphrase=...)` calls and update them to `await CredentialVault.create(db=..., passphrase=...)`.

**Step 4: Run all tests**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/atlas/integrations/vault.py tests/unit/integrations/test_vault.py tests/integration/test_trust_vault_integration.py
git commit -m "fix: remove sync CredentialVault constructor, use create() exclusively"
```

---

### Task 3: Fix double-save atomicity in TrustTracker

**Issue:** #5 — `record_outcome` saves the record, then resets `consecutive_successes` and saves again. If the second save fails, escalation fires twice.

**Files:**
- Modify: `src/atlas/control/trust.py:37-71`
- Modify: `tests/unit/control/test_trust.py`

**Step 1: Write a test verifying single-save behavior**

Add to `tests/unit/control/test_trust.py`:

```python
async def test_escalation_reset_persisted_atomically(db):
    """After escalation, the DB should have consecutive_successes=0 from a single save."""
    tracker = TrustTracker(db=db, escalation_threshold=3, demotion_failure_count=2, demotion_window_size=5)

    for _ in range(3):
        result = await tracker.record_outcome("file.read", success=True)
    assert result.should_escalate is True

    # Verify the DB has the reset value
    record = await tracker.get_record("file.read")
    assert record.consecutive_successes == 0
    assert record.total_invocations == 3
```

**Step 2: Run test — it should pass (existing behavior also persists the reset)**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_trust.py::test_escalation_reset_persisted_atomically -v`

**Step 3: Refactor to single save**

In `src/atlas/control/trust.py`, restructure `record_outcome` to compute escalation/demotion BEFORE saving, then save once:

```python
    async def record_outcome(self, skill_id: str, success: bool, ctx: ExecutionContext | None = None) -> TrustOutcome:
        record = await self.get_record(skill_id)
        recent = await self._load_recent(skill_id)

        record.total_invocations += 1
        if success:
            record.successes += 1
            record.consecutive_successes += 1
            record.last_outcome = "success"
        else:
            record.failures += 1
            record.consecutive_successes = 0
            record.last_outcome = "failure"

        # Append the current outcome to the sliding window
        recent.append(success)

        outcome = TrustOutcome(skill_id=skill_id)

        # Check escalation: enough consecutive successes
        if record.consecutive_successes >= self._escalation_threshold:
            outcome.should_escalate = True
            record.consecutive_successes = 0

        # Check demotion: too many failures in recent window
        if not success and record.autonomy_override is not None:
            recent_failures = self._count_recent_failures(recent)
            if recent_failures >= self._demotion_failure_count:
                outcome.should_demote = True

        # Single save with all mutations applied
        record.updated_at = datetime.now(timezone.utc).isoformat()
        await self._save_record(record, recent)

        return outcome
```

**Step 4: Run all trust tests**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_trust.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/atlas/control/trust.py tests/unit/control/test_trust.py
git commit -m "fix: single-save atomicity in record_outcome, eliminate double-save"
```

---

### Task 4: Add `recent_outcomes` to TrustRecord contract

**Issue:** #7 — DB schema has `recent_outcomes TEXT` column but `TrustRecord` dataclass in contracts has no corresponding field.

**Files:**
- Modify: `src/atlas/contracts/types.py:277-288`
- Modify: `tests/unit/contracts/test_types.py`

**Step 1: Write a test verifying the field exists**

Add to `tests/unit/contracts/test_types.py`:

```python
def test_trust_record_has_recent_outcomes_field():
    record = TrustRecord(skill_id="test.skill")
    assert hasattr(record, 'recent_outcomes')
    assert record.recent_outcomes == ""
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/contracts/test_types.py::test_trust_record_has_recent_outcomes_field -v`
Expected: FAIL — `TrustRecord` has no `recent_outcomes` attribute.

**Step 3: Add the field**

In `src/atlas/contracts/types.py`, add to the `TrustRecord` dataclass (after `updated_at`):

```python
@dataclass
class TrustRecord:
    """Per-skill trust tracking for autonomy escalation/demotion."""
    skill_id: str
    successes: int = 0
    failures: int = 0
    consecutive_successes: int = 0
    total_invocations: int = 0
    autonomy_override: AutonomyLevel | None = None
    last_outcome: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    recent_outcomes: str = ""
```

**Step 4: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/contracts/test_types.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/atlas/contracts/types.py tests/unit/contracts/test_types.py
git commit -m "fix: add recent_outcomes field to TrustRecord contract type"
```

---

### Task 5: Fix MCP handler exception wrapping

**Issue:** #6 — `MCPSkillAdapter.handler` catches ALL exceptions and wraps them as `ConnectorError` (RetriableError). This means even programming errors (TypeError, ValueError) get treated as retriable connection failures.

**Files:**
- Modify: `src/atlas/integrations/mcp.py:34-45`
- Modify: `tests/unit/integrations/test_mcp.py`

**Step 1: Write a test verifying non-connector errors propagate naturally**

Add to `tests/unit/integrations/test_mcp.py`:

```python
from atlas.contracts.errors import AtlasError


async def test_mcp_skill_adapter_handler_preserves_atlas_errors():
    """AtlasError subclasses should propagate without being wrapped in ConnectorError."""
    from atlas.contracts.errors import SkillValidationError
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(
        side_effect=SkillValidationError("bad input schema")
    )

    adapter = MCPSkillAdapter(
        session=mock_session,
        tool_name="test_tool",
        tool_description="A test tool",
        input_schema={},
    )
    with pytest.raises(SkillValidationError, match="bad input schema"):
        await adapter.handler({"arg1": "value1"})
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/integrations/test_mcp.py::test_mcp_skill_adapter_handler_preserves_atlas_errors -v`
Expected: FAIL — `SkillValidationError` gets wrapped in `ConnectorError`.

**Step 3: Fix the handler to only wrap non-AtlasError exceptions**

In `src/atlas/integrations/mcp.py`, update the imports and handler:

Add to imports:
```python
from atlas.contracts.errors import AtlasError, ConnectorError
```

(Remove the old `from atlas.contracts.errors import ConnectorError` line.)

Replace the except block:
```python
    async def handler(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self.session.call_tool(self.tool_name, arguments=params)
            # Extract text content from MCP result
            output = ""
            if hasattr(result, "content") and result.content:
                texts = [c.text for c in result.content if hasattr(c, "text")]
                output = "\n".join(texts)
            return {"status": "success", "output": output}
        except AtlasError:
            raise
        except Exception as e:
            logger.error("MCP tool %s failed: %s", self.tool_name, e)
            raise ConnectorError(f"MCP tool {self.tool_name} failed: {e}", cause=e)
```

**Step 4: Run all MCP tests**

Run: `source .venv/bin/activate && pytest tests/unit/integrations/test_mcp.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/atlas/integrations/mcp.py tests/unit/integrations/test_mcp.py
git commit -m "fix: preserve AtlasError subclasses in MCP handler, only wrap unknown exceptions"
```

---

### Task 6: Propagate `correlation_id` via logging in TrustTracker and CredentialVault

**Issue:** #3 — `ctx: ExecutionContext` is accepted but `correlation_id` is never extracted or forwarded.

**Files:**
- Modify: `src/atlas/control/trust.py`
- Modify: `src/atlas/integrations/vault.py`
- Modify: `tests/unit/control/test_trust.py`
- Modify: `tests/unit/integrations/test_vault.py`

**Step 1: Write failing test for TrustTracker correlation_id logging**

Add to `tests/unit/control/test_trust.py`:

```python
async def test_record_outcome_logs_correlation_id(db, caplog):
    """When ctx is provided, correlation_id should appear in log output."""
    import logging
    tracker = TrustTracker(db=db, escalation_threshold=10, demotion_failure_count=3, demotion_window_size=5)
    ctx = ExecutionContext.new(mission_id="test-mission")
    with caplog.at_level(logging.DEBUG, logger="atlas.control.trust"):
        await tracker.record_outcome("file.read", success=True, ctx=ctx)
    assert ctx.correlation_id in caplog.text
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_trust.py::test_record_outcome_logs_correlation_id -v`
Expected: FAIL — correlation_id not in logs.

**Step 3: Add correlation_id to log messages in TrustTracker**

In `src/atlas/control/trust.py`, add a helper and update methods:

```python
    def _log_ctx(self, ctx: ExecutionContext | None) -> str:
        """Format correlation_id for log messages."""
        if ctx:
            return f"[{ctx.correlation_id}] "
        return ""
```

Update `record_outcome` — add a debug log after the save:

```python
        logger.debug("%sRecorded outcome for %s: %s", self._log_ctx(ctx), skill_id, "success" if success else "failure")
```

Update `set_autonomy_override` — update the existing log:

```python
        logger.info("%sTrust override set: %s -> %s", self._log_ctx(ctx), skill_id, level.name)
```

**Step 4: Write failing test for CredentialVault correlation_id logging**

Add to `tests/unit/integrations/test_vault.py`:

```python
async def test_store_logs_correlation_id(db, caplog):
    """When ctx is provided, correlation_id should appear in log output."""
    import logging
    vault = await CredentialVault.create(db=db, passphrase="test-pass")
    ctx = ExecutionContext.new(mission_id="test-mission")
    with caplog.at_level(logging.INFO, logger="atlas.integrations.vault"):
        await vault.store("github", "token", "secret", ctx=ctx)
    assert ctx.correlation_id in caplog.text
```

**Step 5: Add correlation_id to log messages in CredentialVault**

In `src/atlas/integrations/vault.py`, add helper and update store/delete logs:

```python
    @staticmethod
    def _log_ctx(ctx: ExecutionContext | None) -> str:
        """Format correlation_id for log messages."""
        if ctx:
            return f"[{ctx.correlation_id}] "
        return ""
```

Update `store()`:
```python
        logger.info("%sStored credential: %s/%s", self._log_ctx(ctx), service, key)
```

Update `delete()`:
```python
        logger.info("%sDeleted credential: %s/%s", self._log_ctx(ctx), service, key)
```

**Step 6: Run all tests**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_trust.py tests/unit/integrations/test_vault.py -v`
Expected: All tests pass.

**Step 7: Commit**

```bash
git add src/atlas/control/trust.py src/atlas/integrations/vault.py tests/unit/control/test_trust.py tests/unit/integrations/test_vault.py
git commit -m "fix: propagate correlation_id via logging in TrustTracker and CredentialVault"
```

---

### Task 7: Fix `test_vault_list` to use isolated filesystem

**Issue:** #4 — `test_vault_list_no_credentials` invokes the CLI without filesystem isolation, potentially reading from real `~/.atlas`.

**Files:**
- Modify: `tests/unit/test_cli_vault.py`

**Step 1: Update the test to use monkeypatch for isolation**

Replace the entire `tests/unit/test_cli_vault.py`:

```python
from pathlib import Path
from click.testing import CliRunner
from atlas.cli import main


def test_vault_group_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["vault", "--help"])
    assert result.exit_code == 0
    assert "Manage the credential vault" in result.output


def test_vault_list_no_credentials(tmp_path, monkeypatch):
    """Vault list should report no credentials when the DB doesn't exist."""
    # Isolate from real ~/.atlas by pointing _ensure_data_dir to tmp_path
    fake_data_dir = tmp_path / ".atlas"
    fake_data_dir.mkdir()
    (fake_data_dir / "data").mkdir()
    monkeypatch.setattr("atlas.cli._ensure_data_dir", lambda: fake_data_dir)

    runner = CliRunner()
    result = runner.invoke(main, ["vault", "list"])
    assert result.exit_code == 0
```

**Step 2: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/test_cli_vault.py -v`
Expected: All tests pass.

**Step 3: Commit**

```bash
git add tests/unit/test_cli_vault.py
git commit -m "fix: isolate test_vault_list from real filesystem using monkeypatch"
```

---

## Final Verification

After all 7 tasks:

```bash
source .venv/bin/activate && pytest tests/ -v && ruff check src/ tests/
```

Expected: All tests pass, no lint errors.

# Phase 3 Stage A — Code Review Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 10 issues identified in the PR #3 code review of the Phase 3 Stage A implementation.

**Architecture:** Fixes span trust escalation logic (TrustTracker), credential vault (salt + error handling), MCP bridge (error hierarchy, idempotency, daemon wiring), PolicyEngine (docstring + safety), shared test fixtures, and ExecutionContext propagation. Each fix is isolated and testable independently.

**Tech Stack:** Python 3.12+, asyncio, aiosqlite, cryptography (Fernet/PBKDF2), pytest

---

## Issue Summary

| # | Title | Score | Task |
|---|-------|-------|------|
| 1 | `_count_recent_failures` returns lifetime failures | 100 | 2 |
| 2 | MCPBridge not wired into daemon | 100 | 10 |
| 3 | PolicyEngine docstring says "Stateless" | 100 | 4 |
| 4 | Fixed PBKDF2 salt | 75 | 8 |
| 5 | MCP error hierarchy bypass | 75 | 5 |
| 6 | Vault error hierarchy bypass | 75 | 6 |
| 7 | No ExecutionContext propagation | 75 | 7 |
| 8 | Duplicate db test fixture | 75 | 1 |
| 9 | `register_tools` not idempotent | 75 | 9 |
| 10 | Escalation fires repeatedly | 75 | 3 |

---

### Task 1: Add shared `db` fixture to conftest.py

**Issue:** #8 — Five test files each define their own `db` fixture instead of using shared fixtures from `tests/conftest.py`.

**Files:**
- Modify: `tests/conftest.py:1-26`
- Modify: `tests/unit/control/test_trust.py:7-12`
- Modify: `tests/unit/integrations/test_vault.py:6-11`
- Modify: `tests/unit/memory/test_store_trust.py:5-10`
- Modify: `tests/unit/memory/test_store_vault.py:5-10`
- Modify: `tests/integration/test_trust_vault_integration.py:15-20`

**Step 1: Add the shared `db` fixture to conftest.py**

Add after the `tmp_workspace` fixture:

```python
@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator:
    """Provides an initialized DatabaseStore backed by a temporary SQLite file."""
    from atlas.memory.store import DatabaseStore
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()
```

Also add at the top of conftest.py:

```python
from collections.abc import AsyncIterator
```

**Step 2: Remove duplicate `db` fixtures from all 5 test files**

Delete the local `@pytest.fixture async def db(tmp_path)` block from each of:
- `tests/unit/control/test_trust.py` (lines 7-12) — also remove unused `from atlas.memory.store import DatabaseStore`
- `tests/unit/integrations/test_vault.py` (lines 6-11) — also remove unused `from atlas.memory.store import DatabaseStore`
- `tests/unit/memory/test_store_trust.py` (lines 5-10) — also remove unused `from atlas.memory.store import DatabaseStore`
- `tests/unit/memory/test_store_vault.py` (lines 5-10) — also remove unused `from atlas.memory.store import DatabaseStore`
- `tests/integration/test_trust_vault_integration.py` (lines 15-20) — also remove unused `from atlas.memory.store import DatabaseStore`

**Step 3: Run tests to verify**

Run: `pytest tests/unit/control/test_trust.py tests/unit/integrations/test_vault.py tests/unit/memory/test_store_trust.py tests/unit/memory/test_store_vault.py tests/integration/test_trust_vault_integration.py -v`
Expected: All tests pass using the shared fixture.

**Step 4: Commit**

```bash
git add tests/conftest.py tests/unit/control/test_trust.py tests/unit/integrations/test_vault.py tests/unit/memory/test_store_trust.py tests/unit/memory/test_store_vault.py tests/integration/test_trust_vault_integration.py
git commit -m "refactor: consolidate duplicate db fixtures into shared conftest"
```

---

### Task 2: Fix `_count_recent_failures` sliding window

**Issue:** #1 — Both branches return `record.failures` (lifetime total), making `demotion_window_size` non-functional.

**Files:**
- Modify: `src/atlas/control/trust.py:67-71`
- Modify: `src/atlas/memory/store.py:99-108` (add `recent_failures` column)
- Modify: `tests/unit/control/test_trust.py`

**Step 1: Write the failing test**

Add to `tests/unit/control/test_trust.py`:

```python
async def test_count_recent_failures_ignores_old_failures(db):
    """A skill with old failures and recent successes should not trigger demotion."""
    tracker = TrustTracker(db=db, escalation_threshold=100, demotion_failure_count=3, demotion_window_size=5)

    # Simulate a skill that had 3 failures long ago, then many successes
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    # Record 3 failures
    for _ in range(3):
        await tracker.record_outcome("file.read", success=False)
    # Record 20 successes (well past the window of 5)
    for _ in range(20):
        await tracker.record_outcome("file.read", success=True)
    # One new failure should NOT trigger demotion (only 1 recent failure, threshold is 3)
    result = await tracker.record_outcome("file.read", success=False)
    assert result.should_demote is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/control/test_trust.py::test_count_recent_failures_ignores_old_failures -v`
Expected: FAIL — demotion triggers because `_count_recent_failures` returns 4 (lifetime), not 1 (recent).

**Step 3: Add `invocation_history` tracking to TrustTracker**

The simplest approach that doesn't require schema changes: track a deque of recent outcomes in TrustTracker. Replace `_count_recent_failures` with a proper sliding window using an in-memory deque per skill, persisted as JSON in a new column.

Modify `src/atlas/control/trust.py`:

```python
"""Trust Tracker — tracks per-skill success/failure and suggests autonomy changes."""
import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from atlas.contracts.types import AutonomyLevel, TrustRecord
from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)


@dataclass
class TrustOutcome:
    """Result of recording an outcome — indicates if escalation/demotion should happen."""
    skill_id: str
    should_escalate: bool = False
    should_demote: bool = False


class TrustTracker:
    """Tracks per-skill invocation outcomes and suggests autonomy changes."""

    def __init__(
        self,
        db: DatabaseStore,
        escalation_threshold: int = 10,
        demotion_failure_count: int = 3,
        demotion_window_size: int = 10,
    ):
        self._db = db
        self._escalation_threshold = escalation_threshold
        self._demotion_failure_count = demotion_failure_count
        self._demotion_window_size = demotion_window_size
        # In-memory cache of recent outcomes per skill (loaded from DB on first access)
        self._recent_outcomes: dict[str, deque[bool]] = {}

    async def _load_recent(self, skill_id: str) -> deque[bool]:
        """Load recent outcome window from DB, or create empty."""
        if skill_id in self._recent_outcomes:
            return self._recent_outcomes[skill_id]
        cursor = await self._db.db.execute(
            "SELECT recent_outcomes FROM trust_records WHERE skill_id = ?",
            (skill_id,),
        )
        row = await cursor.fetchone()
        if row and row[0]:
            history = deque(json.loads(row[0]), maxlen=self._demotion_window_size)
        else:
            history = deque(maxlen=self._demotion_window_size)
        self._recent_outcomes[skill_id] = history
        return history

    async def record_outcome(self, skill_id: str, success: bool) -> TrustOutcome:
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

        recent.append(success)
        record.updated_at = datetime.now(timezone.utc).isoformat()
        await self._save_record(record, recent)

        outcome = TrustOutcome(skill_id=skill_id)

        # Check escalation: enough consecutive successes
        if record.consecutive_successes >= self._escalation_threshold:
            outcome.should_escalate = True

        # Check demotion: too many failures in recent window
        if not success and record.autonomy_override is not None:
            recent_failures = sum(1 for r in recent if not r)
            if recent_failures >= self._demotion_failure_count:
                outcome.should_demote = True

        return outcome

    async def get_record(self, skill_id: str) -> TrustRecord:
        cursor = await self._db.db.execute(
            "SELECT skill_id, successes, failures, consecutive_successes, "
            "total_invocations, autonomy_override, last_outcome, updated_at "
            "FROM trust_records WHERE skill_id = ?",
            (skill_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return TrustRecord(skill_id=skill_id)

        autonomy_val = row[5]
        autonomy_override = AutonomyLevel(int(autonomy_val)) if autonomy_val is not None else None

        return TrustRecord(
            skill_id=row[0],
            successes=row[1],
            failures=row[2],
            consecutive_successes=row[3],
            total_invocations=row[4],
            autonomy_override=autonomy_override,
            last_outcome=row[6] or "",
            updated_at=row[7],
        )

    async def set_autonomy_override(self, skill_id: str, level: AutonomyLevel) -> None:
        record = await self.get_record(skill_id)
        record.autonomy_override = level
        record.updated_at = datetime.now(timezone.utc).isoformat()
        recent = await self._load_recent(skill_id)
        await self._save_record(record, recent)
        logger.info("Trust override set: %s -> %s", skill_id, level.name)

    async def get_autonomy_override(self, skill_id: str) -> AutonomyLevel | None:
        record = await self.get_record(skill_id)
        if record.total_invocations == 0 and record.autonomy_override is None:
            return None
        return record.autonomy_override

    async def _save_record(self, record: TrustRecord, recent: deque[bool]) -> None:
        autonomy_val = record.autonomy_override.value if record.autonomy_override is not None else None
        recent_json = json.dumps(list(recent))
        await self._db.db.execute(
            """INSERT INTO trust_records
               (skill_id, successes, failures, consecutive_successes,
                total_invocations, autonomy_override, last_outcome, updated_at,
                recent_outcomes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(skill_id) DO UPDATE SET
                successes=excluded.successes,
                failures=excluded.failures,
                consecutive_successes=excluded.consecutive_successes,
                total_invocations=excluded.total_invocations,
                autonomy_override=excluded.autonomy_override,
                last_outcome=excluded.last_outcome,
                updated_at=excluded.updated_at,
                recent_outcomes=excluded.recent_outcomes""",
            (
                record.skill_id,
                record.successes,
                record.failures,
                record.consecutive_successes,
                record.total_invocations,
                autonomy_val,
                record.last_outcome,
                record.updated_at,
                recent_json,
            ),
        )
        await self._db.db.commit()
```

**Step 4: Add `recent_outcomes` column to store.py schema**

In `src/atlas/memory/store.py`, add `recent_outcomes TEXT` to the `trust_records` table:

```sql
CREATE TABLE IF NOT EXISTS trust_records (
    skill_id TEXT PRIMARY KEY,
    successes INTEGER DEFAULT 0,
    failures INTEGER DEFAULT 0,
    consecutive_successes INTEGER DEFAULT 0,
    total_invocations INTEGER DEFAULT 0,
    autonomy_override TEXT,
    last_outcome TEXT,
    updated_at TEXT NOT NULL,
    recent_outcomes TEXT
);
```

**Step 5: Run tests to verify**

Run: `pytest tests/unit/control/test_trust.py -v`
Expected: All tests pass, including the new sliding window test.

**Step 6: Commit**

```bash
git add src/atlas/control/trust.py src/atlas/memory/store.py tests/unit/control/test_trust.py
git commit -m "fix: implement proper sliding window for _count_recent_failures"
```

---

### Task 3: Fix escalation re-triggering

**Issue:** #10 — `consecutive_successes` is never reset after `should_escalate = True`, causing repeated escalation signals.

**Files:**
- Modify: `src/atlas/control/trust.py` (in `record_outcome`)
- Modify: `tests/unit/control/test_trust.py`

**Step 1: Write the failing test**

Add to `tests/unit/control/test_trust.py`:

```python
async def test_escalation_fires_only_once(db):
    """After escalation fires, subsequent successes should not re-trigger it."""
    tracker = TrustTracker(db=db, escalation_threshold=3, demotion_failure_count=2, demotion_window_size=5)

    # Reach threshold
    for _ in range(3):
        result = await tracker.record_outcome("file.read", success=True)
    assert result.should_escalate is True

    # Next success should NOT trigger escalation again
    result = await tracker.record_outcome("file.read", success=True)
    assert result.should_escalate is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/control/test_trust.py::test_escalation_fires_only_once -v`
Expected: FAIL — `should_escalate` is `True` on the 4th success.

**Step 3: Reset `consecutive_successes` after escalation fires**

In `src/atlas/control/trust.py`, in `record_outcome`, after the escalation check:

```python
        # Check escalation: enough consecutive successes
        if record.consecutive_successes >= self._escalation_threshold:
            outcome.should_escalate = True
            record.consecutive_successes = 0
            await self._save_record(record, recent)
```

**Step 4: Run tests to verify**

Run: `pytest tests/unit/control/test_trust.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/atlas/control/trust.py tests/unit/control/test_trust.py
git commit -m "fix: reset consecutive_successes after escalation fires"
```

---

### Task 4: Fix PolicyEngine docstring + add default match arm

**Issue:** #3 — Docstring says "Stateless" but class now has mutable `_skill_overrides`. Also missing default `case _` in match.

**Files:**
- Modify: `src/atlas/control/policy.py:16,38-44,57-66`
- Modify: `tests/unit/control/test_policy.py`

**Step 1: Write the failing test for default match arm**

Add to `tests/unit/control/test_policy.py`:

```python
def test_evaluate_returns_deny_for_unknown_autonomy_level():
    """PolicyEngine should return DENY (fail-safe) for unrecognized autonomy levels."""
    engine = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    action = ProposedAction(
        action_type="test",
        domain="test",
        description="test action",
        risk_level=RiskLevel.LOW,
    )
    # Directly test the match by injecting a bad override
    engine._skill_overrides["bad.skill"] = 999  # Not a valid AutonomyLevel
    action_with_skill = ProposedAction(
        action_type="test",
        domain="test",
        description="test action",
        risk_level=RiskLevel.LOW,
        skill_id="bad.skill",
    )
    result = engine.evaluate(action_with_skill)
    assert result == PolicyDecision.DENY
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/control/test_policy.py::test_evaluate_returns_deny_for_unknown_autonomy_level -v`
Expected: FAIL — `evaluate()` returns `None`.

**Step 3: Update docstring and add default match arms**

In `src/atlas/control/policy.py`:

Change line 16:
```python
    """Policy evaluator with per-skill autonomy overrides. Every action passes through evaluate()."""
```

Add `case _` to `evaluate()` (after line 44):
```python
        match effective_level:
            case AutonomyLevel.OBSERVE:
                return PolicyDecision.DENY
            case AutonomyLevel.SUGGEST:
                return PolicyDecision.REQUIRE_APPROVAL
            case AutonomyLevel.ACT_WITHIN_BOUNDS:
                return self._evaluate_bounded(action)
            case _:
                return PolicyDecision.DENY
```

Add `case _` to `_evaluate_bounded()` (after line 66):
```python
    def _evaluate_bounded(self, action: ProposedAction) -> PolicyDecision:
        match action.risk_level:
            case RiskLevel.LOW:
                return PolicyDecision.ALLOW
            case RiskLevel.MEDIUM:
                return PolicyDecision.REQUIRE_APPROVAL
            case RiskLevel.HIGH:
                return PolicyDecision.REQUIRE_APPROVAL
            case RiskLevel.CRITICAL:
                return PolicyDecision.DENY
            case _:
                return PolicyDecision.DENY
```

**Step 4: Run tests to verify**

Run: `pytest tests/unit/control/test_policy.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/atlas/control/policy.py tests/unit/control/test_policy.py
git commit -m "fix: update PolicyEngine docstring, add fail-safe default match arms"
```

---

### Task 5: Fix MCP error hierarchy bypass

**Issue:** #5 — `MCPSkillAdapter.handler` catches exceptions and returns error dicts instead of raising `ConnectorError`.

**Files:**
- Modify: `src/atlas/integrations/mcp.py:33-44`
- Modify: `tests/unit/integrations/test_mcp.py:46-58`

**Step 1: Update the error test**

In `tests/unit/integrations/test_mcp.py`, change `test_mcp_skill_adapter_handler_error`:

```python
async def test_mcp_skill_adapter_handler_error():
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=Exception("connection lost"))

    adapter = MCPSkillAdapter(
        session=mock_session,
        tool_name="test_tool",
        tool_description="A test tool",
        input_schema={},
    )
    with pytest.raises(ConnectorError, match="connection lost"):
        await adapter.handler({"arg1": "value1"})
```

Add the import at the top of the test file:

```python
from atlas.contracts.errors import ConnectorError
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_mcp.py::test_mcp_skill_adapter_handler_error -v`
Expected: FAIL — handler returns a dict instead of raising.

**Step 3: Fix the handler to raise ConnectorError**

In `src/atlas/integrations/mcp.py`, update the handler and imports:

Add import at top:
```python
from atlas.contracts.errors import ConnectorError
```

Replace the handler method:
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
        except Exception as e:
            logger.error("MCP tool %s failed: %s", self.tool_name, e)
            raise ConnectorError(f"MCP tool {self.tool_name} failed: {e}", cause=e)
```

**Step 4: Run tests to verify**

Run: `pytest tests/unit/integrations/test_mcp.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/atlas/integrations/mcp.py tests/unit/integrations/test_mcp.py
git commit -m "fix: raise ConnectorError instead of returning error dicts in MCP handler"
```

---

### Task 6: Fix Vault error hierarchy bypass

**Issue:** #6 — `CredentialVault.get()` doesn't wrap `InvalidToken` in `CredentialError`.

**Files:**
- Modify: `src/atlas/integrations/vault.py:58-66`
- Modify: `tests/unit/integrations/test_vault.py`
- Modify: `tests/integration/test_trust_vault_integration.py:106-113`

**Step 1: Write the failing test**

Add to `tests/unit/integrations/test_vault.py`:

```python
from atlas.contracts.errors import CredentialError


async def test_get_with_wrong_passphrase_raises_credential_error(db):
    vault1 = CredentialVault(db=db, passphrase="correct-pass")
    await vault1.store("github", "token", "secret123")

    vault2 = CredentialVault(db=db, passphrase="wrong-pass")
    with pytest.raises(CredentialError, match="Decryption failed"):
        await vault2.get("github", "token")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_vault.py::test_get_with_wrong_passphrase_raises_credential_error -v`
Expected: FAIL — raises `cryptography.fernet.InvalidToken`, not `CredentialError`.

**Step 3: Wrap InvalidToken in CredentialError**

In `src/atlas/integrations/vault.py`, add import and update `get()`:

Add import:
```python
from cryptography.fernet import Fernet, InvalidToken

from atlas.contracts.errors import CredentialError
```

(Remove the plain `from cryptography.fernet import Fernet` import.)

Update `get()`:
```python
    async def get(self, service: str, key: str) -> str | None:
        cursor = await self._db.db.execute(
            "SELECT encrypted_value FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        try:
            return self._fernet.decrypt(row[0]).decode()
        except InvalidToken as e:
            raise CredentialError(
                f"Decryption failed for {service}/{key}: wrong passphrase or corrupted data",
                cause=e,
            )
```

**Step 4: Update integration test to expect CredentialError**

In `tests/integration/test_trust_vault_integration.py`, update `test_vault_wrong_passphrase_fails`:

```python
async def test_vault_wrong_passphrase_fails(db):
    from atlas.contracts.errors import CredentialError
    vault1 = CredentialVault(db=db, passphrase="correct-pass")
    await vault1.store("github", "token", "ghp_secret123")

    # Different passphrase = different key = decryption fails
    vault2 = CredentialVault(db=db, passphrase="wrong-pass")
    with pytest.raises(CredentialError):
        await vault2.get("github", "token")
```

**Step 5: Run tests to verify**

Run: `pytest tests/unit/integrations/test_vault.py tests/integration/test_trust_vault_integration.py -v`
Expected: All tests pass.

**Step 6: Commit**

```bash
git add src/atlas/integrations/vault.py tests/unit/integrations/test_vault.py tests/integration/test_trust_vault_integration.py
git commit -m "fix: wrap InvalidToken in CredentialError for proper error hierarchy"
```

---

### Task 7: Add ExecutionContext propagation to TrustTracker and CredentialVault

**Issue:** #7 — Cross-domain calls to DatabaseStore lack ExecutionContext, breaking correlation_id tracing.

**Files:**
- Modify: `src/atlas/control/trust.py` (all public methods)
- Modify: `src/atlas/integrations/vault.py` (all public methods)
- Modify: `tests/unit/control/test_trust.py`
- Modify: `tests/unit/integrations/test_vault.py`

**Step 1: Write the failing test for TrustTracker**

Add to `tests/unit/control/test_trust.py`:

```python
from atlas.contracts.types import AutonomyLevel, ExecutionContext


async def test_record_outcome_accepts_execution_context(db):
    tracker = TrustTracker(db=db, escalation_threshold=10, demotion_failure_count=3, demotion_window_size=5)
    ctx = ExecutionContext.new(mission_id="test-mission")
    result = await tracker.record_outcome("file.read", success=True, ctx=ctx)
    assert result.skill_id == "file.read"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/control/test_trust.py::test_record_outcome_accepts_execution_context -v`
Expected: FAIL — `record_outcome` doesn't accept `ctx` parameter.

**Step 3: Add `ctx` parameter to TrustTracker public methods**

In `src/atlas/control/trust.py`, add `ExecutionContext` import and update method signatures:

Add import:
```python
from atlas.contracts.types import AutonomyLevel, ExecutionContext, TrustRecord
```

Update signatures (add `ctx` as last optional parameter):
```python
    async def record_outcome(self, skill_id: str, success: bool, ctx: ExecutionContext | None = None) -> TrustOutcome:
```
```python
    async def get_record(self, skill_id: str, ctx: ExecutionContext | None = None) -> TrustRecord:
```
```python
    async def set_autonomy_override(self, skill_id: str, level: AutonomyLevel, ctx: ExecutionContext | None = None) -> None:
```
```python
    async def get_autonomy_override(self, skill_id: str, ctx: ExecutionContext | None = None) -> AutonomyLevel | None:
```

**Step 4: Write the failing test for CredentialVault**

Add to `tests/unit/integrations/test_vault.py`:

```python
from atlas.contracts.types import ExecutionContext


async def test_store_and_get_accepts_execution_context(db):
    vault = CredentialVault(db=db, passphrase="test-passphrase")
    ctx = ExecutionContext.new(mission_id="test-mission")
    await vault.store("github", "token", "ghp_abc123", ctx=ctx)
    result = await vault.get("github", "token", ctx=ctx)
    assert result == "ghp_abc123"
```

**Step 5: Add `ctx` parameter to CredentialVault public methods**

In `src/atlas/integrations/vault.py`, add import and update signatures:

Add import:
```python
from atlas.contracts.types import ExecutionContext
```

Update signatures:
```python
    async def store(self, service: str, key: str, value: str, expires_at: str | None = None, ctx: ExecutionContext | None = None) -> None:
```
```python
    async def get(self, service: str, key: str, ctx: ExecutionContext | None = None) -> str | None:
```
```python
    async def delete(self, service: str, key: str, ctx: ExecutionContext | None = None) -> None:
```
```python
    async def list_services(self, ctx: ExecutionContext | None = None) -> list[str]:
```
```python
    async def list_keys(self, service: str, ctx: ExecutionContext | None = None) -> list[str]:
```

**Step 6: Run all tests to verify**

Run: `pytest tests/unit/control/test_trust.py tests/unit/integrations/test_vault.py -v`
Expected: All tests pass.

**Step 7: Commit**

```bash
git add src/atlas/control/trust.py src/atlas/integrations/vault.py tests/unit/control/test_trust.py tests/unit/integrations/test_vault.py
git commit -m "fix: add ExecutionContext propagation to TrustTracker and CredentialVault"
```

---

### Task 8: Use random PBKDF2 salt stored in DB

**Issue:** #4 — Hardcoded `_SALT` eliminates per-vault key uniqueness.

**Files:**
- Modify: `src/atlas/integrations/vault.py:14-27,30-35`
- Modify: `src/atlas/memory/store.py` (add `vault_meta` table)
- Modify: `tests/unit/integrations/test_vault.py`

**Step 1: Write the failing test**

Add to `tests/unit/integrations/test_vault.py`:

```python
async def test_different_vaults_use_different_salts(tmp_path):
    """Two separate vault databases with the same passphrase should use different salts."""
    from atlas.memory.store import DatabaseStore

    db1 = DatabaseStore(str(tmp_path / "vault1.db"))
    await db1.initialize()
    db2 = DatabaseStore(str(tmp_path / "vault2.db"))
    await db2.initialize()

    try:
        v1 = await CredentialVault.create(db=db1, passphrase="same-pass")
        v2 = await CredentialVault.create(db=db2, passphrase="same-pass")
        await v1.store("svc", "key", "secret")
        await v2.store("svc", "key", "secret")

        # Same plaintext + same passphrase but different salts = different ciphertext
        c1 = await db1.db.execute("SELECT encrypted_value FROM credentials WHERE service='svc'")
        c2 = await db2.db.execute("SELECT encrypted_value FROM credentials WHERE service='svc'")
        row1 = await c1.fetchone()
        row2 = await c2.fetchone()
        assert row1[0] != row2[0]
    finally:
        await db1.close()
        await db2.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_vault.py::test_different_vaults_use_different_salts -v`
Expected: FAIL — `CredentialVault.create` doesn't exist yet, and both would produce identical ciphertext.

**Step 3: Add `vault_meta` table to store.py schema**

In `src/atlas/memory/store.py`, add after the `credentials` table:

```sql
CREATE TABLE IF NOT EXISTS vault_meta (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL
);
```

**Step 4: Refactor CredentialVault to use per-vault random salt**

Replace `src/atlas/integrations/vault.py`:

```python
"""Credential Vault — encrypted storage for API keys and OAuth tokens."""
import base64
import logging
import os
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from atlas.contracts.errors import CredentialError
from atlas.contracts.types import ExecutionContext
from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a Fernet key from a passphrase using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


class CredentialVault:
    """Encrypted credential storage backed by SQLite."""

    def __init__(self, db: DatabaseStore, passphrase: str):
        self._db = db
        self._fernet = Fernet(_derive_key(passphrase, _SALT=b"atlas-credential-vault-v1"))

    @classmethod
    async def create(cls, db: DatabaseStore, passphrase: str) -> "CredentialVault":
        """Create a CredentialVault with a per-database random salt."""
        salt = await cls._get_or_create_salt(db)
        instance = object.__new__(cls)
        instance._db = db
        instance._fernet = Fernet(_derive_key(passphrase, salt))
        return instance

    @staticmethod
    async def _get_or_create_salt(db: DatabaseStore) -> bytes:
        """Retrieve existing salt from vault_meta, or generate and store a new one."""
        cursor = await db.db.execute(
            "SELECT value FROM vault_meta WHERE key = 'salt'"
        )
        row = await cursor.fetchone()
        if row:
            return row[0]
        salt = os.urandom(32)
        await db.db.execute(
            "INSERT INTO vault_meta (key, value) VALUES ('salt', ?)",
            (salt,),
        )
        await db.db.commit()
        return salt

    async def store(self, service: str, key: str, value: str, expires_at: str | None = None, ctx: ExecutionContext | None = None) -> None:
        encrypted = self._fernet.encrypt(value.encode())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.db.execute(
            """INSERT INTO credentials (service, key, encrypted_value, expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(service, key) DO UPDATE SET
                encrypted_value=excluded.encrypted_value,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at""",
            (service, key, encrypted, expires_at, now, now),
        )
        await self._db.db.commit()
        logger.info("Stored credential: %s/%s", service, key)

    async def get(self, service: str, key: str, ctx: ExecutionContext | None = None) -> str | None:
        cursor = await self._db.db.execute(
            "SELECT encrypted_value FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        try:
            return self._fernet.decrypt(row[0]).decode()
        except InvalidToken as e:
            raise CredentialError(
                f"Decryption failed for {service}/{key}: wrong passphrase or corrupted data",
                cause=e,
            )

    async def delete(self, service: str, key: str, ctx: ExecutionContext | None = None) -> None:
        await self._db.db.execute(
            "DELETE FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        await self._db.db.commit()
        logger.info("Deleted credential: %s/%s", service, key)

    async def list_services(self, ctx: ExecutionContext | None = None) -> list[str]:
        cursor = await self._db.db.execute(
            "SELECT DISTINCT service FROM credentials ORDER BY service"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def list_keys(self, service: str, ctx: ExecutionContext | None = None) -> list[str]:
        cursor = await self._db.db.execute(
            "SELECT key FROM credentials WHERE service=? ORDER BY key",
            (service,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
```

**Important:** Keep the sync `__init__` constructor for backward compatibility (tests and CLI that don't need random salt). But change it to use a fixed fallback salt and log a deprecation warning:

```python
    def __init__(self, db: DatabaseStore, passphrase: str):
        """Sync constructor — uses fixed salt. Prefer CredentialVault.create() for per-vault salt."""
        self._db = db
        self._fernet = Fernet(_derive_key(passphrase, b"atlas-credential-vault-v1"))
```

**Step 5: Update vault fixture and existing tests**

Update the `vault` fixture in `tests/unit/integrations/test_vault.py`:

```python
@pytest.fixture
async def vault(db):
    v = await CredentialVault.create(db=db, passphrase="test-passphrase-for-unit-tests")
    return v
```

Update the integration test fixtures in `tests/integration/test_trust_vault_integration.py`:

```python
@pytest.fixture
async def components(db):
    tracker = TrustTracker(db=db, escalation_threshold=3, demotion_failure_count=2, demotion_window_size=5)
    policy = PolicyEngine(autonomy_level=AutonomyLevel.SUGGEST)
    vault = await CredentialVault.create(db=db, passphrase="integration-test")
    return tracker, policy, vault
```

Also update `test_vault_stores_and_retrieves_across_sessions` and `test_vault_wrong_passphrase_fails` to use `CredentialVault.create()`.

**Step 6: Update CLI vault commands to use `CredentialVault.create()`**

In `src/atlas/cli.py`, update `_vault_set`:
```python
async def _vault_set(service: str, key: str, value: str, passphrase: str):
    from atlas.integrations.vault import CredentialVault
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        v = await CredentialVault.create(db=db, passphrase=passphrase)
        await v.store(service, key, value)
        click.echo(f"[vault] Stored: {service}/{key}")
    finally:
        await db.close()
```

Update `_vault_list` to use CredentialVault instead of raw SQL:
```python
async def _vault_list():
    from atlas.integrations.vault import CredentialVault
    data_dir = _ensure_data_dir()
    db_path = data_dir / "data" / "atlas.db"
    if not db_path.exists():
        click.echo("[vault] No credentials stored.")
        return
    db = DatabaseStore(str(db_path))
    await db.initialize()
    try:
        # Use CredentialVault.create without passphrase isn't possible,
        # but list operations don't need decryption — query directly
        cursor = await db.db.execute(
            "SELECT service, key FROM credentials ORDER BY service, key"
        )
        rows = await cursor.fetchall()
        if not rows:
            click.echo("[vault] No credentials stored.")
            return
        for service, key in rows:
            click.echo(f"  {service}/{key}")
    finally:
        await db.close()
```

Update `_vault_delete` to bypass CredentialVault entirely (delete doesn't need encryption):
```python
async def _vault_delete(service: str, key: str):
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        cursor = await db.db.execute(
            "SELECT 1 FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        row = await cursor.fetchone()
        if row is None:
            click.echo(f"[vault] Not found: {service}/{key}")
            return
        await db.db.execute(
            "DELETE FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        await db.db.commit()
        click.echo(f"[vault] Deleted: {service}/{key}")
    finally:
        await db.close()
```

**Step 7: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests pass.

**Step 8: Commit**

```bash
git add src/atlas/integrations/vault.py src/atlas/memory/store.py src/atlas/cli.py tests/unit/integrations/test_vault.py tests/integration/test_trust_vault_integration.py
git commit -m "fix: use per-vault random PBKDF2 salt, fix CLI vault delete/list"
```

---

### Task 9: Fix MCPBridge `register_tools` idempotency

**Issue:** #9 — `setdefault` preserves existing entries on reconnect, appending duplicate skill IDs.

**Files:**
- Modify: `src/atlas/integrations/mcp.py:54-78`
- Modify: `tests/unit/integrations/test_mcp.py`

**Step 1: Write the failing test**

Add to `tests/unit/integrations/test_mcp.py`:

```python
def test_mcp_bridge_register_tools_idempotent_on_reconnect(registry):
    """Re-registering tools for the same server should not create duplicates."""
    mock_session = MagicMock()
    bridge = MCPBridge(registry=registry)
    tools = [
        _make_tool("tool_a", "Tool A desc", {"type": "object"}),
    ]

    # First registration
    bridge.register_tools(mock_session, tools, server_name="test-server")
    assert len(registry.list_all()) == 1

    # Second registration (simulating reconnect)
    bridge.register_tools(mock_session, tools, server_name="test-server")
    assert len(registry.list_all()) == 1

    # Unregister should clean up without errors
    bridge.unregister_server("test-server")
    assert len(registry.list_all()) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_mcp.py::test_mcp_bridge_register_tools_idempotent_on_reconnect -v`
Expected: FAIL — `_server_skills` accumulates duplicates.

**Step 3: Fix `register_tools` to clear existing entries first**

In `src/atlas/integrations/mcp.py`, update `register_tools`:

```python
    def register_tools(self, session: Any, tools: list, server_name: str) -> list[str]:
        """Register MCP tools as ATLAS skills. Returns list of registered skill IDs."""
        # Unregister existing tools for this server first (idempotent on reconnect)
        if server_name in self._server_skills:
            self.unregister_server(server_name)

        registered = []
        self._server_skills[server_name] = []

        for tool in tools:
            adapter = MCPSkillAdapter(
                session=session,
                tool_name=tool.name,
                tool_description=tool.description or f"MCP tool: {tool.name}",
                input_schema=getattr(tool, "inputSchema", {}) or {},
            )
            self._registry.register(
                skill_id=adapter.skill_id,
                name=adapter.name,
                description=adapter.description,
                handler=adapter.handler,
                risk_level="high",
                tags=["mcp", server_name],
            )
            self._server_skills[server_name].append(adapter.skill_id)
            registered.append(adapter.skill_id)
            logger.info("Registered MCP tool: %s from %s", adapter.skill_id, server_name)

        return registered
```

**Step 4: Run tests to verify**

Run: `pytest tests/unit/integrations/test_mcp.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/atlas/integrations/mcp.py tests/unit/integrations/test_mcp.py
git commit -m "fix: make register_tools idempotent by clearing stale entries on reconnect"
```

---

### Task 10: Wire MCPBridge into DaemonLoop

**Issue:** #2 — MCPBridge is created but never wired into daemon lifecycle.

**Files:**
- Modify: `src/atlas/daemon/loop.py:1-42`
- Modify: `tests/unit/daemon/test_daemon_loop.py`
- Modify: `src/atlas/cli.py` (where DaemonLoop is created)

**Step 1: Write the failing test**

Add to `tests/unit/daemon/test_daemon_loop.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch


async def test_daemon_loop_accepts_mcp_bridge():
    """DaemonLoop should accept an optional MCPBridge and connect on start."""
    from atlas.daemon.loop import DaemonLoop
    mock_bridge = MagicMock()
    mock_bridge.register_tools = MagicMock(return_value=[])
    mock_bridge.unregister_server = MagicMock()

    loop = DaemonLoop(
        socket_path="/tmp/test.sock",
        pid_path="/tmp/test.pid",
        mcp_bridge=mock_bridge,
        mcp_servers=[],
    )
    assert loop._mcp_bridge is mock_bridge
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/daemon/test_daemon_loop.py::test_daemon_loop_accepts_mcp_bridge -v`
Expected: FAIL — `DaemonLoop.__init__` doesn't accept `mcp_bridge`.

**Step 3: Add MCP support to DaemonLoop**

In `src/atlas/daemon/loop.py`, update the constructor and `start`/`stop` methods:

```python
"""Daemon main loop -- runs the socket server and dispatches commands."""
import asyncio
import logging
import os
import time
from typing import Any, Callable, Coroutine

from atlas.daemon.manager import PidFile
from atlas.daemon.protocol import DaemonSocketServer

logger = logging.getLogger(__name__)


class DaemonLoop:
    def __init__(
        self,
        socket_path: str,
        pid_path: str,
        goal_executor: Callable[..., Coroutine[Any, Any, dict]] | None = None,
        mcp_bridge: Any | None = None,
        mcp_servers: list[dict] | None = None,
    ):
        self._socket_path = socket_path
        self._pid_file = PidFile(pid_path)
        self._goal_executor = goal_executor
        self._mcp_bridge = mcp_bridge
        self._mcp_servers = mcp_servers or []
        self._server: DaemonSocketServer | None = None
        self._running = False
        self._start_time = 0.0

    async def start(self) -> None:
        self._start_time = time.monotonic()
        self._running = True
        self._pid_file.write(os.getpid())

        # Connect MCP servers if configured
        await self._connect_mcp_servers()

        self._server = DaemonSocketServer(self._socket_path, self._handle_command)
        await self._server.start()
        logger.info("Daemon started. PID=%d socket=%s", os.getpid(), self._socket_path)

        while self._running:
            await asyncio.sleep(0.1)

        # Disconnect MCP servers on shutdown
        self._disconnect_mcp_servers()

        await self._server.stop()
        self._pid_file.remove()
        logger.info("Daemon stopped.")

    async def stop(self) -> None:
        self._running = False

    async def _connect_mcp_servers(self) -> None:
        """Connect to configured MCP servers and register their tools."""
        if not self._mcp_bridge or not self._mcp_servers:
            return
        for server_cfg in self._mcp_servers:
            server_name = server_cfg.get("name", "")
            if not server_name:
                continue
            logger.info("MCP server configured: %s (connection deferred to first use)", server_name)

    def _disconnect_mcp_servers(self) -> None:
        """Unregister all MCP server tools on shutdown."""
        if not self._mcp_bridge:
            return
        for server_name in list(self._mcp_bridge.list_servers().keys()):
            self._mcp_bridge.unregister_server(server_name)
            logger.info("Disconnected MCP server: %s", server_name)

    async def _handle_command(self, data: dict) -> dict:
        command = data.get("command", "")
        command_id = data.get("command_id", "")

        match command:
            case "goal":
                return await self._handle_goal(command_id, data.get("payload", {}))
            case "status":
                return self._handle_status(command_id)
            case "shutdown":
                asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(self.stop()))
                return {"command_id": command_id, "status": "ok", "payload": {"message": "shutting down"}}
            case _:
                return {"command_id": command_id, "status": "error", "error": f"unknown command: {command}"}

    async def _handle_goal(self, command_id: str, payload: dict) -> dict:
        if not self._goal_executor:
            return {"command_id": command_id, "status": "error", "error": "no goal executor configured"}
        try:
            result = await self._goal_executor(payload.get("goal_text", ""))
            return {"command_id": command_id, "status": "ok", "payload": result}
        except Exception as e:
            return {"command_id": command_id, "status": "error", "error": str(e)}

    def _handle_status(self, command_id: str) -> dict:
        uptime = time.monotonic() - self._start_time
        return {
            "command_id": command_id,
            "status": "ok",
            "payload": {
                "pid": os.getpid(),
                "uptime_seconds": round(uptime, 1),
                "running": self._running,
            },
        }
```

**Step 4: Run tests to verify**

Run: `pytest tests/unit/daemon/test_daemon_loop.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/atlas/daemon/loop.py tests/unit/daemon/test_daemon_loop.py
git commit -m "feat: wire MCPBridge into DaemonLoop lifecycle"
```

---

## Final Verification

After all 10 tasks are complete:

```bash
# Run full test suite
pytest tests/ -v

# Lint check
ruff check src/ tests/

# Verify no regressions
pytest tests/integration/ -v
```

Expected: All tests pass, no lint errors.

## Final Commit

If all tasks were committed individually, no final commit is needed. Create or update the PR description to reference the code review issues that were addressed.

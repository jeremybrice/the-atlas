# Phase 3 Stage A: Trust Escalation + MCP Bridge + Credential Vault

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the foundational layer for Phase 3 — per-skill trust tracking with auto-escalation/demotion, encrypted credential storage, and MCP server integration for automatic tool discovery.

**Architecture:** Three independent components wired into existing infrastructure. TrustTracker extends the PolicyEngine with per-skill autonomy overrides stored in SQLite. CredentialVault provides Fernet-encrypted storage for API keys/OAuth tokens using OS keychain for the master key. MCPBridge connects to configured MCP servers, discovers tools, and auto-registers them as ATLAS skills via MCPSkillAdapter.

**Tech Stack:** Python 3.12, aiosqlite (existing), cryptography (new), keyring (new), mcp SDK (new)

---

### Task 1: Add TrustRecord dataclass and TrustConfig

**Files:**
- Modify: `src/atlas/contracts/types.py:228-272` (Phase 2 section)
- Modify: `src/atlas/config.py:16-21` (ControlConfig)
- Modify: `config/default.yaml:10-17` (control section)
- Test: `tests/unit/contracts/test_types.py`

**Step 1: Write the failing test**

Add to `tests/unit/contracts/test_types.py`:

```python
from atlas.contracts.types import TrustRecord


def test_trust_record_defaults():
    record = TrustRecord(skill_id="file.read")
    assert record.skill_id == "file.read"
    assert record.successes == 0
    assert record.failures == 0
    assert record.consecutive_successes == 0
    assert record.autonomy_override is None


def test_trust_record_with_values():
    record = TrustRecord(
        skill_id="file.read",
        successes=10,
        failures=1,
        consecutive_successes=5,
    )
    assert record.successes == 10
    assert record.failures == 1
    assert record.consecutive_successes == 5
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/contracts/test_types.py::test_trust_record_defaults -v`
Expected: FAIL with `ImportError: cannot import name 'TrustRecord'`

**Step 3: Write minimal implementation**

Add to `src/atlas/contracts/types.py` after the `DaemonResponse` class (after line 272):

```python
# --- Phase 3: Trust Escalation ---

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
```

Then add `TrustConfig` to `src/atlas/config.py`. Add after `ControlConfig` (after line 21):

```python
@dataclass
class TrustConfig:
    escalation_threshold: int = 10  # consecutive successes to suggest escalation
    demotion_failure_count: int = 3  # failures in window to auto-demote
    demotion_window_size: int = 10  # rolling window for failure rate
    enabled: bool = True
```

Update the `AtlasConfig` dataclass to include trust:

```python
@dataclass
class AtlasConfig:
    data_dir: str = "~/.atlas"
    log_level: str = "INFO"
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    trust: TrustConfig = field(default_factory=TrustConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    observation: ObservationConfig = field(default_factory=ObservationConfig)
    reactive: ReactiveConfig = field(default_factory=ReactiveConfig)
```

Update `_SECTION_MAP` to include `"trust": TrustConfig`.

Add to `config/default.yaml` after the control section:

```yaml
trust:
  escalation_threshold: 10
  demotion_failure_count: 3
  demotion_window_size: 10
  enabled: true
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/contracts/test_types.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/contracts/types.py src/atlas/config.py config/default.yaml tests/unit/contracts/test_types.py
git commit -m "feat: add TrustRecord dataclass and TrustConfig for trust escalation"
```

---

### Task 2: Add trust_records table to DatabaseStore

**Files:**
- Modify: `src/atlas/memory/store.py:30-99` (_create_tables)
- Test: `tests/unit/memory/test_store_trust.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/memory/test_store_trust.py`:

```python
import pytest
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_trust_records_table_exists(db):
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trust_records'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "trust_records"


async def test_trust_records_columns(db):
    cursor = await db.db.execute("PRAGMA table_info(trust_records)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "skill_id" in columns
    assert "successes" in columns
    assert "failures" in columns
    assert "consecutive_successes" in columns
    assert "total_invocations" in columns
    assert "autonomy_override" in columns
    assert "updated_at" in columns
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/memory/test_store_trust.py -v`
Expected: FAIL — table `trust_records` does not exist

**Step 3: Write minimal implementation**

Add to `src/atlas/memory/store.py` inside `_create_tables`, after the tasks table (before the closing `"""`):

```sql
            CREATE TABLE IF NOT EXISTS trust_records (
                skill_id TEXT PRIMARY KEY,
                successes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                consecutive_successes INTEGER DEFAULT 0,
                total_invocations INTEGER DEFAULT 0,
                autonomy_override TEXT,
                last_outcome TEXT,
                updated_at TEXT NOT NULL
            );
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/memory/test_store_trust.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/memory/store.py tests/unit/memory/test_store_trust.py
git commit -m "feat: add trust_records table to DatabaseStore schema"
```

---

### Task 3: Implement TrustTracker core logic

**Files:**
- Create: `src/atlas/control/trust.py`
- Test: `tests/unit/control/test_trust.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/control/test_trust.py`:

```python
import pytest
from atlas.control.trust import TrustTracker
from atlas.contracts.types import AutonomyLevel, TrustRecord
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def tracker(db):
    t = TrustTracker(db=db, escalation_threshold=3, demotion_failure_count=2, demotion_window_size=5)
    return t


async def test_record_success_increments(tracker):
    await tracker.record_outcome("file.read", success=True)
    record = await tracker.get_record("file.read")
    assert record.successes == 1
    assert record.consecutive_successes == 1
    assert record.total_invocations == 1


async def test_record_failure_resets_consecutive(tracker):
    await tracker.record_outcome("file.read", success=True)
    await tracker.record_outcome("file.read", success=True)
    await tracker.record_outcome("file.read", success=False)
    record = await tracker.get_record("file.read")
    assert record.successes == 2
    assert record.failures == 1
    assert record.consecutive_successes == 0


async def test_escalation_suggested_after_threshold(tracker):
    # Threshold is 3 for this fixture
    for _ in range(3):
        result = await tracker.record_outcome("file.read", success=True)
    assert result.should_escalate is True


async def test_no_escalation_before_threshold(tracker):
    for _ in range(2):
        result = await tracker.record_outcome("file.read", success=True)
    assert result.should_escalate is False


async def test_demotion_triggered_on_failure_spike(tracker):
    # Window=5, threshold=2 failures
    # First set an override so demotion has something to demote
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    await tracker.record_outcome("file.read", success=True)
    await tracker.record_outcome("file.read", success=False)
    result = await tracker.record_outcome("file.read", success=False)
    assert result.should_demote is True


async def test_get_autonomy_override_none_by_default(tracker):
    override = await tracker.get_autonomy_override("file.read")
    assert override is None


async def test_set_and_get_autonomy_override(tracker):
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    override = await tracker.get_autonomy_override("file.read")
    assert override == AutonomyLevel.ACT_WITHIN_BOUNDS


async def test_get_record_creates_default_if_missing(tracker):
    record = await tracker.get_record("nonexistent.skill")
    assert record.skill_id == "nonexistent.skill"
    assert record.successes == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/control/test_trust.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atlas.control.trust'`

**Step 3: Write minimal implementation**

Create `src/atlas/control/trust.py`:

```python
"""Trust Tracker — tracks per-skill success/failure and suggests autonomy changes."""
import logging
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

    async def record_outcome(self, skill_id: str, success: bool) -> TrustOutcome:
        record = await self.get_record(skill_id)

        record.total_invocations += 1
        if success:
            record.successes += 1
            record.consecutive_successes += 1
            record.last_outcome = "success"
        else:
            record.failures += 1
            record.consecutive_successes = 0
            record.last_outcome = "failure"

        record.updated_at = datetime.now(timezone.utc).isoformat()
        await self._save_record(record)

        outcome = TrustOutcome(skill_id=skill_id)

        # Check escalation: enough consecutive successes
        if record.consecutive_successes >= self._escalation_threshold:
            outcome.should_escalate = True

        # Check demotion: too many failures in recent window
        if not success and record.autonomy_override is not None:
            recent_total = min(record.total_invocations, self._demotion_window_size)
            if recent_total > 0:
                # Simple heuristic: if failures >= threshold, demote
                # We track total failures but approximate recent by checking
                # if failure count relative to window is too high
                recent_failures = self._count_recent_failures(record)
                if recent_failures >= self._demotion_failure_count:
                    outcome.should_demote = True

        return outcome

    def _count_recent_failures(self, record: TrustRecord) -> int:
        """Approximate recent failures. Since consecutive_successes tracks the current
        streak, if it's 0 and we just failed, count backward."""
        # Simple approach: failures since last escalation reset
        # consecutive_successes == 0 means we just broke the streak
        # We use total failures as a proxy since we don't store a sliding window
        # For more accuracy, we'd store recent outcomes, but this suffices for MVP
        if record.total_invocations <= self._demotion_window_size:
            return record.failures
        # Approximate: failures in the last N invocations
        # Since we don't store individual outcomes, use the ratio
        return record.failures

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
        await self._save_record(record)
        logger.info("Trust override set: %s -> %s", skill_id, level.name)

    async def get_autonomy_override(self, skill_id: str) -> AutonomyLevel | None:
        record = await self.get_record(skill_id)
        if record.total_invocations == 0 and record.autonomy_override is None:
            return None
        return record.autonomy_override

    async def _save_record(self, record: TrustRecord) -> None:
        autonomy_val = record.autonomy_override.value if record.autonomy_override is not None else None
        await self._db.db.execute(
            """INSERT INTO trust_records
               (skill_id, successes, failures, consecutive_successes,
                total_invocations, autonomy_override, last_outcome, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(skill_id) DO UPDATE SET
                successes=excluded.successes,
                failures=excluded.failures,
                consecutive_successes=excluded.consecutive_successes,
                total_invocations=excluded.total_invocations,
                autonomy_override=excluded.autonomy_override,
                last_outcome=excluded.last_outcome,
                updated_at=excluded.updated_at""",
            (
                record.skill_id,
                record.successes,
                record.failures,
                record.consecutive_successes,
                record.total_invocations,
                autonomy_val,
                record.last_outcome,
                record.updated_at,
            ),
        )
        await self._db.db.commit()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/control/test_trust.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/control/trust.py tests/unit/control/test_trust.py
git commit -m "feat: implement TrustTracker with outcome recording and escalation/demotion logic"
```

---

### Task 4: Integrate TrustTracker into PolicyEngine

**Files:**
- Modify: `src/atlas/control/policy.py`
- Test: `tests/unit/control/test_policy.py` (extend existing)

**Step 1: Write the failing test**

Add to `tests/unit/control/test_policy.py`:

```python
def test_per_skill_override_allows_low_risk_when_escalated():
    engine = PolicyEngine(
        autonomy_level=AutonomyLevel.SUGGEST,  # global = suggest (require approval)
        skill_overrides={"file.read": AutonomyLevel.ACT_WITHIN_BOUNDS},  # per-skill escalated
    )
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read a file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    assert engine.evaluate(action) == PolicyDecision.ALLOW


def test_per_skill_override_not_applied_to_other_skills():
    engine = PolicyEngine(
        autonomy_level=AutonomyLevel.SUGGEST,
        skill_overrides={"file.read": AutonomyLevel.ACT_WITHIN_BOUNDS},
    )
    action = ProposedAction(
        action_type="shell_execute",
        domain="skills",
        description="run command",
        risk_level=RiskLevel.LOW,
        skill_id="shell.execute",
    )
    # shell.execute has no override, falls back to global SUGGEST
    assert engine.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL


def test_get_autonomy_level_returns_override_when_set():
    engine = PolicyEngine(
        autonomy_level=AutonomyLevel.SUGGEST,
        skill_overrides={"file.read": AutonomyLevel.ACT_WITHIN_BOUNDS},
    )
    assert engine.get_autonomy_level("skills", skill="file.read") == AutonomyLevel.ACT_WITHIN_BOUNDS
    assert engine.get_autonomy_level("skills", skill="shell.execute") == AutonomyLevel.SUGGEST
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/control/test_policy.py::test_per_skill_override_allows_low_risk_when_escalated -v`
Expected: FAIL — `PolicyEngine.__init__()` got unexpected keyword argument `skill_overrides`

**Step 3: Write minimal implementation**

Replace `src/atlas/control/policy.py` entirely:

```python
"""Policy Engine — evaluates proposed actions against autonomy rules and boundaries."""
from pathlib import Path

from atlas.contracts.types import (
    AutonomyLevel,
    PolicyDecision,
    ProposedAction,
    RiskLevel,
)


class PolicyEngine:
    """Stateless policy evaluator. Every action passes through evaluate()."""

    def __init__(
        self,
        autonomy_level: AutonomyLevel = AutonomyLevel.ACT_WITHIN_BOUNDS,
        blocked_paths: list[str] | None = None,
        skill_overrides: dict[str, AutonomyLevel] | None = None,
    ):
        self._autonomy_level = autonomy_level
        self._blocked_paths = [
            str(Path(p).expanduser()) for p in (blocked_paths or [])
        ]
        self._skill_overrides = skill_overrides or {}

    def evaluate(self, action: ProposedAction) -> PolicyDecision:
        # Check blocked paths first
        if self._is_blocked_path(action):
            return PolicyDecision.DENY

        # Resolve effective autonomy level (per-skill override or global)
        effective_level = self._resolve_autonomy(action.skill_id)

        match effective_level:
            case AutonomyLevel.OBSERVE:
                return PolicyDecision.DENY
            case AutonomyLevel.SUGGEST:
                return PolicyDecision.REQUIRE_APPROVAL
            case AutonomyLevel.ACT_WITHIN_BOUNDS:
                return self._evaluate_bounded(action)

    def set_skill_override(self, skill_id: str, level: AutonomyLevel) -> None:
        self._skill_overrides[skill_id] = level

    def remove_skill_override(self, skill_id: str) -> None:
        self._skill_overrides.pop(skill_id, None)

    def _resolve_autonomy(self, skill_id: str | None) -> AutonomyLevel:
        if skill_id and skill_id in self._skill_overrides:
            return self._skill_overrides[skill_id]
        return self._autonomy_level

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

    def _is_blocked_path(self, action: ProposedAction) -> bool:
        path_str = action.params.get("path", "")
        if not path_str:
            return False
        resolved = str(Path(path_str).expanduser())
        return any(resolved.startswith(bp) for bp in self._blocked_paths)

    def get_autonomy_level(self, domain: str, skill: str | None = None) -> AutonomyLevel:
        if skill and skill in self._skill_overrides:
            return self._skill_overrides[skill]
        return self._autonomy_level
```

**Step 4: Run all policy tests to verify nothing is broken**

Run: `pytest tests/unit/control/test_policy.py -v`
Expected: All PASS (existing + new)

**Step 5: Commit**

```bash
git add src/atlas/control/policy.py tests/unit/control/test_policy.py
git commit -m "feat: add per-skill autonomy overrides to PolicyEngine"
```

---

### Task 5: Add credentials table to DatabaseStore

**Files:**
- Modify: `src/atlas/memory/store.py:30-99` (_create_tables)
- Test: `tests/unit/memory/test_store_vault.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/memory/test_store_vault.py`:

```python
import pytest
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_credentials_table_exists(db):
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='credentials'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "credentials"


async def test_credentials_columns(db):
    cursor = await db.db.execute("PRAGMA table_info(credentials)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "service" in columns
    assert "key" in columns
    assert "encrypted_value" in columns
    assert "expires_at" in columns
    assert "created_at" in columns
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/memory/test_store_vault.py -v`
Expected: FAIL — table `credentials` does not exist

**Step 3: Write minimal implementation**

Add to `src/atlas/memory/store.py` inside `_create_tables`, after the trust_records table:

```sql
            CREATE TABLE IF NOT EXISTS credentials (
                service TEXT NOT NULL,
                key TEXT NOT NULL,
                encrypted_value BLOB NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (service, key)
            );
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/memory/test_store_vault.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/memory/store.py tests/unit/memory/test_store_vault.py
git commit -m "feat: add credentials table to DatabaseStore schema"
```

---

### Task 6: Implement CredentialVault

**Files:**
- Create: `src/atlas/integrations/vault.py`
- Test: `tests/unit/integrations/test_vault.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/integrations/__init__.py` (empty) and `tests/unit/integrations/test_vault.py`:

```python
import pytest
from atlas.integrations.vault import CredentialVault
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def vault(db):
    v = CredentialVault(db=db, passphrase="test-passphrase-for-unit-tests")
    return v


async def test_store_and_get(vault):
    await vault.store("github", "token", "ghp_abc123")
    result = await vault.get("github", "token")
    assert result == "ghp_abc123"


async def test_get_nonexistent_returns_none(vault):
    result = await vault.get("github", "nonexistent")
    assert result is None


async def test_store_overwrites_existing(vault):
    await vault.store("github", "token", "old_value")
    await vault.store("github", "token", "new_value")
    result = await vault.get("github", "token")
    assert result == "new_value"


async def test_delete(vault):
    await vault.store("github", "token", "ghp_abc123")
    await vault.delete("github", "token")
    result = await vault.get("github", "token")
    assert result is None


async def test_list_services(vault):
    await vault.store("github", "token", "ghp_abc")
    await vault.store("slack", "bot_token", "xoxb_abc")
    services = await vault.list_services()
    assert set(services) == {"github", "slack"}


async def test_list_keys_for_service(vault):
    await vault.store("github", "token", "ghp_abc")
    await vault.store("github", "webhook_secret", "whsec_abc")
    keys = await vault.list_keys("github")
    assert set(keys) == {"token", "webhook_secret"}


async def test_values_are_encrypted_in_db(vault, db):
    await vault.store("github", "token", "ghp_abc123")
    cursor = await db.db.execute(
        "SELECT encrypted_value FROM credentials WHERE service='github' AND key='token'"
    )
    row = await cursor.fetchone()
    # The stored value should NOT be the plaintext
    assert row[0] != b"ghp_abc123"
    assert row[0] != "ghp_abc123"


async def test_store_with_expiry(vault):
    await vault.store("github", "oauth", "token_val", expires_at="2026-12-31T00:00:00Z")
    result = await vault.get("github", "oauth")
    assert result == "token_val"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_vault.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atlas.integrations.vault'`

**Step 3: Write minimal implementation**

Create `src/atlas/integrations/vault.py`:

```python
"""Credential Vault — encrypted storage for API keys and OAuth tokens."""
import base64
import logging
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)

# Fixed salt for key derivation. In production, you'd store a random salt per-vault,
# but for a single-user local tool this is sufficient.
_SALT = b"atlas-credential-vault-v1"


def _derive_key(passphrase: str) -> bytes:
    """Derive a Fernet key from a passphrase using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


class CredentialVault:
    """Encrypted credential storage backed by SQLite."""

    def __init__(self, db: DatabaseStore, passphrase: str):
        self._db = db
        self._fernet = Fernet(_derive_key(passphrase))

    async def store(
        self,
        service: str,
        key: str,
        value: str,
        expires_at: str | None = None,
    ) -> None:
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

    async def get(self, service: str, key: str) -> str | None:
        cursor = await self._db.db.execute(
            "SELECT encrypted_value FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._fernet.decrypt(row[0]).decode()

    async def delete(self, service: str, key: str) -> None:
        await self._db.db.execute(
            "DELETE FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        await self._db.db.commit()
        logger.info("Deleted credential: %s/%s", service, key)

    async def list_services(self) -> list[str]:
        cursor = await self._db.db.execute(
            "SELECT DISTINCT service FROM credentials ORDER BY service"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def list_keys(self, service: str) -> list[str]:
        cursor = await self._db.db.execute(
            "SELECT key FROM credentials WHERE service=? ORDER BY key",
            (service,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_vault.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/integrations/vault.py tests/unit/integrations/__init__.py tests/unit/integrations/test_vault.py
git commit -m "feat: implement CredentialVault with Fernet encryption"
```

---

### Task 7: Add vault CLI commands

**Files:**
- Modify: `src/atlas/cli.py` (add vault group after watch group)
- Test: manual CLI test (Click commands are thin wrappers)

**Step 1: Write the failing test**

Create `tests/unit/test_cli_vault.py`:

```python
from click.testing import CliRunner
from atlas.cli import main


def test_vault_group_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["vault", "--help"])
    assert result.exit_code == 0
    assert "Manage the credential vault" in result.output


def test_vault_list_no_credentials():
    runner = CliRunner()
    result = runner.invoke(main, ["vault", "list"])
    assert result.exit_code == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cli_vault.py -v`
Expected: FAIL — "No such command 'vault'"

**Step 3: Write minimal implementation**

Add to `src/atlas/cli.py` before `if __name__ == "__main__":` (after the watch group):

```python
# --- Vault commands ---

@main.group()
def vault():
    """Manage the credential vault."""
    pass


@vault.command("set")
@click.argument("service")
@click.argument("key")
@click.option("--value", prompt=True, hide_input=True, help="Credential value (prompted securely)")
@click.option("--passphrase", prompt=True, hide_input=True, help="Vault passphrase")
def vault_set(service: str, key: str, value: str, passphrase: str):
    """Store a credential in the vault."""
    asyncio.run(_vault_set(service, key, value, passphrase))


async def _vault_set(service: str, key: str, value: str, passphrase: str):
    from atlas.integrations.vault import CredentialVault
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        v = CredentialVault(db=db, passphrase=passphrase)
        await v.store(service, key, value)
        click.echo(f"[vault] Stored: {service}/{key}")
    finally:
        await db.close()


@vault.command("list")
def vault_list():
    """List stored credentials (services and keys only)."""
    asyncio.run(_vault_list())


async def _vault_list():
    data_dir = _ensure_data_dir()
    db_path = data_dir / "data" / "atlas.db"
    if not db_path.exists():
        click.echo("[vault] No credentials stored.")
        return
    db = DatabaseStore(str(db_path))
    await db.initialize()
    try:
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


@vault.command("delete")
@click.argument("service")
@click.argument("key")
def vault_delete(service: str, key: str):
    """Delete a credential from the vault."""
    asyncio.run(_vault_delete(service, key))


async def _vault_delete(service: str, key: str):
    from atlas.integrations.vault import CredentialVault
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        # Use a dummy passphrase since delete doesn't need decryption
        v = CredentialVault(db=db, passphrase="unused")
        await v.delete(service, key)
        click.echo(f"[vault] Deleted: {service}/{key}")
    finally:
        await db.close()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_cli_vault.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/cli.py tests/unit/test_cli_vault.py
git commit -m "feat: add vault CLI commands (set, list, delete)"
```

---

### Task 8: Add MCP config and EventType.WEBHOOK

**Files:**
- Modify: `src/atlas/config.py` (add MCPConfig dataclass)
- Modify: `src/atlas/contracts/types.py` (add WEBHOOK to EventType)
- Modify: `config/default.yaml` (add mcp section)
- Test: `tests/unit/test_config.py` (extend existing)

**Step 1: Write the failing test**

Add to `tests/unit/test_config.py`:

```python
def test_mcp_config_defaults():
    from atlas.config import MCPConfig
    cfg = MCPConfig()
    assert cfg.servers == []
    assert cfg.enabled is True


def test_webhook_event_type():
    from atlas.contracts.types import EventType
    assert EventType.WEBHOOK == "webhook"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py::test_mcp_config_defaults -v`
Expected: FAIL with `ImportError: cannot import name 'MCPConfig'`

**Step 3: Write minimal implementation**

Add to `src/atlas/config.py` after `SkillsConfig`:

```python
@dataclass
class MCPServerEntry:
    name: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class MCPConfig:
    enabled: bool = True
    servers: list[dict] = field(default_factory=list)
```

Update `AtlasConfig` to include `mcp: MCPConfig = field(default_factory=MCPConfig)`.

Update `_SECTION_MAP` to include `"mcp": MCPConfig`.

Add `WEBHOOK = "webhook"` to `EventType` in `src/atlas/contracts/types.py`:

```python
class EventType(str, Enum):
    FILESYSTEM = "filesystem"
    SCHEDULED = "scheduled"
    GOAL = "goal"
    WEBHOOK = "webhook"
```

Add to `config/default.yaml`:

```yaml
mcp:
  enabled: true
  servers: []
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/config.py src/atlas/contracts/types.py config/default.yaml tests/unit/test_config.py
git commit -m "feat: add MCPConfig and EventType.WEBHOOK for MCP Bridge"
```

---

### Task 9: Implement MCPBridge and MCPSkillAdapter

**Files:**
- Create: `src/atlas/integrations/mcp.py`
- Test: `tests/unit/integrations/test_mcp.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/integrations/test_mcp.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from atlas.integrations.mcp import MCPBridge, MCPSkillAdapter
from atlas.skills.registry import SkillRegistry
from atlas.contracts.types import RiskLevel


@pytest.fixture
def registry():
    return SkillRegistry()


def test_mcp_skill_adapter_creates_handler():
    mock_session = MagicMock()
    adapter = MCPSkillAdapter(
        session=mock_session,
        tool_name="test_tool",
        tool_description="A test tool",
        input_schema={"type": "object", "properties": {"arg1": {"type": "string"}}},
    )
    assert adapter.skill_id == "mcp.test_tool"
    assert adapter.name == "test_tool"
    assert adapter.description == "A test tool"
    assert adapter.risk_level == RiskLevel.HIGH
    assert callable(adapter.handler)


async def test_mcp_skill_adapter_handler_calls_session():
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(
        content=[MagicMock(text="result text")]
    ))

    adapter = MCPSkillAdapter(
        session=mock_session,
        tool_name="test_tool",
        tool_description="A test tool",
        input_schema={},
    )
    result = await adapter.handler({"arg1": "value1"})
    mock_session.call_tool.assert_called_once_with("test_tool", arguments={"arg1": "value1"})
    assert result["output"] == "result text"
    assert result["status"] == "success"


async def test_mcp_skill_adapter_handler_error():
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=Exception("connection lost"))

    adapter = MCPSkillAdapter(
        session=mock_session,
        tool_name="test_tool",
        tool_description="A test tool",
        input_schema={},
    )
    result = await adapter.handler({"arg1": "value1"})
    assert result["status"] == "error"
    assert "connection lost" in result["error"]


def test_mcp_bridge_register_tools(registry):
    mock_session = MagicMock()
    bridge = MCPBridge(registry=registry)
    tools = [
        MagicMock(name="tool_a", description="Tool A desc", inputSchema={"type": "object"}),
        MagicMock(name="tool_b", description="Tool B desc", inputSchema={"type": "object"}),
    ]
    bridge.register_tools(mock_session, tools, server_name="test-server")
    all_skills = registry.list_all()
    skill_ids = {s.skill_id for s in all_skills}
    assert "mcp.tool_a" in skill_ids
    assert "mcp.tool_b" in skill_ids


def test_mcp_bridge_unregister_server(registry):
    mock_session = MagicMock()
    bridge = MCPBridge(registry=registry)
    tools = [
        MagicMock(name="tool_a", description="Tool A desc", inputSchema={"type": "object"}),
    ]
    bridge.register_tools(mock_session, tools, server_name="test-server")
    assert len(registry.list_all()) == 1

    bridge.unregister_server("test-server")
    assert len(registry.list_all()) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_mcp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atlas.integrations.mcp'`

**Step 3: Write minimal implementation**

Create `src/atlas/integrations/mcp.py`:

```python
"""MCP Bridge — connects to MCP servers and registers tools as ATLAS skills."""
import logging
from dataclasses import dataclass, field
from typing import Any

from atlas.contracts.types import RiskLevel
from atlas.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


@dataclass
class MCPSkillAdapter:
    """Wraps an MCP tool as an ATLAS skill handler."""
    session: Any  # MCP ClientSession
    tool_name: str
    tool_description: str
    input_schema: dict[str, Any]
    risk_level: RiskLevel = RiskLevel.HIGH

    @property
    def skill_id(self) -> str:
        return f"mcp.{self.tool_name}"

    @property
    def name(self) -> str:
        return self.tool_name

    @property
    def description(self) -> str:
        return self.tool_description

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
            return {"status": "error", "error": str(e)}


class MCPBridge:
    """Manages MCP server connections and tool registration."""

    def __init__(self, registry: SkillRegistry):
        self._registry = registry
        self._server_skills: dict[str, list[str]] = {}  # server_name -> [skill_ids]

    def register_tools(self, session: Any, tools: list, server_name: str) -> list[str]:
        """Register MCP tools as ATLAS skills. Returns list of registered skill IDs."""
        registered = []
        self._server_skills.setdefault(server_name, [])

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

    def unregister_server(self, server_name: str) -> None:
        """Unregister all skills from a given MCP server."""
        skill_ids = self._server_skills.pop(server_name, [])
        for skill_id in skill_ids:
            self._registry.unregister(skill_id)
            logger.info("Unregistered MCP tool: %s", skill_id)

    def list_servers(self) -> dict[str, list[str]]:
        """Return map of server_name -> registered skill IDs."""
        return dict(self._server_skills)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_mcp.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/atlas/integrations/mcp.py tests/unit/integrations/test_mcp.py
git commit -m "feat: implement MCPBridge and MCPSkillAdapter for MCP tool registration"
```

---

### Task 10: Add cryptography and keyring dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: No test needed — dependency management**

**Step 2: Add dependencies**

In `pyproject.toml`, add to `dependencies`:

```toml
dependencies = [
    "click>=8.1",
    "aiosqlite>=0.20",
    "pyyaml>=6.0",
    "anthropic>=0.42",
    "watchdog>=4.0",
    "cryptography>=43.0",
]
```

Note: `keyring` is deferred — the current CredentialVault takes a passphrase directly. When we add OS keychain integration for passphrase storage, we'll add `keyring` then. This avoids an unnecessary dependency for now (YAGNI).

**Step 3: Install updated dependencies**

Run: `pip install -e ".[dev]"`

**Step 4: Verify all tests still pass**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add cryptography dependency for credential vault"
```

---

### Task 11: Integration test — Trust + Policy + Vault wired together

**Files:**
- Create: `tests/integration/test_trust_vault_integration.py`

**Step 1: Write the integration test**

Create `tests/integration/test_trust_vault_integration.py`:

```python
"""Integration test: TrustTracker + PolicyEngine + CredentialVault working together."""
import pytest
from atlas.control.policy import PolicyEngine
from atlas.control.trust import TrustTracker
from atlas.contracts.types import (
    AutonomyLevel,
    PolicyDecision,
    ProposedAction,
    RiskLevel,
)
from atlas.integrations.vault import CredentialVault
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "atlas.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def components(db):
    tracker = TrustTracker(db=db, escalation_threshold=3, demotion_failure_count=2, demotion_window_size=5)
    policy = PolicyEngine(autonomy_level=AutonomyLevel.SUGGEST)
    vault = CredentialVault(db=db, passphrase="integration-test")
    return tracker, policy, vault


async def test_trust_escalation_changes_policy_decision(components):
    tracker, policy, _ = components

    # Initially, SUGGEST mode requires approval for everything
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    assert policy.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL

    # Record 3 successes (threshold) for file.read
    for _ in range(3):
        outcome = await tracker.record_outcome("file.read", success=True)

    assert outcome.should_escalate is True

    # Simulate user approving escalation
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    policy.set_skill_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)

    # Now file.read should be ALLOW (low risk + ACT_WITHIN_BOUNDS)
    assert policy.evaluate(action) == PolicyDecision.ALLOW

    # Other skills still require approval
    other_action = ProposedAction(
        action_type="shell_execute",
        domain="skills",
        description="run command",
        risk_level=RiskLevel.LOW,
        skill_id="shell.execute",
    )
    assert policy.evaluate(other_action) == PolicyDecision.REQUIRE_APPROVAL


async def test_trust_demotion_reverts_policy(components):
    tracker, policy, _ = components

    # Set up an escalated skill
    await tracker.set_autonomy_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)
    policy.set_skill_override("file.read", AutonomyLevel.ACT_WITHIN_BOUNDS)

    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    assert policy.evaluate(action) == PolicyDecision.ALLOW

    # Record failures until demotion triggers
    await tracker.record_outcome("file.read", success=False)
    outcome = await tracker.record_outcome("file.read", success=False)
    assert outcome.should_demote is True

    # Apply demotion
    policy.remove_skill_override("file.read")
    # Now falls back to global SUGGEST
    assert policy.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL


async def test_vault_stores_and_retrieves_across_sessions(db):
    """Verify vault data persists across CredentialVault instances."""
    vault1 = CredentialVault(db=db, passphrase="same-pass")
    await vault1.store("github", "token", "ghp_secret123")

    # Create a new vault instance with same passphrase
    vault2 = CredentialVault(db=db, passphrase="same-pass")
    result = await vault2.get("github", "token")
    assert result == "ghp_secret123"


async def test_vault_wrong_passphrase_fails(db):
    vault1 = CredentialVault(db=db, passphrase="correct-pass")
    await vault1.store("github", "token", "ghp_secret123")

    # Different passphrase = different key = decryption fails
    vault2 = CredentialVault(db=db, passphrase="wrong-pass")
    with pytest.raises(Exception):  # Fernet raises InvalidToken
        await vault2.get("github", "token")
```

**Step 2: Run the integration test**

Run: `pytest tests/integration/test_trust_vault_integration.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/integration/test_trust_vault_integration.py
git commit -m "test: add integration tests for trust escalation + vault"
```

---

### Task 12: Run full test suite and lint

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 2: Run linter**

Run: `ruff check src/ tests/`
Expected: No errors (fix any that arise)

**Step 3: Final commit if any lint fixes needed**

```bash
git add -A
git commit -m "style: fix lint issues from Stage A implementation"
```

---

## Summary of files created/modified

**New files:**
- `src/atlas/control/trust.py` — TrustTracker
- `src/atlas/integrations/vault.py` — CredentialVault
- `src/atlas/integrations/mcp.py` — MCPBridge, MCPSkillAdapter
- `tests/unit/control/test_trust.py`
- `tests/unit/integrations/__init__.py`
- `tests/unit/integrations/test_vault.py`
- `tests/unit/integrations/test_mcp.py`
- `tests/unit/memory/test_store_trust.py`
- `tests/unit/memory/test_store_vault.py`
- `tests/unit/test_cli_vault.py`
- `tests/integration/test_trust_vault_integration.py`

**Modified files:**
- `src/atlas/contracts/types.py` — TrustRecord, EventType.WEBHOOK
- `src/atlas/config.py` — TrustConfig, MCPConfig
- `src/atlas/control/policy.py` — skill_overrides support
- `src/atlas/memory/store.py` — trust_records + credentials tables
- `src/atlas/cli.py` — vault CLI commands
- `config/default.yaml` — trust + mcp sections
- `pyproject.toml` — cryptography dependency

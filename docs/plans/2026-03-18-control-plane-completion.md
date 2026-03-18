# Control Plane Completion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the ATLAS Control Plane with graceful daemon controls (pause/resume/kill), batch + standing approval rules, trust recommendations with post-mission summary, and full dashboard API (20 endpoints).

**Architecture:** Four vertical feature slices, each delivering end-to-end from DB schema through business logic through CLI/API surface. Slice 1 adds emergency controls to the daemon via the existing Unix socket protocol. Slice 2 introduces persistent approval rules with glob-based matching and batch approval in the execution loop. Slice 3 adds trust recommendations that accumulate during a mission and present as a post-mission summary. Slice 4 fills remaining dashboard API gaps (tasks, health, config, connectors).

**Tech Stack:** Python 3.12, asyncio, aiosqlite (existing), aiohttp (existing), Click (existing), pytest, pytest-aiohttp

---

## Slice 1: Emergency Controls

### Task 1: Add ApprovalRule and TrustRecommendation dataclasses to contracts

**Files:**
- Modify: `src/atlas/contracts/types.py:276-289`
- Test: `tests/unit/contracts/test_types.py`

**Step 1: Write the failing test**

Add to `tests/unit/contracts/test_types.py`:

```python
from atlas.contracts.types import ApprovalRule, TrustRecommendation


def test_approval_rule_defaults():
    rule = ApprovalRule(match_skill="file.*", decision="allow")
    assert rule.rule_type == "standing"
    assert rule.match_risk == "*"
    assert rule.match_path is None
    assert rule.expires_at is None
    assert rule.rule_id  # should have an auto-generated id


def test_trust_recommendation_defaults():
    rec = TrustRecommendation(skill_id="file.read", direction="escalate")
    assert rec.status == "pending"
    assert rec.resolved_at is None
    assert rec.recommendation_id  # auto-generated
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/contracts/test_types.py::test_approval_rule_defaults tests/unit/contracts/test_types.py::test_trust_recommendation_defaults -v`
Expected: FAIL with `ImportError: cannot import name 'ApprovalRule'`

**Step 3: Write minimal implementation**

In `src/atlas/contracts/types.py`, add after the `TrustRecord` class (after line 289):

```python
# --- Phase 3: Approval Rules ---

@dataclass
class ApprovalRule:
    """Persistent rule for auto-approving or auto-denying actions."""
    rule_id: str = field(default_factory=new_id)
    rule_type: str = "standing"
    match_skill: str = "*"
    match_risk: str = "*"
    match_path: str | None = None
    decision: str = "allow"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str | None = None
    description: str = ""


# --- Phase 3: Trust Recommendations ---

@dataclass
class TrustRecommendation:
    """Recommendation to escalate or demote a skill's autonomy level."""
    recommendation_id: str = field(default_factory=new_id)
    skill_id: str = ""
    current_level: str = ""
    recommended_level: str = ""
    direction: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    mission_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: str | None = None
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && pytest tests/unit/contracts/test_types.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/atlas/contracts/types.py tests/unit/contracts/test_types.py
git commit -m "feat: add ApprovalRule and TrustRecommendation dataclasses to contracts"
```

---

### Task 2: Add approval_rules and trust_recommendations tables to schema

**Files:**
- Modify: `src/atlas/memory/store.py:34-157`

**Step 1: Add the new tables**

In `src/atlas/memory/store.py`, inside the `_create_tables` method's `executescript` block, add before the closing `"""`  (before line 157):

```sql
            CREATE TABLE IF NOT EXISTS approval_rules (
                rule_id TEXT PRIMARY KEY,
                rule_type TEXT NOT NULL,
                match_skill TEXT NOT NULL,
                match_risk TEXT NOT NULL,
                match_path TEXT,
                decision TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS trust_recommendations (
                recommendation_id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                current_level TEXT NOT NULL,
                recommended_level TEXT NOT NULL,
                direction TEXT NOT NULL,
                evidence TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                mission_id TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
```

**Step 2: Verify existing tests still pass**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: 273 tests pass (no regressions)

**Step 3: Commit**

```bash
git add src/atlas/memory/store.py
git commit -m "feat: add approval_rules and trust_recommendations tables to schema"
```

---

### Task 3: Implement EmergencyController

**Files:**
- Create: `src/atlas/control/emergency.py`
- Create: `tests/unit/control/test_emergency.py`

**Step 1: Write the failing tests**

Create `tests/unit/control/test_emergency.py`:

```python
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from atlas.control.emergency import EmergencyController


@pytest.fixture
def controller():
    return EmergencyController()


async def test_initial_state_is_not_paused(controller):
    assert controller.is_paused is False
    assert controller.active_task_id is None


async def test_pause_sets_paused_flag(controller):
    controller.pause()
    assert controller.is_paused is True


async def test_resume_clears_paused_flag(controller):
    controller.pause()
    controller.resume()
    assert controller.is_paused is False


async def test_wait_if_paused_blocks_when_paused(controller):
    controller.pause()
    # Should not complete within timeout
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(controller.wait_if_paused(), timeout=0.1)


async def test_wait_if_paused_returns_immediately_when_not_paused(controller):
    # Should complete instantly
    await asyncio.wait_for(controller.wait_if_paused(), timeout=0.1)


async def test_wait_if_paused_unblocks_on_resume(controller):
    controller.pause()

    async def resume_soon():
        await asyncio.sleep(0.05)
        controller.resume()

    asyncio.create_task(resume_soon())
    await asyncio.wait_for(controller.wait_if_paused(), timeout=0.5)
    assert controller.is_paused is False


async def test_set_and_clear_active_task(controller):
    controller.set_active_task("task-123")
    assert controller.active_task_id == "task-123"
    controller.clear_active_task()
    assert controller.active_task_id is None


async def test_kill_task_marks_cancelled(controller):
    controller.set_active_task("task-abc")
    result = controller.kill_task("task-abc")
    assert result is True
    assert controller.is_task_cancelled("task-abc")


async def test_kill_task_wrong_id_returns_false(controller):
    controller.set_active_task("task-abc")
    result = controller.kill_task("task-xyz")
    assert result is False
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_emergency.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atlas.control.emergency'`

**Step 3: Write minimal implementation**

Create `src/atlas/control/emergency.py`:

```python
"""Emergency Controller — pause, resume, and kill operations for the daemon."""
import asyncio
import logging

logger = logging.getLogger(__name__)


class EmergencyController:
    """Manages daemon pause/resume state and task cancellation."""

    def __init__(self) -> None:
        self._running = asyncio.Event()
        self._running.set()  # starts unpaused
        self._active_task_id: str | None = None
        self._cancelled_tasks: set[str] = set()

    @property
    def is_paused(self) -> bool:
        return not self._running.is_set()

    @property
    def active_task_id(self) -> str | None:
        return self._active_task_id

    def pause(self) -> None:
        """Pause the execution loop. Running tasks finish; new tasks wait."""
        self._running.clear()
        logger.info("Emergency: execution paused")

    def resume(self) -> None:
        """Resume the execution loop."""
        self._running.set()
        self._cancelled_tasks.clear()
        logger.info("Emergency: execution resumed")

    async def wait_if_paused(self) -> None:
        """Block until resumed. Call before each task execution."""
        await self._running.wait()

    def set_active_task(self, task_id: str) -> None:
        self._active_task_id = task_id

    def clear_active_task(self) -> None:
        self._active_task_id = None

    def kill_task(self, task_id: str) -> bool:
        """Mark a task for cancellation. Returns True if the task is active."""
        if self._active_task_id == task_id:
            self._cancelled_tasks.add(task_id)
            logger.info("Emergency: task %s marked for cancellation", task_id)
            return True
        return False

    def is_task_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancelled_tasks
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_emergency.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/atlas/control/emergency.py tests/unit/control/test_emergency.py
git commit -m "feat: implement EmergencyController with pause/resume/kill"
```

---

### Task 4: Wire EmergencyController into DaemonLoop

**Files:**
- Modify: `src/atlas/daemon/loop.py:14-122`
- Modify: `tests/unit/daemon/test_daemon_loop.py`

**Step 1: Write the failing tests**

Add to `tests/unit/daemon/test_daemon_loop.py`:

```python
async def test_daemon_loop_pause_command():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"
    executor = AsyncMock()

    loop = DaemonLoop(socket_path=socket_path, pid_path=pid_path, goal_executor=executor)
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    try:
        from atlas.daemon.protocol import DaemonSocketClient
        client = DaemonSocketClient(socket_path)
        resp = await client.send(DaemonCommand(command="pause"))
        assert resp["status"] == "ok"

        # Status should now report paused
        status_resp = await client.send(DaemonCommand(command="status"))
        assert status_resp["payload"]["paused"] is True
    finally:
        await loop.stop()
        await task


async def test_daemon_loop_resume_command():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"
    executor = AsyncMock()

    loop = DaemonLoop(socket_path=socket_path, pid_path=pid_path, goal_executor=executor)
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    try:
        from atlas.daemon.protocol import DaemonSocketClient
        client = DaemonSocketClient(socket_path)
        await client.send(DaemonCommand(command="pause"))
        resp = await client.send(DaemonCommand(command="resume"))
        assert resp["status"] == "ok"

        status_resp = await client.send(DaemonCommand(command="status"))
        assert status_resp["payload"]["paused"] is False
    finally:
        await loop.stop()
        await task


async def test_daemon_loop_kill_command_no_active_task():
    tmpdir = tempfile.mkdtemp()
    socket_path = f"{tmpdir}/t.sock"
    pid_path = f"{tmpdir}/t.pid"
    executor = AsyncMock()

    loop = DaemonLoop(socket_path=socket_path, pid_path=pid_path, goal_executor=executor)
    task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.1)

    try:
        from atlas.daemon.protocol import DaemonSocketClient
        client = DaemonSocketClient(socket_path)
        resp = await client.send(DaemonCommand(command="kill", payload={"task_id": "nonexistent"}))
        assert resp["status"] == "ok"
        assert resp["payload"]["killed"] is False
    finally:
        await loop.stop()
        await task
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/daemon/test_daemon_loop.py::test_daemon_loop_pause_command -v`
Expected: FAIL (KeyError — "pause" command not handled)

**Step 3: Modify DaemonLoop**

In `src/atlas/daemon/loop.py`, add the import and wire EmergencyController:

Add to imports (after line 9):
```python
from atlas.control.emergency import EmergencyController
```

Modify `__init__` to create an EmergencyController (add after line 38):
```python
        self._emergency = EmergencyController()
```

Add new cases to `_handle_command` (in the match block, before `case _:`, after the `"shutdown"` case at line 98):

```python
            case "pause":
                self._emergency.pause()
                return {"command_id": command_id, "status": "ok", "payload": {"message": "paused"}}
            case "resume":
                self._emergency.resume()
                return {"command_id": command_id, "status": "ok", "payload": {"message": "resumed"}}
            case "kill":
                task_id = data.get("payload", {}).get("task_id", "")
                killed = self._emergency.kill_task(task_id)
                return {"command_id": command_id, "status": "ok", "payload": {"killed": killed}}
```

Update `_handle_status` to include `paused` and `active_task_id` (in the payload dict):

```python
    def _handle_status(self, command_id: str) -> dict:
        uptime = time.monotonic() - self._start_time
        return {
            "command_id": command_id,
            "status": "ok",
            "payload": {
                "pid": os.getpid(),
                "uptime_seconds": round(uptime, 1),
                "running": self._running,
                "http_running": self._http_running,
                "paused": self._emergency.is_paused,
                "active_task_id": self._emergency.active_task_id,
            },
        }
```

Also expose the emergency controller as a property so cli.py can pass it to the dashboard:

```python
    @property
    def emergency(self) -> EmergencyController:
        return self._emergency
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && pytest tests/unit/daemon/test_daemon_loop.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/atlas/daemon/loop.py tests/unit/daemon/test_daemon_loop.py
git commit -m "feat: wire EmergencyController into DaemonLoop with pause/resume/kill commands"
```

---

### Task 5: Wire EmergencyController into ExecutionLoop

**Files:**
- Modify: `src/atlas/core/loop.py:54-92,152-161,215-291`
- Modify: `tests/integration/test_execution_loop.py` (or create `tests/unit/core/test_loop_emergency.py`)

**Step 1: Write the failing test**

Create `tests/unit/core/test_loop_emergency.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from atlas.control.emergency import EmergencyController
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.contracts.types import (
    AutonomyLevel, PolicyDecision, SkillDescriptor, SkillResult, RiskLevel, TaskStatus,
)
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime


@pytest.fixture
async def db(tmp_path):
    from atlas.memory.store import DatabaseStore
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def components(db):
    registry = SkillRegistry()

    async def noop_handler(params):
        return {"output": "done"}

    registry.register("file.read", "File Read", "Reads files", noop_handler, "low")

    runtime = InvocationRuntime(registry)
    env = MagicMock()
    policy = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    audit = MagicMock()
    audit.log = AsyncMock()
    approval = ApprovalWorkflow(auto_approve=True)
    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    return {
        "registry": registry,
        "runtime": runtime,
        "environment": env,
        "policy": policy,
        "audit": audit,
        "approval": approval,
        "working_memory": working,
        "episodic_memory": episodic,
    }


async def test_execution_loop_pauses_between_tasks(components):
    emergency = EmergencyController()
    loop = ExecutionLoop(**components, emergency_controller=emergency)

    # Pause before execution starts
    emergency.pause()

    task = Task(description="read a file", skill_id="file.read", input_params={"path": "test.txt"})
    mission = Mission(goal_text="test", tasks=[task])

    # Mission should not complete while paused
    exec_task = asyncio.create_task(loop.execute_mission(mission))

    await asyncio.sleep(0.2)
    assert not exec_task.done()

    # Resume — mission should complete
    emergency.resume()
    result = await asyncio.wait_for(exec_task, timeout=2.0)
    assert result.status.value == "completed"


async def test_execution_loop_kill_cancels_task(components):
    emergency = EmergencyController()
    loop = ExecutionLoop(**components, emergency_controller=emergency)

    task = Task(description="read a file", skill_id="file.read", input_params={"path": "test.txt"})
    emergency.kill_task(task.task_id)

    # Pre-cancel the task — the loop should check before executing
    mission = Mission(goal_text="test", tasks=[task])
    result = await loop.execute_mission(mission)
    # Task should be cancelled since we killed it before execution
    assert task.status == TaskStatus.CANCELLED or task.status == TaskStatus.FAILED
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/core/test_loop_emergency.py -v`
Expected: FAIL (TypeError — `emergency_controller` is not an accepted parameter)

**Step 3: Modify ExecutionLoop**

In `src/atlas/core/loop.py`:

Add import (after line 7):
```python
from atlas.control.emergency import EmergencyController
```

Add `emergency_controller` parameter to `__init__` (after `keyword_weight` param, line 74):
```python
        emergency_controller: EmergencyController | None = None,
```

Store it (after line 91):
```python
        self._emergency = emergency_controller
```

In `execute_mission`, before each task execution (line 161, before `logger.info("[task %d/%d]..."`), add:
```python
            # Check emergency controls
            if self._emergency:
                await self._emergency.wait_if_paused()
                self._emergency.set_active_task(task.task_id)
                if self._emergency.is_task_cancelled(task.task_id):
                    task.status = TaskStatus.CANCELLED
                    task.error = "Cancelled by emergency control"
                    if self._emergency:
                        self._emergency.clear_active_task()
                    i += 1
                    continue
```

After each task execution completes (after `actions_log.append(...)` at line 167), add:
```python
            if self._emergency:
                self._emergency.clear_active_task()
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && pytest tests/unit/core/test_loop_emergency.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass (the new `emergency_controller` param defaults to None so existing tests are unaffected)

**Step 6: Commit**

```bash
git add src/atlas/core/loop.py tests/unit/core/test_loop_emergency.py
git commit -m "feat: wire EmergencyController into ExecutionLoop for pause/kill support"
```

---

### Task 6: Add daemon pause/resume/kill CLI commands

**Files:**
- Modify: `src/atlas/cli.py:518-557`

**Step 1: Add the CLI commands**

In `src/atlas/cli.py`, add after the `daemon_status` command (after line 552):

```python
@daemon.command("pause")
def daemon_pause():
    """Pause the running daemon (stops accepting new tasks)."""
    config = _load_config()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))
    if not pid_file.is_running():
        click.echo("[daemon] Not running.")
        return
    socket_path = str(Path(config.daemon.socket_path).expanduser())
    result = asyncio.run(_send_daemon_command(socket_path, "pause"))
    if result.get("status") == "ok":
        click.echo("[daemon] Paused.")
    else:
        click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)


@daemon.command("resume")
def daemon_resume():
    """Resume a paused daemon."""
    config = _load_config()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))
    if not pid_file.is_running():
        click.echo("[daemon] Not running.")
        return
    socket_path = str(Path(config.daemon.socket_path).expanduser())
    result = asyncio.run(_send_daemon_command(socket_path, "resume"))
    if result.get("status") == "ok":
        click.echo("[daemon] Resumed.")
    else:
        click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)


@daemon.command("kill")
@click.argument("task_id")
def daemon_kill(task_id: str):
    """Kill a specific running task."""
    config = _load_config()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))
    if not pid_file.is_running():
        click.echo("[daemon] Not running.")
        return
    socket_path = str(Path(config.daemon.socket_path).expanduser())
    result = asyncio.run(_send_daemon_command_with_payload(socket_path, "kill", {"task_id": task_id}))
    if result.get("status") == "ok":
        killed = result.get("payload", {}).get("killed", False)
        if killed:
            click.echo(f"[daemon] Task {task_id} cancelled.")
        else:
            click.echo(f"[daemon] Task {task_id} not found or not active.")
    else:
        click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)
```

Also add the helper function `_send_daemon_command_with_payload` after the existing `_send_daemon_command` (after line 557):

```python
async def _send_daemon_command_with_payload(socket_path: str, command: str, payload: dict) -> dict:
    client = DaemonSocketClient(socket_path)
    return await client.send(DaemonCommand(command=command, payload=payload))
```

**Step 2: Verify CLI group shows new commands**

Run: `source .venv/bin/activate && atlas daemon --help`
Expected: Shows `pause`, `resume`, `kill` alongside `start`, `stop`, `status`

**Step 3: Run existing tests**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass

**Step 4: Commit**

```bash
git add src/atlas/cli.py
git commit -m "feat: add atlas daemon pause/resume/kill CLI commands"
```

---

## Slice 2: Batch + Standing Approval Rules

### Task 7: Implement ApprovalRuleStore

**Files:**
- Create: `src/atlas/control/approval_rules.py`
- Create: `tests/unit/control/test_approval_rules.py`

**Step 1: Write the failing tests**

Create `tests/unit/control/test_approval_rules.py`:

```python
import pytest
from atlas.contracts.types import ApprovalRule, ProposedAction, RiskLevel
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def rule_store(db):
    return ApprovalRuleStore(db)


async def test_add_and_list_rule(rule_store):
    rule = ApprovalRule(match_skill="file.*", decision="allow", description="allow all file ops")
    rule_id = await rule_store.add_rule(rule)
    assert rule_id == rule.rule_id

    rules = await rule_store.list_rules()
    assert len(rules) == 1
    assert rules[0].match_skill == "file.*"


async def test_remove_rule(rule_store):
    rule = ApprovalRule(match_skill="file.*", decision="allow")
    await rule_store.add_rule(rule)

    removed = await rule_store.remove_rule(rule.rule_id)
    assert removed is True

    rules = await rule_store.list_rules()
    assert len(rules) == 0


async def test_remove_nonexistent_returns_false(rule_store):
    removed = await rule_store.remove_rule("nonexistent-id")
    assert removed is False


async def test_find_matching_skill_glob(rule_store):
    await rule_store.add_rule(ApprovalRule(match_skill="file.*", decision="allow"))

    action = ProposedAction(
        action_type="skill_invoke:file.read",
        domain="core",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    match = await rule_store.find_matching(action)
    assert match is not None
    assert match.decision == "allow"


async def test_find_matching_wildcard_skill(rule_store):
    await rule_store.add_rule(ApprovalRule(match_skill="*", match_risk="low", decision="allow"))

    action = ProposedAction(
        action_type="skill_invoke:shell.execute",
        domain="core",
        description="run command",
        risk_level=RiskLevel.LOW,
        skill_id="shell.execute",
    )
    match = await rule_store.find_matching(action)
    assert match is not None


async def test_find_matching_respects_risk_level(rule_store):
    await rule_store.add_rule(ApprovalRule(match_skill="*", match_risk="low", decision="allow"))

    action = ProposedAction(
        action_type="skill_invoke:shell.execute",
        domain="core",
        description="run command",
        risk_level=RiskLevel.HIGH,
        skill_id="shell.execute",
    )
    match = await rule_store.find_matching(action)
    assert match is None  # HIGH risk doesn't match "low" rule


async def test_find_matching_deny_rule(rule_store):
    await rule_store.add_rule(ApprovalRule(match_skill="shell.*", decision="deny"))

    action = ProposedAction(
        action_type="skill_invoke:shell.execute",
        domain="core",
        description="run command",
        risk_level=RiskLevel.LOW,
        skill_id="shell.execute",
    )
    match = await rule_store.find_matching(action)
    assert match is not None
    assert match.decision == "deny"


async def test_expired_rules_are_skipped(rule_store):
    await rule_store.add_rule(ApprovalRule(
        match_skill="file.*",
        decision="allow",
        expires_at="2020-01-01T00:00:00+00:00",  # already expired
    ))

    action = ProposedAction(
        action_type="skill_invoke:file.read",
        domain="core",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    match = await rule_store.find_matching(action)
    assert match is None


async def test_no_rules_returns_none(rule_store):
    action = ProposedAction(
        action_type="skill_invoke:file.read",
        domain="core",
        description="read file",
        risk_level=RiskLevel.LOW,
        skill_id="file.read",
    )
    match = await rule_store.find_matching(action)
    assert match is None
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_approval_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atlas.control.approval_rules'`

**Step 3: Write implementation**

Create `src/atlas/control/approval_rules.py`:

```python
"""Approval Rule Store — persistent standing and batch rules for auto-approval/denial."""

import fnmatch
import logging
from datetime import datetime, timezone

from atlas.contracts.types import ApprovalRule, ProposedAction, RiskLevel
from atlas.memory.store import DatabaseStore

logger = logging.getLogger(__name__)

# Risk levels ordered by severity for comparison
_RISK_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


class ApprovalRuleStore:
    """CRUD and matching for persistent approval rules."""

    def __init__(self, db: DatabaseStore) -> None:
        self._db = db

    async def add_rule(self, rule: ApprovalRule) -> str:
        """Insert a rule and return its rule_id."""
        await self._db.db.execute(
            """INSERT INTO approval_rules
               (rule_id, rule_type, match_skill, match_risk, match_path,
                decision, created_at, expires_at, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.rule_id,
                rule.rule_type,
                rule.match_skill,
                rule.match_risk,
                rule.match_path,
                rule.decision,
                rule.created_at,
                rule.expires_at,
                rule.description,
            ),
        )
        await self._db.db.commit()
        logger.info("Added approval rule: %s (%s %s → %s)",
                     rule.rule_id, rule.match_skill, rule.match_risk, rule.decision)
        return rule.rule_id

    async def remove_rule(self, rule_id: str) -> bool:
        """Delete a rule. Returns True if it existed."""
        cursor = await self._db.db.execute(
            "DELETE FROM approval_rules WHERE rule_id = ?", (rule_id,)
        )
        await self._db.db.commit()
        return cursor.rowcount > 0

    async def list_rules(self) -> list[ApprovalRule]:
        """Return all non-expired rules."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.db.execute(
            "SELECT rule_id, rule_type, match_skill, match_risk, match_path, "
            "decision, created_at, expires_at, description "
            "FROM approval_rules "
            "WHERE expires_at IS NULL OR expires_at > ?",
            (now,),
        )
        rows = await cursor.fetchall()
        return [
            ApprovalRule(
                rule_id=r[0], rule_type=r[1], match_skill=r[2], match_risk=r[3],
                match_path=r[4], decision=r[5], created_at=r[6], expires_at=r[7],
                description=r[8] or "",
            )
            for r in rows
        ]

    async def find_matching(self, action: ProposedAction) -> ApprovalRule | None:
        """Find the first rule that matches the action. Returns None if no match."""
        rules = await self.list_rules()
        for rule in rules:
            if self._matches(rule, action):
                return rule
        return None

    def _matches(self, rule: ApprovalRule, action: ProposedAction) -> bool:
        """Check if a rule matches an action."""
        skill_id = action.skill_id or ""

        # Match skill pattern (fnmatch glob)
        if rule.match_skill != "*" and not fnmatch.fnmatch(skill_id, rule.match_skill):
            return False

        # Match risk level (rule specifies max risk it covers)
        if rule.match_risk != "*":
            rule_max = _RISK_ORDER.get(rule.match_risk, -1)
            action_risk = _RISK_ORDER.get(action.risk_level.value, 99)
            if action_risk > rule_max:
                return False

        # Match path prefix if specified
        if rule.match_path:
            action_path = action.params.get("path", "")
            if not action_path.startswith(rule.match_path):
                return False

        return True
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_approval_rules.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/atlas/control/approval_rules.py tests/unit/control/test_approval_rules.py
git commit -m "feat: implement ApprovalRuleStore with glob matching and expiration"
```

---

### Task 8: Wire ApprovalRuleStore into ApprovalWorkflow

**Files:**
- Modify: `src/atlas/control/approval.py:1-50`
- Modify: `tests/unit/control/test_approval.py`

**Step 1: Write the failing test**

Add to `tests/unit/control/test_approval.py`:

```python
from unittest.mock import AsyncMock, MagicMock
from atlas.contracts.types import ApprovalRule


async def test_standing_rule_auto_approves(tmp_path):
    from atlas.memory.store import DatabaseStore
    from atlas.control.approval_rules import ApprovalRuleStore

    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    try:
        rule_store = ApprovalRuleStore(db)
        await rule_store.add_rule(ApprovalRule(match_skill="file.*", decision="allow"))

        workflow = ApprovalWorkflow(rule_store=rule_store)
        request = ApprovalRequest(
            action=ProposedAction(
                action_type="skill_invoke:file.read",
                domain="core",
                description="read file",
                risk_level=RiskLevel.LOW,
                skill_id="file.read",
            ),
        )
        result = await workflow.request_approval(request)
        assert result == ApprovalResult.APPROVED
    finally:
        await db.close()


async def test_standing_deny_rule_blocks(tmp_path):
    from atlas.memory.store import DatabaseStore
    from atlas.control.approval_rules import ApprovalRuleStore

    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    try:
        rule_store = ApprovalRuleStore(db)
        await rule_store.add_rule(ApprovalRule(match_skill="shell.*", decision="deny"))

        workflow = ApprovalWorkflow(rule_store=rule_store)
        request = ApprovalRequest(
            action=ProposedAction(
                action_type="skill_invoke:shell.execute",
                domain="core",
                description="run command",
                risk_level=RiskLevel.MEDIUM,
                skill_id="shell.execute",
            ),
        )
        result = await workflow.request_approval(request)
        assert result == ApprovalResult.DENIED
    finally:
        await db.close()
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_approval.py::test_standing_rule_auto_approves -v`
Expected: FAIL (TypeError — `rule_store` not an accepted param)

**Step 3: Modify ApprovalWorkflow**

In `src/atlas/control/approval.py`, replace the entire file:

```python
"""Approval Workflow — human-in-the-loop approval for actions requiring permission."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from atlas.contracts.types import ApprovalRequest, ApprovalResult

if TYPE_CHECKING:
    from atlas.control.approval_rules import ApprovalRuleStore

logger = logging.getLogger(__name__)


class ApprovalWorkflow:
    """Handles approval requests with optional standing rules."""

    def __init__(
        self,
        auto_approve: bool = False,
        auto_deny: bool = False,
        interactive: bool = True,
        rule_store: ApprovalRuleStore | None = None,
    ):
        self._auto_approve = auto_approve
        self._auto_deny = auto_deny
        self._interactive = interactive
        self._rule_store = rule_store

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        if self._auto_approve:
            return ApprovalResult.APPROVED
        if self._auto_deny:
            return ApprovalResult.DENIED

        # Check standing rules
        if self._rule_store and request.action:
            match = await self._rule_store.find_matching(request.action)
            if match:
                decision = ApprovalResult.APPROVED if match.decision == "allow" else ApprovalResult.DENIED
                logger.info("Standing rule %s matched: %s", match.rule_id, match.decision)
                return decision

        if not self._interactive:
            return ApprovalResult.DENIED

        return await self._prompt_terminal(request)

    async def request_batch_approval(
        self, requests: list[ApprovalRequest],
    ) -> list[ApprovalResult]:
        """Approve or deny a batch of requests together."""
        if self._auto_approve:
            return [ApprovalResult.APPROVED] * len(requests)
        if self._auto_deny:
            return [ApprovalResult.DENIED] * len(requests)

        # Check standing rules first — auto-resolve what we can
        results: list[ApprovalResult | None] = [None] * len(requests)
        pending_indices: list[int] = []

        if self._rule_store:
            for i, req in enumerate(requests):
                if req.action:
                    match = await self._rule_store.find_matching(req.action)
                    if match:
                        results[i] = ApprovalResult.APPROVED if match.decision == "allow" else ApprovalResult.DENIED
                        continue
                pending_indices.append(i)
        else:
            pending_indices = list(range(len(requests)))

        if not pending_indices:
            return results  # all resolved by rules

        if not self._interactive:
            for i in pending_indices:
                results[i] = ApprovalResult.DENIED
            return results

        # Present batch prompt for remaining
        print(f"\n[approval] {len(pending_indices)} actions pending:")
        for idx, i in enumerate(pending_indices, 1):
            req = requests[i]
            action = req.action
            desc = action.description if action else "Unknown"
            risk = action.risk_level.value if action else "unknown"
            skill = action.skill_id if action else "unknown"
            print(f"  {idx}. {skill} — {desc} ({risk.upper()} risk)")

        try:
            response = input("Approve all? (y/n/select): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            for i in pending_indices:
                results[i] = ApprovalResult.DENIED
            return results

        if response in ("y", "yes"):
            for i in pending_indices:
                results[i] = ApprovalResult.APPROVED
        elif response == "select":
            for i in pending_indices:
                results[i] = await self._prompt_terminal(requests[i])
        else:
            for i in pending_indices:
                results[i] = ApprovalResult.DENIED

        return results

    async def _prompt_terminal(self, request: ApprovalRequest) -> ApprovalResult:
        action = request.action
        print(f"\n[approval] {action.description if action else 'Unknown action'}")
        if request.reasoning:
            print(f"  Reason: {request.reasoning}")
        if action:
            print(f"  Risk: {action.risk_level.value}")
            if action.params:
                for k, v in action.params.items():
                    print(f"  {k}: {v}")

        try:
            response = input("  Approve? (y/n/always/never): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ApprovalResult.DENIED

        if response == "always" and self._rule_store and action:
            from atlas.contracts.types import ApprovalRule
            rule = ApprovalRule(
                match_skill=action.skill_id or "*",
                match_risk=action.risk_level.value,
                decision="allow",
                description=f"Standing allow for {action.skill_id}",
            )
            await self._rule_store.add_rule(rule)
            print(f"  [rule] Created standing ALLOW rule for {action.skill_id}")
            return ApprovalResult.APPROVED
        elif response == "never" and self._rule_store and action:
            from atlas.contracts.types import ApprovalRule
            rule = ApprovalRule(
                match_skill=action.skill_id or "*",
                match_risk=action.risk_level.value,
                decision="deny",
                description=f"Standing deny for {action.skill_id}",
            )
            await self._rule_store.add_rule(rule)
            print(f"  [rule] Created standing DENY rule for {action.skill_id}")
            return ApprovalResult.DENIED
        elif response in ("y", "yes"):
            return ApprovalResult.APPROVED
        return ApprovalResult.DENIED
```

**Step 4: Run all approval tests**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_approval.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass (existing tests don't pass rule_store, which defaults to None)

**Step 6: Commit**

```bash
git add src/atlas/control/approval.py tests/unit/control/test_approval.py
git commit -m "feat: wire ApprovalRuleStore into ApprovalWorkflow with standing rules and batch approval"
```

---

### Task 9: Add atlas rules CLI commands

**Files:**
- Modify: `src/atlas/cli.py`

**Step 1: Add rules command group**

In `src/atlas/cli.py`, add the rules command group after the vault commands (after line 685, before `if __name__`):

```python
# --- Rules commands ---

@main.group()
def rules():
    """Manage standing approval rules."""
    pass


@rules.command("list")
def rules_list():
    """List all standing approval rules."""
    asyncio.run(_rules_list())


async def _rules_list():
    from atlas.control.approval_rules import ApprovalRuleStore
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        store = ApprovalRuleStore(db)
        all_rules = await store.list_rules()
        if not all_rules:
            click.echo("[rules] No standing rules configured.")
            return
        for r in all_rules:
            expires = f" (expires {r.expires_at})" if r.expires_at else ""
            click.echo(f"  {r.rule_id[:8]}  {r.match_skill}  risk<={r.match_risk}  → {r.decision}{expires}")
            if r.description:
                click.echo(f"           {r.description}")
    finally:
        await db.close()


@rules.command("add")
@click.option("--skill", default="*", help="Skill pattern (glob), e.g. 'file.*'")
@click.option("--risk", default="*", type=click.Choice(["low", "medium", "high", "*"]),
              help="Maximum risk level to match")
@click.option("--decision", required=True, type=click.Choice(["allow", "deny"]))
@click.option("--description", default="", help="Human-readable description")
def rules_add(skill: str, risk: str, decision: str, description: str):
    """Add a standing approval rule."""
    asyncio.run(_rules_add(skill, risk, decision, description))


async def _rules_add(skill: str, risk: str, decision: str, description: str):
    from atlas.contracts.types import ApprovalRule
    from atlas.control.approval_rules import ApprovalRuleStore
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        store = ApprovalRuleStore(db)
        rule = ApprovalRule(match_skill=skill, match_risk=risk, decision=decision, description=description)
        rule_id = await store.add_rule(rule)
        click.echo(f"[rules] Created rule {rule_id[:8]}: {skill} risk<={risk} → {decision}")
    finally:
        await db.close()


@rules.command("remove")
@click.argument("rule_id")
def rules_remove(rule_id: str):
    """Remove a standing approval rule by ID (prefix match)."""
    asyncio.run(_rules_remove(rule_id))


async def _rules_remove(rule_id_prefix: str):
    from atlas.control.approval_rules import ApprovalRuleStore
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        store = ApprovalRuleStore(db)
        all_rules = await store.list_rules()
        # Support prefix matching for convenience
        matches = [r for r in all_rules if r.rule_id.startswith(rule_id_prefix)]
        if not matches:
            click.echo(f"[rules] No rule matching '{rule_id_prefix}'")
            return
        for r in matches:
            await store.remove_rule(r.rule_id)
            click.echo(f"[rules] Removed rule {r.rule_id[:8]}")
    finally:
        await db.close()
```

**Step 2: Verify CLI shows new commands**

Run: `source .venv/bin/activate && atlas rules --help`
Expected: Shows `list`, `add`, `remove`

**Step 3: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass

**Step 4: Commit**

```bash
git add src/atlas/cli.py
git commit -m "feat: add atlas rules list/add/remove CLI commands"
```

---

## Slice 3: Trust Recommendations

### Task 10: Add recommendation methods to TrustTracker

**Files:**
- Modify: `src/atlas/control/trust.py:1-169`
- Create: `tests/unit/control/test_trust_recommendations.py`

**Step 1: Write the failing tests**

Create `tests/unit/control/test_trust_recommendations.py`:

```python
import pytest
from atlas.contracts.types import AutonomyLevel, TrustRecommendation
from atlas.control.trust import TrustTracker
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def tracker(db):
    return TrustTracker(db=db, escalation_threshold=3, demotion_failure_count=2, demotion_window_size=5)


async def test_create_escalation_recommendation(tracker):
    # Record enough successes to warrant escalation
    for _ in range(5):
        await tracker.record_outcome("file.read", success=True)

    rec = await tracker.create_recommendation("file.read", "escalate", mission_id="m1")
    assert rec.skill_id == "file.read"
    assert rec.direction == "escalate"
    assert rec.status == "pending"
    assert rec.recommended_level == "SUGGEST"  # from None → SUGGEST
    assert rec.evidence["success_rate"] > 0
    assert rec.mission_id == "m1"


async def test_create_demotion_recommendation(tracker, db):
    # Set an override first
    await tracker.set_autonomy_override("shell.execute", AutonomyLevel.ACT_WITHIN_BOUNDS)
    await tracker.record_outcome("shell.execute", success=False)

    rec = await tracker.create_recommendation("shell.execute", "demote", mission_id="m1")
    assert rec.direction == "demote"
    assert rec.recommended_level == "SUGGEST"  # from ACT_WITHIN_BOUNDS → SUGGEST


async def test_list_recommendations_filters_by_status(tracker):
    await tracker.record_outcome("file.read", success=True)
    await tracker.create_recommendation("file.read", "escalate", mission_id="m1")

    pending = await tracker.list_recommendations(status="pending")
    assert len(pending) == 1

    dismissed = await tracker.list_recommendations(status="dismissed")
    assert len(dismissed) == 0


async def test_resolve_recommendation_accepted(tracker):
    await tracker.record_outcome("file.read", success=True)
    rec = await tracker.create_recommendation("file.read", "escalate", mission_id="m1")

    await tracker.resolve_recommendation(rec.recommendation_id, accepted=True)

    # Recommendation should be accepted
    pending = await tracker.list_recommendations(status="pending")
    assert len(pending) == 0

    accepted = await tracker.list_recommendations(status="accepted")
    assert len(accepted) == 1

    # Autonomy override should be applied
    override = await tracker.get_autonomy_override("file.read")
    assert override == AutonomyLevel.SUGGEST


async def test_resolve_recommendation_dismissed(tracker):
    await tracker.record_outcome("file.read", success=True)
    rec = await tracker.create_recommendation("file.read", "escalate", mission_id="m1")

    await tracker.resolve_recommendation(rec.recommendation_id, accepted=False)

    dismissed = await tracker.list_recommendations(status="dismissed")
    assert len(dismissed) == 1

    # No autonomy override should be applied
    override = await tracker.get_autonomy_override("file.read")
    assert override is None
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_trust_recommendations.py -v`
Expected: FAIL (AttributeError — `TrustTracker` has no `create_recommendation`)

**Step 3: Add recommendation methods to TrustTracker**

In `src/atlas/control/trust.py`, add the import at the top (after line 6):

```python
from atlas.contracts.types import AutonomyLevel, ExecutionContext, TrustRecord, TrustRecommendation
```

(Update the existing import line to include `TrustRecommendation`.)

Add these methods to the `TrustTracker` class, after `_save_record` (after line 169):

```python
    # --- Escalation levels ---
    _ESCALATION_ORDER = [AutonomyLevel.OBSERVE, AutonomyLevel.SUGGEST, AutonomyLevel.ACT_WITHIN_BOUNDS]

    def _next_level(self, current: AutonomyLevel | None, direction: str) -> str:
        """Compute the next autonomy level name given direction."""
        order = self._ESCALATION_ORDER
        if current is None:
            idx = -1  # treat None as below OBSERVE
        else:
            idx = order.index(current) if current in order else -1

        if direction == "escalate":
            next_idx = min(idx + 1, len(order) - 1)
        else:  # demote
            next_idx = max(idx - 1, 0)

        return order[next_idx].name

    async def create_recommendation(
        self, skill_id: str, direction: str, mission_id: str | None = None,
    ) -> TrustRecommendation:
        """Create and persist a trust recommendation."""
        record = await self.get_record(skill_id)
        total = record.total_invocations or 1
        success_rate = round(record.successes / total, 3)

        current_name = record.autonomy_override.name if record.autonomy_override else "NONE"
        recommended_name = self._next_level(record.autonomy_override, direction)

        evidence = {
            "success_rate": success_rate,
            "sample_size": record.total_invocations,
            "consecutive_successes": record.consecutive_successes,
            "failures": record.failures,
        }

        rec = TrustRecommendation(
            skill_id=skill_id,
            current_level=current_name,
            recommended_level=recommended_name,
            direction=direction,
            evidence=evidence,
            mission_id=mission_id,
        )

        await self._db.db.execute(
            """INSERT INTO trust_recommendations
               (recommendation_id, skill_id, current_level, recommended_level,
                direction, evidence, status, mission_id, created_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.recommendation_id,
                rec.skill_id,
                rec.current_level,
                rec.recommended_level,
                rec.direction,
                json.dumps(rec.evidence),
                rec.status,
                rec.mission_id,
                rec.created_at,
                rec.resolved_at,
            ),
        )
        await self._db.db.commit()
        logger.info("Created trust recommendation: %s %s %s → %s",
                     rec.recommendation_id[:8], direction, skill_id, recommended_name)
        return rec

    async def list_recommendations(self, status: str = "pending") -> list[TrustRecommendation]:
        """List recommendations filtered by status."""
        cursor = await self._db.db.execute(
            "SELECT recommendation_id, skill_id, current_level, recommended_level, "
            "direction, evidence, status, mission_id, created_at, resolved_at "
            "FROM trust_recommendations WHERE status = ? ORDER BY created_at DESC",
            (status,),
        )
        rows = await cursor.fetchall()
        return [
            TrustRecommendation(
                recommendation_id=r[0], skill_id=r[1], current_level=r[2],
                recommended_level=r[3], direction=r[4], evidence=json.loads(r[5]),
                status=r[6], mission_id=r[7], created_at=r[8], resolved_at=r[9],
            )
            for r in rows
        ]

    async def resolve_recommendation(self, recommendation_id: str, accepted: bool) -> None:
        """Accept or dismiss a recommendation. If accepted, apply the autonomy override."""
        new_status = "accepted" if accepted else "dismissed"
        now = datetime.now(timezone.utc).isoformat()

        await self._db.db.execute(
            "UPDATE trust_recommendations SET status = ?, resolved_at = ? "
            "WHERE recommendation_id = ?",
            (new_status, now, recommendation_id),
        )
        await self._db.db.commit()

        if accepted:
            # Look up the recommendation to apply the override
            cursor = await self._db.db.execute(
                "SELECT skill_id, recommended_level FROM trust_recommendations "
                "WHERE recommendation_id = ?",
                (recommendation_id,),
            )
            row = await cursor.fetchone()
            if row:
                skill_id, level_name = row
                level = AutonomyLevel[level_name]
                await self.set_autonomy_override(skill_id, level)
                logger.info("Applied trust recommendation: %s → %s", skill_id, level_name)
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_trust_recommendations.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/atlas/control/trust.py tests/unit/control/test_trust_recommendations.py
git commit -m "feat: add trust recommendation create/list/resolve to TrustTracker"
```

---

### Task 11: Collect trust signals in ExecutionLoop and surface post-mission

**Files:**
- Modify: `src/atlas/core/loop.py:54-92,278-306`
- Modify: `src/atlas/cli.py:230-288`

**Step 1: Modify ExecutionLoop to collect trust signals**

In `src/atlas/core/loop.py`:

Add `trust_tracker` to `__init__` params (after `emergency_controller`):
```python
        trust_tracker=None,
```

Store it:
```python
        self._trust_tracker = trust_tracker
```

In `execute_mission`, after the task loop completes but before recording the episode (before line 203), add trust signal collection:

```python
        # Collect trust recommendations from signals gathered during execution
        trust_recommendations = []
        if self._trust_tracker and hasattr(self, '_trust_signals'):
            for signal in self._trust_signals:
                direction = "escalate" if signal.should_escalate else "demote"
                try:
                    rec = await self._trust_tracker.create_recommendation(
                        signal.skill_id, direction, mission_id=mission.mission_id,
                    )
                    trust_recommendations.append(rec)
                except Exception as e:
                    logger.warning("Failed to create trust recommendation: %s", e)
            self._trust_signals = []
```

In `_execute_task`, after the skill result check (after the `if result.status == "success"` block around line 282-291), add trust outcome recording:

```python
        # Record trust outcome
        if self._trust_tracker:
            try:
                from atlas.control.trust import TrustOutcome
                outcome = await self._trust_tracker.record_outcome(
                    task.skill_id, success=(result.status == "success"), ctx=ctx,
                )
                if outcome.should_escalate or outcome.should_demote:
                    if not hasattr(self, '_trust_signals'):
                        self._trust_signals = []
                    self._trust_signals.append(outcome)
            except Exception as e:
                logger.warning("Trust tracking failed: %s", e)
```

Change `execute_mission` return to include recommendations. After recording the episode, add:

```python
        mission.trust_recommendations = trust_recommendations
```

Note: This requires adding a `trust_recommendations` attribute to Mission. In `src/atlas/core/missions.py`, add to the Mission class:

```python
    trust_recommendations: list = field(default_factory=list)
```

**Step 2: Add post-mission trust summary to CLI**

In `src/atlas/cli.py`, after the mission result report (after line 286 `click.echo(f"  - {t.description}: {t.error}", err=True)`), add:

```python
        # Trust recommendations
        if hasattr(result, 'trust_recommendations') and result.trust_recommendations:
            click.echo("\nTrust recommendations based on this mission:")
            for idx, rec in enumerate(result.trust_recommendations, 1):
                evidence = rec.evidence
                if rec.direction == "escalate":
                    detail = f"{evidence.get('consecutive_successes', '?')} consecutive successes"
                else:
                    detail = f"{evidence.get('failures', '?')} failures"
                click.echo(f"  {idx}. {rec.skill_id} — {rec.direction} to {rec.recommended_level} ({detail})")

            try:
                response = input("Accept recommendations? (y/n/select): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                response = "n"

            if response in ("y", "yes"):
                from atlas.control.trust import TrustTracker
                trust = TrustTracker(db=db, **{
                    k: getattr(config.trust, k)
                    for k in ("escalation_threshold", "demotion_failure_count", "demotion_window_size")
                })
                for rec in result.trust_recommendations:
                    await trust.resolve_recommendation(rec.recommendation_id, accepted=True)
                click.echo("[trust] All recommendations accepted.")
            elif response == "select":
                from atlas.control.trust import TrustTracker
                trust = TrustTracker(db=db, **{
                    k: getattr(config.trust, k)
                    for k in ("escalation_threshold", "demotion_failure_count", "demotion_window_size")
                })
                for rec in result.trust_recommendations:
                    try:
                        choice = input(f"  {rec.skill_id} → {rec.recommended_level}? (y/n): ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        choice = "n"
                    await trust.resolve_recommendation(rec.recommendation_id, accepted=(choice in ("y", "yes")))
                click.echo("[trust] Recommendations resolved.")
            else:
                click.echo("[trust] Recommendations saved for later review.")
```

**Step 3: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass (existing tests don't pass trust_tracker, defaults to None)

**Step 4: Commit**

```bash
git add src/atlas/core/loop.py src/atlas/core/missions.py src/atlas/cli.py
git commit -m "feat: collect trust signals in ExecutionLoop and show post-mission summary"
```

---

### Task 12: Add atlas trust CLI commands

**Files:**
- Modify: `src/atlas/cli.py`

**Step 1: Add trust command group**

In `src/atlas/cli.py`, add after the rules commands (before `if __name__`):

```python
# --- Trust commands ---

@main.group()
def trust():
    """Manage skill trust and autonomy recommendations."""
    pass


@trust.command("recommendations")
def trust_recommendations():
    """List pending trust recommendations."""
    asyncio.run(_trust_recommendations())


async def _trust_recommendations():
    from atlas.control.trust import TrustTracker
    data_dir = _ensure_data_dir()
    config = _load_config()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        tracker = TrustTracker(
            db=db,
            escalation_threshold=config.trust.escalation_threshold,
            demotion_failure_count=config.trust.demotion_failure_count,
            demotion_window_size=config.trust.demotion_window_size,
        )
        recs = await tracker.list_recommendations(status="pending")
        if not recs:
            click.echo("[trust] No pending recommendations.")
            return
        for r in recs:
            click.echo(f"  {r.recommendation_id[:8]}  {r.skill_id}  {r.direction} → {r.recommended_level}")
            click.echo(f"           evidence: {r.evidence}")
    finally:
        await db.close()


@trust.command("accept")
@click.argument("recommendation_id")
def trust_accept(recommendation_id: str):
    """Accept a trust recommendation (prefix match)."""
    asyncio.run(_trust_resolve(recommendation_id, accepted=True))


@trust.command("dismiss")
@click.argument("recommendation_id")
def trust_dismiss(recommendation_id: str):
    """Dismiss a trust recommendation (prefix match)."""
    asyncio.run(_trust_resolve(recommendation_id, accepted=False))


async def _trust_resolve(rec_id_prefix: str, accepted: bool):
    from atlas.control.trust import TrustTracker
    data_dir = _ensure_data_dir()
    config = _load_config()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        tracker = TrustTracker(
            db=db,
            escalation_threshold=config.trust.escalation_threshold,
            demotion_failure_count=config.trust.demotion_failure_count,
            demotion_window_size=config.trust.demotion_window_size,
        )
        recs = await tracker.list_recommendations(status="pending")
        matches = [r for r in recs if r.recommendation_id.startswith(rec_id_prefix)]
        if not matches:
            click.echo(f"[trust] No pending recommendation matching '{rec_id_prefix}'")
            return
        for r in matches:
            await tracker.resolve_recommendation(r.recommendation_id, accepted=accepted)
            action = "Accepted" if accepted else "Dismissed"
            click.echo(f"[trust] {action}: {r.skill_id} {r.direction} → {r.recommended_level}")
    finally:
        await db.close()


@trust.command("status")
def trust_status():
    """Show trust records for all tracked skills."""
    asyncio.run(_trust_status())


async def _trust_status():
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        cursor = await db.db.execute(
            "SELECT skill_id, successes, failures, total_invocations, "
            "autonomy_override, consecutive_successes "
            "FROM trust_records ORDER BY skill_id"
        )
        rows = await cursor.fetchall()
        if not rows:
            click.echo("[trust] No trust records.")
            return
        for r in rows:
            override = f" (override: {AutonomyLevel(int(r[4])).name})" if r[4] is not None else ""
            rate = round(r[1] / r[3] * 100, 1) if r[3] > 0 else 0
            click.echo(f"  {r[0]}  {r[1]}✓ {r[2]}✗ ({rate}% success, {r[3]} total){override}")
    finally:
        await db.close()
```

**Step 2: Verify CLI shows new commands**

Run: `source .venv/bin/activate && atlas trust --help`
Expected: Shows `recommendations`, `accept`, `dismiss`, `status`

**Step 3: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass

**Step 4: Commit**

```bash
git add src/atlas/cli.py
git commit -m "feat: add atlas trust recommendations/accept/dismiss/status CLI commands"
```

---

## Slice 4: Full Dashboard API

### Task 13: Refactor DashboardServer to DashboardContext and add all endpoints

**Files:**
- Modify: `src/atlas/integrations/dashboard.py:1-113`
- Modify: `tests/unit/integrations/test_dashboard.py:1-138`

**Step 1: Write failing tests for new endpoints**

Add to `tests/unit/integrations/test_dashboard.py`:

```python
from atlas.control.emergency import EmergencyController
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.control.trust import TrustTracker
from atlas.contracts.types import ApprovalRule


@pytest.fixture
async def full_dashboard(db, audit, registry, received_goals):
    from atlas.config import load_config
    config = load_config()

    async def goal_handler(goal_text: str) -> dict:
        received_goals.append(goal_text)
        return {"status": "accepted"}

    emergency = EmergencyController()
    rule_store = ApprovalRuleStore(db)
    trust_tracker = TrustTracker(
        db=db, escalation_threshold=10,
        demotion_failure_count=3, demotion_window_size=5,
    )

    server = DashboardServer(
        db=db, audit=audit, registry=registry,
        goal_handler=goal_handler,
        config=config,
        emergency_controller=emergency,
        approval_rule_store=rule_store,
        trust_tracker=trust_tracker,
    )
    return server, emergency, rule_store, trust_tracker


async def test_health_endpoint(full_dashboard, aiohttp_client):
    server, _, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/health")
    assert resp.status == 200
    data = await resp.json()
    assert "database" in data


async def test_tasks_endpoint(full_dashboard, aiohttp_client):
    server, _, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/tasks")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)


async def test_emergency_pause_endpoint(full_dashboard, aiohttp_client):
    server, emergency, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.post("/api/emergency/pause")
    assert resp.status == 200
    assert emergency.is_paused is True


async def test_emergency_resume_endpoint(full_dashboard, aiohttp_client):
    server, emergency, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    await client.post("/api/emergency/pause")
    resp = await client.post("/api/emergency/resume")
    assert resp.status == 200
    assert emergency.is_paused is False


async def test_approval_rules_endpoint(full_dashboard, aiohttp_client):
    server, _, rule_store, _ = full_dashboard
    await rule_store.add_rule(ApprovalRule(match_skill="file.*", decision="allow"))

    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/approvals/rules")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1


async def test_trust_records_endpoint(full_dashboard, aiohttp_client):
    server, _, _, trust = full_dashboard
    await trust.record_outcome("file.read", success=True)

    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/trust/records")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) >= 1


async def test_config_endpoint(full_dashboard, aiohttp_client):
    server, _, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/config")
    assert resp.status == 200
    data = await resp.json()
    assert "autonomy_level" in data


async def test_connectors_endpoint(full_dashboard, aiohttp_client):
    server, _, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/api/connectors")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/integrations/test_dashboard.py::test_health_endpoint -v`
Expected: FAIL (TypeError — new params not accepted)

**Step 3: Rewrite DashboardServer**

Replace `src/atlas/integrations/dashboard.py` entirely:

```python
"""Dashboard API — HTTP REST endpoints for monitoring and control."""
import json
import logging
import time
from typing import Any, Callable, Coroutine

from aiohttp import web

from atlas.config import AtlasConfig
from atlas.control.audit import AuditLogger
from atlas.control.emergency import EmergencyController
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.control.trust import TrustTracker
from atlas.memory.store import DatabaseStore
from atlas.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

GoalHandler = Callable[[str], Coroutine[Any, Any, dict]]


class DashboardServer:
    """REST API for monitoring and controlling ATLAS state."""

    def __init__(
        self,
        db: DatabaseStore,
        audit: AuditLogger,
        registry: SkillRegistry,
        goal_handler: GoalHandler | None = None,
        config: AtlasConfig | None = None,
        emergency_controller: EmergencyController | None = None,
        approval_rule_store: ApprovalRuleStore | None = None,
        trust_tracker: TrustTracker | None = None,
    ):
        self._db = db
        self._audit = audit
        self._registry = registry
        self._goal_handler = goal_handler
        self._config = config
        self._emergency = emergency_controller
        self._rule_store = approval_rule_store
        self._trust = trust_tracker
        self._start_time = time.monotonic()

    def create_app(self) -> web.Application:
        app = web.Application()
        # Existing
        app.router.add_get("/api/status", self._handle_status)
        app.router.add_get("/api/missions", self._handle_missions)
        app.router.add_get("/api/skills", self._handle_skills)
        app.router.add_get("/api/memory/stats", self._handle_memory_stats)
        app.router.add_get("/api/audit", self._handle_audit)
        app.router.add_post("/api/goal", self._handle_goal)
        # Slice 1: Emergency
        app.router.add_post("/api/emergency/pause", self._handle_pause)
        app.router.add_post("/api/emergency/resume", self._handle_resume)
        app.router.add_post("/api/emergency/kill", self._handle_kill)
        # Slice 2: Approval rules
        app.router.add_get("/api/approvals/rules", self._handle_list_rules)
        app.router.add_post("/api/approvals/rules", self._handle_add_rule)
        app.router.add_delete("/api/approvals/rules/{rule_id}", self._handle_remove_rule)
        # Slice 3: Trust
        app.router.add_get("/api/trust/recommendations", self._handle_trust_recommendations)
        app.router.add_post("/api/trust/recommendations/{id}/accept", self._handle_trust_accept)
        app.router.add_post("/api/trust/recommendations/{id}/dismiss", self._handle_trust_dismiss)
        app.router.add_get("/api/trust/records", self._handle_trust_records)
        # Slice 4: Remaining
        app.router.add_get("/api/tasks", self._handle_tasks)
        app.router.add_get("/api/health", self._handle_health)
        app.router.add_get("/api/config", self._handle_config)
        app.router.add_get("/api/connectors", self._handle_connectors)
        return app

    # --- Existing endpoints ---

    async def _handle_status(self, request: web.Request) -> web.Response:
        uptime = time.monotonic() - self._start_time
        payload = {
            "status": "running",
            "uptime_seconds": round(uptime, 1),
            "paused": self._emergency.is_paused if self._emergency else False,
            "active_task_id": self._emergency.active_task_id if self._emergency else None,
        }
        if self._rule_store:
            rules = await self._rule_store.list_rules()
            payload["standing_rules_count"] = len(rules)
        return web.json_response(payload)

    async def _handle_missions(self, request: web.Request) -> web.Response:
        cursor = await self._db.db.execute(
            "SELECT mission_id, goal_text, status, created_at, updated_at "
            "FROM missions ORDER BY created_at DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
        missions = [
            {
                "mission_id": r[0], "goal_text": r[1], "status": r[2],
                "created_at": r[3], "updated_at": r[4],
            }
            for r in rows
        ]
        return web.json_response(missions)

    async def _handle_skills(self, request: web.Request) -> web.Response:
        skills = self._registry.list_all()
        data = [
            {
                "skill_id": s.skill_id, "name": s.name, "description": s.description,
                "risk_level": s.risk_level.value, "tags": s.tags,
            }
            for s in skills
        ]
        return web.json_response(data)

    async def _handle_memory_stats(self, request: web.Request) -> web.Response:
        episode_cursor = await self._db.db.execute("SELECT COUNT(*) FROM episodes")
        episode_count = (await episode_cursor.fetchone())[0]
        mission_cursor = await self._db.db.execute("SELECT COUNT(*) FROM missions")
        mission_count = (await mission_cursor.fetchone())[0]
        embedding_cursor = await self._db.db.execute("SELECT COUNT(*) FROM episode_embeddings")
        embedding_count = (await embedding_cursor.fetchone())[0]
        return web.json_response({
            "episode_count": episode_count,
            "mission_count": mission_count,
            "embedding_count": embedding_count,
        })

    async def _handle_audit(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        entries = await self._audit.query(limit=limit)
        return web.json_response(entries)

    async def _handle_goal(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"status": "error", "message": "invalid JSON"}, status=400)
        goal_text = body.get("goal_text")
        if not goal_text:
            return web.json_response({"status": "error", "message": "goal_text is required"}, status=400)
        if not self._goal_handler:
            return web.json_response({"status": "error", "message": "no goal handler configured"}, status=500)
        result = await self._goal_handler(goal_text)
        return web.json_response(result)

    # --- Slice 1: Emergency endpoints ---

    async def _handle_pause(self, request: web.Request) -> web.Response:
        if not self._emergency:
            return web.json_response({"error": "emergency controls not configured"}, status=501)
        self._emergency.pause()
        return web.json_response({"status": "paused"})

    async def _handle_resume(self, request: web.Request) -> web.Response:
        if not self._emergency:
            return web.json_response({"error": "emergency controls not configured"}, status=501)
        self._emergency.resume()
        return web.json_response({"status": "resumed"})

    async def _handle_kill(self, request: web.Request) -> web.Response:
        if not self._emergency:
            return web.json_response({"error": "emergency controls not configured"}, status=501)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        task_id = body.get("task_id", "")
        killed = self._emergency.kill_task(task_id)
        return web.json_response({"killed": killed})

    # --- Slice 2: Approval rule endpoints ---

    async def _handle_list_rules(self, request: web.Request) -> web.Response:
        if not self._rule_store:
            return web.json_response({"error": "approval rules not configured"}, status=501)
        rules = await self._rule_store.list_rules()
        data = [
            {
                "rule_id": r.rule_id, "rule_type": r.rule_type,
                "match_skill": r.match_skill, "match_risk": r.match_risk,
                "match_path": r.match_path, "decision": r.decision,
                "created_at": r.created_at, "expires_at": r.expires_at,
                "description": r.description,
            }
            for r in rules
        ]
        return web.json_response(data)

    async def _handle_add_rule(self, request: web.Request) -> web.Response:
        if not self._rule_store:
            return web.json_response({"error": "approval rules not configured"}, status=501)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        from atlas.contracts.types import ApprovalRule
        rule = ApprovalRule(
            match_skill=body.get("match_skill", "*"),
            match_risk=body.get("match_risk", "*"),
            match_path=body.get("match_path"),
            decision=body.get("decision", "allow"),
            description=body.get("description", ""),
        )
        rule_id = await self._rule_store.add_rule(rule)
        return web.json_response({"rule_id": rule_id})

    async def _handle_remove_rule(self, request: web.Request) -> web.Response:
        if not self._rule_store:
            return web.json_response({"error": "approval rules not configured"}, status=501)
        rule_id = request.match_info["rule_id"]
        removed = await self._rule_store.remove_rule(rule_id)
        if not removed:
            return web.json_response({"error": "rule not found"}, status=404)
        return web.json_response({"status": "removed"})

    # --- Slice 3: Trust endpoints ---

    async def _handle_trust_recommendations(self, request: web.Request) -> web.Response:
        if not self._trust:
            return web.json_response({"error": "trust tracker not configured"}, status=501)
        status_filter = request.query.get("status", "pending")
        recs = await self._trust.list_recommendations(status=status_filter)
        data = [
            {
                "recommendation_id": r.recommendation_id, "skill_id": r.skill_id,
                "current_level": r.current_level, "recommended_level": r.recommended_level,
                "direction": r.direction, "evidence": r.evidence,
                "status": r.status, "mission_id": r.mission_id,
                "created_at": r.created_at, "resolved_at": r.resolved_at,
            }
            for r in recs
        ]
        return web.json_response(data)

    async def _handle_trust_accept(self, request: web.Request) -> web.Response:
        if not self._trust:
            return web.json_response({"error": "trust tracker not configured"}, status=501)
        rec_id = request.match_info["id"]
        await self._trust.resolve_recommendation(rec_id, accepted=True)
        return web.json_response({"status": "accepted"})

    async def _handle_trust_dismiss(self, request: web.Request) -> web.Response:
        if not self._trust:
            return web.json_response({"error": "trust tracker not configured"}, status=501)
        rec_id = request.match_info["id"]
        await self._trust.resolve_recommendation(rec_id, accepted=False)
        return web.json_response({"status": "dismissed"})

    async def _handle_trust_records(self, request: web.Request) -> web.Response:
        cursor = await self._db.db.execute(
            "SELECT skill_id, successes, failures, consecutive_successes, "
            "total_invocations, autonomy_override, last_outcome, updated_at "
            "FROM trust_records ORDER BY skill_id"
        )
        rows = await cursor.fetchall()
        data = [
            {
                "skill_id": r[0], "successes": r[1], "failures": r[2],
                "consecutive_successes": r[3], "total_invocations": r[4],
                "autonomy_override": r[5], "last_outcome": r[6], "updated_at": r[7],
            }
            for r in rows
        ]
        return web.json_response(data)

    # --- Slice 4: Remaining endpoints ---

    async def _handle_tasks(self, request: web.Request) -> web.Response:
        mission_id = request.query.get("mission_id")
        if mission_id:
            cursor = await self._db.db.execute(
                "SELECT task_id, mission_id, description, skill_id, status, result "
                "FROM tasks WHERE mission_id = ? ORDER BY created_at",
                (mission_id,),
            )
        else:
            cursor = await self._db.db.execute(
                "SELECT task_id, mission_id, description, skill_id, status, result "
                "FROM tasks ORDER BY created_at DESC LIMIT 50"
            )
        rows = await cursor.fetchall()
        data = [
            {
                "task_id": r[0], "mission_id": r[1], "description": r[2],
                "skill_id": r[3], "status": r[4], "result": r[5],
            }
            for r in rows
        ]
        return web.json_response(data)

    async def _handle_health(self, request: web.Request) -> web.Response:
        health = {}
        # Database
        try:
            await self._db.db.execute("SELECT 1")
            health["database"] = "ok"
        except Exception as e:
            health["database"] = f"error: {e}"
        # Skill registry
        try:
            count = len(self._registry.list_all())
            health["skill_registry"] = f"ok ({count} skills)"
        except Exception as e:
            health["skill_registry"] = f"error: {e}"
        # Memory
        try:
            cursor = await self._db.db.execute("SELECT COUNT(*) FROM episodes")
            count = (await cursor.fetchone())[0]
            health["memory"] = f"ok ({count} episodes)"
        except Exception as e:
            health["memory"] = f"error: {e}"
        # Emergency
        if self._emergency:
            health["emergency"] = "paused" if self._emergency.is_paused else "ok"
        else:
            health["emergency"] = "not_configured"
        return web.json_response(health)

    async def _handle_config(self, request: web.Request) -> web.Response:
        if not self._config:
            return web.json_response({"error": "config not available"}, status=501)
        # Return non-sensitive config
        data = {
            "autonomy_level": self._config.control.autonomy_level,
            "log_level": self._config.log_level,
            "episode_retention_days": self._config.memory.episode_retention_days,
            "context_token_budget": self._config.memory.context_token_budget,
            "vector_search_enabled": self._config.memory.vector_search.enabled,
            "forge_enabled": self._config.skills.forge_enabled,
            "seed_skills": self._config.skills.seed_skills,
            "trust_escalation_threshold": self._config.trust.escalation_threshold,
            "trust_demotion_failure_count": self._config.trust.demotion_failure_count,
            "observation_watches": self._config.observation.watches,
            "reactive_enabled": self._config.reactive.enabled,
            "mcp_enabled": self._config.mcp.enabled,
            "webhook_enabled": self._config.webhook.enabled,
        }
        return web.json_response(data)

    async def _handle_connectors(self, request: web.Request) -> web.Response:
        connectors = []
        if self._config and self._config.github.token:
            connectors.append({
                "name": "github",
                "status": "configured",
                "owner": self._config.github.owner,
                "repo": self._config.github.repo,
            })
        return web.json_response(connectors)
```

**Step 4: Update existing dashboard tests to work with new constructor**

The existing tests pass only `db`, `audit`, `registry`, and `goal_handler` — these still work because the new params default to `None`. Verify:

Run: `source .venv/bin/activate && pytest tests/unit/integrations/test_dashboard.py -v`
Expected: ALL PASS (existing + new)

**Step 5: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass

**Step 6: Run linter**

Run: `source .venv/bin/activate && ruff check src/ tests/`
Expected: No errors

**Step 7: Commit**

```bash
git add src/atlas/integrations/dashboard.py tests/unit/integrations/test_dashboard.py
git commit -m "feat: complete dashboard API with 20 endpoints — emergency, approval, trust, health, config"
```

---

### Task 14: Wire everything into cli.py daemon startup

**Files:**
- Modify: `src/atlas/cli.py:328-515`

**Step 1: Update _run_daemon to create and wire all new components**

In `src/atlas/cli.py`, in the `_run_daemon` function:

Add imports at top of file (after line 37):
```python
from atlas.control.emergency import EmergencyController
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.control.trust import TrustTracker
```

After creating the execution loop (after line 420), add:
```python
    # Initialize control plane completion components
    emergency = EmergencyController()
    rule_store = ApprovalRuleStore(db)
    trust_tracker = TrustTracker(
        db=db,
        escalation_threshold=config.trust.escalation_threshold,
        demotion_failure_count=config.trust.demotion_failure_count,
        demotion_window_size=config.trust.demotion_window_size,
    )
```

Pass `emergency_controller` and `trust_tracker` to `ExecutionLoop`:
```python
    execution_loop = ExecutionLoop(
        ...,
        emergency_controller=emergency,
        trust_tracker=trust_tracker,
    )
```

Update the DashboardServer construction (around line 489) to pass all new components:
```python
            dashboard_server = DashboardServer(
                db=db,
                audit=audit,
                registry=registry,
                goal_handler=goal_executor,
                config=config,
                emergency_controller=emergency,
                approval_rule_store=rule_store,
                trust_tracker=trust_tracker,
            )
```

Also pass `emergency` to the DaemonLoop or expose it. Since DaemonLoop now creates its own EmergencyController, we need to share the same instance. Update DaemonLoop's `__init__` to accept an optional `emergency_controller`:

In `src/atlas/daemon/loop.py`, modify `__init__` to accept:
```python
        emergency_controller: EmergencyController | None = None,
```

And use it if provided:
```python
        self._emergency = emergency_controller or EmergencyController()
```

Then in `cli.py`, pass it:
```python
    daemon_loop = DaemonLoop(
        ...,
        emergency_controller=emergency,
    )
```

Also wire `rule_store` into the `ApprovalWorkflow` in daemon mode (update line 350):
```python
    approval = ApprovalWorkflow(auto_approve=True, rule_store=rule_store)
```

And for the inline `_run_goal` path (line 157), wire rule_store too:
```python
    rule_store = ApprovalRuleStore(db)
    approval = ApprovalWorkflow(auto_approve=auto_approve, rule_store=rule_store)
```

And wire trust_tracker into inline execution loop:
```python
    trust_tracker = TrustTracker(
        db=db,
        escalation_threshold=config.trust.escalation_threshold,
        demotion_failure_count=config.trust.demotion_failure_count,
        demotion_window_size=config.trust.demotion_window_size,
    )
    loop = ExecutionLoop(
        ...,
        emergency_controller=EmergencyController(),
        trust_tracker=trust_tracker,
    )
```

**Step 2: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass

**Step 3: Run linter**

Run: `source .venv/bin/activate && ruff check src/ tests/`
Expected: No errors

**Step 4: Commit**

```bash
git add src/atlas/cli.py src/atlas/daemon/loop.py
git commit -m "feat: wire EmergencyController, ApprovalRuleStore, TrustTracker into daemon and CLI startup"
```

---

### Task 15: Integration test — full control plane flow

**Files:**
- Create: `tests/integration/test_control_plane_completion.py`

**Step 1: Write integration test**

Create `tests/integration/test_control_plane_completion.py`:

```python
"""Integration test: control plane completion — emergency, rules, trust recommendations."""
import pytest
from atlas.contracts.types import (
    ApprovalRule, ApprovalRequest, ApprovalResult,
    AutonomyLevel, ProposedAction, RiskLevel,
)
from atlas.control.approval import ApprovalWorkflow
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.control.emergency import EmergencyController
from atlas.control.trust import TrustTracker
from atlas.memory.store import DatabaseStore


@pytest.fixture
async def db(tmp_path):
    store = DatabaseStore(str(tmp_path / "test.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_standing_rule_integrates_with_approval_workflow(db):
    """Standing rule auto-approves without terminal prompt."""
    rule_store = ApprovalRuleStore(db)
    await rule_store.add_rule(ApprovalRule(
        match_skill="file.*", match_risk="low", decision="allow",
    ))

    workflow = ApprovalWorkflow(interactive=False, rule_store=rule_store)
    request = ApprovalRequest(
        action=ProposedAction(
            action_type="skill_invoke:file.read",
            domain="core",
            description="read a file",
            risk_level=RiskLevel.LOW,
            skill_id="file.read",
        ),
    )
    result = await workflow.request_approval(request)
    assert result == ApprovalResult.APPROVED


async def test_standing_rule_deny_blocks_even_in_non_interactive(db):
    """A deny rule takes precedence even without interactive mode."""
    rule_store = ApprovalRuleStore(db)
    await rule_store.add_rule(ApprovalRule(
        match_skill="shell.*", decision="deny",
    ))

    workflow = ApprovalWorkflow(interactive=False, rule_store=rule_store)
    request = ApprovalRequest(
        action=ProposedAction(
            action_type="skill_invoke:shell.execute",
            domain="core",
            description="run dangerous command",
            risk_level=RiskLevel.HIGH,
            skill_id="shell.execute",
        ),
    )
    result = await workflow.request_approval(request)
    assert result == ApprovalResult.DENIED


async def test_trust_recommendation_full_lifecycle(db):
    """Create, list, and resolve a trust recommendation."""
    tracker = TrustTracker(
        db=db, escalation_threshold=3,
        demotion_failure_count=2, demotion_window_size=5,
    )

    # Build up trust
    for _ in range(5):
        await tracker.record_outcome("file.read", success=True)

    # Create recommendation
    rec = await tracker.create_recommendation("file.read", "escalate", mission_id="m1")
    assert rec.status == "pending"

    # Verify it's listed
    pending = await tracker.list_recommendations(status="pending")
    assert len(pending) == 1

    # Accept it
    await tracker.resolve_recommendation(rec.recommendation_id, accepted=True)

    # Verify override was applied
    override = await tracker.get_autonomy_override("file.read")
    assert override == AutonomyLevel.SUGGEST

    # Verify no more pending
    pending = await tracker.list_recommendations(status="pending")
    assert len(pending) == 0


async def test_emergency_controller_state_management():
    """Emergency controller pause/resume/kill flow."""
    ec = EmergencyController()

    assert not ec.is_paused
    ec.pause()
    assert ec.is_paused
    ec.resume()
    assert not ec.is_paused

    ec.set_active_task("t1")
    assert ec.active_task_id == "t1"
    assert ec.kill_task("t1") is True
    assert ec.is_task_cancelled("t1")
    ec.clear_active_task()
    assert ec.active_task_id is None
```

**Step 2: Run integration tests**

Run: `source .venv/bin/activate && pytest tests/integration/test_control_plane_completion.py -v`
Expected: ALL PASS

**Step 3: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short -q`
Expected: All tests pass

**Step 4: Run linter**

Run: `source .venv/bin/activate && ruff check src/ tests/`
Expected: No errors

**Step 5: Commit**

```bash
git add tests/integration/test_control_plane_completion.py
git commit -m "test: add integration tests for control plane completion"
```

---

## Final Verification

After all tasks:

```bash
source .venv/bin/activate && pytest tests/ -v && ruff check src/ tests/
```

Expected: All tests pass, no lint errors.

Verify CLI commands:
```bash
atlas daemon --help    # shows pause, resume, kill
atlas rules --help     # shows list, add, remove
atlas trust --help     # shows recommendations, accept, dismiss, status
```

# Phase 2 Code Review Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve the 6 issues found during code review of PR #1 (Phase 2).

**Architecture:** Each fix is self-contained. Issues 2+3 are combined (same file). Issue 4 requires wiring `build_replan_prompt` into the execution loop. Issue 6 rewrites a test to use real components.

**Tech Stack:** Python 3.12+, anthropic SDK (AsyncAnthropic), asyncio, aiosqlite, pytest

---

### Task 1: Fix `_dedup_keys` never cleaned on task completion

The `TaskQueue._dedup_keys` set is populated on enqueue but never cleaned when tasks complete or fail. This permanently blocks re-enqueue of the same `dedup_key` for the lifetime of the queue — breaking reactive mode where the same event should be able to trigger new tasks after the previous one finishes.

**Files:**
- Modify: `src/atlas/core/tasks.py:63-71`
- Modify: `tests/unit/core/test_tasks.py`

**Step 1: Write the failing test**

Append to `tests/unit/core/test_tasks.py`:

```python
def test_dedup_key_cleared_on_complete():
    """After completing a task, the same dedup_key can be enqueued again."""
    q = TaskQueue()
    q.enqueue(Task(description="run tests", dedup_key="tests"))
    task = q.get_next()
    q.complete(task.task_id)

    # Same dedup_key should now be accepted again
    q.enqueue(Task(description="run tests again", dedup_key="tests"))
    assert q.pending_count() == 1


def test_dedup_key_cleared_on_fail():
    """After a task fails, the same dedup_key can be enqueued again."""
    q = TaskQueue()
    q.enqueue(Task(description="run tests", dedup_key="tests"))
    task = q.get_next()
    q.fail(task.task_id, error="broke")

    q.enqueue(Task(description="run tests retry", dedup_key="tests"))
    assert q.pending_count() == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/core/test_tasks.py -v -k "cleared"`
Expected: FAIL — `pending_count()` returns 0 because dedup_key is still in the set

**Step 3: Fix `complete()` and `fail()` to clear dedup_key**

In `src/atlas/core/tasks.py`, update both methods:

```python
def complete(self, task_id: str, result: Any = None) -> None:
    task = self._tasks[task_id]
    task.status = TaskStatus.COMPLETED
    task.result = result
    if task.dedup_key:
        self._dedup_keys.discard(task.dedup_key)

def fail(self, task_id: str, error: str = "") -> None:
    task = self._tasks[task_id]
    task.status = TaskStatus.FAILED
    task.error = error
    if task.dedup_key:
        self._dedup_keys.discard(task.dedup_key)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/core/test_tasks.py -v`
Expected: All PASS (existing + 2 new)

**Step 5: Commit**

```bash
git add src/atlas/core/tasks.py tests/unit/core/test_tasks.py
git commit -m "fix: clear dedup_key from TaskQueue on complete/fail so reactive tasks can re-enqueue"
```

---

### Task 2: Switch to AsyncAnthropic and pass timeout to SDK

The `ClaudeCodeBridge` uses sync `anthropic.Anthropic()` inside `async def oneshot()`, blocking the event loop. Also, `self._timeout` is stored but never passed to the SDK (which defaults to 600s). Fix both: use `AsyncAnthropic` with `await`, and pass `timeout` to the client.

**Files:**
- Modify: `src/atlas/env/claude.py:45-97`
- Modify: `tests/unit/env/test_claude.py`

**Step 1: Write the failing test**

Append to `tests/unit/env/test_claude.py`:

```python
def test_bridge_uses_async_client():
    """ClaudeCodeBridge should use AsyncAnthropic, not sync Anthropic."""
    import anthropic as _anthropic
    bridge = ClaudeCodeBridge.__new__(ClaudeCodeBridge)
    bridge._model = "test"
    bridge._timeout = 60
    bridge._client = _anthropic.AsyncAnthropic(api_key="test-key")
    assert isinstance(bridge._client, _anthropic.AsyncAnthropic)
```

Add this import at the top of the test file:

```python
from atlas.env.claude import ClaudeCodeBridge
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/env/test_claude.py::test_bridge_uses_async_client -v`
Expected: PASS (this test passes because we construct it manually — the real verification is the code change)

**Step 3: Rewrite `ClaudeCodeBridge` to use `AsyncAnthropic`**

Replace the class in `src/atlas/env/claude.py` starting at line 45:

```python
class ClaudeCodeBridge:
    """Calls the Anthropic Messages API via async client."""

    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = 120):
        self._model = model
        self._timeout = timeout
        self._client = anthropic.AsyncAnthropic(timeout=timeout)

    async def oneshot(
        self, prompt: str, system_prompt: str | None = None
    ) -> ClaudeResponse:
        start = time.monotonic()
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=system_prompt or "",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as e:
            raise ClaudeCodeUnavailableError(
                "ANTHROPIC_API_KEY not set or invalid."
            ) from e
        except anthropic.APITimeoutError as e:
            raise ClaudeCodeError(
                f"Anthropic API timed out after {self._timeout}s"
            ) from e
        except anthropic.APIError as e:
            raise ClaudeCodeError(f"Anthropic API error: {e}") from e

        elapsed = int((time.monotonic() - start) * 1000)

        # Extract text from the response
        text = ""
        for block in message.content:
            if block.type == "text":
                text += block.text

        if not text.strip():
            logger.warning(
                "Claude returned empty text. model=%s, stop_reason=%s, elapsed=%dms",
                message.model, message.stop_reason, elapsed,
            )

        response = parse_response_text(text)
        response.execution_time_ms = elapsed
        response.tokens_used = message.usage.input_tokens + message.usage.output_tokens
        return response
```

Key changes:
- `anthropic.Anthropic()` → `anthropic.AsyncAnthropic(timeout=timeout)`
- `self._client.messages.create(...)` → `await self._client.messages.create(...)`
- Removed dead `try/except AuthenticationError` around constructor (SDK never raises at init)

**Step 4: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/env/claude.py tests/unit/env/test_claude.py
git commit -m "fix: use AsyncAnthropic with timeout to avoid blocking event loop"
```

---

### Task 3: Wire `build_replan_prompt` into execution loop

`build_replan_prompt()` exists but is never called. The old early-exit on failure was removed, so tasks blindly continue after failures. Wire in replanning: when a task fails, ask Claude to replan remaining tasks with error context.

**Files:**
- Modify: `src/atlas/core/loop.py:52-115`
- Modify: `tests/unit/core/test_replan.py`

**Step 1: Write the failing test**

Append to `tests/unit/core/test_replan.py`:

```python
import pytest
from unittest.mock import AsyncMock
from atlas.contracts.types import ClaudeResponse
from atlas.core.loop import ExecutionLoop
from atlas.core.tasks import Task
from atlas.core.missions import Mission, parse_task_plan


async def test_replan_called_on_task_failure(tmp_path):
    """When a task fails, the loop should attempt replanning via Claude."""
    from atlas.contracts.types import AutonomyLevel
    from atlas.control.policy import PolicyEngine
    from atlas.control.audit import AuditLogger
    from atlas.control.approval import ApprovalWorkflow
    from atlas.memory.working import WorkingMemoryStore
    from atlas.memory.episodic import EpisodicMemoryStore
    from atlas.memory.store import DatabaseStore
    from atlas.env.filesystem import FilesystemProvider
    from atlas.env.process import ProcessProvider
    from atlas.env.claude import ClaudeCodeBridge
    from atlas.env.facade import EnvironmentFacade
    from atlas.skills.registry import SkillRegistry
    from atlas.skills.runtime import InvocationRuntime
    from atlas.skills.seed import register_seed_skills

    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(tmp_path))
    proc = ProcessProvider()

    # Mock only the Claude bridge
    mock_claude = AsyncMock(spec=ClaudeCodeBridge)
    mock_claude.oneshot = AsyncMock(return_value=ClaudeResponse(
        content='{"tasks": []}',
        parsed_output={"tasks": []},
    ))

    env = EnvironmentFacade(filesystem=fs, process=proc, claude=mock_claude)

    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)
    runtime = InvocationRuntime(registry)

    policy = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    audit = AuditLogger(db=db.db)
    await audit.initialize()
    approval = ApprovalWorkflow(auto_approve=True)
    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
    )

    # Task that will fail (file doesn't exist)
    tasks = [
        Task(description="Read nonexistent file", skill_id="file.read",
             input_params={"path": str(tmp_path / "nonexistent.txt")}),
        Task(description="Write a file", skill_id="file.write",
             input_params={"path": str(tmp_path / "out.txt"), "content": "hello"}),
    ]
    mission = Mission(goal_text="test replanning", tasks=tasks)
    result = await loop.execute_mission(mission)

    # Claude should have been called for replanning after the first task failed
    assert mock_claude.oneshot.call_count >= 1

    await db.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_replan.py::test_replan_called_on_task_failure -v`
Expected: FAIL — `mock_claude.oneshot.call_count` is 0

**Step 3: Wire replanning into `execute_mission`**

In `src/atlas/core/loop.py`, add the `SkillForge` type import and update `execute_mission`:

Add import at top:
```python
from atlas.core.missions import Mission, parse_task_plan, PLANNING_SYSTEM_PROMPT
```

Update `ExecutionLoop.__init__` to type the forge parameter:
```python
from atlas.skills.forge import SkillForge

class ExecutionLoop:
    def __init__(
        self,
        ...
        forge: SkillForge | None = None,
        max_replans: int = 2,
    ):
        ...
        self._forge = forge
        self._max_replans = max_replans
```

Replace `execute_mission` body (lines 77-115) with:

```python
    async def execute_mission(self, mission: Mission) -> Mission:
        mission.status = MissionStatus.ACTIVE
        ctx = ExecutionContext.new(mission_id=mission.mission_id)
        actions_log: list[dict] = []
        replans_remaining = self._max_replans

        total = len(mission.tasks)
        for i, task in enumerate(mission.tasks):
            step_ctx = ExecutionContext(
                correlation_id=ctx.correlation_id,
                mission_id=mission.mission_id,
                task_id=task.task_id,
            )
            logger.info(f"[task {i+1}/{total}] {task.description}")

            success = await self._execute_task(task, step_ctx)
            actions_log.append({
                "task_id": task.task_id,
                "description": task.description,
                "skill_id": task.skill_id,
                "status": task.status.value,
            })

            if not success and replans_remaining > 0:
                replans_remaining -= 1
                remaining_descs = [t.description for t in mission.tasks[i+1:]]
                skills_desc = ", ".join(
                    s.skill_id for s in self._registry.list_all()
                )
                replan_prompt = build_replan_prompt(
                    original_goal=mission.goal_text,
                    failed_task_desc=task.description,
                    error=task.error or "unknown",
                    remaining_tasks=remaining_descs,
                    skills=skills_desc,
                    context="",
                )
                try:
                    response = await self._env.claude_oneshot(
                        replan_prompt, system_prompt=PLANNING_SYSTEM_PROMPT,
                    )
                    new_tasks = parse_task_plan(response.content)
                    if new_tasks:
                        # Replace remaining tasks with replanned ones
                        mission.tasks = mission.tasks[:i+1] + new_tasks
                        total = len(mission.tasks)
                        logger.info("Replanned: %d new tasks after failure", len(new_tasks))
                except Exception as e:
                    logger.warning("Replanning failed: %s", e)
            elif not success:
                break  # no replans left, stop execution

        all_succeeded = all(
            t.status == TaskStatus.COMPLETED for t in mission.tasks
        )
        mission.status = MissionStatus.COMPLETED if all_succeeded else MissionStatus.FAILED

        # Record episode
        await self._episodic.record(Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger=mission.goal_text,
            plan="; ".join(t.description for t in mission.tasks),
            actions=actions_log,
            outcome=mission.status.value,
            mission_id=mission.mission_id,
            correlation_id=ctx.correlation_id,
        ))

        return mission
```

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/core/loop.py tests/unit/core/test_replan.py
git commit -m "fix: wire build_replan_prompt into execution loop, restore early-exit when replans exhausted"
```

---

### Task 4: Remove `from __future__ import annotations` from new files

CLAUDE.md says this is not needed for Python 3.12+. All 12 new Phase 2 files include it unnecessarily.

**Files:**
- Modify: `src/atlas/daemon/loop.py:1-3`
- Modify: `src/atlas/daemon/manager.py:1-3`
- Modify: `src/atlas/daemon/protocol.py:1-3`
- Modify: `src/atlas/config.py:1-3`
- Modify: `src/atlas/memory/patterns.py:1-3`
- Modify: `src/atlas/memory/procedural.py:1-3`
- Modify: `src/atlas/observation/engine.py:1-3`
- Modify: `src/atlas/observation/router.py:1-3`
- Modify: `src/atlas/observation/scheduler.py:1-3`
- Modify: `src/atlas/observation/watcher.py:1-3`
- Modify: `src/atlas/skills/forge.py:1-3`
- Modify: `src/atlas/skills/loader.py:1-3`

**Step 1: Remove the import from all 12 files**

For each file, delete the line `from __future__ import annotations` (line 3 in each).

**Step 2: Run tests to verify nothing breaks**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 3: Run linter**

Run: `ruff check src/ tests/`
Expected: All checks passed

**Step 4: Commit**

```bash
git add src/atlas/daemon/ src/atlas/config.py src/atlas/memory/patterns.py src/atlas/memory/procedural.py src/atlas/observation/ src/atlas/skills/forge.py src/atlas/skills/loader.py
git commit -m "style: remove unnecessary 'from __future__ import annotations' from new Phase 2 files"
```

---

### Task 5: Rewrite forge integration test to use real components

`test_forge_integration.py` mocks SkillRegistry, InvocationRuntime, PolicyEngine, and other domain objects. CLAUDE.md says only ClaudeCodeBridge should be mocked. Rewrite as an integration test using real components with `tmp_path`.

**Files:**
- Modify: `tests/unit/core/test_forge_integration.py`

**Step 1: Rewrite the test**

Replace the entire file:

```python
# tests/unit/core/test_forge_integration.py
"""Integration test: Forge is triggered when execution loop encounters missing skill."""

from unittest.mock import AsyncMock

import pytest

from atlas.contracts.types import AutonomyLevel, ClaudeResponse
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.env.claude import ClaudeCodeBridge
from atlas.env.facade import EnvironmentFacade
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.forge import SkillForge
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime
from atlas.skills.seed import register_seed_skills


async def test_execution_loop_triggers_forge_on_missing_skill(tmp_path):
    """When a task references a skill that doesn't exist, the loop should attempt forge."""
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(tmp_path))
    proc = ProcessProvider()

    # Mock only the Claude bridge
    mock_claude = AsyncMock(spec=ClaudeCodeBridge)
    mock_claude.oneshot = AsyncMock(return_value=ClaudeResponse(
        content="not valid skill code",
        parsed_output=None,
    ))

    env = EnvironmentFacade(filesystem=fs, process=proc, claude=mock_claude)
    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)
    runtime = InvocationRuntime(registry)

    policy = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    audit = AuditLogger(db=db.db)
    await audit.initialize()
    approval = ApprovalWorkflow(auto_approve=True)
    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    forge = SkillForge(
        registry=registry,
        claude_bridge=mock_claude,
        skills_dir=str(tmp_path / "skills"),
        workspace=str(tmp_path),
        max_retries=0,
    )

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
        forge=forge,
    )

    task = Task(description="deploy the app", skill_id="custom.deploy")
    mission = Mission(goal_text="deploy", tasks=[task])
    result = await loop.execute_mission(mission)

    # Forge should have been called (Claude bridge invoked for skill generation)
    assert mock_claude.oneshot.call_count >= 1

    # Task should have failed (mock Claude didn't return valid skill code)
    assert task.error is not None
    assert "forge failed" in task.error.lower() or "not found" in task.error.lower()

    await db.close()
```

**Step 2: Run the test**

Run: `pytest tests/unit/core/test_forge_integration.py -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/unit/core/test_forge_integration.py
git commit -m "fix: rewrite forge integration test to use real components, mock only ClaudeCodeBridge"
```

---

### Task 6: Final verification

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 2: Run linter**

Run: `ruff check src/ tests/`
Expected: All checks passed

**Step 3: Commit any remaining fixes**

```bash
git add -u
git commit -m "chore: code review fixes — all 6 issues resolved"
```

**Step 4: Push**

```bash
git push
```

---

## Summary

| Task | Issue | Files |
|------|-------|-------|
| 1 | `_dedup_keys` never cleaned | `tasks.py`, `test_tasks.py` |
| 2 | Sync client + missing timeout | `claude.py`, `test_claude.py` |
| 3 | `build_replan_prompt` never called | `loop.py`, `test_replan.py` |
| 4 | `from __future__` in new files | 12 files in daemon/, observation/, etc. |
| 5 | Tests mock beyond ClaudeCodeBridge | `test_forge_integration.py` |
| 6 | Final verification | — |

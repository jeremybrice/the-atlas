# Phase 3 — Score-75 Code Review Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 3 issues scored 75+ during code review of the re-review fix commits on PR #5

**Architecture:** Three independent fixes: (1) propagate ExecutionContext through GitHubConnector following vault.py's `_log_ctx` pattern, (2) align `dashboard_enabled` default with `webhook.enabled` to eliminate dead config, (3) add HTTP health to daemon status response so callers can detect silent degradation. Ordered standalone-first.

**Tech Stack:** Python 3.12, aiohttp, pytest, pytest-asyncio

---

## Context

After pushing 5 fix commits and running a code review, three issues scored 75 (just below the 80 auto-comment threshold). All three are real and worth fixing before merge:

1. `ctx: ExecutionContext` is accepted but silently discarded in GitHubConnector — violates CLAUDE.md's correlation_id propagation rule
2. `dashboard_enabled: true` is dead config when `webhook.enabled: false` — incoherent sibling defaults
3. Daemon `_handle_status` doesn't report HTTP health — silent degradation after port conflict

---

### Task 1: Propagate ExecutionContext through GitHubConnector

The vault.py module has the established pattern: a `_log_ctx()` helper that formats `correlation_id` for log messages. GitHubConnector should follow the same pattern.

**Files:**
- Modify: `src/atlas/integrations/connectors/github.py:32-55`
- Modify: `tests/unit/integrations/test_github.py`

**Step 1: Write the failing test**

Add a test to `tests/unit/integrations/test_github.py` that verifies `correlation_id` appears in log output when `ctx` is passed:

```python
async def test_handle_event_logs_correlation_id(connector, caplog):
    """ExecutionContext.correlation_id should appear in log output."""
    from atlas.contracts.types import ExecutionContext
    ctx = ExecutionContext(correlation_id="test-corr-123", mission_id="m1", task_id="t1")
    with caplog.at_level("INFO"):
        await connector.handle_event("push", {"ref": "main"}, ctx=ctx)
    assert "test-corr-123" in caplog.text


async def test_authenticate_logs_correlation_id(connector, caplog):
    from atlas.contracts.types import ExecutionContext
    ctx = ExecutionContext(correlation_id="auth-corr-456", mission_id="m1", task_id="t1")
    with caplog.at_level("INFO"):
        await connector.authenticate(ctx=ctx)
    assert "auth-corr-456" in caplog.text
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/integrations/test_github.py::test_handle_event_logs_correlation_id tests/unit/integrations/test_github.py::test_authenticate_logs_correlation_id -v`
Expected: FAIL (correlation_id not in log output)

**Step 3: Add `_log_ctx` helper and use it in GitHubConnector**

In `src/atlas/integrations/connectors/github.py`, add a `_log_ctx` static method (matching `vault.py:45-49`) and update the three methods that accept `ctx` to include correlation_id in their log lines.

Add after line 30 (`self._headers: dict[str, str] = {}`):
```python
    @staticmethod
    def _log_ctx(ctx: ExecutionContext | None) -> str:
        if ctx:
            return f"[{ctx.correlation_id}] "
        return ""
```

Change `authenticate` (line 38) from:
```python
        logger.info("GitHub connector authenticated for %s/%s", self._owner, self._repo)
```
to:
```python
        logger.info("%sGitHub connector authenticated for %s/%s", self._log_ctx(ctx), self._owner, self._repo)
```

Change `handle_event` (line 41) from:
```python
        logger.info("GitHub event: %s action=%s", event_type, payload.get("action", ""))
```
to:
```python
        logger.info("%sGitHub event: %s action=%s", self._log_ctx(ctx), event_type, payload.get("action", ""))
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/unit/integrations/test_github.py -v`
Expected: ALL PASS

**Step 5: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/integrations/connectors/github.py tests/unit/integrations/test_github.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/atlas/integrations/connectors/github.py tests/unit/integrations/test_github.py
git commit -m "fix: propagate ExecutionContext correlation_id in GitHubConnector logging"
```

---

### Task 2: Align dashboard_enabled default with webhook.enabled

When `webhook.enabled` is `false`, the entire HTTP block in `cli.py` is skipped, making `dashboard_enabled: true` dead config. Fix: default `dashboard_enabled` to `false` so both are coherent. Users who enable webhooks explicitly opt into the dashboard too.

**Files:**
- Modify: `src/atlas/config.py:77`
- Modify: `config/default.yaml:63`

**Step 1: Change default in config.py**

In `src/atlas/config.py` line 77, change:
```python
    dashboard_enabled: bool = True
```
to:
```python
    dashboard_enabled: bool = False
```

**Step 2: Change default in default.yaml**

In `config/default.yaml` line 63, change:
```yaml
  dashboard_enabled: true
```
to:
```yaml
  dashboard_enabled: false
```

**Step 3: Run tests**

Run: `source .venv/bin/activate && pytest tests/ -v -k "config or webhook or daemon or dashboard"`
Expected: ALL PASS (no test depends on dashboard_enabled being true by default)

**Step 4: Commit**

```bash
git add src/atlas/config.py config/default.yaml
git commit -m "fix: default dashboard_enabled to false — coherent with webhook.enabled"
```

---

### Task 3: Add HTTP health to daemon status response

After a port conflict, the daemon silently runs without HTTP. The `status` command should report whether the HTTP server is active so operators can detect degradation.

**Files:**
- Modify: `src/atlas/daemon/loop.py:37,67,108-118`
- Modify: `tests/unit/daemon/test_daemon_loop.py`

**Step 1: Write the failing test**

Add a test to `tests/unit/daemon/test_daemon_loop.py` that checks for `http_running` in the status response:

```python
async def test_daemon_loop_status_includes_http_running():
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
        resp = await client.send(DaemonCommand(command="status"))
        assert resp["status"] == "ok"
        assert "http_running" in resp["payload"]
        assert resp["payload"]["http_running"] is False  # no http_app configured
    finally:
        await loop.stop()
        await task
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/daemon/test_daemon_loop.py::test_daemon_loop_status_includes_http_running -v`
Expected: FAIL (KeyError: 'http_running')

**Step 3: Add `_http_running` tracking and include in status**

In `src/atlas/daemon/loop.py`, add an `_http_running` instance variable and include it in status.

Add after line 37 (`self._http_runner = None`):
```python
        self._http_running = False
```

In the `else` block of the TCPSite try/except (line 67-68), after the existing `logger.info` line, add:
```python
                self._http_running = True
```

So lines 67-69 become:
```python
            else:
                logger.info("HTTP server started on %s:%d", self._http_host, self._http_port)
                self._http_running = True
```

In `_handle_status` (line 108-118), add `http_running` to the payload. Change:
```python
            "payload": {
                "pid": os.getpid(),
                "uptime_seconds": round(uptime, 1),
                "running": self._running,
            },
```
to:
```python
            "payload": {
                "pid": os.getpid(),
                "uptime_seconds": round(uptime, 1),
                "running": self._running,
                "http_running": self._http_running,
            },
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/unit/daemon/test_daemon_loop.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/atlas/daemon/loop.py tests/unit/daemon/test_daemon_loop.py
git commit -m "fix: report HTTP health in daemon status response"
```

---

## Verification

After all tasks, run:
```bash
source .venv/bin/activate && pytest tests/ -v
source .venv/bin/activate && ruff check src/ tests/
```

All 3 issues resolved:
1. ExecutionContext correlation_id propagated in GitHubConnector logging (Task 1)
2. dashboard_enabled defaults to false — coherent with webhook.enabled (Task 2)
3. Daemon status reports http_running field (Task 3)

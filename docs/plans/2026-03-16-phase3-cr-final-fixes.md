# Phase 3 — Final Code Review Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 4 issues scored 75+ from the final code review of PR #5

**Architecture:** Four independent fixes: (1) call `authenticate()` on GitHubConnector in daemon startup, (2) add `asyncio.Lock` to rate limiter to prevent TOCTOU race, (3) fix sync lambda in webhook signature test, (4) make `ObservationEngine._on_event` a public method. Ordered by severity — the two score-100 bugs first.

**Tech Stack:** Python 3.12, asyncio, aiohttp, pytest, pytest-asyncio

---

## Context

After the re-review fix commits and score-75 fix commits, a final code review found 4 issues:

1. `GitHubConnector.authenticate()` never called in daemon startup — outbound API calls fail with 401 (score 100)
2. `_check_rate_limit()` has an asyncio TOCTOU race condition — concurrent calls can bypass the rate limiter (score 100)
3. `test_webhook_accepts_valid_signature` passes a sync lambda where an async callback is expected (score 75)
4. `obs_engine._on_event` (private method) passed as a public cross-domain callback (score 75)

---

### Task 1: Call authenticate() on GitHubConnector in daemon startup

**Files:**
- Modify: `src/atlas/cli.py:390`

**Step 1: Read the file**

Read `src/atlas/cli.py` lines 375-415 to confirm current state.

**Step 2: Add authenticate() call**

In `src/atlas/cli.py`, after line 389 (closing paren of `GitHubConnector(...)`) and before line 390 (`event_bridge.register_parser(...)`), add:

```python
            await github_connector.authenticate()
```

So lines 385-391 become:
```python
            github_connector = GitHubConnector(
                token=config.github.token,
                owner=config.github.owner,
                repo=config.github.repo,
            )
            await github_connector.authenticate()
            event_bridge.register_parser("github", github_connector.get_event_parser())
```

**Step 3: Run tests**

Run: `source .venv/bin/activate && pytest tests/ -v -k "daemon or webhook or github or config" 2>&1 | tail -20`
Expected: ALL PASS (no test directly exercises the `_run_daemon` path with a real connector)

**Step 4: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/cli.py`
Expected: No errors

**Step 5: Commit**

```bash
git add src/atlas/cli.py
git commit -m "fix: call authenticate() on GitHubConnector in daemon startup"
```

---

### Task 2: Add asyncio.Lock to rate limiter

The `_check_rate_limit` method has a TOCTOU race: two concurrent coroutines can both pass the length check before either appends a timestamp. Fix by adding an `asyncio.Lock`.

**Files:**
- Modify: `src/atlas/integrations/connector.py:21-24,45-59`
- Modify: `tests/unit/integrations/test_connector.py`

**Step 1: Write the failing test**

Add a test to `tests/unit/integrations/test_connector.py` that verifies concurrent calls are properly serialized:

```python
async def test_rate_limit_serializes_concurrent_calls():
    """Concurrent calls should not bypass the rate limit."""
    conn = FakeConnector()
    conn._rate_limit_rpm = 2  # low limit to test easily

    # Fire 4 concurrent calls
    results = await asyncio.gather(
        conn.execute_action("a", {}),
        conn.execute_action("b", {}),
        conn.execute_action("c", {}),
        conn.execute_action("d", {}),
    )

    # All should complete (rate limiter waits, doesn't reject)
    assert len(results) == 4
    # But timestamps should show serialization — at most 2 in any 1-second window
    # The lock ensures check-then-append is atomic
    assert len(conn._call_timestamps) == 4
```

Add `import asyncio` to the top of the test file.

**Step 2: Run test to verify it passes (it may pass by luck)**

Run: `source .venv/bin/activate && pytest tests/unit/integrations/test_connector.py::test_rate_limit_serializes_concurrent_calls -v`

Note: The test may pass even without the lock due to asyncio scheduling. The fix is still needed for correctness.

**Step 3: Add asyncio.Lock to ConnectorABC**

In `src/atlas/integrations/connector.py`, modify `__init__` to add a lock:

Change lines 21-24 from:
```python
    def __init__(self, service_name: str, rate_limit_rpm: int = 60):
        self._service_name = service_name
        self._rate_limit_rpm = rate_limit_rpm
        self._call_timestamps: list[float] = []
```
to:
```python
    def __init__(self, service_name: str, rate_limit_rpm: int = 60):
        self._service_name = service_name
        self._rate_limit_rpm = rate_limit_rpm
        self._call_timestamps: list[float] = []
        self._rate_limit_lock = asyncio.Lock()
```

Wrap the body of `_check_rate_limit` in an async lock. Change lines 45-59 from:
```python
    async def _check_rate_limit(self) -> None:
        """Wait if rate limit would be exceeded."""
        now = time.monotonic()
        window = 60.0  # 1 minute window
        # Prune old timestamps
        self._call_timestamps = [t for t in self._call_timestamps if now - t < window]
        if len(self._call_timestamps) >= self._rate_limit_rpm:
            wait_time = window - (now - self._call_timestamps[0])
            if wait_time > 0:
                logger.warning(
                    "%s rate limit reached (%d rpm), waiting %.1fs",
                    self._service_name, self._rate_limit_rpm, wait_time,
                )
                await asyncio.sleep(wait_time)
        self._call_timestamps.append(time.monotonic())
```
to:
```python
    async def _check_rate_limit(self) -> None:
        """Wait if rate limit would be exceeded."""
        async with self._rate_limit_lock:
            now = time.monotonic()
            window = 60.0  # 1 minute window
            # Prune old timestamps
            self._call_timestamps = [t for t in self._call_timestamps if now - t < window]
            if len(self._call_timestamps) >= self._rate_limit_rpm:
                wait_time = window - (now - self._call_timestamps[0])
                if wait_time > 0:
                    logger.warning(
                        "%s rate limit reached (%d rpm), waiting %.1fs",
                        self._service_name, self._rate_limit_rpm, wait_time,
                    )
                    await asyncio.sleep(wait_time)
            self._call_timestamps.append(time.monotonic())
```

**Step 4: Run all connector tests**

Run: `source .venv/bin/activate && pytest tests/unit/integrations/test_connector.py -v`
Expected: ALL PASS

**Step 5: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/integrations/connector.py tests/unit/integrations/test_connector.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/atlas/integrations/connector.py tests/unit/integrations/test_connector.py
git commit -m "fix: add asyncio.Lock to rate limiter to prevent TOCTOU race"
```

---

### Task 3: Fix sync lambda in webhook signature test

The test `test_webhook_accepts_valid_signature` passes `lambda e: received.append(e)` as the `event_callback`. The production code does `await self._callback(event)`. The sync lambda works only because the resulting `TypeError` is swallowed by the try/except. Fix: make it an async function.

**Files:**
- Modify: `tests/unit/integrations/test_webhook.py:108-111`

**Step 1: Read the test file**

Read `tests/unit/integrations/test_webhook.py` to confirm current state.

**Step 2: Fix the callback**

In `tests/unit/integrations/test_webhook.py`, change lines 108-111 from:
```python
    received = []
    server = WebhookServer(
        event_bridge=bridge,
        event_callback=lambda e: received.append(e),
```
to:
```python
    received = []

    async def on_event(e):
        received.append(e)

    server = WebhookServer(
        event_bridge=bridge,
        event_callback=on_event,
```

**Step 3: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/integrations/test_webhook.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/unit/integrations/test_webhook.py
git commit -m "fix: use async callback in test_webhook_accepts_valid_signature"
```

---

### Task 4: Make ObservationEngine._on_event public

`cli.py` passes `obs_engine._on_event` (private) as a cross-domain callback to `WebhookServer`. The CLAUDE.md convention says contracts are canonical and cross-domain calls should use public interfaces. Fix: rename `_on_event` to `on_event`.

**Files:**
- Modify: `src/atlas/observation/engine.py:30,42,62`
- Modify: `src/atlas/cli.py:394`

**Step 1: Read both files**

Read `src/atlas/observation/engine.py` and `src/atlas/cli.py` to confirm current state.

**Step 2: Rename _on_event to on_event in engine.py**

In `src/atlas/observation/engine.py`, change all three occurrences of `_on_event` to `on_event`:

Line 30: change `callback=self._on_event,` to `callback=self.on_event,`
Line 42: change `callback=self._on_event,` to `callback=self.on_event,`
Line 62: change `async def _on_event(self, event: ObservationEvent) -> None:` to `async def on_event(self, event: ObservationEvent) -> None:`

**Step 3: Update cli.py reference**

In `src/atlas/cli.py` line 394, change:
```python
            event_callback=obs_engine._on_event,
```
to:
```python
            event_callback=obs_engine.on_event,
```

**Step 4: Run tests**

Run: `source .venv/bin/activate && pytest tests/ -v -k "observation or webhook or daemon"`
Expected: ALL PASS

**Step 5: Run linter**

Run: `source .venv/bin/activate && ruff check src/atlas/observation/engine.py src/atlas/cli.py`
Expected: No errors

**Step 6: Commit**

```bash
git add src/atlas/observation/engine.py src/atlas/cli.py
git commit -m "fix: make ObservationEngine.on_event public for cross-domain use"
```

---

## Verification

After all tasks, run:
```bash
source .venv/bin/activate && pytest tests/ -v
source .venv/bin/activate && ruff check src/ tests/
```

All 4 issues resolved:
1. GitHubConnector.authenticate() called in daemon startup (Task 1)
2. Rate limiter protected by asyncio.Lock (Task 2)
3. Webhook signature test uses async callback (Task 3)
4. ObservationEngine.on_event is public (Task 4)

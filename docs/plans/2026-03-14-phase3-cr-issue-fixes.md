# Phase 3 Code Review Issue Fixes — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix two code review issues from PR #4: remove trivial tests violating CLAUDE.md, and wire `TrustRecord.recent_outcomes` into `get_record()` so the contract field is not dead.

**Architecture:** Task 1 deletes two trivial tests. Task 2 adds `recent_outcomes` to the `get_record()` SELECT query so the contract type reflects actual DB state. Both are small, surgical changes.

**Tech Stack:** Python 3.12+, asyncio, SQLite

---

### Task 1: Remove trivial tests that violate CLAUDE.md

**Files:**
- Modify: `tests/unit/contracts/test_types.py:101-104` (delete test)
- Modify: `tests/unit/integrations/test_vault.py:111-115` (delete test)

**Step 1: Delete `test_trust_record_has_recent_outcomes_field`**

In `tests/unit/contracts/test_types.py`, delete lines 100-104:

```python
# DELETE THIS:
def test_trust_record_has_recent_outcomes_field():
    record = TrustRecord(skill_id="test.skill")
    assert hasattr(record, 'recent_outcomes')
    assert record.recent_outcomes == ""
```

This test checks a trivial dataclass default. CLAUDE.md says "Unit test complex logic only."

**Step 2: Delete `test_credential_vault_has_no_sync_constructor`**

In `tests/unit/integrations/test_vault.py`, delete lines 111-115:

```python
# DELETE THIS:
def test_credential_vault_has_no_sync_constructor():
    """CredentialVault should only be constructed via create() to ensure correct salt usage."""
    assert hasattr(CredentialVault, 'create')
    # Verify that create is a classmethod
    assert isinstance(CredentialVault.__dict__['create'], classmethod)
```

This test checks metaclass machinery (`isinstance(..., classmethod)`), not logic.

**Step 3: Run tests to verify nothing breaks**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: 183 tests pass (2 removed from the previous 185).

**Step 4: Commit**

```bash
git add tests/unit/contracts/test_types.py tests/unit/integrations/test_vault.py
git commit -m "fix: remove trivial tests per CLAUDE.md 'unit test complex logic only'"
```

---

### Task 2: Populate `TrustRecord.recent_outcomes` in `get_record()`

**Files:**
- Modify: `src/atlas/control/trust.py:100-121` (update SELECT and TrustRecord construction)
- Modify: `tests/unit/control/test_trust.py` (add test verifying `recent_outcomes` is populated)

**Step 1: Write the failing test**

In `tests/unit/control/test_trust.py`, add at the end of the file:

```python
async def test_get_record_populates_recent_outcomes(db):
    """get_record should populate recent_outcomes from the DB, not leave it empty."""
    tracker = TrustTracker(db=db, escalation_threshold=10, demotion_failure_count=3, demotion_window_size=5)

    # Record some outcomes so recent_outcomes has data
    await tracker.record_outcome("file.read", success=True)
    await tracker.record_outcome("file.read", success=False)
    await tracker.record_outcome("file.read", success=True)

    record = await tracker.get_record("file.read")
    assert record.recent_outcomes != "", "recent_outcomes should be populated from DB"
    import json
    outcomes = json.loads(record.recent_outcomes)
    assert outcomes == [True, False, True]
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/unit/control/test_trust.py::test_get_record_populates_recent_outcomes -v`
Expected: FAIL — `record.recent_outcomes` is `""` because `get_record()` doesn't SELECT it.

**Step 3: Update `get_record()` to include `recent_outcomes`**

In `src/atlas/control/trust.py`, change the `get_record` method (lines 99-121).

Change the SELECT from:

```python
        cursor = await self._db.db.execute(
            "SELECT skill_id, successes, failures, consecutive_successes, "
            "total_invocations, autonomy_override, last_outcome, updated_at "
            "FROM trust_records WHERE skill_id = ?",
            (skill_id,),
        )
```

to:

```python
        cursor = await self._db.db.execute(
            "SELECT skill_id, successes, failures, consecutive_successes, "
            "total_invocations, autonomy_override, last_outcome, updated_at, "
            "recent_outcomes "
            "FROM trust_records WHERE skill_id = ?",
            (skill_id,),
        )
```

And change the TrustRecord construction from:

```python
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
```

to:

```python
        return TrustRecord(
            skill_id=row[0],
            successes=row[1],
            failures=row[2],
            consecutive_successes=row[3],
            total_invocations=row[4],
            autonomy_override=autonomy_override,
            last_outcome=row[6] or "",
            updated_at=row[7],
            recent_outcomes=row[8] or "",
        )
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All 184 tests pass (183 existing + 1 new).

**Step 5: Run lint**

Run: `source .venv/bin/activate && ruff check src/ tests/`
Expected: All checks passed.

**Step 6: Commit**

```bash
git add src/atlas/control/trust.py tests/unit/control/test_trust.py
git commit -m "fix: populate TrustRecord.recent_outcomes in get_record()"
```

---

## Verification

```bash
source .venv/bin/activate && pytest tests/ -v && ruff check src/ tests/
```

Expected: 184 tests pass, no lint errors.

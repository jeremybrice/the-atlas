"""Trust Tracker — tracks per-skill success/failure and suggests autonomy changes."""
import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from atlas.contracts.types import AutonomyLevel, ExecutionContext, TrustRecord
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

    @staticmethod
    def _log_ctx(ctx: ExecutionContext | None) -> str:
        """Format correlation_id for log messages."""
        if ctx:
            return f"[{ctx.correlation_id}] "
        return ""

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

        logger.debug("%sRecorded outcome for %s: %s", self._log_ctx(ctx), skill_id, "success" if success else "failure")

        return outcome

    def _count_recent_failures(self, recent: deque[bool]) -> int:
        """Count failures within the sliding window of recent outcomes."""
        return sum(1 for r in recent if not r)

    async def _load_recent(self, skill_id: str) -> deque[bool]:
        """Load the recent outcomes deque from the database."""
        cursor = await self._db.db.execute(
            "SELECT recent_outcomes FROM trust_records WHERE skill_id = ?",
            (skill_id,),
        )
        row = await cursor.fetchone()
        if row is None or row[0] is None:
            return deque(maxlen=self._demotion_window_size)
        outcomes = json.loads(row[0])
        return deque(outcomes, maxlen=self._demotion_window_size)

    async def get_record(self, skill_id: str, ctx: ExecutionContext | None = None) -> TrustRecord:
        cursor = await self._db.db.execute(
            "SELECT skill_id, successes, failures, consecutive_successes, "
            "total_invocations, autonomy_override, last_outcome, updated_at, "
            "recent_outcomes "
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
            recent_outcomes=row[8] if row[8] is not None else "[]",
        )

    async def set_autonomy_override(self, skill_id: str, level: AutonomyLevel, ctx: ExecutionContext | None = None) -> None:
        record = await self.get_record(skill_id)
        recent = await self._load_recent(skill_id)
        record.autonomy_override = level
        record.updated_at = datetime.now(timezone.utc).isoformat()
        await self._save_record(record, recent)
        logger.info("%sTrust override set: %s -> %s", self._log_ctx(ctx), skill_id, level.name)

    async def get_autonomy_override(self, skill_id: str, ctx: ExecutionContext | None = None) -> AutonomyLevel | None:
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

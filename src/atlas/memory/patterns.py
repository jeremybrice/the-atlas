"""Pattern Extraction — discovers repeated patterns in episodic memory."""

from collections import Counter
from atlas.contracts.types import Episode


class PatternExtractor:
    def __init__(self, min_occurrences: int = 3):
        self._min_occurrences = min_occurrences

    def find_patterns(self, episodes: list[Episode]) -> list[dict]:
        # Extract skill sequences from completed episodes
        sequences: list[tuple[str, ...]] = []
        for ep in episodes:
            if ep.outcome != "completed" or not ep.actions:
                continue
            seq = tuple(
                a.get("skill_id", "")
                for a in ep.actions
                if a.get("status") == "completed" and a.get("skill_id")
            )
            if seq:
                sequences.append(seq)

        counts = Counter(sequences)
        patterns = []
        for seq, count in counts.most_common():
            if count >= self._min_occurrences:
                patterns.append(
                    {
                        "skill_sequence": list(seq),
                        "occurrences": count,
                    }
                )
        return patterns

    def find_recurring_failures(self, episodes: list[Episode]) -> list[dict]:
        failure_skills: list[str] = []
        for ep in episodes:
            if ep.outcome != "failed" or not ep.actions:
                continue
            for a in ep.actions:
                if a.get("status") == "failed" and a.get("skill_id"):
                    failure_skills.append(a["skill_id"])

        counts = Counter(failure_skills)
        failures = []
        for skill_id, count in counts.most_common():
            if count >= self._min_occurrences:
                failures.append({"skill_id": skill_id, "failure_count": count})
        # Also return failures with lower threshold (2+) as warnings
        for skill_id, count in counts.most_common():
            if count >= 2 and not any(f["skill_id"] == skill_id for f in failures):
                failures.append({"skill_id": skill_id, "failure_count": count})
        return failures

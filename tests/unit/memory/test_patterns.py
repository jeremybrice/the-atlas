# tests/unit/memory/test_patterns.py
from atlas.memory.patterns import PatternExtractor
from atlas.contracts.types import Episode, EpisodeType


async def test_extracts_repeated_skill_sequence():
    episodes = [
        Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger="run tests",
            actions=[{"skill_id": "shell.execute", "status": "completed"}],
            outcome="completed",
        ),
        Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger="run tests again",
            actions=[{"skill_id": "shell.execute", "status": "completed"}],
            outcome="completed",
        ),
        Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger="run tests once more",
            actions=[{"skill_id": "shell.execute", "status": "completed"}],
            outcome="completed",
        ),
    ]
    extractor = PatternExtractor(min_occurrences=3)
    patterns = extractor.find_patterns(episodes)
    assert len(patterns) >= 1
    assert patterns[0]["skill_sequence"] == ["shell.execute"]


async def test_identifies_recurring_failures():
    episodes = [
        Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger="deploy",
            actions=[{"skill_id": "shell.execute", "status": "failed"}],
            outcome="failed",
        ),
        Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger="deploy again",
            actions=[{"skill_id": "shell.execute", "status": "failed"}],
            outcome="failed",
        ),
    ]
    extractor = PatternExtractor(min_occurrences=2)
    failures = extractor.find_recurring_failures(episodes)
    assert len(failures) >= 1


async def test_no_patterns_below_threshold():
    episodes = [
        Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger="task A",
            actions=[{"skill_id": "file.read", "status": "completed"}],
            outcome="completed",
        ),
    ]
    extractor = PatternExtractor(min_occurrences=3)
    patterns = extractor.find_patterns(episodes)
    assert len(patterns) == 0

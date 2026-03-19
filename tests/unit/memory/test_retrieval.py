from atlas.contracts.types import ContextQuery, Episode, EpisodeType, Procedure
from atlas.memory.retrieval import ContextAssembler


def test_assemble_within_budget():
    episodes = [
        Episode(trigger=f"task-{i}", outcome=f"result-{i}" * 50) for i in range(10)
    ]
    assembler = ContextAssembler()
    query = ContextQuery(
        purpose="planning",
        task_description="test task",
        token_budget=500,
    )
    bundle = assembler.assemble(query, episodes)
    assert bundle.total_tokens <= bundle.budget_tokens
    assert bundle.budget_tokens == 500
    assert len(bundle.contents) > 0


def test_assemble_empty_episodes():
    assembler = ContextAssembler()
    query = ContextQuery(purpose="planning", task_description="test")
    bundle = assembler.assemble(query, [])
    assert bundle.total_tokens == 0
    assert len(bundle.contents) == 0


def test_estimate_tokens():
    assembler = ContextAssembler()
    # ~4 chars per token is the approximation
    assert assembler.estimate_tokens("a" * 400) == 100
    assert assembler.estimate_tokens("") == 0


def test_assemble_prioritizes_recent():
    episodes = [
        Episode(trigger=f"old-task-{i}", outcome="old result") for i in range(5)
    ]
    recent = Episode(trigger="recent-task", outcome="recent result")
    episodes.append(recent)

    assembler = ContextAssembler()
    query = ContextQuery(
        purpose="planning",
        task_description="test",
        token_budget=200,  # tight budget — only a few fit
    )
    bundle = assembler.assemble(query, episodes)
    # Most recent should be included
    sources = [c["source"] for c in bundle.contents]
    assert any("recent-task" in s for s in sources)


def test_assemble_planning_context_includes_procedures():
    assembler = ContextAssembler()
    episodes = [
        Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger="run tests",
            outcome="completed",
        ),
    ]
    procedures = [
        Procedure(
            name="run-tests",
            description="pytest after change",
            trigger_pattern="filesystem:*.py",
            steps=[{"skill": "shell.execute", "params": {"command": "pytest"}}],
        ),
    ]
    query = ContextQuery(
        purpose="planning",
        task_description="run tests on changed files",
        token_budget=4000,
    )
    bundle = assembler.assemble(query, episodes, procedures=procedures)
    all_text = " ".join(c["text"] for c in bundle.contents)
    assert "run-tests" in all_text


def test_assemble_reflection_context_prioritizes_failures():
    assembler = ContextAssembler()
    success_ep = Episode(
        episode_type=EpisodeType.TASK_EXECUTION, trigger="task A", outcome="completed"
    )
    failure_ep = Episode(
        episode_type=EpisodeType.TASK_EXECUTION,
        trigger="task B",
        outcome="failed",
        lessons=["don't do X"],
    )
    query = ContextQuery(
        purpose="reflection", task_description="analyze recent work", token_budget=500
    )
    bundle = assembler.assemble(query, [success_ep, failure_ep])
    # Failure episode should appear first in reflection context
    first_text = bundle.contents[0]["text"]
    assert "failed" in first_text.lower() or "don't do X" in first_text


def test_hybrid_merge_both_sets():
    """Episodes in both keyword and semantic results get blended scores."""
    assembler = ContextAssembler()
    keyword_scores = {"ep-1": 0.8, "ep-2": 0.5}
    semantic_scores = {"ep-1": 0.9, "ep-3": 0.7}

    merged = assembler.merge_scores(
        keyword_scores,
        semantic_scores,
        semantic_weight=0.6,
        keyword_weight=0.4,
    )

    # ep-1 in both: 0.6*0.9 + 0.4*0.8 = 0.86
    assert abs(merged["ep-1"] - 0.86) < 0.01
    # ep-2 keyword only: 0.4*0.5 = 0.2
    assert abs(merged["ep-2"] - 0.2) < 0.01
    # ep-3 semantic only: 0.6*0.7 = 0.42
    assert abs(merged["ep-3"] - 0.42) < 0.01


def test_hybrid_merge_empty_semantic():
    """When semantic results are empty, keyword scores are scaled by keyword_weight."""
    assembler = ContextAssembler()
    keyword_scores = {"ep-1": 1.0}
    semantic_scores = {}

    merged = assembler.merge_scores(
        keyword_scores,
        semantic_scores,
        semantic_weight=0.6,
        keyword_weight=0.4,
    )
    assert abs(merged["ep-1"] - 0.4) < 0.01


def test_hybrid_merge_empty_keyword():
    """When keyword results are empty, semantic scores are scaled by semantic_weight."""
    assembler = ContextAssembler()
    keyword_scores = {}
    semantic_scores = {"ep-1": 1.0}

    merged = assembler.merge_scores(
        keyword_scores,
        semantic_scores,
        semantic_weight=0.6,
        keyword_weight=0.4,
    )
    assert abs(merged["ep-1"] - 0.6) < 0.01


def test_rank_by_merged_scores():
    """assemble_ranked should rank episodes by merged score, not recency."""
    assembler = ContextAssembler()
    ep_high = Episode(
        episode_id="ep-high", trigger="highly relevant", outcome="success"
    )
    ep_low = Episode(episode_id="ep-low", trigger="less relevant", outcome="success")
    episodes_by_id = {"ep-high": ep_high, "ep-low": ep_low}
    merged_scores = {"ep-high": 0.9, "ep-low": 0.3}

    query = ContextQuery(purpose="planning", task_description="test", token_budget=4000)
    bundle = assembler.assemble_ranked(query, episodes_by_id, merged_scores)

    assert len(bundle.contents) == 2
    assert bundle.contents[0]["source"] == "highly relevant"

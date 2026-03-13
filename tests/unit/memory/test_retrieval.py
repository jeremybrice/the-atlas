from atlas.contracts.types import ContextQuery, Episode, EpisodeType, Procedure
from atlas.memory.retrieval import ContextAssembler


def test_assemble_within_budget():
    episodes = [
        Episode(trigger=f"task-{i}", outcome=f"result-{i}" * 50)
        for i in range(10)
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
        Episode(trigger=f"old-task-{i}", outcome="old result")
        for i in range(5)
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
        Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="run tests", outcome="completed"),
    ]
    procedures = [
        Procedure(name="run-tests", description="pytest after change",
                  trigger_pattern="filesystem:*.py",
                  steps=[{"skill": "shell.execute", "params": {"command": "pytest"}}]),
    ]
    query = ContextQuery(purpose="planning", task_description="run tests on changed files", token_budget=4000)
    bundle = assembler.assemble(query, episodes, procedures=procedures)
    all_text = " ".join(c["text"] for c in bundle.contents)
    assert "run-tests" in all_text


def test_assemble_reflection_context_prioritizes_failures():
    assembler = ContextAssembler()
    success_ep = Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="task A", outcome="completed")
    failure_ep = Episode(episode_type=EpisodeType.TASK_EXECUTION, trigger="task B", outcome="failed",
                         lessons=["don't do X"])
    query = ContextQuery(purpose="reflection", task_description="analyze recent work", token_budget=500)
    bundle = assembler.assemble(query, [success_ep, failure_ep])
    # Failure episode should appear first in reflection context
    first_text = bundle.contents[0]["text"]
    assert "failed" in first_text.lower() or "don't do X" in first_text

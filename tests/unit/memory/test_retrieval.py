from atlas.contracts.types import ContextQuery, Episode
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

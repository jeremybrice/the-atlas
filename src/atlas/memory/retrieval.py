"""Context Assembler — builds token-budgeted context bundles for Claude Code prompts."""

from __future__ import annotations

from atlas.contracts.types import ContextBundle, ContextQuery, Episode


class ContextAssembler:
    """Assembles context from episodes into token-budgeted bundles."""

    CHARS_PER_TOKEN = 4  # rough approximation

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(text) // self.CHARS_PER_TOKEN

    def assemble(self, query: ContextQuery, episodes: list[Episode]) -> ContextBundle:
        if not episodes:
            return ContextBundle(budget_tokens=query.token_budget)

        # Most recent first (episodes should already be ordered, but ensure it)
        sorted_episodes = list(reversed(episodes))

        contents: list[dict] = []
        total_tokens = 0

        for episode in sorted_episodes:
            text = self._episode_to_text(episode)
            tokens = self.estimate_tokens(text)

            if total_tokens + tokens > query.token_budget:
                # Try to fit a truncated version
                remaining = query.token_budget - total_tokens
                if remaining > 20:  # worth including something
                    truncated = text[: remaining * self.CHARS_PER_TOKEN]
                    contents.append({
                        "source": episode.trigger,
                        "text": truncated,
                        "tokens": remaining,
                        "truncated": True,
                    })
                    total_tokens += remaining
                break

            contents.append({
                "source": episode.trigger,
                "text": text,
                "tokens": tokens,
                "truncated": False,
            })
            total_tokens += tokens

        return ContextBundle(
            contents=contents,
            total_tokens=total_tokens,
            budget_tokens=query.token_budget,
        )

    def _episode_to_text(self, episode: Episode) -> str:
        parts = []
        if episode.trigger:
            parts.append(f"Trigger: {episode.trigger}")
        if episode.plan:
            parts.append(f"Plan: {episode.plan}")
        if episode.outcome:
            parts.append(f"Outcome: {episode.outcome}")
        if episode.lessons:
            parts.append(f"Lessons: {', '.join(episode.lessons)}")
        return "\n".join(parts)

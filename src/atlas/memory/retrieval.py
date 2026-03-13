"""Context Assembler — builds token-budgeted context bundles for Claude Code prompts."""

from __future__ import annotations

from atlas.contracts.types import ContextBundle, ContextQuery, Episode, Procedure


class ContextAssembler:
    """Assembles context from episodes into token-budgeted bundles.

    Supports purpose-aware ranking:
    - planning: includes procedures, prioritizes recent similar episodes
    - reflection: sorts failed episodes before successful ones
    - forge: prioritizes skill-creation episodes
    - default: recency-based
    """

    CHARS_PER_TOKEN = 4  # rough approximation

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(text) // self.CHARS_PER_TOKEN

    def assemble(
        self,
        query: ContextQuery,
        episodes: list[Episode],
        procedures: list[Procedure] | None = None,
    ) -> ContextBundle:
        if not episodes and not procedures:
            return ContextBundle(budget_tokens=query.token_budget)

        # Sort episodes based on purpose
        sorted_episodes = self._sort_for_purpose(query.purpose, episodes)

        contents: list[dict] = []
        total_tokens = 0

        # For planning purpose, include procedures first
        if query.purpose == "planning" and procedures:
            for proc in procedures:
                text = self._procedure_to_text(proc)
                tokens = self.estimate_tokens(text)
                if total_tokens + tokens > query.token_budget:
                    break
                contents.append({
                    "source": f"procedure:{proc.name}",
                    "text": text,
                    "tokens": tokens,
                    "truncated": False,
                })
                total_tokens += tokens

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

    def _sort_for_purpose(self, purpose: str, episodes: list[Episode]) -> list[Episode]:
        if purpose == "reflection":
            # Failed episodes first, then successful
            failed = [e for e in episodes if e.outcome == "failed"]
            others = [e for e in episodes if e.outcome != "failed"]
            return list(reversed(failed)) + list(reversed(others))
        # Default: most recent first
        return list(reversed(episodes))

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

    def _procedure_to_text(self, proc: Procedure) -> str:
        parts = [
            f"Procedure: {proc.name}",
            f"Description: {proc.description}",
            f"Trigger: {proc.trigger_pattern}",
            f"Success rate: {proc.success_rate:.0%}",
        ]
        return "\n".join(parts)

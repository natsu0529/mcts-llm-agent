"""The contract between the search engine and any coding-agent CLI.

Implementing this protocol for a new agent is the primary way to extend agent-mcts:
the search core never imports a concrete adapter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field


class AdapterError(RuntimeError):
    """Infrastructure failure: binary missing, timeout, unparseable output.

    Distinct from the *agent* reporting an error, which is a valid episode
    result (`EpisodeResult.is_error`) — the engine scores those branches low
    instead of crashing the run.
    """


class EpisodeResult(BaseModel):
    """Outcome of one agent episode (one node expansion)."""

    session_id: str
    summary: str  # the agent's final message
    cost_usd: float = 0.0
    duration_s: float = 0.0
    is_error: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)  # full agent-native payload


class AgentBackend(Protocol):
    """A coding agent that can run one episode in a directory, optionally forking a session."""

    @property
    def name(self) -> str: ...

    async def run_episode(
        self,
        prompt: str,
        workdir: Path,
        *,
        resume_session: str | None = None,
    ) -> EpisodeResult:
        """Run the agent on `prompt` with `workdir` as its working tree.

        `resume_session` forks the given session so the episode inherits its
        conversation without mutating it. Raises `AdapterError` on
        infrastructure failure.
        """
        ...

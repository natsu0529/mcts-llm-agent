"""The contract between the search engine and any coding-agent CLI.

Implementing this protocol for a new agent is the primary way to extend agent-mcts:
the search core never imports a concrete adapter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Token counts for one episode, for backends that meter usage but not dollars."""

    input_tokens: int = 0
    cached_input_tokens: int = 0  # subset of input_tokens served from cache, if reported
    output_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class AdapterError(RuntimeError):
    """Infrastructure failure: binary missing, timeout, unparseable output.

    Distinct from the *agent* reporting an error, which is a valid episode
    result (`EpisodeResult.is_error`) — the engine scores those branches low
    instead of crashing the run.

    `cost_known` is False whenever the failure happened *after* the agent
    process started: spend is billed as the episode runs but is only reported
    in the final payload, so any failure that loses that payload also loses the
    number. Failures that precede execution (no binary, bad arguments) cost
    nothing and keep the default True.
    """

    def __init__(self, message: str, *, cost_known: bool = True) -> None:
        super().__init__(message)
        self.cost_known = cost_known


class AdapterTimeout(AdapterError):
    """An agent episode exceeded its wall-clock timeout.

    Claude reports cost only in its final result payload, so a killed episode's
    spend is unknown even though it may have done useful work in the worktree.
    """

    def __init__(self, message: str, *, duration_s: float) -> None:
        super().__init__(message, cost_known=False)
        self.duration_s = duration_s


class EpisodeResult(BaseModel):
    """Outcome of one agent episode (one node expansion)."""

    session_id: str
    summary: str  # the agent's final message
    cost_usd: float | None = 0.0  # None: this backend never reports a dollar figure
    cost_known: bool = True  # False when a cost figure was expected but lost
    usage: TokenUsage | None = None  # token counts, when the backend reports them
    duration_s: float = 0.0
    is_error: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)  # full agent-native payload


class AgentBackend(Protocol):
    """A coding agent that can run one episode in a directory, optionally forking a session."""

    @property
    def name(self) -> str: ...

    @property
    def reports_cost(self) -> bool:
        """Whether completed episodes carry a dollar figure.

        False means the backend meters tokens (or nothing) but never dollars, so
        `max_cost_usd` cannot be enforced: its episodes return `cost_usd=None`, count
        $0 toward the ceiling, and the search is bounded by `max_nodes`. This is
        distinct from a *lost* figure (`cost_known=False`), which still stops the search.
        """
        ...

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

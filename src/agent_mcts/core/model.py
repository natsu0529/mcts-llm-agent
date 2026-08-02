"""Search-tree data model: nodes, run metadata, and the in-memory tree."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class NodeStatus(StrEnum):
    PENDING = "pending"  # created, agent has not run yet
    RUNNING = "running"  # agent episode in flight
    EVALUATED = "evaluated"  # episode finished and value function scored it
    FAILED = "failed"  # episode errored or was cut off by budget


class Node(BaseModel):
    """One search-tree node = one agent attempt over an isolated worktree."""

    id: str
    parent_id: str | None = None
    status: NodeStatus = NodeStatus.PENDING

    prompt: str = ""  # what this expansion asked the agent to do
    summary: str = ""  # the agent's final message for this episode
    session_id: str | None = None  # agent session backing this node
    branch: str | None = None  # git branch holding this node's code snapshot

    reward: float | None = None  # this node's own evaluation in [0, 1]
    visits: int = 0  # MCTS N
    value_sum: float = 0.0  # MCTS W

    cost_usd: float = 0.0
    duration_s: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def q(self) -> float:
        """Mean backed-up value (0.0 while unvisited)."""
        return self.value_sum / self.visits if self.visits else 0.0


class RunMeta(BaseModel):
    """Immutable metadata for one search run."""

    run_id: str
    task: str
    agent: str = "claude"
    repo_root: str
    base_commit: str | None = None  # commit the root worktree was created from
    created_at: datetime = Field(default_factory=_utcnow)


class Tree:
    """In-memory search tree. Persistence lives in `journal`; policy lives in the engine."""

    def __init__(self, meta: RunMeta) -> None:
        self.meta = meta
        self.nodes: dict[str, Node] = {}

    @property
    def root(self) -> Node | None:
        return next((n for n in self.nodes.values() if n.parent_id is None), None)

    def add(self, node: Node) -> Node:
        if node.id in self.nodes:
            raise ValueError(f"duplicate node id: {node.id}")
        if node.parent_id is not None and node.parent_id not in self.nodes:
            raise ValueError(f"unknown parent id: {node.parent_id}")
        if node.parent_id is None and self.root is not None:
            raise ValueError("tree already has a root")
        self.nodes[node.id] = node
        return node

    def next_id(self) -> str:
        return f"n{len(self.nodes)}"

    def children(self, node_id: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.parent_id == node_id]

    def path(self, node_id: str) -> list[Node]:
        """Nodes from the root down to (and including) `node_id`."""
        out: list[Node] = []
        current: str | None = node_id
        while current is not None:
            node = self.nodes[current]
            out.append(node)
            current = node.parent_id
        out.reverse()
        return out

    def best(self) -> Node | None:
        """Highest-reward evaluated node — the branch `apply` offers by default."""
        scored = [n for n in self.nodes.values() if n.reward is not None]
        return max(scored, key=lambda n: n.reward or 0.0) if scored else None

    def backup(self, node_id: str, value: float) -> list[Node]:
        """Propagate `value` from `node_id` to the root; returns the updated nodes."""
        updated = self.path(node_id)
        for node in updated:
            node.visits += 1
            node.value_sum += value
        return updated

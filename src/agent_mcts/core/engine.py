"""The UCT search loop: wires an agent adapter, worktrees, a value function, and the journal.

Policy summary (see docs/design.md):
- one node expansion = one complete agent episode over an isolated worktree
- expand-first with fixed widths (root_width diverse attempts, refine_width revisions)
- UCT descent with c = sqrt(2) by default; failed episodes back up 0
- anytime: every state change is journaled, so Ctrl-C leaves a valid tree
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from agent_mcts.adapters.base import AdapterError, AdapterTimeout, AgentBackend
from agent_mcts.core import journal, prompts
from agent_mcts.core.model import Node, NodeStatus, Tree
from agent_mcts.core.value import ValueFunction
from agent_mcts.core.worktree import WorktreeManager


class SearchConfig(BaseModel):
    max_nodes: int = 12  # episode budget (the root baseline is not an episode)
    max_cost_usd: float = 10.0
    c_uct: float = 1.414  # sqrt(2), the classic UCT exploration constant
    root_width: int = 3  # diverse first attempts under the root
    refine_width: int = 2  # revision children per non-root node
    max_depth: int = 3  # root is depth 0
    success_threshold: float = 0.999  # stop as soon as a node scores this high


class SearchEngine:
    """Runs one search. Sequential in v0.1; parallel expansion is roadmapped."""

    def __init__(
        self,
        *,
        tree: Tree,
        adapter: AgentBackend,
        value_fn: ValueFunction,
        worktrees: WorktreeManager,
        journal_path: Path,
        config: SearchConfig | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.tree = tree
        self.adapter = adapter
        self.value_fn = value_fn
        self.worktrees = worktrees
        self.journal_path = journal_path
        self.config = config or SearchConfig()
        self.on_change = on_change  # reassignable: the live TUI attaches itself here

    @property
    def total_cost_usd(self) -> float:
        return sum(n.cost_usd for n in self.tree.nodes.values())

    @property
    def unknown_cost_episodes(self) -> int:
        return sum(not n.cost_known for n in self.tree.nodes.values())

    @property
    def episodes(self) -> int:
        return max(0, len(self.tree.nodes) - 1)

    async def run(self) -> Tree:
        if self.tree.root is None:
            await self._init_root()
        while self._within_budget():
            parent = self._select()
            if parent is None:
                break  # every node is at width/depth capacity
            node = await self._expand(parent)
            if (
                node.status is NodeStatus.EVALUATED
                and (node.reward or 0.0) >= self.config.success_threshold
            ):
                break
        return self.tree

    # -- setup ---------------------------------------------------------------

    async def _init_root(self) -> None:
        journal.append_meta(self.journal_path, self.tree.meta)
        root = self.tree.add(Node(id=self.tree.next_id(), status=NodeStatus.RUNNING))
        self._journal([root])

        self.worktrees.create(root.id)
        root.branch = self.worktrees.branch_name(root.id)
        evaluation = await self.value_fn.evaluate(self.worktrees.worktree_path(root.id))
        root.reward = evaluation.score
        root.eval_detail = evaluation.detail
        root.status = NodeStatus.EVALUATED
        self.tree.backup(root.id, evaluation.score)
        self._journal([root])

    # -- selection -----------------------------------------------------------

    def _width(self, node: Node) -> int:
        return self.config.root_width if node.parent_id is None else self.config.refine_width

    def _depth(self, node: Node) -> int:
        return len(self.tree.path(node.id)) - 1

    def _can_expand(self, node: Node) -> bool:
        return (
            node.status is NodeStatus.EVALUATED
            and self._depth(node) < self.config.max_depth
            and len(self.tree.children(node.id)) < self._width(node)
        )

    def _subtree_has_capacity(self, node: Node) -> bool:
        if self._can_expand(node):
            return True
        return any(self._subtree_has_capacity(c) for c in self.tree.children(node.id))

    def _uct(self, parent: Node, child: Node) -> float:
        explore = math.sqrt(math.log(max(parent.visits, 1)) / child.visits)
        return child.q + self.config.c_uct * explore

    def _select(self) -> Node | None:
        """Descend from the root; expand at the first node with spare width."""
        root = self.tree.root
        if root is None:
            return None
        node: Node = root
        while True:
            if self._can_expand(node):
                return node
            viable = [c for c in self.tree.children(node.id) if self._subtree_has_capacity(c)]
            if not viable:
                return None
            parent = node
            node = max(viable, key=lambda c: self._uct(parent, c))

    # -- expansion -----------------------------------------------------------

    async def _expand(self, parent: Node) -> Node:
        siblings = [c.summary for c in self.tree.children(parent.id)]
        if parent.parent_id is None:
            prompt = prompts.root_attempt_prompt(self.tree.meta.task, parent.eval_detail, siblings)
        else:
            prompt = prompts.revision_prompt(
                self.tree.meta.task, parent.reward or 0.0, parent.eval_detail, siblings
            )

        node = self.tree.add(
            Node(
                id=self.tree.next_id(),
                parent_id=parent.id,
                status=NodeStatus.RUNNING,
                prompt=prompt,
            )
        )
        self._journal([node])

        workdir = self.worktrees.create(node.id, base=parent.branch)
        try:
            result = await self.adapter.run_episode(
                prompt, workdir, resume_session=parent.session_id
            )
            node.session_id = result.session_id
            node.summary = result.summary
            node.cost_usd = result.cost_usd
            node.duration_s = result.duration_s
            if result.is_error:
                self.worktrees.commit_all(node.id, message=f"agent-mcts partial {node.id}")
                node.branch = self.worktrees.branch_name(node.id)
                node.status = NodeStatus.FAILED
                node.reward = 0.0
                node.eval_detail = f"agent reported an error: {result.summary}"
            else:
                self.worktrees.commit_all(node.id)
                node.branch = self.worktrees.branch_name(node.id)
                evaluation = await self.value_fn.evaluate(workdir)
                node.reward = evaluation.score
                node.eval_detail = evaluation.detail
                node.status = NodeStatus.EVALUATED
        except AdapterError as exc:
            # A timed-out or crashed agent may still have produced valuable edits. Snapshot
            # them before CLI cleanup removes the disposable worktree, while keeping the
            # node failed so an incomplete attempt can never become the automatic best.
            self.worktrees.commit_all(node.id, message=f"agent-mcts partial {node.id}")
            node.branch = self.worktrees.branch_name(node.id)
            node.status = NodeStatus.FAILED
            node.reward = 0.0
            node.eval_detail = str(exc)
            node.summary = "Agent failed; partial worktree state was preserved for inspection."
            if isinstance(exc, AdapterTimeout):
                node.duration_s = exc.duration_s
                node.cost_known = False

        updated = self.tree.backup(node.id, node.reward or 0.0)
        self._journal(updated)
        return node

    # -- bookkeeping ----------------------------------------------------------

    def _within_budget(self) -> bool:
        return (
            self.episodes < self.config.max_nodes
            and self.total_cost_usd < self.config.max_cost_usd
            and self.unknown_cost_episodes == 0
        )

    def _journal(self, nodes: list[Node]) -> None:
        for node in nodes:
            journal.append_node(self.journal_path, node)
        if self.on_change is not None:
            self.on_change()

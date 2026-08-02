"""Engine tests drive the real Tree/WorktreeManager/journal against fake agents.

The fake backend mutates the worktree (so snapshots are real commits) and the
scripted value function returns a fixed score sequence. Score index 0 is always
the root baseline.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agent_mcts.adapters.base import AdapterError, EpisodeResult
from agent_mcts.core import journal
from agent_mcts.core.engine import SearchConfig, SearchEngine
from agent_mcts.core.model import NodeStatus, RunMeta, Tree
from agent_mcts.core.value import Evaluation
from agent_mcts.core.worktree import WorktreeManager


class FakeBackend:
    def __init__(self, *, cost_usd: float = 0.01, fail_calls: set[int] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.cost_usd = cost_usd
        self.fail_calls = fail_calls or set()

    @property
    def name(self) -> str:
        return "fake"

    async def run_episode(
        self, prompt: str, workdir: Path, *, resume_session: str | None = None
    ) -> EpisodeResult:
        call_no = len(self.calls) + 1
        self.calls.append({"prompt": prompt, "workdir": workdir, "resume": resume_session})
        if call_no in self.fail_calls:
            raise AdapterError("infrastructure exploded")
        (workdir / f"attempt_{call_no}.txt").write_text("work\n")
        return EpisodeResult(
            session_id=f"s{call_no}", summary=f"approach {call_no}", cost_usd=self.cost_usd
        )


class ScriptedValue:
    def __init__(self, scores: list[float]) -> None:
        self.scores = list(scores)

    async def evaluate(self, workdir: Path) -> Evaluation:
        score = self.scores.pop(0)
        return Evaluation(score=score, detail=f"scored {score} in {workdir.name}")


def run_search(
    repo: Path, scores: list[float], config: SearchConfig, backend: FakeBackend | None = None
) -> tuple[Tree, FakeBackend, Path]:
    meta = RunMeta(run_id="r1", task="make the tests pass", repo_root=str(repo))
    backend = backend or FakeBackend()
    journal_path = repo / ".agent-mcts" / "runs" / "r1" / "tree.jsonl"
    engine = SearchEngine(
        tree=Tree(meta),
        adapter=backend,
        value_fn=ScriptedValue(scores),
        worktrees=WorktreeManager(repo, "r1"),
        journal_path=journal_path,
        config=config,
    )
    tree = asyncio.run(engine.run())
    return tree, backend, journal_path


def test_root_baseline_then_diverse_children(repo: Path) -> None:
    config = SearchConfig(max_nodes=3, root_width=3)
    tree, backend, journal_path = run_search(repo, [0.1, 0.5, 0.6, 0.7], config)

    root = tree.root
    assert root is not None
    assert root.reward == pytest.approx(0.1)  # baseline evaluated without an episode
    assert root.status is NodeStatus.EVALUATED

    children = tree.children(root.id)
    assert len(children) == 3  # all budget spent on diverse root attempts
    assert all(c.status is NodeStatus.EVALUATED for c in children)
    assert all(c.branch and c.session_id for c in children)

    # Root attempts start fresh sessions (nothing to fork) and mention the task.
    assert all(call["resume"] is None for call in backend.calls)
    assert "make the tests pass" in backend.calls[0]["prompt"]
    # Later siblings are steered away from earlier approaches.
    assert "approach 1" in backend.calls[2]["prompt"]

    # The journal replays to the same tree.
    loaded = journal.load(journal_path)
    assert loaded.nodes.keys() == tree.nodes.keys()
    assert loaded.nodes[children[0].id] == children[0]


def test_uct_descends_into_promising_branch(repo: Path) -> None:
    config = SearchConfig(max_nodes=3, root_width=2, refine_width=2, c_uct=0.5)
    tree, backend, _ = run_search(repo, [0.0, 0.9, 0.1, 0.5], config)

    root = tree.root
    assert root is not None
    strong, weak = tree.children(root.id)
    assert strong.reward == pytest.approx(0.9)
    revisions = tree.children(strong.id)

    assert len(revisions) == 1  # third episode revised the strong attempt...
    assert tree.children(weak.id) == []  # ...not the weak one
    # The revision forked the strong attempt's session and saw its feedback.
    assert backend.calls[2]["resume"] == strong.session_id
    assert "0.90" in backend.calls[2]["prompt"]
    assert "scored 0.9" in backend.calls[2]["prompt"]


def test_stops_early_on_success(repo: Path) -> None:
    config = SearchConfig(max_nodes=10, root_width=3)
    tree, backend, _ = run_search(repo, [0.0, 1.0], config)

    assert len(backend.calls) == 1  # solved on the first attempt → no more spending
    best = tree.best()
    assert best is not None and best.reward == 1.0


def test_stops_on_cost_budget(repo: Path) -> None:
    config = SearchConfig(max_nodes=10, max_cost_usd=10.0, root_width=5)
    _tree, backend, _ = run_search(
        repo, [0.0, 0.2, 0.3, 0.4], config, backend=FakeBackend(cost_usd=6.0)
    )

    assert len(backend.calls) == 2  # 6 + 6 crosses the $10 line, third never starts


def test_stops_when_tree_is_saturated(repo: Path) -> None:
    config = SearchConfig(max_nodes=50, root_width=1, refine_width=1, max_depth=2)
    tree, backend, _ = run_search(repo, [0.0, 0.2, 0.3], config)

    # Capacity is root->n1->n2 and nothing else; the engine must stop by itself.
    assert len(backend.calls) == 2
    assert len(tree.nodes) == 3


def test_adapter_failure_marks_node_and_continues(repo: Path) -> None:
    config = SearchConfig(max_nodes=3, root_width=3)
    tree, backend, _ = run_search(
        repo, [0.0, 0.5, 0.6], config, backend=FakeBackend(fail_calls={2})
    )

    root = tree.root
    assert root is not None
    children = tree.children(root.id)
    failed = [c for c in children if c.status is NodeStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].reward == 0.0
    assert "infrastructure exploded" in failed[0].eval_detail
    assert len(backend.calls) == 3  # the run survived the failure


def test_agent_reported_error_fails_node(repo: Path) -> None:
    class ErroringBackend(FakeBackend):
        async def run_episode(
            self, prompt: str, workdir: Path, *, resume_session: str | None = None
        ) -> EpisodeResult:
            self.calls.append({"prompt": prompt, "workdir": workdir, "resume": resume_session})
            return EpisodeResult(session_id="s1", summary="I crashed", is_error=True)

    config = SearchConfig(max_nodes=1, root_width=1)
    tree, _, _ = run_search(repo, [0.0], config, backend=ErroringBackend())

    root = tree.root
    assert root is not None
    (child,) = tree.children(root.id)
    assert child.status is NodeStatus.FAILED
    assert child.branch is None  # nothing was snapshotted
    assert root.q < 0.5  # the failure backed up as 0

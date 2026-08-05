"""Engine tests drive the real Tree/WorktreeManager/journal against fake agents.

The fake backend mutates the worktree (so snapshots are real commits) and the
scripted value function returns a fixed score sequence. Score index 0 is always
the root baseline.
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_mcts.adapters.base import AdapterError, AdapterTimeout, EpisodeResult
from agent_mcts.core import journal
from agent_mcts.core.engine import SearchConfig, SearchEngine
from agent_mcts.core.model import NodeStatus, RunMeta, Tree
from agent_mcts.core.value import Evaluation
from agent_mcts.core.worktree import GitError, WorktreeManager


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
    assert failed[0].branch is not None  # even failed attempts retain an inspectable snapshot
    assert "infrastructure exploded" in failed[0].eval_detail
    assert len(backend.calls) == 3  # the run survived the failure


def test_timeout_preserves_partial_work_marks_cost_unknown_and_stops(repo: Path) -> None:
    class TimingOutBackend(FakeBackend):
        async def run_episode(
            self, prompt: str, workdir: Path, *, resume_session: str | None = None
        ) -> EpisodeResult:
            self.calls.append({"prompt": prompt, "workdir": workdir, "resume": resume_session})
            (workdir / "partial.txt").write_text("useful unfinished work\n")
            raise AdapterTimeout("episode timed out", duration_s=12.5)

    config = SearchConfig(max_nodes=3, root_width=3)
    tree, backend, _ = run_search(repo, [0.0], config, backend=TimingOutBackend())

    root = tree.root
    assert root is not None
    (child,) = tree.children(root.id)
    assert child.status is NodeStatus.FAILED
    assert child.branch is not None
    assert child.duration_s == pytest.approx(12.5)
    assert not child.cost_known
    assert len(backend.calls) == 1  # unknown spend makes the cost ceiling unenforceable
    saved = subprocess.run(
        ["git", "show", f"{child.branch}:partial.txt"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert saved == "useful unfinished work\n"


def test_non_timeout_failure_after_launch_marks_cost_unknown_and_stops(repo: Path) -> None:
    """A crash after the agent started also loses the cost report, not just a timeout.

    Claude bills as it works and only reports the total in its final payload, so bad
    JSON / an empty result / a missing session_id leave the spend unmeasured. Treating
    those as $0 lets the search keep burning money past the ceiling.
    """

    class CrashingBackend(FakeBackend):
        async def run_episode(
            self, prompt: str, workdir: Path, *, resume_session: str | None = None
        ) -> EpisodeResult:
            self.calls.append({"prompt": prompt, "workdir": workdir, "resume": resume_session})
            (workdir / "partial.txt").write_text("work done before the crash\n")
            raise AdapterError("claude exited with no JSON payload", cost_known=False)

    config = SearchConfig(max_nodes=3, max_cost_usd=0.01, root_width=3)
    tree, backend, _ = run_search(repo, [0.0], config, backend=CrashingBackend())

    root = tree.root
    assert root is not None
    (child,) = tree.children(root.id)
    assert child.status is NodeStatus.FAILED
    assert not child.cost_known
    assert len(backend.calls) == 1  # the search stopped instead of spending blind
    assert child.branch is not None
    saved = subprocess.run(
        ["git", "show", f"{child.branch}:partial.txt"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert saved == "work done before the crash\n"


def test_prelaunch_failure_keeps_cost_known(repo: Path) -> None:
    """A failure that never ran the agent costs nothing and must not stall the search."""
    config = SearchConfig(max_nodes=3, root_width=3)
    tree, backend, _ = run_search(
        repo, [0.0, 0.5, 0.6], config, backend=FakeBackend(fail_calls={1})
    )

    root = tree.root
    assert root is not None
    failed = next(c for c in tree.children(root.id) if c.status is NodeStatus.FAILED)
    assert failed.cost_known
    assert len(backend.calls) == 3


def test_result_without_cost_marks_the_node_unknown(repo: Path) -> None:
    class UnpricedBackend(FakeBackend):
        async def run_episode(
            self, prompt: str, workdir: Path, *, resume_session: str | None = None
        ) -> EpisodeResult:
            self.calls.append({"prompt": prompt, "workdir": workdir, "resume": resume_session})
            (workdir / "work.txt").write_text("done\n")
            return EpisodeResult(session_id="s1", summary="ok", cost_usd=0.0, cost_known=False)

    config = SearchConfig(max_nodes=3, root_width=3)
    tree, backend, _ = run_search(repo, [0.0, 0.5], config, backend=UnpricedBackend())

    root = tree.root
    assert root is not None
    (child,) = tree.children(root.id)
    assert child.status is NodeStatus.EVALUATED  # the episode itself succeeded
    assert not child.cost_known
    assert len(backend.calls) == 1  # ...but the budget is no longer enforceable


def test_interrupt_preserves_partial_work(repo: Path) -> None:
    """Ctrl-C mid-episode must leave a snapshotted branch, not a permanent RUNNING node."""

    class CancellingBackend(FakeBackend):
        async def run_episode(
            self, prompt: str, workdir: Path, *, resume_session: str | None = None
        ) -> EpisodeResult:
            self.calls.append({"prompt": prompt, "workdir": workdir, "resume": resume_session})
            (workdir / "partial.txt").write_text("half-finished but valuable\n")
            raise asyncio.CancelledError

    meta = RunMeta(run_id="r1", task="t", repo_root=str(repo))
    backend = CancellingBackend()
    worktrees = WorktreeManager(repo, "r1")
    journal_path = repo / ".agent-mcts" / "runs" / "r1" / "tree.jsonl"
    engine = SearchEngine(
        tree=Tree(meta),
        adapter=backend,
        value_fn=ScriptedValue([0.0]),
        worktrees=worktrees,
        journal_path=journal_path,
        config=SearchConfig(max_nodes=3, root_width=3),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(engine.run())

    root = engine.tree.root
    assert root is not None
    (child,) = engine.tree.children(root.id)
    assert child.status is NodeStatus.FAILED  # not stuck RUNNING
    assert child.branch is not None
    assert not child.cost_known
    assert "interrupted" in child.eval_detail

    worktrees.cleanup()  # what the CLI's finally block does
    saved = subprocess.run(
        ["git", "show", f"{child.branch}:partial.txt"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert saved == "half-finished but valuable\n"
    # The interrupted node is on disk, so `show` works after the process dies.
    assert journal.load(journal_path).nodes[child.id].branch == child.branch


def test_snapshot_commit_failure_keeps_the_worktree(repo: Path) -> None:
    """A repo hook must not be able to delete the rescue snapshot it just rejected.

    `--no-verify` handles pre-commit hooks; this covers whatever still gets through
    (here: an unwritable index) by keeping the worktree on disk and surfacing the
    original failure rather than a git error on top of it.
    """

    class TimingOutBackend(FakeBackend):
        async def run_episode(
            self, prompt: str, workdir: Path, *, resume_session: str | None = None
        ) -> EpisodeResult:
            self.calls.append({"prompt": prompt, "workdir": workdir, "resume": resume_session})
            (workdir / "partial.txt").write_text("unfinished\n")
            raise AdapterTimeout("episode timed out", duration_s=1.0)

    meta = RunMeta(run_id="r1", task="t", repo_root=str(repo))

    class BrokenCommit(WorktreeManager):
        def commit_all(self, node_id: str, message: str | None = None) -> str:
            if node_id != "n0":  # let the root baseline through
                raise GitError("pre-commit hook rejected the snapshot")
            return super().commit_all(node_id, message)

    broken = BrokenCommit(repo, "r1")
    engine = SearchEngine(
        tree=Tree(meta),
        adapter=TimingOutBackend(),
        value_fn=ScriptedValue([0.0]),
        worktrees=broken,
        journal_path=repo / ".agent-mcts" / "runs" / "r1" / "tree.jsonl",
        config=SearchConfig(max_nodes=3, root_width=3),
    )
    tree = asyncio.run(engine.run())

    root = tree.root
    assert root is not None
    (child,) = tree.children(root.id)
    assert child.status is NodeStatus.FAILED
    assert "episode timed out" in child.eval_detail  # the real cause is not masked
    assert "pre-commit hook rejected" in child.eval_detail
    assert child.id in broken.preserved

    broken.cleanup()
    kept = broken.preserved[child.id] / "partial.txt"
    assert kept.read_text() == "unfinished\n"  # survived the cleanup that would erase it


def test_snapshot_commit_survives_a_failing_pre_commit_hook(repo: Path) -> None:
    """The normal path: internal snapshots bypass hooks and signing entirely."""
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'no commits for you' >&2\nexit 1\n")
    hook.chmod(0o755)
    subprocess.run(
        ["git", "config", "commit.gpgsign", "true"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.signingkey", "DOESNOTEXIST"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    config = SearchConfig(max_nodes=1, root_width=1)
    tree, _, _ = run_search(repo, [0.0, 0.7], config)

    root = tree.root
    assert root is not None
    (child,) = tree.children(root.id)
    assert child.status is NodeStatus.EVALUATED
    assert child.branch is not None
    assert (
        subprocess.run(
            ["git", "show", f"{child.branch}:attempt_1.txt"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        == "work\n"
    )


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
    assert child.branch is not None  # error results can still contain useful partial edits
    assert root.q < 0.5  # the failure backed up as 0

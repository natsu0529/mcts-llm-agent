import subprocess
from pathlib import Path

import pytest

from agent_mcts.core.worktree import GitError, WorktreeManager


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.name", "Test")
    run("config", "user.email", "test@example.com")
    (root / "app.py").write_text("print('hi')\n")
    run("add", "-A")
    run("commit", "-qm", "init")
    return root


def test_create_snapshots_and_isolation(repo: Path) -> None:
    mgr = WorktreeManager(repo, run_id="r1")

    wt_a = mgr.create("n1")
    wt_b = mgr.create("n2")
    (wt_a / "a.txt").write_text("from n1\n")
    (wt_b / "b.txt").write_text("from n2\n")

    assert not (wt_a / "b.txt").exists()
    assert not (wt_b / "a.txt").exists()
    assert not (repo / "a.txt").exists()  # user's tree untouched

    sha_a = mgr.commit_all("n1")
    assert sha_a != mgr.current_head()


def test_child_branches_from_parent_snapshot(repo: Path) -> None:
    mgr = WorktreeManager(repo, run_id="r1")
    parent = mgr.create("n1")
    (parent / "feature.py").write_text("x = 1\n")
    mgr.commit_all("n1")

    child = mgr.create("n2", base=mgr.branch_name("n1"))
    assert (child / "feature.py").read_text() == "x = 1\n"


def test_commit_all_is_noop_safe(repo: Path) -> None:
    mgr = WorktreeManager(repo, run_id="r1")
    mgr.create("n1")
    sha_first = mgr.commit_all("n1")
    sha_second = mgr.commit_all("n1")
    assert sha_first == sha_second


def test_cleanup_removes_worktrees_keeps_branches(repo: Path) -> None:
    mgr = WorktreeManager(repo, run_id="r1")
    wt = mgr.create("n1")
    mgr.commit_all("n1")
    mgr.cleanup()

    assert not wt.exists()
    branches = subprocess.run(
        ["git", "branch", "--list", "agent-mcts/r1/*"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "agent-mcts/r1/n1" in branches


def test_artifacts_are_git_excluded(repo: Path) -> None:
    WorktreeManager(repo, run_id="r1")
    exclude = (repo / ".git" / "info" / "exclude").read_text()
    assert ".agent-mcts/" in exclude
    # Idempotent: constructing again must not duplicate the entry.
    WorktreeManager(repo, run_id="r2")
    exclude = (repo / ".git" / "info" / "exclude").read_text()
    assert exclude.count(".agent-mcts/") == 1


def test_git_errors_are_reported(repo: Path) -> None:
    mgr = WorktreeManager(repo, run_id="r1")
    with pytest.raises(GitError, match="worktree"):
        mgr.remove("never-created")

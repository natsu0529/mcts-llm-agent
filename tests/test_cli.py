"""CLI end-to-end tests: a fake adapter is injected, everything else is real
(engine, worktrees, journal, value command, git)."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_mcts import __version__, cli
from agent_mcts.adapters.base import EpisodeResult

runner = CliRunner()

VALUE_CMD = "test -f attempt.txt"  # baseline lacks the file → 0.0; any episode → 1.0


class FakeAdapter:
    """Constructor-compatible stand-in for ClaudeCodeAdapter."""

    calls = 0

    def __init__(
        self,
        binary: str | None = None,
        *,
        model: str | None = None,
        permission_mode: str = "acceptEdits",
        timeout_s: float = 600.0,
    ) -> None:
        self.model = model

    @property
    def name(self) -> str:
        return "fake"

    async def run_episode(
        self, prompt: str, workdir: Path, *, resume_session: str | None = None
    ) -> EpisodeResult:
        FakeAdapter.calls += 1
        (workdir / "attempt.txt").write_text(f"episode {FakeAdapter.calls}\n")
        return EpisodeResult(
            session_id=f"s{FakeAdapter.calls}",
            summary=f"approach {FakeAdapter.calls}",
            cost_usd=0.5,
        )


@pytest.fixture
def project_repo(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "ClaudeCodeAdapter", FakeAdapter)
    FakeAdapter.calls = 0
    return repo


def do_run(args: list[str] | None = None) -> str:
    result = runner.invoke(
        cli.app, ["run", "fix the widget", "-y", "--value", VALUE_CMD, *(args or [])]
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_run_end_to_end(project_repo: Path) -> None:
    output = do_run(["-n", "3"])

    assert "Best:" in output and "n1" in output
    assert "Search finished: 1 episodes" in output  # perfect score → early stop
    journals = list((project_repo / ".agent-mcts" / "runs").glob("*/tree.jsonl"))
    assert len(journals) == 1
    # Worktrees are cleaned up; snapshot branches survive.
    branches = subprocess.run(
        ["git", "branch", "--list", "agent-mcts/*"],
        cwd=project_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "/n1" in branches
    assert not any((project_repo / ".agent-mcts" / "worktrees").rglob("attempt.txt"))


def test_show_tree_and_node(project_repo: Path) -> None:
    do_run()

    tree_view = runner.invoke(cli.app, ["show"])
    assert tree_view.exit_code == 0, tree_view.output
    assert "n0" in tree_view.output and "n1" in tree_view.output
    assert "best" in tree_view.output
    # UCT stats must survive rich markup (regression: [r=…] was parsed as a tag).
    assert "Q=" in tree_view.output and "r=1.00" in tree_view.output

    node_view = runner.invoke(cli.app, ["show", "n1"])
    assert node_view.exit_code == 0, node_view.output
    assert "prompt" in node_view.output
    assert "fix the widget" in node_view.output.replace("\n", " ")

    missing = runner.invoke(cli.app, ["show", "n9"])
    assert missing.exit_code == 1


def test_apply_stages_best_node(project_repo: Path) -> None:
    do_run()

    result = runner.invoke(cli.app, ["apply"])
    assert result.exit_code == 0, result.output
    assert "Staged" in result.output

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=project_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "attempt.txt" in staged


def test_apply_refuses_dirty_tree(project_repo: Path) -> None:
    do_run()
    (project_repo / "app.py").write_text("print('changed')\n")

    result = runner.invoke(cli.app, ["apply"])
    assert result.exit_code == 1
    assert "uncommitted" in result.output


def test_run_without_value_command_fails(project_repo: Path) -> None:
    result = runner.invoke(cli.app, ["run", "fix it", "-y"])
    assert result.exit_code == 1
    assert "--value" in result.output


def test_show_without_runs_fails(project_repo: Path) -> None:
    result = runner.invoke(cli.app, ["show"])
    assert result.exit_code == 1
    assert "no runs" in result.output

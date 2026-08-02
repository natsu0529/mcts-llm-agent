from typer.testing import CliRunner

from agent_mcts import __version__
from agent_mcts.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_run_is_stubbed() -> None:
    result = runner.invoke(app, ["run", "fix the tests"])
    assert result.exit_code == 1
    assert "pre-alpha" in result.output

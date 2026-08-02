import asyncio
from pathlib import Path

import pytest

from agent_mcts.core.value import CommandValueFunction, Evaluation


def evaluate(command: str, workdir: Path, timeout_s: float = 30.0) -> Evaluation:
    return asyncio.run(CommandValueFunction(command, timeout_s=timeout_s).evaluate(workdir))


def test_exit_zero_is_perfect(tmp_path: Path) -> None:
    result = evaluate("echo all good", tmp_path)
    assert result.score == 1.0
    assert "all good" in result.detail


def test_pytest_style_partial_credit(tmp_path: Path) -> None:
    result = evaluate("echo '=== 3 failed, 2 passed in 0.5s ==='; exit 1", tmp_path)
    assert result.score == pytest.approx(0.4)


def test_errors_count_against_score(tmp_path: Path) -> None:
    result = evaluate("echo '1 failed, 2 passed, 1 error in 1s'; exit 1", tmp_path)
    assert result.score == pytest.approx(0.5)


def test_unparseable_failure_is_zero(tmp_path: Path) -> None:
    result = evaluate("echo kaboom >&2; exit 2", tmp_path)
    assert result.score == 0.0
    assert "kaboom" in result.detail  # stderr is folded into the feedback


def test_timeout_is_zero(tmp_path: Path) -> None:
    result = evaluate("sleep 5", tmp_path, timeout_s=0.3)
    assert result.score == 0.0
    assert "timed out" in result.detail


def test_runs_in_workdir(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("here\n")
    result = evaluate("cat marker.txt", tmp_path)
    assert result.score == 1.0
    assert "here" in result.detail

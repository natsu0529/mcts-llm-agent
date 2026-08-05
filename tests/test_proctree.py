"""Tests for killing child process trees.

The Windows branch cannot be exercised on this runner, so it is tested at the seam:
`POSIX` is forced False and `subprocess.run` is captured, proving we issue
`taskkill /F /T` (the /T is what reaches the descendants) and that we still fall back
to a direct kill when taskkill is unavailable.
"""

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from agent_mcts import proctree


def test_kill_tree_reaches_grandchildren(tmp_path: Path) -> None:
    marker = tmp_path / "grandchild.txt"

    async def scenario() -> None:
        proc = await asyncio.create_subprocess_shell(
            f"(sleep 0.6; echo alive > {marker}) & sleep 30",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=proctree.POSIX,
        )
        await asyncio.sleep(0.1)
        await proctree.terminate_tree(proc)
        assert proc.returncode is not None

    asyncio.run(scenario())
    time.sleep(0.9)
    assert not marker.exists()


def test_terminate_tree_is_bounded_when_the_kill_does_not_land(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unkillable child must degrade to a delay, never to a hang."""
    def kill_nothing(_proc: asyncio.subprocess.Process) -> bool:
        return False

    monkeypatch.setattr(proctree, "REAP_GRACE_S", 0.3)
    monkeypatch.setattr(proctree, "kill_tree", kill_nothing)

    async def scenario() -> float:
        proc = await asyncio.create_subprocess_shell(
            "sleep 30", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        started = time.monotonic()
        await proctree.terminate_tree(proc)
        elapsed = time.monotonic() - started
        proc.kill()  # tidy up the survivor
        await proc.wait()
        return elapsed

    assert asyncio.run(scenario()) < 2.0


def test_windows_kill_uses_taskkill_with_the_tree_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        recorded.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(proctree, "POSIX", False)
    monkeypatch.setattr(proctree.subprocess, "run", fake_run)

    async def scenario() -> None:
        proc = await asyncio.create_subprocess_shell(
            "sleep 30", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        assert proctree.kill_tree(proc) is True
        assert recorded == [["taskkill", "/F", "/T", "/PID", str(proc.pid)]]
        proc.kill()  # our fake taskkill did not actually kill anything
        await proc.wait()

    asyncio.run(scenario())


def test_windows_falls_back_to_direct_kill_when_taskkill_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(proctree, "POSIX", False)
    monkeypatch.setattr(proctree.subprocess, "run", fake_run)
    monkeypatch.setattr(proctree, "REAP_GRACE_S", 2.0)

    async def scenario() -> int | None:
        proc = await asyncio.create_subprocess_shell(
            "sleep 30", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        assert proctree.kill_tree(proc) is False  # descendants would survive; the child does not
        await asyncio.wait_for(proc.wait(), timeout=2.0)
        return proc.returncode

    assert asyncio.run(scenario()) is not None


def test_kill_tree_is_a_noop_for_an_exited_process() -> None:
    async def scenario() -> None:
        proc = await asyncio.create_subprocess_shell(
            "true", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        await proc.wait()
        assert proctree.kill_tree(proc) is True

    asyncio.run(scenario())

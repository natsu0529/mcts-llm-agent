"""Codex adapter tests use a fake `codex` executable, so CI never calls a real API."""

import asyncio
import json
import os
import stat
import time
from pathlib import Path
from typing import Any

import pytest

from agent_mcts.adapters.base import AdapterError, AdapterTimeout
from agent_mcts.adapters.codex_cli import (
    ENV_BINARY_OVERRIDE,
    CodexCliAdapter,
    find_codex_binary,
)

EVENTS: list[dict[str, Any]] = [
    {"type": "thread.started", "thread_id": "sess-123"},
    {
        "type": "item.completed",
        "item": {"id": "item_1", "type": "agent_message", "text": "Fixed the test."},
    },
    {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
]


def make_fake_codex(
    directory: Path, events: list[dict[str, Any]] | None = None, *, sleep_s: float = 0.0
) -> Path:
    script = directory / "codex"
    body = "\n".join(json.dumps(event) for event in (events or EVENTS))
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "codex-cli 9.9.9"; exit 0; fi\n'
        f"sleep {sleep_s}\n"
        'printf "%s " "$@" > codex_args.txt\n'
        f"cat <<'EOF'\n{body}\nEOF\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_discovery_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = make_fake_codex(tmp_path)
    monkeypatch.setenv(ENV_BINARY_OVERRIDE, str(fake))
    assert find_codex_binary() == str(fake)


def test_discovery_fails_with_helpful_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_BINARY_OVERRIDE, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    with pytest.raises(AdapterError, match="No working `codex` binary"):
        find_codex_binary()


def test_run_episode_parses_jsonl_events(tmp_path: Path) -> None:
    fake = make_fake_codex(tmp_path)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = CodexCliAdapter(binary=str(fake))

    result = run(adapter.run_episode("fix it", workdir))

    assert result.session_id == "sess-123"
    assert result.summary == "Fixed the test."
    assert result.cost_usd == 0.0
    assert not result.cost_known
    assert not result.is_error


def test_run_episode_ignores_non_json_status_lines(tmp_path: Path) -> None:
    script = tmp_path / "codex"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "codex-cli 9.9.9"; exit 0; fi\n'
        'echo "Reading additional input from stdin..."\n'
        'echo \'{"type":"thread.started","thread_id":"sess-123"}\'\n'
        'echo \'{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\'\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = CodexCliAdapter(binary=str(script))

    result = run(adapter.run_episode("fix it", workdir))

    assert result.session_id == "sess-123"
    assert result.summary == "Done."


def test_run_episode_flags_and_cwd(tmp_path: Path) -> None:
    fake = make_fake_codex(tmp_path)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = CodexCliAdapter(binary=str(fake), model="gpt-5")

    run(adapter.run_episode("try again", workdir, resume_session="parent-sess"))

    args = (workdir / "codex_args.txt").read_text()
    for expected in (
        "exec",
        "--json",
        "--sandbox workspace-write",
        "--model gpt-5",
        "Continue from parent session parent-sess",
        "try again",
    ):
        assert expected in args


def test_agent_reported_error_is_a_result(tmp_path: Path) -> None:
    fake = make_fake_codex(
        tmp_path,
        [
            {"type": "session.started", "session_id": "sess-123"},
            {"type": "error", "message": "Something broke."},
        ],
    )
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = CodexCliAdapter(binary=str(fake))

    result = run(adapter.run_episode("fix it", workdir))
    assert result.is_error


def test_garbage_output_raises(tmp_path: Path) -> None:
    script = tmp_path / "codex"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "codex-cli 9.9.9"; exit 0; fi\n'
        'echo "not json at all"\nexit 1\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = CodexCliAdapter(binary=str(script))

    with pytest.raises(AdapterError, match="no JSON events"):
        run(adapter.run_episode("fix it", workdir))


def test_timeout_raises(tmp_path: Path) -> None:
    fake = make_fake_codex(tmp_path, sleep_s=5.0)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = CodexCliAdapter(binary=str(fake), timeout_s=0.3)

    with pytest.raises(AdapterTimeout, match="cost is unknown") as exc_info:
        run(adapter.run_episode("fix it", workdir))
    assert exc_info.value.duration_s >= 0.3
    assert not exc_info.value.cost_known


def test_cancellation_kills_the_agent(tmp_path: Path) -> None:
    marker = tmp_path / "still_running.txt"
    script = tmp_path / "codex"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "codex-cli 9.9.9"; exit 0; fi\n'
        "sleep 3\n"
        f"echo survived > {marker}\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = CodexCliAdapter(binary=str(script), timeout_s=30.0)

    async def cancel_mid_episode() -> None:
        task = asyncio.ensure_future(adapter.run_episode("fix it", workdir))
        await asyncio.sleep(0.4)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(cancel_mid_episode())

    time.sleep(3.2)
    assert not marker.exists()


def test_conforms_to_protocol(tmp_path: Path) -> None:
    from agent_mcts.adapters.base import AgentBackend

    fake = make_fake_codex(tmp_path)
    adapter: AgentBackend = CodexCliAdapter(binary=str(fake))
    assert adapter.name == "codex"


def test_fake_binary_is_executable_helper(tmp_path: Path) -> None:
    fake = make_fake_codex(tmp_path)
    assert os.access(fake, os.X_OK)

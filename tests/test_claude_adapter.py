"""Adapter tests run against a fake `claude` executable — no API calls, no cost.

The fake records its argv (proving flag plumbing and cwd) and prints a canned
payload shaped like the real `--output-format json` output observed in
docs/spikes/2026-08-02-session-fork-worktree.md.
"""

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from agent_mcts.adapters.base import AdapterError, AdapterTimeout
from agent_mcts.adapters.claude_code import (
    ENV_BINARY_OVERRIDE,
    ClaudeCodeAdapter,
    find_claude_binary,
)

PAYLOAD: dict[str, Any] = {
    "is_error": False,
    "session_id": "sess-123",
    "result": "Fixed the test.",
    "total_cost_usd": 0.0214,
    "duration_ms": 6662,
    "type": "result",
}


def make_fake_claude(
    directory: Path, payload: dict[str, Any] | None = None, *, sleep_s: float = 0.0
) -> Path:
    body = json.dumps(payload or PAYLOAD)
    script = directory / "claude"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "9.9.9"; exit 0; fi\n'
        f"sleep {sleep_s}\n"
        'printf "%s " "$@" > claude_args.txt\n'
        f"cat <<'EOF'\n{body}\nEOF\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_discovery_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = make_fake_claude(tmp_path)
    monkeypatch.setenv(ENV_BINARY_OVERRIDE, str(fake))
    assert find_claude_binary() == str(fake)


def test_discovery_skips_broken_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = tmp_path / "broken" / "claude"
    broken.parent.mkdir()
    broken.write_text('#!/bin/sh\necho "not installed" >&2\nexit 1\n')
    broken.chmod(broken.stat().st_mode | stat.S_IEXEC)
    working = make_fake_claude(tmp_path)

    monkeypatch.setenv(ENV_BINARY_OVERRIDE, str(broken))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))

    assert find_claude_binary() == str(working)


def test_discovery_fails_with_helpful_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_BINARY_OVERRIDE, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    with pytest.raises(AdapterError, match="No working `claude` binary"):
        find_claude_binary()


def test_run_episode_parses_payload(tmp_path: Path) -> None:
    fake = make_fake_claude(tmp_path)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = ClaudeCodeAdapter(binary=str(fake))

    result = run(adapter.run_episode("fix it", workdir))

    assert result.session_id == "sess-123"
    assert result.summary == "Fixed the test."
    assert result.cost_usd == pytest.approx(0.0214)
    assert result.duration_s == pytest.approx(6.662)
    assert not result.is_error
    assert result.raw["type"] == "result"


def test_run_episode_flags_and_cwd(tmp_path: Path) -> None:
    fake = make_fake_claude(tmp_path)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = ClaudeCodeAdapter(
        binary=str(fake), model="haiku", allowed_tools=["Bash(pytest -q)", "Read"]
    )

    run(adapter.run_episode("try again", workdir, resume_session="parent-sess"))

    # args file lands in workdir → cwd was the worktree
    args = (workdir / "claude_args.txt").read_text()
    for expected in (
        "-p",
        "--output-format json",
        "--allowedTools Bash(pytest -q),Read",
        "--permission-mode acceptEdits",
        "--model haiku",
        "--resume parent-sess --fork-session",
        "try again",
    ):
        assert expected in args


def test_run_episode_no_fork_without_resume(tmp_path: Path) -> None:
    fake = make_fake_claude(tmp_path)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = ClaudeCodeAdapter(binary=str(fake))

    run(adapter.run_episode("first attempt", workdir))

    args = (workdir / "claude_args.txt").read_text()
    assert "--fork-session" not in args
    assert "--resume" not in args


def test_agent_reported_error_is_a_result(tmp_path: Path) -> None:
    payload = dict(PAYLOAD, is_error=True, result="Something broke.")
    fake = make_fake_claude(tmp_path, payload)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = ClaudeCodeAdapter(binary=str(fake))

    result = run(adapter.run_episode("fix it", workdir))
    assert result.is_error


def test_garbage_output_raises(tmp_path: Path) -> None:
    script = tmp_path / "claude"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "9.9.9"; exit 0; fi\n'
        'echo "segfault-ish garbage" >&2\nexit 3\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = ClaudeCodeAdapter(binary=str(script))

    with pytest.raises(AdapterError, match="code 3"):
        run(adapter.run_episode("fix it", workdir))


def test_timeout_raises(tmp_path: Path) -> None:
    fake = make_fake_claude(tmp_path, sleep_s=5.0)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = ClaudeCodeAdapter(binary=str(fake), timeout_s=0.3)

    with pytest.raises(AdapterTimeout, match="cost is unknown") as exc_info:
        run(adapter.run_episode("fix it", workdir))
    assert exc_info.value.duration_s >= 0.3


def test_missing_session_id_raises(tmp_path: Path) -> None:
    payload = {k: v for k, v in PAYLOAD.items() if k != "session_id"}
    fake = make_fake_claude(tmp_path, payload)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    adapter = ClaudeCodeAdapter(binary=str(fake))

    with pytest.raises(AdapterError, match="session_id"):
        run(adapter.run_episode("fix it", workdir))


def test_conforms_to_protocol(tmp_path: Path) -> None:
    from agent_mcts.adapters.base import AgentBackend

    fake = make_fake_claude(tmp_path)
    adapter: AgentBackend = ClaudeCodeAdapter(binary=str(fake))
    assert adapter.name == "claude"


def test_fake_binary_is_executable_helper(tmp_path: Path) -> None:
    # Guard for the test helper itself: the fake must pass the --version probe.
    fake = make_fake_claude(tmp_path)
    assert os.access(fake, os.X_OK)

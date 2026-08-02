"""Claude Code adapter.

Mechanics validated in docs/spikes/2026-08-02-session-fork-worktree.md:
one episode = one `claude -p` call; forking = `--resume <id> --fork-session`,
which works from any cwd and at any depth.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from agent_mcts.adapters.base import AdapterError, EpisodeResult

ENV_BINARY_OVERRIDE = "AGENT_MCTS_CLAUDE_BIN"


def _executes(binary: Path) -> bool:
    """A candidate counts only if `--version` actually runs — broken npm shims exist
    in the wild (postinstall never ran) that are present but exit non-zero."""
    try:
        proc = subprocess.run(
            [str(binary), "--version"], capture_output=True, timeout=20, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _bundle_version_key(path: Path) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in path.name.split("."))
    except ValueError:
        return (0,)


def find_claude_binary() -> str:
    """Probe candidates in order and return the first that verifiably executes."""
    candidates: list[Path] = []
    override = os.environ.get(ENV_BINARY_OVERRIDE)
    if override:
        candidates.append(Path(override))
    on_path = shutil.which("claude")
    if on_path:
        candidates.append(Path(on_path))
    candidates.append(Path.home() / ".claude" / "local" / "claude")
    bundle_root = Path.home() / "Library" / "Application Support" / "Claude" / "claude-code"
    if bundle_root.is_dir():
        for version_dir in sorted(bundle_root.iterdir(), key=_bundle_version_key, reverse=True):
            candidates.append(version_dir / "claude.app" / "Contents" / "MacOS" / "claude")

    for candidate in candidates:
        if candidate.is_file() and _executes(candidate):
            return str(candidate)

    raise AdapterError(
        "No working `claude` binary found. Install Claude Code "
        "(https://claude.com/claude-code) or point "
        f"{ENV_BINARY_OVERRIDE} at the binary. Note: a `claude` on PATH that "
        "cannot run `claude --version` (e.g. an npm install whose postinstall "
        "never ran) is skipped."
    )


class ClaudeCodeAdapter:
    """Drives Claude Code headlessly; one `run_episode` call = one node expansion."""

    def __init__(
        self,
        binary: str | None = None,
        *,
        model: str | None = None,
        permission_mode: str = "acceptEdits",
        timeout_s: float = 600.0,
    ) -> None:
        self._binary = binary or find_claude_binary()
        self.model = model
        self.permission_mode = permission_mode
        self.timeout_s = timeout_s

    @property
    def name(self) -> str:
        return "claude"

    async def run_episode(
        self,
        prompt: str,
        workdir: Path,
        *,
        resume_session: str | None = None,
    ) -> EpisodeResult:
        cmd = [
            self._binary,
            "-p",
            "--output-format",
            "json",
            "--permission-mode",
            self.permission_mode,
        ]
        if self.model:
            cmd += ["--model", self.model]
        if resume_session:
            cmd += ["--resume", resume_session, "--fork-session"]
        cmd.append(prompt)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise AdapterError(
                f"claude episode timed out after {self.timeout_s:.0f}s in {workdir}"
            ) from None

        payload = self._parse_payload(stdout)
        if payload is None:
            detail = (
                stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
            )
            raise AdapterError(
                f"claude exited with code {proc.returncode} and no JSON payload: {detail[-2000:]}"
            )
        return self._to_result(payload, exit_code=proc.returncode)

    @staticmethod
    def _parse_payload(stdout: bytes) -> dict[str, Any] | None:
        text = stdout.decode(errors="replace").strip()
        if not text:
            return None
        try:
            payload: Any = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return cast(dict[str, Any], payload)

    @staticmethod
    def _to_result(payload: dict[str, Any], *, exit_code: int | None) -> EpisodeResult:
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise AdapterError(f"claude payload has no session_id: {str(payload)[:500]}")
        summary = payload.get("result")
        cost = payload.get("total_cost_usd")
        duration_ms = payload.get("duration_ms")
        return EpisodeResult(
            session_id=session_id,
            summary=summary if isinstance(summary, str) else "",
            cost_usd=float(cost) if isinstance(cost, int | float) else 0.0,
            duration_s=float(duration_ms) / 1000.0 if isinstance(duration_ms, int | float) else 0.0,
            is_error=bool(payload.get("is_error")) or exit_code != 0,
            raw=payload,
        )

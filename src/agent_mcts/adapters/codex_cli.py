"""Codex CLI adapter.

Codex does not expose a session-fork flag, so revision nodes start a fresh
session in the parent node's worktree state and rely on the revision prompt for
context.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, cast

from agent_mcts import proctree
from agent_mcts.adapters.base import AdapterError, AdapterTimeout, EpisodeResult, TokenUsage

ENV_BINARY_OVERRIDE = "AGENT_MCTS_CODEX_BIN"


def _executes(binary: Path) -> bool:
    try:
        proc = subprocess.run(
            [str(binary), "--version"], capture_output=True, timeout=20, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def find_codex_binary() -> str:
    """Probe candidates in order and return the first working Codex CLI binary."""
    candidates: list[Path] = []
    override = os.environ.get(ENV_BINARY_OVERRIDE)
    if override:
        candidates.append(Path(override))
    on_path = shutil.which("codex")
    if on_path:
        candidates.append(Path(on_path))
    candidates.append(Path.home() / ".local" / "bin" / "codex")

    for candidate in candidates:
        if candidate.is_file() and _executes(candidate):
            return str(candidate)

    raise AdapterError(
        "No working `codex` binary found. Install Codex CLI or point "
        f"{ENV_BINARY_OVERRIDE} at the binary."
    )


class CodexCliAdapter:
    """Drives Codex CLI headlessly; one `run_episode` call = one node expansion."""

    def __init__(
        self,
        binary: str | None = None,
        *,
        model: str | None = None,
        timeout_s: float = 600.0,
    ) -> None:
        self._binary = binary or find_codex_binary()
        self.model = model
        self.timeout_s = timeout_s

    @property
    def name(self) -> str:
        return "codex"

    @property
    def reports_cost(self) -> bool:
        return False

    async def run_episode(
        self,
        prompt: str,
        workdir: Path,
        *,
        resume_session: str | None = None,
    ) -> EpisodeResult:
        if resume_session:
            prompt = (
                "The worktree already contains the parent attempt's file changes; "
                f"use the task and evaluation feedback below as context.\n\n{prompt}"
            )
        cmd = [
            self._binary,
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
        ]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append(prompt)

        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=proctree.POSIX,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except TimeoutError:
            await proctree.terminate_tree(proc)
            raise AdapterTimeout(
                f"codex episode timed out after {self.timeout_s:.0f}s in {workdir}; "
                "partial work was snapshotted and cost is unknown",
                duration_s=time.monotonic() - started,
            ) from None
        except asyncio.CancelledError:
            await proctree.terminate_tree(proc)
            raise

        events = self._parse_events(stdout)
        if not events:
            detail = (
                stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
            )
            raise AdapterError(
                f"codex exited with code {proc.returncode} and no JSON events: {detail[-2000:]}",
                cost_known=False,
            )
        return self._to_result(
            events, exit_code=proc.returncode, duration_s=time.monotonic() - started
        )

    @staticmethod
    def _parse_events(stdout: bytes) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in stdout.decode(errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                payload: Any = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(cast(dict[str, Any], payload))
        return events

    @classmethod
    def _to_result(
        cls, events: list[dict[str, Any]], *, exit_code: int | None, duration_s: float
    ) -> EpisodeResult:
        session_id = ""
        summary = ""
        usage: TokenUsage | None = None
        is_error = exit_code != 0

        for event in events:
            session_id = cls._session_id(event) or session_id
            summary = cls._summary(event) or summary
            event_usage = cls._usage(event)
            usage = event_usage if event_usage is not None else usage
            event_type = event.get("type")
            if (
                event.get("is_error") is True
                or event_type == "turn.failed"
                or (isinstance(event_type, str) and "error" in event_type.lower())
            ):
                is_error = True

        if not session_id:
            raise AdapterError(
                f"codex JSON events have no session id: {str(events[-1])[:500]}",
                cost_known=False,
            )
        return EpisodeResult(
            session_id=session_id,
            summary=summary,
            cost_usd=None,
            cost_known=True,
            usage=usage,
            duration_s=duration_s,
            is_error=is_error,
            raw={"events": events[-20:]},
        )

    @staticmethod
    def _session_id(event: dict[str, Any]) -> str | None:
        for key in ("session_id", "conversation_id", "thread_id"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @classmethod
    def _summary(cls, event: dict[str, Any]) -> str | None:
        for key in ("result", "summary", "message", "content", "text"):
            value = event.get(key)
            text = cls._text(value)
            if text:
                return text
        item = event.get("item")
        if isinstance(item, dict):
            typed = cast(dict[str, Any], item)
            if typed.get("role") == "assistant" or typed.get("type") == "agent_message":
                return cls._text(typed)
        return None

    @classmethod
    def _text(cls, value: Any) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            typed = cast(dict[str, Any], value)
            for key in ("text", "content", "message", "result"):
                text = cls._text(typed.get(key))
                if text:
                    return text
        if isinstance(value, list):
            items = cast(list[Any], value)
            parts = [text for item in items if (text := cls._text(item))]
            return "\n".join(parts) if parts else None
        return None

    @staticmethod
    def _usage(event: dict[str, Any]) -> TokenUsage | None:
        if event.get("type") != "turn.completed":
            return None
        usage = event.get("usage")
        if not isinstance(usage, dict):
            return None
        typed = cast(dict[str, Any], usage)
        return TokenUsage(
            input_tokens=CodexCliAdapter._int_usage(typed.get("input_tokens")),
            cached_input_tokens=CodexCliAdapter._int_usage(typed.get("cached_input_tokens")),
            output_tokens=CodexCliAdapter._int_usage(typed.get("output_tokens")),
        )

    @staticmethod
    def _int_usage(raw: Any) -> int:
        if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            return raw
        return 0

"""Value functions: score a node's worktree in [0, 1].

The score drives UCT; the detail (e.g. failing-test output) is fed back into
children's revision prompts, closing the search's feedback loop.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class Evaluation(BaseModel):
    score: float  # in [0, 1]
    detail: str = ""  # feedback shown to humans and to revising agents


class ValueFunction(Protocol):
    async def evaluate(self, workdir: Path) -> Evaluation: ...


_PASSED = re.compile(r"(\d+)\s+passed")
_FAILED = re.compile(r"(\d+)\s+failed")
_ERRORS = re.compile(r"(\d+)\s+errors?")

_DETAIL_TAIL_CHARS = 4000


def _last_int(pattern: re.Pattern[str], output: str) -> int:
    matches = pattern.findall(output)
    return int(matches[-1]) if matches else 0


def _pass_ratio(output: str) -> float:
    passed = _last_int(_PASSED, output)
    total = passed + _last_int(_FAILED, output) + _last_int(_ERRORS, output)
    return passed / total if total else 0.0


class CommandValueFunction:
    """Run a shell command (typically the test suite) in the worktree.

    Exit 0 → 1.0. On failure, a pytest-style summary ("2 failed, 3 passed")
    yields the pass ratio, so partial progress is rewarded; an unparseable
    failure scores 0.0.
    """

    def __init__(self, command: str, *, timeout_s: float = 600.0) -> None:
        self.command = command
        self.timeout_s = timeout_s

    async def evaluate(self, workdir: Path) -> Evaluation:
        proc = await asyncio.create_subprocess_shell(
            self.command,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return Evaluation(
                score=0.0,
                detail=f"value command timed out after {self.timeout_s:.0f}s: {self.command}",
            )
        output = stdout.decode(errors="replace")
        detail = output[-_DETAIL_TAIL_CHARS:]
        if proc.returncode == 0:
            return Evaluation(score=1.0, detail=detail)
        return Evaluation(score=_pass_ratio(output), detail=detail)

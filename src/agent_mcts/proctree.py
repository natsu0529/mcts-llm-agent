"""Spawning and killing child process *trees*.

A timeout or a Ctrl-C has to reach everything a child started, not just the child
itself: `claude` runs tools, and a test command runs compilers, servers, and its own
subprocesses. Killing only the direct child is wrong twice over — the grandchildren
inherit its stdout/stderr, so the read that follows blocks until they finish on their
own (an unbounded wait wearing a timeout's clothes), and they keep writing into a
worktree the search has already abandoned.

Every subprocess agent-mcts starts goes through this module.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess

# POSIX doubles as the `start_new_session` argument for spawning: it puts the child in
# its own session, so a single killpg reaches every descendant. Windows has no process
# group we can signal that way — `taskkill /T` walks the parent chain instead, and needs
# no launch-time flag — so on Windows this is simply False.
POSIX = os.name == "posix"

# How long to wait for a killed tree to actually be reaped. Neither SIGKILL nor
# `taskkill /F` is refusable, so this only elapses for genuinely stuck states
# (uninterruptible IO); we would rather report the timeout than hang the search.
REAP_GRACE_S = 5.0
_TASKKILL_TIMEOUT_S = 10.0


def _taskkill(pid: int) -> bool:
    """Windows: kill `pid` and its descendants. False if taskkill could not be used.

    Blocking on purpose: this runs from cancellation and timeout paths where awaiting
    is fragile, and taskkill returns promptly.
    """
    try:
        completed = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=_TASKKILL_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def kill_tree(proc: asyncio.subprocess.Process) -> bool:
    """Kill `proc` and everything it spawned.

    Returns False if only the direct child could be reached, which leaves descendants
    running — callers cannot do anything about it, but the bounded reap in
    `terminate_tree` means it degrades to a delay rather than a hang.
    """
    if proc.returncode is not None:
        return True
    if POSIX:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return True
        except OSError:  # the group is already gone, or we lost the race to reap it
            pass
    elif _taskkill(proc.pid):
        return True
    with contextlib.suppress(OSError):
        proc.kill()
    return False


async def terminate_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the process tree and reap it, bounded by `REAP_GRACE_S`."""
    kill_tree(proc)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=REAP_GRACE_S)
    _release_pipes(proc)


def _release_pipes(proc: asyncio.subprocess.Process) -> None:
    """Close the pipe transports a completed `communicate()` would have closed for us.

    Cancelling or timing out `communicate()` leaves them open; their finalizer then runs
    after the event loop is gone and raises "Event loop is closed" from `__del__`. There
    is no public API for this, hence the private attribute.
    """
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        with contextlib.suppress(Exception):
            transport.close()

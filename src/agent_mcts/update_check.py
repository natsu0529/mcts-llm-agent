"""Once-a-day PyPI version check so existing users notice new releases.

Deliberately quiet: 2s network timeout, any failure means no notice, result is
cached for 24h, and AGENT_MCTS_NO_UPDATE_CHECK=1 disables it entirely.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PYPI_URL = "https://pypi.org/pypi/agent-mcts/json"
ENV_DISABLE = "AGENT_MCTS_NO_UPDATE_CHECK"
_CACHE_TTL_S = 24 * 3600.0
_TIMEOUT_S = 2.0


def _cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "agent-mcts" / "update-check.json"


def _fetch_latest() -> str | None:
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=_TIMEOUT_S) as resp:
            payload: Any = json.load(resp)
        version = payload.get("info", {}).get("version")
        return version if isinstance(version, str) and version else None
    except Exception:
        return None


def _cached_latest() -> str | None:
    path = _cache_path()
    now = datetime.now(UTC).timestamp()
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        if now - float(data["checked_at"]) < _CACHE_TTL_S:
            latest = data.get("latest")
            return latest if isinstance(latest, str) and latest else None
    except Exception:
        pass
    latest = _fetch_latest()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked_at": now, "latest": latest}), encoding="utf-8")
    except OSError:
        pass
    return latest


def _parse(version: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None  # dev/rc builds opt out of comparison


def notice(current: str) -> str | None:
    """A one-line upgrade hint if PyPI has a newer release, else None."""
    if os.environ.get(ENV_DISABLE):
        return None
    current_parts = _parse(current)
    if current_parts is None:
        return None
    latest = _cached_latest()
    latest_parts = _parse(latest) if latest is not None else None
    if latest is None or latest_parts is None or latest_parts <= current_parts:
        return None
    return f"Update available: {current} → {latest} · upgrade with: uv tool upgrade agent-mcts"

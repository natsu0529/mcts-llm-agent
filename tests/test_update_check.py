import json
import time
from pathlib import Path

import pytest

from agent_mcts import update_check


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(update_check.ENV_DISABLE, raising=False)
    return tmp_path


def set_fetch(monkeypatch: pytest.MonkeyPatch, version: str | None) -> list[int]:
    calls: list[int] = []

    def fake_fetch() -> str | None:
        calls.append(1)
        return version

    monkeypatch.setattr(update_check, "_fetch_latest", fake_fetch)
    return calls


def test_notice_when_newer(monkeypatch: pytest.MonkeyPatch) -> None:
    set_fetch(monkeypatch, "0.2.0")
    message = update_check.notice("0.1.0")
    assert message is not None
    assert "0.1.0 → 0.2.0" in message
    assert "uv tool upgrade agent-mcts" in message


def test_silent_when_current(monkeypatch: pytest.MonkeyPatch) -> None:
    set_fetch(monkeypatch, "0.1.0")
    assert update_check.notice("0.1.0") is None


def test_silent_when_ahead_of_pypi(monkeypatch: pytest.MonkeyPatch) -> None:
    set_fetch(monkeypatch, "0.1.0")
    assert update_check.notice("0.2.0") is None


def test_silent_on_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    set_fetch(monkeypatch, None)
    assert update_check.notice("0.1.0") is None


def test_silent_for_dev_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = set_fetch(monkeypatch, "0.2.0")
    assert update_check.notice("0.1.0.dev0") is None
    assert calls == []  # doesn't even hit the network


def test_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = set_fetch(monkeypatch, "9.9.9")
    monkeypatch.setenv(update_check.ENV_DISABLE, "1")
    assert update_check.notice("0.1.0") is None
    assert calls == []


def test_cache_prevents_repeat_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = set_fetch(monkeypatch, "0.2.0")
    assert update_check.notice("0.1.0") is not None
    assert update_check.notice("0.1.0") is not None
    assert len(calls) == 1  # second call answered from cache


def test_stale_cache_refetches(monkeypatch: pytest.MonkeyPatch, cache_dir: Path) -> None:
    calls = set_fetch(monkeypatch, "0.2.0")
    update_check.notice("0.1.0")
    stale = time.time() - 2 * 24 * 3600
    cache_file = cache_dir / "agent-mcts" / "update-check.json"
    cache_file.write_text(json.dumps({"checked_at": stale, "latest": "0.2.0"}))
    update_check.notice("0.1.0")
    assert len(calls) == 2

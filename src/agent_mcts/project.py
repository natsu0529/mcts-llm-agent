"""Project-level helpers: repo discovery, config file, value-command detection, run listing."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

from agent_mcts.core.engine import SearchConfig

CONFIG_FILENAME = ".agent-mcts.toml"


class ProjectError(RuntimeError):
    pass


class ValueConfig(BaseModel):
    command: str | None = None


class ProjectConfig(BaseModel):
    """Contents of .agent-mcts.toml. Everything is optional; zero-config must work."""

    agent: str = "claude"
    model: str | None = None
    value: ValueConfig = Field(default_factory=ValueConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)


def find_repo_root(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ProjectError(
            "agent-mcts must run inside a git repository (state branching is built on git)."
        )
    return Path(proc.stdout.strip())


def head_commit(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def is_dirty(repo: Path) -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    return bool(out.strip())


def load_project_config(repo: Path) -> ProjectConfig:
    path = repo / CONFIG_FILENAME
    if not path.exists():
        return ProjectConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ProjectError(f"could not parse {CONFIG_FILENAME}: {exc}") from exc
    return ProjectConfig.model_validate(data)


def detect_value_command(repo: Path) -> str | None:
    """Best-effort guess of the project's test command (the default value function)."""
    pyproject = repo / "pyproject.toml"
    if (
        (repo / "pytest.ini").exists()
        or (repo / "tests").is_dir()
        or (pyproject.exists() and "pytest" in pyproject.read_text(encoding="utf-8"))
    ):
        return "pytest -x -q"
    package_json = repo / "package.json"
    if package_json.exists():
        try:
            scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        if isinstance(scripts, dict) and "test" in scripts:
            return "npm test"
    makefile = repo / "Makefile"
    if makefile.exists() and "test:" in makefile.read_text(encoding="utf-8"):
        return "make test"
    return None


def runs_dir(repo: Path) -> Path:
    return repo / ".agent-mcts" / "runs"


def journal_path(repo: Path, run_id: str) -> Path:
    return runs_dir(repo) / run_id / "tree.jsonl"


def latest_run_id(repo: Path) -> str | None:
    """Run ids are timestamps, so lexicographic order is chronological."""
    base = runs_dir(repo)
    if not base.is_dir():
        return None
    candidates = sorted(d.name for d in base.iterdir() if (d / "tree.jsonl").exists())
    return candidates[-1] if candidates else None

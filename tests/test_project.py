import json
from pathlib import Path

import pytest

from agent_mcts import project


def test_find_repo_root(repo: Path) -> None:
    sub = repo / "src" / "pkg"
    sub.mkdir(parents=True)
    assert project.find_repo_root(sub) == repo


def test_find_repo_root_outside_git(tmp_path: Path) -> None:
    with pytest.raises(project.ProjectError, match="git repository"):
        project.find_repo_root(tmp_path)


def test_detect_pytest_via_ini(repo: Path) -> None:
    (repo / "pytest.ini").write_text("[pytest]\n")
    assert project.detect_value_command(repo) == "pytest -x -q"


def test_detect_pytest_via_tests_dir(repo: Path) -> None:
    (repo / "tests").mkdir()
    assert project.detect_value_command(repo) == "pytest -x -q"


def test_detect_npm_test(repo: Path) -> None:
    (repo / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    assert project.detect_value_command(repo) == "npm test"


def test_detect_make_test(repo: Path) -> None:
    (repo / "Makefile").write_text("test:\n\ttrue\n")
    assert project.detect_value_command(repo) == "make test"


def test_detect_nothing(repo: Path) -> None:
    assert project.detect_value_command(repo) is None


def test_config_defaults_without_file(repo: Path) -> None:
    cfg = project.load_project_config(repo)
    assert cfg.agent == "claude"
    assert cfg.value.command is None
    assert cfg.search.max_nodes == 12


def test_config_file_overrides(repo: Path) -> None:
    (repo / project.CONFIG_FILENAME).write_text(
        'agent = "claude"\nmodel = "haiku"\n'
        '[claude]\ntimeout_s = 1200\nallowed_tools = ["Bash(go test *)"]\n'
        '[value]\ncommand = "pytest -q"\n'
        "[search]\nmax_nodes = 5\nc_uct = 0.9\n"
    )
    cfg = project.load_project_config(repo)
    assert cfg.model == "haiku"
    assert cfg.claude.timeout_s == pytest.approx(1200.0)
    assert cfg.claude.allowed_tools == ["Bash(go test *)"]
    assert cfg.value.command == "pytest -q"
    assert cfg.search.max_nodes == 5
    assert cfg.search.c_uct == pytest.approx(0.9)
    assert cfg.search.max_cost_usd == 10.0  # untouched default


def test_config_invalid_toml(repo: Path) -> None:
    (repo / project.CONFIG_FILENAME).write_text("not [valid\n")
    with pytest.raises(project.ProjectError, match="could not parse"):
        project.load_project_config(repo)


def test_latest_run_id(repo: Path) -> None:
    assert project.latest_run_id(repo) is None
    for run_id in ("20260801-120000", "20260802-090000"):
        path = project.journal_path(repo, run_id)
        path.parent.mkdir(parents=True)
        path.write_text("")
    assert project.latest_run_id(repo) == "20260802-090000"

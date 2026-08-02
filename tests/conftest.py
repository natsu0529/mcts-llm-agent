import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal git repository with one commit."""
    root = tmp_path / "repo"
    root.mkdir()

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.name", "Test")
    run("config", "user.email", "test@example.com")
    (root / "app.py").write_text("print('hi')\n")
    run("add", "-A")
    run("commit", "-qm", "init")
    return root

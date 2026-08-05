"""Per-node git worktree management.

Every node gets an isolated worktree on its own branch (`agent-mcts/<run>/<node>`).
After an agent episode, `commit_all` snapshots the worktree onto the node branch so
children can branch from an immutable state and `apply` is an ordinary merge.
Worktrees are disposable; branches are the durable record.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_EXCLUDE_ENTRY = ".agent-mcts/"
# Snapshots are internal bookkeeping, not the user's commits: they must not be blocked
# by a repo's pre-commit hooks, GPG signing, or commit templates. A rejected snapshot
# would take the agent's partial work down with the disposable worktree.
_SNAPSHOT_CONFIG = [
    "-c",
    "user.name=agent-mcts",
    "-c",
    "user.email=noreply@agent-mcts.dev",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "commit.template=",
]


class GitError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed in {cwd}:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


class WorktreeManager:
    """Creates, snapshots, and removes the per-node worktrees of one run."""

    def __init__(self, repo_root: Path, run_id: str) -> None:
        self.repo_root = repo_root
        self.run_id = run_id
        self.worktrees_dir = repo_root / ".agent-mcts" / "worktrees" / run_id
        self._preserved: dict[str, Path] = {}
        self._ensure_excluded()

    @property
    def preserved(self) -> dict[str, Path]:
        """Node id -> worktree path for worktrees `cleanup` must not delete."""
        return dict(self._preserved)

    def branch_name(self, node_id: str) -> str:
        return f"agent-mcts/{self.run_id}/{node_id}"

    def worktree_path(self, node_id: str) -> Path:
        return self.worktrees_dir / node_id

    def create(self, node_id: str, base: str | None = None) -> Path:
        """Add a worktree for `node_id` branched off `base` (default: current HEAD)."""
        path = self.worktree_path(node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        args = ["worktree", "add", "-b", self.branch_name(node_id), str(path)]
        if base is not None:
            args.append(base)
        _git(args, cwd=self.repo_root)
        return path

    def commit_all(self, node_id: str, message: str | None = None) -> str:
        """Commit everything in the node's worktree onto its branch; returns the HEAD sha.

        A no-op episode (agent changed nothing) is fine — the current HEAD is returned.
        """
        path = self.worktree_path(node_id)
        _git(["add", "-A"], cwd=path)
        if _git(["status", "--porcelain"], cwd=path):
            msg = message or f"agent-mcts snapshot {self.run_id}/{node_id}"
            _git([*_SNAPSHOT_CONFIG, "commit", "--no-verify", "-m", msg], cwd=path)
        return _git(["rev-parse", "HEAD"], cwd=path)

    def preserve(self, node_id: str) -> Path:
        """Exempt a worktree from `cleanup`, so unsnapshottable work survives the run."""
        path = self.worktree_path(node_id)
        self._preserved[node_id] = path
        return path

    def remove(self, node_id: str) -> None:
        """Remove the worktree (the node's branch survives)."""
        _git(
            ["worktree", "remove", "--force", str(self.worktree_path(node_id))], cwd=self.repo_root
        )

    def cleanup(self) -> None:
        """Remove every worktree of this run; branches remain for `show`/`apply`.

        Preserved worktrees are skipped: they hold changes that never made it into a
        commit, so deleting them would destroy the only copy.
        """
        keep = {p.resolve() for p in self._preserved.values()}
        for path in sorted(self.worktrees_dir.glob("*")):
            if path.is_dir() and path.resolve() not in keep:
                _git(["worktree", "remove", "--force", str(path)], cwd=self.repo_root)
        _git(["worktree", "prune"], cwd=self.repo_root)

    def current_head(self) -> str:
        return _git(["rev-parse", "HEAD"], cwd=self.repo_root)

    def _ensure_excluded(self) -> None:
        """Keep run artifacts out of the user's `git status` without touching .gitignore."""
        git_dir = Path(_git(["rev-parse", "--git-common-dir"], cwd=self.repo_root))
        if not git_dir.is_absolute():
            git_dir = self.repo_root / git_dir
        exclude = git_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if _EXCLUDE_ENTRY not in existing.split("\n"):
            with exclude.open("a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(f"{_EXCLUDE_ENTRY}\n")

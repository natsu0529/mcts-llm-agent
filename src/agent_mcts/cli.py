"""Command-line entry point: run / show / apply."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.tree import Tree as RichTree

from agent_mcts import __version__, project
from agent_mcts.adapters import AdapterError, ClaudeCodeAdapter
from agent_mcts.core import journal
from agent_mcts.core.engine import SearchEngine
from agent_mcts.core.model import Node, NodeStatus, RunMeta, Tree
from agent_mcts.core.value import CommandValueFunction
from agent_mcts.core.worktree import WorktreeManager

app = typer.Typer(
    help="Turn any coding agent into a tree-searching agent.",
    no_args_is_help=True,
)
console = Console()

_ICON = {
    NodeStatus.PENDING: "…",
    NodeStatus.RUNNING: "●",
    NodeStatus.EVALUATED: "✓",
    NodeStatus.FAILED: "✗",
}


def _fail(message: str) -> NoReturn:
    console.print(f"[red]error:[/] {message}")
    raise typer.Exit(code=1)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"agent-mcts {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """agent-mcts — MCTS test-time search for coding agents."""


class _Progress:
    """Prints one line per node status transition (the live TUI lands with v0.1 polish)."""

    def __init__(self, tree: Tree) -> None:
        self.tree = tree
        self._seen: dict[str, NodeStatus] = {}

    def __call__(self) -> None:
        for node in sorted(self.tree.nodes.values(), key=lambda n: int(n.id[1:])):
            if self._seen.get(node.id) is node.status:
                continue
            self._seen[node.id] = node.status
            if node.status is NodeStatus.RUNNING:
                origin = "" if node.parent_id in (None, "n0") else f" ← revising {node.parent_id}"
                console.print(f"[dim]●[/] {node.id} expanding…{origin}")
            elif node.status is NodeStatus.EVALUATED:
                reward = node.reward if node.reward is not None else 0.0
                summary = node.summary.splitlines()[0][:70] if node.summary else "(baseline)"
                console.print(
                    f"[green]✓[/] {node.id} reward={reward:.2f} (${node.cost_usd:.2f}) {summary}"
                )
            elif node.status is NodeStatus.FAILED:
                detail = node.eval_detail.splitlines()[0][:70] if node.eval_detail else ""
                console.print(f"[red]✗[/] {node.id} failed {detail}")


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="The task to search a solution for.")],
    max_nodes: Annotated[
        int | None, typer.Option("-n", "--max-nodes", help="Episode budget.")
    ] = None,
    max_cost: Annotated[
        float | None, typer.Option("--max-cost", help="Cost ceiling in USD.")
    ] = None,
    value: Annotated[
        str | None,
        typer.Option("--value", help="Value command (defaults to auto-detected tests)."),
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Agent model override.")] = None,
    yes: Annotated[bool, typer.Option("-y", "--yes", help="Skip confirmations.")] = False,
) -> None:
    """Search for a solution to TASK with your coding agent."""
    try:
        repo = project.find_repo_root(Path.cwd())
        cfg = project.load_project_config(repo)
    except project.ProjectError as exc:
        _fail(str(exc))
    if max_nodes is not None:
        cfg.search.max_nodes = max_nodes
    if max_cost is not None:
        cfg.search.max_cost_usd = max_cost

    value_command = value or cfg.value.command or project.detect_value_command(repo)
    if value_command is None:
        _fail(
            "could not detect a test command to use as the value function. "
            f"Pass --value '<command>' or set [value].command in {project.CONFIG_FILENAME}."
        )

    try:
        adapter = ClaudeCodeAdapter(model=model or cfg.model)
    except AdapterError as exc:
        _fail(str(exc))

    if project.is_dirty(repo):
        console.print(
            "[yellow]warning:[/] uncommitted changes detected — the search branches "
            "from HEAD and will not see them."
        )
    console.print(
        f"Agent: [bold]{cfg.agent}[/] · Value: [bold]{value_command}[/] · "
        f"Budget: [bold]{cfg.search.max_nodes}[/] nodes / ${cfg.search.max_cost_usd:.2f}"
    )
    if not yes:
        typer.confirm("Proceed?", abort=True)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    tree = Tree(
        RunMeta(
            run_id=run_id,
            task=task,
            agent=cfg.agent,
            repo_root=str(repo),
            base_commit=project.head_commit(repo),
        )
    )
    worktrees = WorktreeManager(repo, run_id)
    engine = SearchEngine(
        tree=tree,
        adapter=adapter,
        value_fn=CommandValueFunction(value_command),
        worktrees=worktrees,
        journal_path=project.journal_path(repo, run_id),
        config=cfg.search,
        on_change=_Progress(tree),
    )
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/] — the partial tree is saved and usable.")
    finally:
        worktrees.cleanup()

    console.print(
        f"\nSearch finished: {engine.episodes} episodes, "
        f"${engine.total_cost_usd:.2f} · run {run_id}"
    )
    best = tree.best()
    if best is None or best.parent_id is None:
        console.print("No attempt beat the baseline. Inspect with: [bold]agent-mcts show[/]")
    else:
        reward = best.reward if best.reward is not None else 0.0
        summary = best.summary.splitlines()[0][:80] if best.summary else ""
        console.print(f"Best: [bold]{best.id}[/] reward={reward:.2f} {summary}")
        console.print("Next: [bold]agent-mcts show[/] · [bold]agent-mcts apply[/]")


def _load_tree(run_id: str | None) -> Tree:
    try:
        repo = project.find_repo_root(Path.cwd())
    except project.ProjectError as exc:
        _fail(str(exc))
    resolved = run_id or project.latest_run_id(repo)
    if resolved is None:
        _fail('no runs found. Start one with: agent-mcts run "<task>"')
    path = project.journal_path(repo, resolved)
    if not path.exists():
        _fail(f"run {resolved} has no journal at {path}")
    return journal.load(path)


def _node_label(tree: Tree, node: Node) -> str:
    icon = _ICON[node.status]
    best = tree.best()
    reward = f"r={node.reward:.2f}" if node.reward is not None else "r=?"
    summary = node.summary.splitlines()[0][:60] if node.summary else ""
    marker = "  [bold magenta]← best[/]" if best is not None and node.id == best.id else ""
    stats = f"{reward} Q={node.q:.2f} N={node.visits}"
    return f"{icon} [bold]{node.id}[/] \\[{stats}] {summary}{marker}"


def _add_children(tree: Tree, node: Node, rich_node: RichTree) -> None:
    for child in tree.children(node.id):
        branch = rich_node.add(_node_label(tree, child))
        _add_children(tree, child, branch)


@app.command()
def show(
    node: Annotated[str | None, typer.Argument(help="Node id for details (e.g. n3).")] = None,
    run_id: Annotated[str | None, typer.Option("--run", help="Run id (default: latest).")] = None,
) -> None:
    """Show the search tree of a run, or one node's full details."""
    tree = _load_tree(run_id)
    if node is None:
        root = tree.root
        if root is None:
            _fail("run has an empty tree")
        console.print(f"task: {tree.meta.task}  ·  run {tree.meta.run_id}")
        rich_root = RichTree(_node_label(tree, root))
        _add_children(tree, root, rich_root)
        console.print(rich_root)
        return
    found = tree.nodes.get(node)
    if found is None:
        _fail(f"no node {node} in run {tree.meta.run_id}")
    status = f"{found.status.value}  reward={found.reward}  Q={found.q:.2f}  N={found.visits}"
    for title, body in (
        ("status", status),
        ("branch", found.branch or "-"),
        ("session", found.session_id or "-"),
        ("cost", f"${found.cost_usd:.2f} in {found.duration_s:.0f}s"),
        ("prompt", found.prompt or "-"),
        ("summary", found.summary or "-"),
        ("evaluation", found.eval_detail or "-"),
    ):
        console.print(f"[bold]{title}[/]: {body}")


@app.command()
def apply(
    node: Annotated[
        str | None, typer.Argument(help="Node id to apply (default: the best node).")
    ] = None,
    run_id: Annotated[str | None, typer.Option("--run", help="Run id (default: latest).")] = None,
) -> None:
    """Stage a node's changes onto your working tree (squash merge — you commit)."""
    tree = _load_tree(run_id)
    target = tree.nodes.get(node) if node is not None else tree.best()
    if target is None:
        _fail(f"no node {node} in run {tree.meta.run_id}" if node else "run has no scored nodes")
    if target.parent_id is None:
        _fail("the best node is the untouched baseline — nothing to apply")
    if target.branch is None:
        _fail(f"node {target.id} has no snapshot branch (it failed before committing)")

    repo = Path(tree.meta.repo_root)
    if project.is_dirty(repo):
        _fail("your working tree has uncommitted changes; commit or stash before applying")
    proc = subprocess.run(
        ["git", "merge", "--squash", target.branch],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        _fail(f"squash merge of {target.branch} failed:\n{proc.stdout}{proc.stderr}")
    reward = target.reward if target.reward is not None else 0.0
    console.print(
        f"Staged [bold]{target.id}[/] (reward={reward:.2f}) from {target.branch}.\n"
        "Review with [bold]git diff --cached[/] and commit when happy."
    )

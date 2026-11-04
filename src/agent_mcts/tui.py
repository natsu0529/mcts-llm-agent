"""Terminal rendering: shared tree drawing and the live view of a running search."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.live import Live
from rich.markup import escape
from rich.text import Text
from rich.tree import Tree as RichTree

from agent_mcts.core.engine import SearchEngine
from agent_mcts.core.model import Node, NodeStatus, Tree

_ICON = {
    NodeStatus.PENDING: "…",
    NodeStatus.RUNNING: "[dim]●[/]",
    NodeStatus.EVALUATED: "[green]✓[/]",
    NodeStatus.FAILED: "[red]✗[/]",
}


def node_label(tree: Tree, node: Node) -> str:
    icon = _ICON[node.status]
    reward = f"r={node.reward:.2f}" if node.reward is not None else "r=?"
    stats = escape(f"[{reward} Q={node.q:.2f} N={node.visits}]")
    summary = escape(node.summary.splitlines()[0][:60]) if node.summary else ""
    if node.status is NodeStatus.RUNNING:
        elapsed = int((datetime.now(UTC) - node.created_at).total_seconds())
        summary = f"[dim]expanding… {elapsed}s[/]"
    best = tree.best()
    marker = "  [bold magenta]← best[/]" if best is not None and node.id == best.id else ""
    return f"{icon} [bold]{node.id}[/] {stats} {summary}{marker}"


def format_tokens(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def usage_label(engine: SearchEngine) -> str:
    """`1.2k in / 300 out` — the spend figure for backends that meter tokens, not dollars."""
    usage = engine.total_usage
    return f"{format_tokens(usage.input_tokens)} in / {format_tokens(usage.output_tokens)} out"


def spend_label(engine: SearchEngine) -> str:
    """Compact spend-vs-ceiling for the status line.

    Dollars against the ceiling when the backend reports them; token counts (with no
    ceiling, since none can be enforced) otherwise. Lost figures are flagged in both.
    """
    unknown = f" + {engine.unknown_cost_episodes} unknown" if engine.unknown_cost_episodes else ""
    if engine.adapter.reports_cost:
        return f"cost ${engine.total_cost_usd:.2f}{unknown}/${engine.config.max_cost_usd:.2f}"
    return f"tokens {usage_label(engine)}{unknown}"


def render_tree(tree: Tree) -> RenderableType:
    root = tree.root
    if root is None:
        return Text("(empty tree)", style="dim")
    rich_root = RichTree(node_label(tree, root))
    _add_children(tree, root, rich_root)
    return rich_root


def _add_children(tree: Tree, node: Node, rich_node: RichTree) -> None:
    for child in tree.children(node.id):
        branch = rich_node.add(node_label(tree, child))
        _add_children(tree, child, branch)


class _Dynamic:
    """Re-renders on every Live refresh tick, so elapsed times move on their own."""

    def __init__(self, render: Callable[[], RenderableType]) -> None:
        self._render = render

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self._render()


class LiveSearchView:
    """Renders the growing search tree in place while the engine runs.

    Wire it up by assigning `engine.on_change = view.refresh` and entering the
    context around `engine.run()`. On non-interactive terminals rich degrades
    gracefully (the final frame is printed once).
    """

    def __init__(self, engine: SearchEngine, console: Console) -> None:
        self.engine = engine
        self._live = Live(_Dynamic(self._render), console=console, refresh_per_second=4)

    def __enter__(self) -> Self:
        self._live.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._live.refresh()  # final frame reflects the finished tree
        self._live.__exit__(exc_type, exc, tb)

    def refresh(self) -> None:
        self._live.refresh()

    def _render(self) -> RenderableType:
        engine = self.engine
        meta = engine.tree.meta
        cfg = engine.config
        header = Text(f"task: {meta.task}", style="bold")
        status = Text(
            f"run {meta.run_id} · episodes {engine.episodes}/{cfg.max_nodes} · "
            f"{spend_label(engine)}",
            style="dim",
        )
        return Group(header, status, render_tree(engine.tree))

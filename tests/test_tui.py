import io
from pathlib import Path

from rich.console import Console

from agent_mcts.core.engine import SearchConfig, SearchEngine
from agent_mcts.core.model import Node, NodeStatus, RunMeta, Tree
from agent_mcts.tui import LiveSearchView, node_label, render_tree


def make_tree() -> Tree:
    tree = Tree(RunMeta(run_id="r1", task="fix the [weird] widget", repo_root="/x"))
    tree.add(Node(id="n0", status=NodeStatus.EVALUATED, reward=0.0, visits=2, value_sum=0.9))
    tree.add(
        Node(
            id="n1",
            parent_id="n0",
            status=NodeStatus.EVALUATED,
            reward=0.9,
            visits=1,
            value_sum=0.9,
            summary="used [brackets] and fixed it",
        )
    )
    return tree


def render_to_text(tree: Tree) -> str:
    console = Console(file=io.StringIO(), width=120)
    console.print(render_tree(tree))
    file = console.file
    assert isinstance(file, io.StringIO)
    return file.getvalue()


def test_tree_rendering_shows_stats_and_best() -> None:
    out = render_to_text(make_tree())
    assert "[r=0.90 Q=0.90 N=1]" in out
    assert "← best" in out


def test_labels_survive_rich_markup_in_summaries() -> None:
    # Agent summaries may contain square brackets; they must render literally,
    # not be swallowed as rich markup tags.
    out = render_to_text(make_tree())
    assert "used [brackets] and fixed it" in out


def test_empty_tree_renders() -> None:
    tree = Tree(RunMeta(run_id="r1", task="t", repo_root="/x"))
    out = render_to_text(tree)
    assert "empty" in out


def test_node_label_unscored() -> None:
    tree = make_tree()
    pending = tree.add(Node(id="n2", parent_id="n0", status=NodeStatus.RUNNING))
    assert "r=?" in node_label(tree, pending)


class NullAdapter:
    @property
    def name(self) -> str:
        return "null"


def test_live_view_prints_header_and_tree() -> None:
    tree = make_tree()
    engine = SearchEngine(
        tree=tree,
        adapter=NullAdapter(),  # type: ignore[arg-type]  # never called: we only render
        value_fn=None,  # type: ignore[arg-type]
        worktrees=None,  # type: ignore[arg-type]
        journal_path=Path("/dev/null"),
        config=SearchConfig(max_nodes=5, max_cost_usd=2.0),
    )
    console = Console(file=io.StringIO(), width=120)
    with LiveSearchView(engine, console) as view:
        view.refresh()
    file = console.file
    assert isinstance(file, io.StringIO)
    out = file.getvalue()
    assert "fix the [weird] widget" in out
    assert "episodes 1/5" in out
    assert "$0.00/$2.00" in out
    assert "n1" in out

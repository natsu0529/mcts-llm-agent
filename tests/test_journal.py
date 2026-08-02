from pathlib import Path

import pytest

from agent_mcts.core import journal
from agent_mcts.core.model import Node, NodeStatus, RunMeta, Tree


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "tree.jsonl"
    meta = RunMeta(run_id="r1", task="fix the flaky test", repo_root="/tmp/repo")
    tree = Tree(meta)
    root = tree.add(Node(id="n0", prompt="root"))
    child = tree.add(Node(id="n1", parent_id="n0", reward=0.8, status=NodeStatus.EVALUATED))

    journal.append_meta(path, meta)
    journal.append_node(path, root)
    journal.append_node(path, child)

    loaded = journal.load(path)
    assert loaded.meta == meta
    assert loaded.nodes.keys() == {"n0", "n1"}
    assert loaded.nodes["n1"] == child


def test_last_snapshot_wins(tmp_path: Path) -> None:
    path = tmp_path / "tree.jsonl"
    meta = RunMeta(run_id="r1", task="t", repo_root="/x")
    journal.append_meta(path, meta)
    node = Node(id="n0", status=NodeStatus.RUNNING)
    journal.append_node(path, node)
    node.status = NodeStatus.EVALUATED
    node.reward = 0.7
    node.visits = 3
    journal.append_node(path, node)

    loaded = journal.load(path)
    assert loaded.nodes["n0"].status is NodeStatus.EVALUATED
    assert loaded.nodes["n0"].reward == 0.7
    assert loaded.nodes["n0"].visits == 3


def test_load_orders_parents_before_children(tmp_path: Path) -> None:
    # Journal updates can reorder lines relative to tree order; load must cope.
    path = tmp_path / "tree.jsonl"
    meta = RunMeta(run_id="r1", task="t", repo_root="/x")
    journal.append_meta(path, meta)
    journal.append_node(path, Node(id="n1", parent_id="n0"))
    journal.append_node(path, Node(id="n0"))

    loaded = journal.load(path)
    root = loaded.root
    assert root is not None and root.id == "n0"
    assert [n.id for n in loaded.children("n0")] == ["n1"]


def test_load_rejects_missing_meta(tmp_path: Path) -> None:
    path = tmp_path / "tree.jsonl"
    journal.append_node(path, Node(id="n0"))
    with pytest.raises(ValueError, match="no meta"):
        journal.load(path)


def test_load_rejects_orphans(tmp_path: Path) -> None:
    path = tmp_path / "tree.jsonl"
    journal.append_meta(path, RunMeta(run_id="r1", task="t", repo_root="/x"))
    journal.append_node(path, Node(id="n0"))
    journal.append_node(path, Node(id="n5", parent_id="ghost"))
    with pytest.raises(ValueError, match="orphaned"):
        journal.load(path)

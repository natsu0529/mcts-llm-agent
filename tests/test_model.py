import pytest

from agent_mcts.core.model import Node, NodeStatus, RunMeta, Tree


def make_tree() -> Tree:
    return Tree(RunMeta(run_id="r1", task="fix tests", repo_root="/tmp/x"))


def test_add_and_relations() -> None:
    tree = make_tree()
    root = tree.add(Node(id=tree.next_id()))
    child_a = tree.add(Node(id=tree.next_id(), parent_id=root.id))
    child_b = tree.add(Node(id=tree.next_id(), parent_id=root.id))
    grandchild = tree.add(Node(id=tree.next_id(), parent_id=child_a.id))

    assert tree.root is root
    assert {n.id for n in tree.children(root.id)} == {child_a.id, child_b.id}
    assert [n.id for n in tree.path(grandchild.id)] == [root.id, child_a.id, grandchild.id]


def test_add_integrity_checks() -> None:
    tree = make_tree()
    tree.add(Node(id="n0"))
    with pytest.raises(ValueError, match="duplicate"):
        tree.add(Node(id="n0"))
    with pytest.raises(ValueError, match="unknown parent"):
        tree.add(Node(id="n1", parent_id="nope"))
    with pytest.raises(ValueError, match="already has a root"):
        tree.add(Node(id="n2"))


def test_backup_propagates_to_root() -> None:
    tree = make_tree()
    tree.add(Node(id="n0"))
    tree.add(Node(id="n1", parent_id="n0"))
    tree.add(Node(id="n2", parent_id="n1"))

    tree.backup("n2", 1.0)
    tree.backup("n2", 0.0)
    tree.backup("n1", 0.5)

    assert tree.nodes["n2"].visits == 2
    assert tree.nodes["n2"].q == pytest.approx(0.5)
    assert tree.nodes["n1"].visits == 3
    assert tree.nodes["n1"].q == pytest.approx(0.5)
    assert tree.nodes["n0"].visits == 3
    assert tree.nodes["n0"].value_sum == pytest.approx(1.5)


def test_q_is_zero_when_unvisited() -> None:
    assert Node(id="n0").q == 0.0


def test_best_picks_highest_reward() -> None:
    tree = make_tree()
    tree.add(Node(id="n0"))
    tree.add(Node(id="n1", parent_id="n0", reward=0.3, status=NodeStatus.EVALUATED))
    tree.add(Node(id="n2", parent_id="n0", reward=0.9, status=NodeStatus.EVALUATED))
    best = tree.best()
    assert best is not None and best.id == "n2"


def test_best_is_none_without_rewards() -> None:
    tree = make_tree()
    tree.add(Node(id="n0"))
    assert tree.best() is None


def test_best_prefers_deeper_node_on_tie() -> None:
    # A green-suite baseline and a successful attempt both score 1.0;
    # the attempt (which did work) must win the tie, not the untouched root.
    tree = make_tree()
    tree.add(Node(id="n0", reward=1.0, status=NodeStatus.EVALUATED))
    tree.add(Node(id="n1", parent_id="n0", reward=1.0, status=NodeStatus.EVALUATED))
    best = tree.best()
    assert best is not None and best.id == "n1"

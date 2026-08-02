"""Append-only jsonl persistence for search trees.

Format: first line is the run metadata, every following line is a full node snapshot.
Snapshots are last-wins per node id, so updating a node is just appending it again.
Append-only means a Ctrl-C'd run is still a valid, resumable tree (MCTS is anytime).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_mcts.core.model import Node, RunMeta, Tree

_KIND_META = "meta"
_KIND_NODE = "node"


def _append(path: Path, kind: str, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, **payload}, ensure_ascii=False) + "\n")


def append_meta(path: Path, meta: RunMeta) -> None:
    _append(path, _KIND_META, meta.model_dump(mode="json"))


def append_node(path: Path, node: Node) -> None:
    _append(path, _KIND_NODE, node.model_dump(mode="json"))


def load(path: Path) -> Tree:
    """Rebuild a tree by replaying the journal (last snapshot wins per node)."""
    meta: RunMeta | None = None
    snapshots: dict[str, Node] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            kind = record.pop("kind")
            if kind == _KIND_META:
                meta = RunMeta.model_validate(record)
            elif kind == _KIND_NODE:
                node = Node.model_validate(record)
                snapshots[node.id] = node
            else:
                raise ValueError(f"unknown journal record kind: {kind!r}")
    if meta is None:
        raise ValueError(f"journal has no meta record: {path}")
    tree = Tree(meta)
    # Insert parents before children so Tree.add's integrity checks hold.
    remaining = dict(snapshots)
    while remaining:
        progressed = False
        for node_id, node in list(remaining.items()):
            if node.parent_id is None or node.parent_id in tree.nodes:
                tree.add(node)
                del remaining[node_id]
                progressed = True
        if not progressed:
            raise ValueError(f"journal has orphaned nodes: {sorted(remaining)}")
    return tree

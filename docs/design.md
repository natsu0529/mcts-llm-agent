# agent-mcts design notes

Living document. Decisions land here with their reasoning; supersedes nothing silently.

## Node = (git worktree, agent session)

Validated by [the WP2 spike](spikes/2026-08-02-session-fork-worktree.md):

- **Filesystem state** branches via `git worktree` — one worktree per node, one branch per
  node (`agent-mcts/<run>/<node>`). After the agent finishes an expansion, the manager
  commits everything in the worktree onto the node's branch, so children can branch from
  an immutable snapshot and `apply` is an ordinary merge.
- **Conversation state** branches via session forking (`claude -p --resume <id>
  --fork-session`), which works across directories and at any depth.

## Expansion granularity: one node = one complete attempt

One node expansion = one headless agent episode (`claude -p <prompt>`) that runs until the
agent considers the task done, followed by evaluation (value function) of the resulting
worktree.

- **Root's children** explore *diverse approaches*: each child prompt asks the agent to
  attempt the task, optionally steered away from approaches its siblings already took.
- **Deeper children** are *revisions*: the child inherits the parent's conversation and
  code state, and its prompt includes the parent's evaluation feedback (failing tests,
  judge critique) with the instruction to repair or improve.

Why not step-level (one node = one agent action), as some research systems do:

1. A headless CLI call is naturally a whole episode; capping it to single actions fights
   the agent harness and its own planning.
2. The test-based value signal is only meaningful after a complete attempt — mid-attempt
   the tests are red for uninteresting reasons.
3. Episode nodes keep the tree shallow (depth 2–4, tens of nodes), which is what a
   several-minutes-per-node, dollars-per-run budget can afford.

This makes the MCTS action space "revision strategies" rather than "editor actions" —
the same flavor as SWE-Search's iterative refinement, and a natural fit for UCT: siblings
compete on approach, depth accumulates refinement.

## MCTS bookkeeping

Classic UCT statistics live on the node: `visits` (N), `value_sum` (W), `q = W/N`.
A node's own evaluation is `reward` ∈ [0, 1]; `backup()` propagates a value from a node
up to the root. Selection policy (UCT constant, expansion width, etc.) lives in the
search engine, not the data model.

## Persistence: append-only journal

`.agent-mcts/runs/<run-id>/tree.jsonl` — first line is run metadata, then one full node
snapshot per line, last-wins per node id. Crash-safe (append-only), trivially replayable,
and doubles as the export format for future visualization. MCTS is anytime: whatever is
in the journal when you Ctrl-C is a valid, resumable tree.

## Run artifacts layout

```
<repo>/.agent-mcts/
  runs/<run-id>/tree.jsonl      # the tree
  worktrees/<run-id>/<node-id>/ # per-node worktrees (removable; branches survive)
```

The tool never touches the user's `.gitignore`; it appends `.agent-mcts/` to
`.git/info/exclude` instead.

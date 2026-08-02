# Spike: tree-node branching via session fork × git worktree

**Date:** 2026-08-02 · **Status:** ✅ validated · **Claude Code:** 2.1.219

The core architectural bet of agent-mcts is that a search-tree node can be represented as
**(git worktree, agent session)**, and that a parent node can be expanded into multiple
children. This spike validated every link in that chain against the real `claude` CLI.

## What was tested

Scratch git repo with two worktrees (`wt-a`, `wt-b`). All calls headless with
`--output-format json`, `--model haiku`.

1. **Parent session** — ran `claude -p "Remember this codeword: PINEAPPLE-42..."` in the
   main worktree. Got `session_id`, `total_cost_usd`, per-model `usage`, and the final
   `result` text from a single JSON object on stdout.
2. **Fork into child A** — from `wt-a` (a *different* cwd than where the parent session
   was created): `claude -p --resume <parent-id> --fork-session "What was the codeword?
   Write it into note.txt..."` with `--permission-mode acceptEdits`.
3. **Fork into child B** — same parent, from `wt-b`, with a diverging task (reverse the
   codeword).
4. **Fork a child (grandchild)** — resumed child A's session with `--fork-session` and
   asked for a summary of the whole lineage.

## Results

| Claim | Result |
|---|---|
| Headless JSON gives session id, cost, usage, result | ✅ all present in one stdout JSON object |
| `--resume <id> --fork-session` works from a different cwd | ✅ **sessions are not locked to the project dir they were created in** |
| Forked children inherit parent conversation | ✅ both children recalled `PINEAPPLE-42` |
| One parent → many children | ✅ two forks from the same parent id, distinct new session ids |
| Depth > 1 (fork a fork) | ✅ grandchild recalled parent fact *and* child A's action |
| Worktree isolation | ✅ `wt-a/note.txt` = `PINEAPPLE-42`, `wt-b/note.txt` = `24-ELPPAENIP`, main worktree untouched |

Measured single-turn haiku calls: ~$0.02 and ~6s each.

## Implications for the adapter (WP4)

- Node expansion = `claude -p --resume <parent-session> --fork-session <prompt>` executed
  with `cwd` set to the child's worktree. No session-file copying, no context re-injection
  needed for Claude Code.
- Parse the single JSON object from stdout: `session_id` (store on the node),
  `total_cost_usd` (budget accounting), `result` (node summary), `is_error` /
  `permission_denials` (failure handling).
- File edits in headless mode need an explicit permission grant; `--permission-mode
  acceptEdits` worked. The adapter should expose this (and consider `--allowedTools`
  scoping) rather than reaching for `--dangerously-skip-permissions`.
- **Binary discovery needs care.** On this machine the npm-global `claude` shim was broken
  (postinstall never ran → 500-byte error stub), while a working binary lived inside the
  desktop app bundle (`~/Library/Application Support/Claude/claude-code/<ver>/claude.app/
  Contents/MacOS/claude`). The adapter should probe candidates (PATH → `~/.claude/local`
  → desktop bundle), *run `--version` to verify the binary actually executes*, and fail
  with a helpful message.

## Open question carried forward

Expansion granularity (what one node asks the agent to do) is a search-design decision,
not a mechanism question — the mechanism supports any granularity. To be settled in WP3/WP5.

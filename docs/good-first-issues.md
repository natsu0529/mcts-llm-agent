# Issues to file at launch

Drafts for the initial `good first issue` / `help wanted` batch. File these on
GitHub when the repo goes public so contributors have obvious entry points.

---

## [help wanted] Codex CLI adapter

**Labels:** `adapter`, `help wanted`

Implement `AgentBackend` for OpenAI's Codex CLI, the v0.2 flagship feature.

- Protocol: `src/agent_mcts/adapters/base.py` (~50 lines to implement)
- Reference implementation: `src/agent_mcts/adapters/claude_code.py`
- Mechanics: headless mode is `codex exec --json`; resuming is
  `codex exec resume <session-id>`. Codex has no `--fork-session` equivalent,
  so either verify that resuming the same session twice diverges safely, or
  start fresh sessions and inject parent context into the prompt (see the
  fallback discussion in `docs/design.md`).
- Definition of done: `agent-mcts run --agent codex` completes a search on a
  toy repo; adapter tests use a fake `codex` binary (see
  `tests/test_claude_adapter.py` for the pattern — no API calls in CI).

Note: the CLI currently hardcodes the Claude adapter; this issue includes
adding an `--agent` option backed by a simple adapter registry.

---

## [help wanted] Kimi CLI adapter

**Labels:** `adapter`, `help wanted`

Same shape as the Codex issue. Headless mode is
`kimi -p --output-format stream-json --yolo`; session forking is unverified,
so context injection is the expected route.

---

## [good first issue] Gemini CLI adapter

**Labels:** `adapter`, `good first issue`

Gemini CLI has a straightforward headless mode (`gemini -p`). Follow the
adapter guide in CONTRIBUTING.md; the fake-binary test pattern makes this a
self-contained few-hundred-line PR.

---

## [good first issue] `agent-mcts resume`

**Labels:** `cli`, `good first issue`

The journal is already append-only and replayable (`journal.load()` rebuilds a
tree from any interrupted run), and `SearchEngine` accepts a pre-populated
tree. What's missing is the CLI plumbing: a `resume [run-id]` command that
loads the latest journal, reconstructs the `WorktreeManager` state (recreate
worktrees from node branches), and continues the loop under the original
budget. Design note: worktrees are disposable by design — branches are the
durable record.

---

## [help wanted] LLM-as-judge value function

**Labels:** `search`, `help wanted`

`CommandValueFunction` scores by tests alone. Add a judge that asks an LLM to
score a node's diff against the task (0–1), and a combiner
(`w_test * test + w_judge * judge`). This is the hybrid value design from
SWE-Search (ICLR 2025). Keep it behind `[value] judge = true` in
`.agent-mcts.toml`, defaulting off. Needs a design discussion first —
comment on the issue before building.

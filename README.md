# agent-mcts 🌳

**Turn any coding agent into a tree-searching agent.**

`agent-mcts` is an open-source (MIT) test-time search harness that wraps coding agents — Claude Code, Codex CLI, Kimi CLI — with Monte Carlo Tree Search. Instead of a single trajectory that either works or doesn't, your agent explores multiple solution branches, backtracks from dead ends, and concentrates budget on the most promising path.

![agent-mcts searching, applying the best branch, and the resulting diff](demo/demo.gif)

> **Status: v0.1.** Early but real — the full loop (search → live tree → apply) works today with Claude Code. Built in the open; star the repo to follow along, or [jump in](#contributing) — early contributors shape the architecture.

## Why

Production coding agents (Claude Code, Codex, Kimi, ...) run a **single linear loop**: act, observe, retry in place. No branching, no backtracking, no principled exploration.

Research shows search helps: [SWE-Search (ICLR 2025)](https://arxiv.org/abs/2410.20285) reported a ~23% relative improvement on SWE-bench by adding MCTS on top of software agents. But that result lives in a research framework — there is no tool that brings it to the agent you already use.

`agent-mcts` closes that gap:

- **Bring your own agent.** A thin adapter layer speaks to each agent's headless mode (`claude -p`, `codex exec`, `kimi -p`). The search engine never knows which agent it's driving.
- **Real MCTS, not best-of-N.** UCT selection, expansion, evaluation, backup. Budget flows toward branches that look promising, away from dead ends.
- **State you can trust.** Every node is an isolated `git worktree` + a forked agent session. Your working tree is never touched until *you* apply a result.
- **Terminal-native.** Watch the tree grow live in your terminal. 100% Python, no browser required.

## Quickstart

```bash
uv tool install agent-mcts
cd your-project
agent-mcts run "fix the flaky test in tests/test_auth.py"
```

The run auto-detects your installed agent and your test command, then shows the plan before spending anything:

```
Agent: claude · Value: pytest -x -q · Budget: 12 nodes / $10.00
Proceed? [y/N]
```

While searching, the tree grows live in your terminal (real output):

```
task: fix the flaky test in tests/test_auth.py
run 20260802-190219 · episodes 3/12 · cost $0.31/$10.00
✓ n0 [r=0.00 Q=0.42 N=4]
├── ✓ n1 [r=0.67 Q=0.78 N=2] mocked the clock in the auth fixture
│   └── ● n3 [r=? Q=0.00 N=0] expanding…
└── ✗ n2 [r=0.00 Q=0.00 N=1] sleep-based fix (tests timed out)
```

When it finishes (or when you Ctrl-C — MCTS is anytime, the partial tree is saved):

```bash
agent-mcts show        # inspect the tree; `show n3` prints a node's prompt, summary, evaluation
agent-mcts apply       # stage the best node's changes (squash merge — you review and commit)
agent-mcts apply n2    # ...or pick a different branch
```

## How it works

```
                ┌─────────────────────────────┐
                │        search engine        │   UCT selection · expansion
                │   (agent-agnostic, Python)  │   hybrid value fn · backup
                └──────────────┬──────────────┘
                               │ AgentBackend protocol
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
     claude adapter      codex adapter      kimi adapter
      (claude -p)        (codex exec)        (kimi -p)
```

- **Node = (git worktree, agent session).** Filesystem state branches via worktrees; conversation state branches via session forking (native on Claude Code, context-injection fallback elsewhere).
- **Value function = your tests.** Exit 0 scores 1.0; a pytest-style summary earns partial credit by pass ratio, and the failing output is fed into children's revision prompts. `pytest` / `npm test` / `make test` are picked up automatically. (LLM-as-judge lands in v0.2.)
- **Every node is a git branch** (`agent-mcts/<run>/<node>`), so `apply` is an ordinary squash merge and everything is auditable after the fact. Worktrees are disposable; branches are the record.
- **Every state change is journaled** (append-only jsonl per run), so an interrupted search is still a valid, inspectable tree.

## Supported agents

| Agent | Headless | Session fork | Status |
|---|---|---|---|
| Claude Code | `claude -p` | native (`--fork-session`) | ✅ v0.1 |
| Codex CLI | `codex exec` | resume + context injection | planned (v0.2) |
| Kimi CLI | `kimi -p` | context injection | planned (v0.3) |
| Gemini CLI, OpenCode, ... | | | [adapter PRs welcome!](#contributing) |

## Configuration

Zero config required. When you need it, `.agent-mcts.toml`:

```toml
agent = "claude"
model = "haiku"                   # optional agent-model override

[claude]
timeout_s = 1200                  # wall-clock limit for each agent episode
allowed_tools = ["Bash(go test *)"] # optional additional headless permissions

[value]
command = "pytest tests/ -x -q"   # exit code + pass ratio → score in [0, 1]

[search]
max_nodes = 20                    # episode budget
max_cost_usd = 10.0               # ceiling based on costs reported by completed episodes
c_uct = 1.414                     # UCT exploration constant — yes, it's exposed
root_width = 3                    # diverse first attempts under the root
refine_width = 2                  # revision children per node
max_depth = 3
```

CLI flags (`-n`, `--max-cost`, `--value`, `--model`, `--agent-timeout`) override the file. The configured value command is automatically allowed inside the headless Claude session; use `claude.allowed_tools` for additional commands the agent may need. If your `claude` binary lives somewhere unusual, point `AGENT_MCTS_CLAUDE_BIN` at it.

If an episode times out, the agent process fails, or you hit Ctrl-C mid-episode, agent-mcts snapshots any partial changes onto that node's branch before cleaning up its worktree. The node remains failed and is never selected automatically, but you can inspect it with `agent-mcts show <node>` and explicitly recover it with `agent-mcts apply <node>`. These snapshots run with `--no-verify` and signing disabled so a repo's commit hooks cannot reject them; in the rare case a snapshot still fails, the worktree is left on disk and its path is printed instead of being deleted.

Claude only reports cost in its final JSON payload, so any episode cut off before that payload arrives — a timeout, a crash, unparseable output, Ctrl-C — is shown with unknown rather than zero cost, and the search stops rather than claiming that subsequent calls still fit the cost ceiling. `--agent-timeout` bounds the whole episode: each agent runs in its own process group, which is terminated as a unit, so tool subprocesses cannot extend it.

> **Python projects managed with uv:** the value command runs inside fresh worktrees, which don't inherit your virtualenv — use `command = "uv run pytest -q"` (or pass `--value "uv run pytest -q"`) so each worktree resolves its own environment.

agent-mcts checks PyPI at most once a day and prints a one-line hint when a newer version exists; set `AGENT_MCTS_NO_UPDATE_CHECK=1` to disable.

Search hyperparameters are first-class: this is built by an MCTS researcher and meant to double as a research harness for test-time search over real software tasks.

## Roadmap

- [x] **v0.1** — Claude Code adapter, UCT engine, worktree state, test-based value fn, live TUI
- [ ] **v0.2** — Codex CLI adapter (+ `--agent` registry), LLM-as-judge value fn, `resume`, parallel expansion
- [ ] **v0.3** — Kimi CLI adapter, in-agent activation (`/tree` inside Claude Code via MCP)
- [ ] **v0.4** — search-tree export + richer visualization, benchmark mode (same task, N agents, compare trees)

## Contributing

This project is **open source under the MIT license** and developed fully in the open — issues, design discussions, and PRs all happen here on GitHub. Contributions are welcome from day one.

The highest-impact contribution is an **agent adapter**: a few hundred lines implementing the [`AgentBackend` protocol](src/agent_mcts/adapters/base.py) for your favorite CLI agent, with no need to touch the search core. Use the [Claude Code adapter](src/agent_mcts/adapters/claude_code.py) as the reference, and the fake-binary pattern in [its tests](tests/test_claude_adapter.py) to keep CI free of API calls. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup.

Also welcome: bug reports, docs, benchmark tasks, and arguing with our UCT constants.

## License

[MIT](LICENSE) — do whatever you want, just keep the notice.

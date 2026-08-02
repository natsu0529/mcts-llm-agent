# agentree 🌳

**Turn any coding agent into a tree-searching agent.**

`agentree` is an open-source (MIT) test-time search harness that wraps coding agents — Claude Code, Codex CLI, Kimi CLI — with Monte Carlo Tree Search. Instead of a single trajectory that either works or doesn't, your agent explores multiple solution branches, backtracks from dead ends, and concentrates budget on the most promising path.

> **Status: early development (pre-alpha).** The design is settled, the code is being written in the open. Star the repo to follow along, or [jump in](#contributing) — early contributors shape the architecture.

## Why

Production coding agents (Claude Code, Codex, Kimi, ...) run a **single linear loop**: act, observe, retry in place. No branching, no backtracking, no principled exploration.

Research shows search helps: [SWE-Search (ICLR 2025)](https://arxiv.org/abs/2410.20285) reported a ~23% relative improvement on SWE-bench by adding MCTS on top of software agents. But that result lives in a research framework — there is no tool that brings it to the agent you already use.

`agentree` closes that gap:

- **Bring your own agent.** A thin adapter layer speaks to each agent's headless mode (`claude -p`, `codex exec`, `kimi -p`). The search engine never knows which agent it's driving.
- **Real MCTS, not best-of-N.** UCT selection, expansion, evaluation, backup. Budget flows toward branches that look promising, away from dead ends.
- **State you can trust.** Every node is an isolated `git worktree` + a forked agent session. Your working tree is never touched until *you* apply a result.
- **Terminal-native.** Watch the tree grow live in your terminal. 100% Python, no browser required.

## Quickstart

> ⚠️ Not yet on PyPI — the interface below is the committed design and tracks the implementation.

```bash
uv tool install agentree
cd your-project
agentree "fix the flaky test in tests/test_auth.py"
```

First run auto-detects your installed agent and your test command, then shows the plan before spending anything:

```
Agent: claude  ·  Value fn: pytest -x -q  ·  Budget: 12 nodes (est. $3–8)
Continue? [Y/n]
```

While searching, the tree renders live:

```
● root  fix flaky test_auth
├─ ● n1  [Q=0.80  N=5]  mock the clock
│  ├─ ✓ n4  [Q=0.90]  freeze time in fixture   ← best
│  └─ ✗ n5  [Q=0.20]  sleep-based fix
└─ ● n2  [Q=0.40  N=2]  rewrite assertion
```

When it finishes (or when you Ctrl-C — MCTS is anytime):

```bash
agentree show        # inspect the tree and per-node agent transcripts
agentree apply       # merge the best branch into your working tree
agentree apply n5    # ...or pick a different branch
agentree resume      # continue searching from where you stopped
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
- **Value function = your tests + optional LLM-as-judge**, the hybrid design validated by SWE-Search. If `pytest` or `npm test` exists, it's picked up automatically.
- **Every node is a git branch** (`agentree/run3/n5`), so "apply" is an ordinary merge and everything is auditable after the fact.

## Supported agents

| Agent | Headless | Session fork | Status |
|---|---|---|---|
| Claude Code | `claude -p` | native (`--fork-session`) | 🚧 first target |
| Codex CLI | `codex exec` | resume + context injection | planned |
| Kimi CLI | `kimi -p` | context injection | planned |
| Gemini CLI, OpenCode, ... | | | [adapter PRs welcome!](#contributing) |

## Configuration

Zero config required. When you need it, `.agentree.toml`:

```toml
agent = "claude"

[value]
command = "pytest tests/ -x -q"   # exit code + pass rate → score
judge = true                      # add LLM-as-judge to the value estimate

[search]
max_nodes = 20
max_cost_usd = 10
c_uct = 1.4                       # exploration constant — yes, it's exposed
```

Search hyperparameters are first-class: this is built by an MCTS researcher and meant to double as a research harness for test-time search over real software tasks.

## Roadmap

- [ ] **v0.1** — Claude Code adapter, UCT engine, worktree state, test-based value fn, live TUI
- [ ] **v0.2** — Codex CLI adapter, LLM-as-judge value fn, `resume`
- [ ] **v0.3** — Kimi CLI adapter, in-agent activation (`/tree` inside Claude Code via MCP)
- [ ] **v0.4** — search-tree export + richer visualization, benchmark mode (same task, N agents, compare trees)

## Contributing

This project is **open source under the MIT license** and developed fully in the open — issues, design discussions, and PRs all happen here on GitHub. Contributions are welcome from day one.

The highest-impact contribution is an **agent adapter**: a few hundred lines implementing the `AgentBackend` protocol for your favorite CLI agent, with no need to touch the search core. A step-by-step adapter guide is coming with v0.1; until then, open an issue and we'll design it together.

Also welcome: bug reports, docs, benchmark tasks, and arguing with our UCT constants.

## License

[MIT](LICENSE) — do whatever you want, just keep the notice.

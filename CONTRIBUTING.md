# Contributing

Thanks for your interest! This project is developed fully in the open, and contributions are welcome from day one — including while we're still pre-alpha.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and Python 3.11+.

`main` is protected — nobody pushes to it directly, and all changes land through a
pull request from a fork. So start by forking the repo on GitHub, then:

```bash
gh repo fork natsu0529/mcts-llm-agent --clone   # or fork in the UI and clone your fork
cd mcts-llm-agent
uv sync --group dev
```

Run the checks (these are exactly what CI runs):

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pyright               # type check (strict mode)
uv run pytest                # tests
```

Try the CLI from your checkout:

```bash
uv run agent-mcts --version
```

## What to contribute

- **Agent adapters** are the highest-impact contribution: a small module implementing the `AgentBackend` protocol ([src/agent_mcts/adapters/base.py](src/agent_mcts/adapters/base.py)) for a coding agent CLI (Codex, Kimi, Gemini CLI, OpenCode, ...), without touching the search core. Use the Claude Code adapter as the reference implementation, and test against a fake binary (see `tests/test_claude_adapter.py`) so CI never calls a real API.
- Bug reports, docs fixes, and benchmark tasks are always welcome.
- Search-engine changes (selection policy, value functions) are welcome too — please include the reasoning, and numbers if you have them.

## Pull requests

Work on a branch in your fork, never on `main`:

```bash
git checkout -b my-change
# ... make changes, run the checks above ...
git push -u origin my-change
gh pr create --repo natsu0529/mcts-llm-agent
```

Then:

- Keep PRs focused: one topic per PR.
- All code is typed (`pyright` strict must pass) and formatted with `ruff format`.
- Add or update tests for behavior changes.
- If you're unsure whether an idea fits, open an issue first — it saves everyone time.

What happens after you open it:

- CI (lint + tests on Python 3.11–3.14) must pass. For a first-time contributor, a
  maintainer has to approve the workflow run before it starts — that's a GitHub
  safeguard, not a comment on your PR.
- A maintainer review is required before merge, and all review threads must be
  resolved.
- Keep your branch up to date with `main` (the "Update branch" button, or rebase).
- PRs are merged as a single squashed commit, so your branch history stays yours.

## Reporting security issues

Please don't open a public issue. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).

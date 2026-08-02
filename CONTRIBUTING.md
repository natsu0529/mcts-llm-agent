# Contributing

Thanks for your interest! This project is developed fully in the open, and contributions are welcome from day one — including while we're still pre-alpha.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
git clone https://github.com/natsu0529/mcts-llm-agent
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

- **Agent adapters** are the highest-impact contribution: a small module implementing the `AgentBackend` protocol for a coding agent CLI (Gemini CLI, OpenCode, ...), without touching the search core. The protocol lands in v0.1; until then, open an issue and we'll design it together.
- Bug reports, docs fixes, and benchmark tasks are always welcome.
- Search-engine changes (selection policy, value functions) are welcome too — please include the reasoning, and numbers if you have them.

## Pull requests

- Keep PRs focused: one topic per PR.
- All code is typed (`pyright` strict must pass) and formatted with `ruff format`.
- Add or update tests for behavior changes.
- If you're unsure whether an idea fits, open an issue first — it saves everyone time.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).

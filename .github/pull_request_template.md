## What & why

<!-- What does this change, and what problem does it solve? Link the issue if there is one (e.g. "Fixes #12"). -->

## How it was tested

<!-- Commands you ran, or the new tests you added. -->

## Checklist

- [ ] This PR is focused on one topic
- [ ] `uv run ruff check . && uv run ruff format --check .` passes
- [ ] `uv run pyright` passes (strict)
- [ ] `uv run pytest` passes, and tests cover the behavior change
- [ ] No test calls a real agent CLI or a paid API
- [ ] Docs / README updated if user-facing behavior changed

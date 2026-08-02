# Cutting a release

## One-time setup (before the first release)

1. On PyPI, create the project's **trusted publisher** (no API tokens needed):
   PyPI → your account → Publishing → "Add a new pending publisher" with
   - PyPI project name: `agent-mcts`
   - Owner: `natsu0529` · Repository: `mcts-llm-agent`
   - Workflow: `release.yml` · Environment: `pypi`
2. On GitHub, create an environment named `pypi`
   (repo → Settings → Environments). Optionally require manual approval there —
   that makes every publish a two-step, fat-finger-proof action.

## Every release

1. Bump `__version__` in `src/agent_mcts/__init__.py` (the single source of
   truth — pyproject reads it via hatch).
2. Update the README if the release changes user-facing behavior. For the
   first release: delete the "Not yet on PyPI" warning in the Quickstart.
3. Commit, then tag and push:

   ```bash
   git tag v0.1.0
   git push origin main v0.1.0
   ```

4. The `Release` workflow runs the full check suite, builds, and publishes to
   PyPI. Verify with:

   ```bash
   uv tool install agent-mcts && agent-mcts --version
   ```

Version scheme: pre-1.0 semver. Breaking CLI or adapter-protocol changes bump
the minor version; fixes bump the patch.

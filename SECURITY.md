# Security Policy

## Supported versions

This project is pre-1.0. Only the latest released version on PyPI receives security fixes.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub Security Advisories:

👉 https://github.com/natsu0529/mcts-llm-agent/security/advisories/new

Include what you can: affected version, a description of the issue, and steps to
reproduce. You can expect an initial response within 7 days.

## Scope notes

`agent-mcts` orchestrates local coding-agent CLIs, which execute code and edit files
on your machine. The following are expected behavior, not vulnerabilities:

- The agent modifies files in a workspace you pointed it at.
- The agent runs commands permitted by the underlying CLI's own permission settings.

Things that *are* in scope:

- Escaping the configured workspace directory.
- Leaking API keys or credentials into logs, tree state, or generated artifacts.
- Command injection through task descriptions, tree state, or adapter output.
- Anything that causes code to run without the underlying agent CLI's approval flow.

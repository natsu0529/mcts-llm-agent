"""Agent adapters: thin backends that let the search core drive a specific coding agent CLI."""

from agent_mcts.adapters.base import AdapterError, AdapterTimeout, AgentBackend, EpisodeResult
from agent_mcts.adapters.claude_code import ClaudeCodeAdapter, find_claude_binary
from agent_mcts.adapters.codex_cli import CodexCliAdapter, find_codex_binary

__all__ = [
    "AdapterError",
    "AdapterTimeout",
    "AgentBackend",
    "ClaudeCodeAdapter",
    "CodexCliAdapter",
    "EpisodeResult",
    "find_claude_binary",
    "find_codex_binary",
]

"""Agent adapters: thin backends that let the search core drive a specific coding agent CLI."""

from agent_mcts.adapters.base import AdapterError, AgentBackend, EpisodeResult
from agent_mcts.adapters.claude_code import ClaudeCodeAdapter, find_claude_binary

__all__ = [
    "AdapterError",
    "AgentBackend",
    "ClaudeCodeAdapter",
    "EpisodeResult",
    "find_claude_binary",
]

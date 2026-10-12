"""Backend-neutral LLM access (ADR-005).

Callers depend only on `LLMBackend` and `Tool`. A backend is chosen by name, so
switching from the Claude Code CLI to another invocation method means adding a
backend here, not changing callers.
"""

from .base import LLMBackend, LLMError, Tool


def create_backend(name: str = "claude_cli", **options) -> LLMBackend:
    if name == "claude_cli":
        from .claude_cli import ClaudeCliBackend

        return ClaudeCliBackend(**options)
    raise ValueError(f"unknown LLM backend '{name}'")


__all__ = ["LLMBackend", "LLMError", "Tool", "create_backend"]

"""Codex runner adapter."""
from __future__ import annotations

from loom.adapters.subprocess_base import SubprocessAdapter


class CodexAdapter(SubprocessAdapter):
    """Runs Codex CLI (``codex -p <spec>``) via subprocess.

    Inherits command construction, cwd fallback, and timeout enforcement
    from :class:`SubprocessAdapter`. See that class for parameter docs.
    """

    name = "codex"
    default_binary = "codex"
    print_flag = "-p"  # unused: codex takes the prompt positionally under `exec`
    parse_cost = True

    def build_command(self, spec: str) -> list[str]:
        """``codex exec --json <spec>`` — the non-interactive JSONL interface."""
        prefix = self._binary if isinstance(self._binary, list) else [self._binary]
        return [*prefix, "exec", "--json", spec]

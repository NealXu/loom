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
    print_flag = "-p"

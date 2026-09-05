"""Claude Code (cc) runner adapter."""
from __future__ import annotations

from loom.adapters.subprocess_base import SubprocessAdapter


class CCAdapter(SubprocessAdapter):
    """Runs Claude Code CLI (``claude -p <spec>``) via subprocess.

    Inherits command construction, cwd fallback, and timeout enforcement
    from :class:`SubprocessAdapter`. See that class for parameter docs.
    """

    name = "cc"
    default_binary = "claude"
    print_flag = "-p"

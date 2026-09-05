"""Pi (pi) runner adapter."""
from __future__ import annotations

from loom.adapters.subprocess_base import SubprocessAdapter


class PIAdapter(SubprocessAdapter):
    """Runs Pi CLI (``pi -p <spec>``) via subprocess.

    Inherits command construction, cwd fallback, and timeout enforcement
    from :class:`SubprocessAdapter`. See that class for parameter docs.
    """

    name = "pi"
    default_binary = "pi"
    print_flag = "-p"

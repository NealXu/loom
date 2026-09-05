"""DSH runner adapter."""
from __future__ import annotations

from loom.adapters.subprocess_base import SubprocessAdapter


class DshAdapter(SubprocessAdapter):
    """Runs DSH CLI (``dsh -p <spec>``) via subprocess.

    Inherits command construction, cwd fallback, and timeout enforcement
    from :class:`SubprocessAdapter`. See that class for parameter docs.
    """

    name = "dsh"
    default_binary = "dsh"
    print_flag = "-p"

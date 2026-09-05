"""DSH runner adapter."""
from __future__ import annotations

from loom.adapters.subprocess_base import SubprocessAdapter


class DshAdapter(SubprocessAdapter):
    """Runs DSH CLI (``dsh -p <spec>``) via subprocess.

    Inherits command construction, cwd fallback, and timeout enforcement
    from :class:`SubprocessAdapter`. See that class for parameter docs.

    Cost parsing is NOT enabled: ``dsh`` is a profile bootstrapper whose
    usage/cost surface depends on the booted profile's app, with no stable
    JSON schema to extract from. Revisit once a profile's output format is
    pinned down (then mirror CCAdapter: parse_cost + build_command).
    """

    name = "dsh"
    default_binary = "dsh"
    print_flag = "-p"

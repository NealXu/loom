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
    parse_cost = True
    extra_args = ["--mode", "json"]

    def build_command(self, spec: str) -> list[str]:
        """``pi --mode json -p <spec>`` — JSON output mode with flags up front."""
        prefix = self._binary if isinstance(self._binary, list) else [self._binary]
        return [*prefix, *self.extra_args, self._print_flag, spec]

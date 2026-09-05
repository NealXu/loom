"""Shared subprocess-driven runner base class (P1-D).

cc / pi / codex / dsh adapters differ only in binary name, so they subclass
this and inherit:

- command construction: ``[binary..., print_flag, spec]``
- cwd fallback to ``node.project_path``
- **timeout enforcement**: a hung CLI is killed after ``timeout`` seconds
  instead of blocking the scheduler forever
- uniform :class:`Result` mapping (success/exit code/stdout/stderr)
"""
from __future__ import annotations

import asyncio
from typing import Union

from loom.adapters.base import RunnerAdapter, Result

DEFAULT_TIMEOUT = 600.0  # seconds; generous ceiling for agent runs


class SubprocessAdapter(RunnerAdapter):
    """Runs an agent CLI in headless/print mode via asyncio subprocess.

    Parameters
    ----------
    binary:
        Either a path to the executable (str) or a list of leading command
        tokens used for test injection (e.g. ``[sys.executable, "-c", code]``).
        Defaults to the subclass's ``default_binary``.
    cwd:
        Working directory for the subprocess. Falls back to
        ``node.project_path`` when *None*.
    timeout:
        Seconds before a hung subprocess is killed and reported as failure.
        ``None`` disables the timeout. Defaults to ``DEFAULT_TIMEOUT``.
    """

    name = "subprocess"
    default_binary = ""
    print_flag = "-p"
    parse_cost = False          # subclasses set True to extract token/cost from JSON stdout
    extra_args: list[str] = []  # extra CLI args appended after the spec (e.g. output-format)

    def __init__(
        self,
        binary: Union[str, list[str], None] = None,
        cwd: str | None = None,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> None:
        self._binary = binary if binary is not None else self.default_binary
        self._cwd = cwd
        self._timeout = timeout
        self._print_flag = self.print_flag

    def build_command(self, spec: str) -> list[str]:
        """Assemble argv for one run. Override for CLIs with subcommands."""
        if isinstance(self._binary, list):
            cmd = [*self._binary, self._print_flag, spec]
        else:
            cmd = [self._binary, self._print_flag, spec]
        return cmd + list(self.extra_args)

    async def run(self, node) -> Result:
        """Invoke the built command with node.spec and return a Result."""
        cmd = self.build_command(node.spec)

        work_dir = self._cwd or node.project_path or None

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return Result(
                success=False,
                error=f"timeout: process killed after {self._timeout}s",
                exit_code=-1,
            )

        returncode = proc.returncode if proc.returncode is not None else 0
        stdout_text = stdout_bytes.decode(errors="replace")
        cost_tokens, cost_usd = (0, 0.0)
        if self.parse_cost and returncode == 0:
            from loom.adapters.cost_parsing import extract_cost
            cost_tokens, cost_usd = extract_cost(stdout_text)

        return Result(
            success=(returncode == 0),
            output=stdout_text,
            error=stderr_bytes.decode(errors="replace"),
            exit_code=returncode,
            artifacts=[],
            cost_tokens=cost_tokens,
            cost_usd=cost_usd,
        )

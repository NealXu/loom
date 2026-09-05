"""Claude Code (cc) runner adapter."""
from __future__ import annotations

import asyncio
from typing import Union

from loom.adapters.base import RunnerAdapter, Result


class CCAdapter(RunnerAdapter):
    """Runs Claude Code CLI in headless/print mode via subprocess.

    Parameters
    ----------
    binary:
        Either a path to the ``claude`` executable (str) or a list of
        leading command tokens used for test injection (e.g.
        ``[sys.executable, "-c", "<code>"]``).
    cwd:
        Working directory for the subprocess.  Falls back to
        ``node.project_path`` when *None*.
    """

    name = "cc"

    def __init__(
        self,
        binary: Union[str, list[str]] = "claude",
        cwd: str | None = None,
    ) -> None:
        self._binary = binary
        self._cwd = cwd

    async def run(self, node) -> Result:  # type: ignore[override]
        """Invoke ``claude -p <node.spec>`` and return a :class:`Result`."""
        # Build command: [binary-or-prefix..., "-p", spec]
        if isinstance(self._binary, list):
            cmd = [*self._binary, "-p", node.spec]
        else:
            cmd = [self._binary, "-p", node.spec]

        work_dir = self._cwd or node.project_path or None

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()

        returncode = proc.returncode or 0
        return Result(
            success=(returncode == 0),
            output=stdout_bytes.decode(errors="replace"),
            error=stderr_bytes.decode(errors="replace"),
            exit_code=returncode,
            artifacts=[],
        )

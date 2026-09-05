"""Tier-based runner routing (P1-C).

Reads ``loom.toml`` and maps ``node.tier`` onto an ordered chain of runner
names with fallback. The router duck-types as a ``RunnerAdapter``: pass it
wherever a runner is expected (engine step_instance, daemon, CLI) and it
selects the concrete adapter per node.

Fallback semantics:
- ``FileNotFoundError`` (binary not installed) -> try next runner in chain.
- A failed ``Result`` (agent ran and reported non-zero) -> NO fallback:
  re-running a coding agent could repeat side effects.
"""
from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from loom.adapters.base import RunnerAdapter, Result

logger = logging.getLogger(__name__)

DEFAULT_TIER = "tooling"


def load_config(path: str) -> dict:
    """Load a TOML config file; return {} when it does not exist."""
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


class RunnerRouter(RunnerAdapter):
    """Routes nodes to runners by tier, with availability fallback."""

    name = "router"

    def __init__(self, config: dict, runners: dict[str, RunnerAdapter]):
        self._config = config
        self._routing = config.get("routing", {})
        self._runners = runners

    @property
    def red_line_usd(self) -> float:
        """Cost red line for morning digest, from [budget] config (default 5.0)."""
        return float(self._config.get("budget", {}).get("red_line_usd", 5.0))

    def route(self, node) -> list[str]:
        """Return the ordered runner-name chain for the node's tier."""
        tier = node.tier if node.tier in self._routing else DEFAULT_TIER
        return self._routing.get(tier, self._routing.get(DEFAULT_TIER, []))

    async def run(self, node) -> Result:
        """Execute the node on the first available runner in the tier chain."""
        chain = self.route(node)
        last_error: Exception | None = None
        for runner_name in chain:
            runner = self._runners.get(runner_name)
            if runner is None:
                continue  # runner not registered/configured
            try:
                return await runner.run(node)
            except FileNotFoundError as e:
                logger.warning(f"runner {runner_name} unavailable: {e}; falling back")
                last_error = e
        raise RuntimeError(f"no available runner for node {node.id} (tier={node.tier}, chain={chain})")

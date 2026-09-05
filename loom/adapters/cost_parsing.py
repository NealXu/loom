"""Extract token/cost usage from agent CLI stdout (P3-J).

Agent CLIs (claude, codex, ...) that emit ``--output-format json`` print a
result object carrying usage + cost. We locate that JSON (whole output or the
last JSON line) and pull the fields into ``(cost_tokens, cost_usd)``. Field
names differ per CLI, so we accept the common aliases. Missing/non-JSON output
degrades to ``(0, 0.0)`` — cost is best-effort, never fatal.
"""
from __future__ import annotations

import json


def _first(d: dict, *keys, default=0):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


def extract_cost(output: str) -> tuple[int, float]:
    """Return (tokens, usd) parsed from an agent CLI's stdout. (0, 0.0) if none."""
    obj = None
    text = output.strip()
    if text:
        try:
            obj = json.loads(text)
        except ValueError:
            # Try the last non-empty line (CLIs often prefix logs).
            for line in reversed(text.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        obj = json.loads(line)
                        break
                    except ValueError:
                        continue
    if not isinstance(obj, dict):
        return (0, 0.0)

    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else obj
    tokens = usage.get("total_tokens")
    if tokens is None:
        tokens = (_first(usage, "input_tokens", "prompt_tokens", default=0)
                  + _first(usage, "output_tokens", "completion_tokens", default=0))
    usd = float(_first(obj, "total_cost_usd", "cost_usd", "cost", default=0.0))
    return (int(tokens or 0), usd)

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


def _record_tokens(obj: dict) -> int:
    """Best token total in one JSON record: any nested usage-style dict."""
    best = 0

    def walk(node):
        nonlocal best
        if isinstance(node, dict):
            t = node.get("total_tokens")
            if t is None:
                t = (_first(node, "input_tokens", "prompt_tokens", default=0)
                     + _first(node, "output_tokens", "completion_tokens", default=0))
            try:
                best = max(best, int(t or 0))
            except (TypeError, ValueError):
                pass
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(obj)
    return best


def _record_cost(obj: dict) -> float:
    """Max cost float found anywhere in one JSON record."""
    best = 0.0

    def walk(node):
        nonlocal best
        if isinstance(node, dict):
            for k in ("total_cost_usd", "cost_usd", "cost"):
                if k in node and isinstance(node[k], (int, float)):
                    best = max(best, float(node[k]))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(obj)
    return best


def extract_cost(output: str) -> tuple[int, float]:
    """Return (tokens, usd) parsed from an agent CLI's stdout. (0, 0.0) if none.

    Handles single-JSON output (claude), trailing-JSON-after-logs, and JSONL
    event streams (codex ``exec --json``): every JSON object is scored and the
    one with the largest token total wins — token_count events report
    cumulative usage, so the max is the final total.
    """
    text = output.strip()
    if not text:
        return (0, 0.0)

    records: list[dict] = []
    try:
        whole = json.loads(text)
        if isinstance(whole, dict):
            records.append(whole)
    except ValueError:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    records.append(obj)

    best = (0, 0.0)
    for rec in records:
        tokens, usd = _record_tokens(rec), _record_cost(rec)
        if tokens > best[0] or (tokens == best[0] and usd > best[1]):
            best = (tokens, usd)
    return best

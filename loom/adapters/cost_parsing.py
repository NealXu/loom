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
    """Best token total in one JSON record: any nested usage-style dict.

    Handles real-world CLI schemas:
    - ``total_tokens`` (claude-style)
    - ``totalTokens`` (pi camelCase)
    - ``input_tokens`` + ``output_tokens`` (codex)
    - ``input`` + ``output`` (pi short-form)
    """
    best = 0

    def walk(node):
        nonlocal best
        if isinstance(node, dict):
            # Try total-style keys first (snake_case, then camelCase)
            t = node.get("total_tokens") or node.get("totalTokens")
            if t is None:
                t = (_first(node, "input_tokens", "prompt_tokens", "input", default=0)
                     + _first(node, "output_tokens", "completion_tokens", "output", default=0))
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
    """Max cost float found anywhere in one JSON record.

    Handles real-world CLI schemas:
    - Flat: ``total_cost_usd``, ``cost_usd`` (float at any depth)
    - Nested: ``cost.total``, ``cost.total_cost_usd`` (pi-style dict)
    - Nested sum: ``cost.input + cost.output`` when no total key present
    """
    best = 0.0

    def walk(node):
        nonlocal best
        if isinstance(node, dict):
            # Direct float cost keys (claude-style)
            for k in ("total_cost_usd", "cost_usd"):
                if k in node and isinstance(node[k], (int, float)):
                    best = max(best, float(node[k]))
            # Nested cost dict (pi-style)
            cost_dict = node.get("cost")
            if isinstance(cost_dict, dict):
                # Try known total keys inside the cost dict
                for tk in ("total", "total_cost_usd", "cost_usd"):
                    if tk in cost_dict and isinstance(cost_dict[tk], (int, float)):
                        best = max(best, float(cost_dict[tk]))
                        break
                else:
                    # Fall back to summing input + output inside the cost dict
                    s = sum(v for v in (cost_dict.get("input"), cost_dict.get("output"))
                            if isinstance(v, (int, float)))
                    if s > 0:
                        best = max(best, float(s))
            elif isinstance(cost_dict, (int, float)):
                # legacy: cost key is a plain number
                best = max(best, float(cost_dict))
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

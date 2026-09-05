"""Event -> template dispatch (P2-K).

Closes the loop between triggers (hooks/inbox/cron write ``events`` rows)
and the daemon (executes instances). Each tick the daemon calls
:func:`dispatch_events`, which:

1. Loads undispatched trigger events (``dispatched = ''``, excluding
   internal ``state_transition`` events).
2. Scans the templates dir; finds the first template whose ``trigger``
   list contains the event source.
3. Instantiates it with ``payload["params"]`` (if any) and persists the
   new instance — the normal scheduler/step loop then executes it.

Terminal markers written to ``events.dispatched``:
- instance id  -> dispatched successfully
- ``nomatch``  -> no template listens to this source (skip on future scans)
- ``error:...`` -> instantiation failed (e.g. missing required params)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from loom.core.loader import instantiate, load_template
from loom.core.store import Store

logger = logging.getLogger(__name__)


def _load_templates(templates_dir: str) -> list:
    """Load all YAML templates from a directory, skipping broken files."""
    templates = []
    d = Path(templates_dir)
    if not d.is_dir():
        return templates
    for path in sorted(d.glob("*.yaml")):
        try:
            templates.append(load_template(str(path)))
        except Exception as e:  # broken template should not kill dispatching
            logger.warning(f"skipping template {path.name}: {e}")
    return templates


def dispatch_events(store: Store, templates_dir: str) -> list[str]:
    """Dispatch undispatched trigger events; return created instance ids."""
    rows = store.conn.execute(
        "SELECT id, source, payload FROM events "
        "WHERE dispatched = '' AND source != 'state_transition' "
        "ORDER BY id"
    ).fetchall()
    if not rows:
        return []

    templates = _load_templates(templates_dir)

    def _mark(event_id: int, marker: str) -> None:
        store.conn.execute(
            "UPDATE events SET dispatched = ? WHERE id = ?", (marker, event_id))
        store.conn.commit()

    created: list[str] = []
    for row in rows:
        try:
            payload = __import__("json").loads(row["payload"]) if row["payload"] else {}
        except ValueError:
            payload = {}

        # A payload "template" key targets by name (used by the scheduler);
        # otherwise match on source ∈ Template.trigger.
        target_name = payload.get("template")
        if target_name:
            match = next((t for t in templates if t.id == target_name), None)
            if match is None:
                _mark(row["id"], f"error:unknown_template:{target_name}")
                continue
        else:
            match = next((t for t in templates if row["source"] in (t.trigger or [])), None)
            if match is None:
                _mark(row["id"], "nomatch")
                continue

        params = payload.get("params", {})
        try:
            # Fail fast on missing required params before creating anything.
            for key, spec in (match.params or {}).items():
                if isinstance(spec, dict) and spec.get("required") and key not in params:
                    raise ValueError(f"missing required param: {key}")
            instance, nodes, edges = instantiate(match, params)
            store.create_instance(instance)
            for n in nodes:
                store.create_node(n)
            for e in edges:
                store.create_edge(e)
        except Exception as e:
            logger.warning(f"dispatch of event {row['id']} failed: {e}")
            _mark(row["id"], f"error:{type(e).__name__}")
            continue

        _mark(row["id"], instance.id)
        logger.info(f"event {row['id']} ({row['source']}) -> instance {instance.id} "
                    f"(template {match.id})")
        created.append(instance.id)

    return created

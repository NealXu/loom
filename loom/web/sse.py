"""SSE event stream over the SQLite events table (P4-C).

Polls for rows with id > last-seen and yields SSE-formatted chunks. Polling
(fast) is fine for a local single-user tool; no push channel from SQLite.
"""
from __future__ import annotations

import asyncio
import json


async def event_stream(store, max_events: int | None = None,
                       poll_interval: float = 1.0, from_id: int = 0):
    """Yield SSE ``data:`` chunks for events, newest last.

    *max_events* bounds the yield count (None = unbounded, for live use);
    *poll_interval* is the DB poll gap in seconds; *from_id* starts the
    cursor (0 = replay full history, MAX+1 = only future events).
    """
    last_id = from_id
    emitted = 0
    while max_events is None or emitted < max_events:
        rows = store.conn.execute(
            "SELECT id, source, payload, received_at FROM events "
            "WHERE id > ? ORDER BY id LIMIT 50", (last_id,)).fetchall()
        for r in rows:
            yield "data: " + json.dumps({
                "id": r["id"], "source": r["source"],
                "payload": json.loads(r["payload"]) if r["payload"] else {},
                "received_at": r["received_at"],
            }) + "\n\n"
            emitted += 1
            last_id = r["id"]
            if max_events is not None and emitted >= max_events:
                return
        await asyncio.sleep(poll_interval)

"""Node/instance state machines and transition logic.

Every state change is recorded as an `events` row with source='state_transition',
per the Global Constraints (all state changes recorded in the events table).
"""

# Shared terminal/retry semantics for both entities. Nodes and instances use the
# same state vocabulary; the maps differ only where the domain requires it.
INSTANCE_STATES = ["pending", "running", "waiting_gate", "succeeded", "failed", "blocked", "cancelled"]
NODE_STATES = ["pending", "running", "waiting_gate", "succeeded", "failed", "blocked", "cancelled"]

# Keyed by current state -> the set of states it may transition to.
INSTANCE_TRANSITIONS = {
    "pending": {"running", "cancelled"},
    "running": {"waiting_gate", "succeeded", "failed", "blocked"},
    "waiting_gate": {"running", "cancelled"},
    "blocked": {"running", "cancelled"},
    "failed": {"running"},  # retry
    "succeeded": set(),
    "cancelled": set(),
}

NODE_TRANSITIONS = {
    "pending": {"running", "cancelled"},
    "running": {"waiting_gate", "succeeded", "failed", "blocked"},
    "waiting_gate": {"running", "cancelled"},
    "blocked": {"running", "cancelled"},
    "failed": {"running"},  # retry
    "succeeded": set(),
    "cancelled": set(),
}

_TABLES = {
    "instance": INSTANCE_TRANSITIONS,
    "node": NODE_TRANSITIONS,
}


def can_transition(entity_kind: str, current: str, new: str) -> bool:
    """Return True if `new` status is a legal transition from `current`."""
    table = _TABLES.get(entity_kind)
    if table is None:
        raise ValueError(f"unknown entity kind: {entity_kind!r}")
    return new in table.get(current, set())


def record_transition(store, entity_kind: str, entity_id: str,
                      from_status: str, to_status: str) -> bool:
    """Validate and record a state transition as an events row.

    Returns True if the transition was recorded, False if it was illegal.
    The transition is recorded with source='state_transition', targeting the
    entity via `consumed_by_instance` (nodes within an instance are reached
    through the instance id for v1).
    """
    if not can_transition(entity_kind, from_status, to_status):
        return False

    from .models import Event
    event = Event(
        source="state_transition",
        payload={
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "from_status": from_status,
            "to_status": to_status,
        },
        consumed_by_instance=entity_id,
    )
    store.conn.execute(
        """INSERT INTO events (source, payload, received_at, consumed_by_instance)
           VALUES (?, ?, ?, ?)""",
        (event.source, _payload_json(event.payload), event.received_at.isoformat(),
         event.consumed_by_instance),
    )
    store.conn.commit()
    return True


def _payload_json(payload: dict) -> str:
    import json
    return json.dumps(payload)

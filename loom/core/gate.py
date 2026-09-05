"""Gate decision flow — approval / rejection for gated nodes.

When a node has ``gate: approve`` the orchestrator sets its status to
``waiting_gate`` and waits.  A human (or automated) reviewer records a
``GateDecision`` via :func:`record_gate_decision`, which:

1. Inserts a row into the ``gate_decisions`` table.
2. Transitions the node status:
   - approved  → ``waiting_gate`` to ``running``
   - rejected  → ``waiting_gate`` to ``cancelled``
3. Records a ``state_transition`` event via :func:`record_transition`.

:func:`get_pending_gates` returns nodes currently in ``waiting_gate`` status,
optionally filtered by instance.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class GateDecision:
    """A single gate approval or rejection for a node."""

    node_id: str
    instance_id: str
    approved: bool
    approver: str = "me"
    reason: str = ""
    decided_at: datetime = field(default_factory=datetime.now)


def record_gate_decision(store, decision: GateDecision) -> bool:
    """Persist *decision* and transition the node accordingly.

    Returns True on success, False if the state transition was illegal
    (e.g. the node is no longer in ``waiting_gate``).
    """
    from .state import record_transition

    # Determine target status.
    target_status = "running" if decision.approved else "cancelled"

    # Look up current node status.
    node = store.get_node(decision.node_id)
    if node is None:
        raise ValueError(f"node not found: {decision.node_id!r}")

    # Record the state transition (validates the move).
    ok = record_transition(store, "node", decision.node_id,
                           node.status, target_status)
    if not ok:
        return False

    # Update the node row in the DB.
    store.conn.execute(
        "UPDATE nodes SET status = ? WHERE id = ?",
        (target_status, decision.node_id),
    )
    store.conn.commit()

    # Persist the gate decision.
    store.conn.execute(
        """INSERT INTO gate_decisions
           (node_id, instance_id, approved, approver, reason, decided_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (decision.node_id, decision.instance_id, int(decision.approved),
         decision.approver, decision.reason, decision.decided_at.isoformat()),
    )
    store.conn.commit()
    return True


def get_pending_gates(store, instance_id: Optional[str] = None) -> list[dict]:
    """Return nodes currently in ``waiting_gate`` status.

    If *instance_id* is given, only nodes belonging to that instance are
    returned.  Each result is a dict with at least ``id``, ``instance_id``,
    ``title``, ``kind``, ``gate``, and ``status`` keys.
    """
    sql = "SELECT id, instance_id, title, kind, gate, status FROM nodes WHERE status = ?"
    params: list = ["waiting_gate"]
    if instance_id is not None:
        sql += " AND instance_id = ?"
        params.append(instance_id)
    rows = store.conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]

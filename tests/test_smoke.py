"""M1 end-to-end smoke test.

Proves that Store + Scheduler + State + FakeRunner compose into a working
instance lifecycle: nodes run in dependency order, all succeed, the instance
succeeds, and every state transition is recorded as an event.
"""
import asyncio
import json
import tempfile
import os

import pytest

from loom.core.models import Node, Instance, Edge
from loom.core.store import Store
from loom.core.scheduler import topological_order, ready_nodes
from loom.core.state import record_transition
from loom.adapters.fake import FakeRunner


def _insert_edge(store, edge: Edge):
    """Insert an edge row (Store has no create_edge helper in M1)."""
    store.conn.execute(
        "INSERT INTO edges (instance_id, from_node, to_node, type, condition) "
        "VALUES (?, ?, ?, ?, ?)",
        (edge.instance_id, edge.from_node, edge.to_node, edge.type, edge.condition),
    )
    store.conn.commit()


def _update_node_status(store, node_id: str, status: str):
    store.conn.execute(
        "UPDATE nodes SET status = ? WHERE id = ?", (status, node_id),
    )
    store.conn.commit()


def _update_instance_status(store, inst_id: str, status: str):
    store.conn.execute(
        "UPDATE instances SET status = ? WHERE id = ?", (status, inst_id),
    )
    store.conn.commit()


def _run_coroutine(coro):
    """Run an async coroutine from sync test code."""
    return asyncio.run(coro)


@pytest.fixture()
def store():
    """Create a temp-db store with one instance, three nodes, and edges A->C, B->C."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "smoke.db")
    with Store(db_path) as s:
        inst = Instance(id="inst-1", template_id="tmpl-1", status="pending")
        s.create_instance(inst)

        for nid, spec in [("A", "step-a"), ("B", "step-b"), ("C", "step-c")]:
            s.create_node(Node(id=nid, instance_id="inst-1", template_id="tmpl-1", spec=spec))

        _insert_edge(s, Edge(instance_id="inst-1", from_node="A", to_node="C"))
        _insert_edge(s, Edge(instance_id="inst-1", from_node="B", to_node="C"))

        yield s


EDGE_DICTS = [
    {"from_node": "A", "to_node": "C"},
    {"from_node": "B", "to_node": "C"},
]


def test_end_to_end_instance_completes_with_fake_runner(store):
    """Full lifecycle: pending -> run all nodes -> instance succeeded."""
    node_ids = ["A", "B", "C"]
    edges = EDGE_DICTS
    fake = FakeRunner()

    # 1. Topological order: A and B must come before C.
    order = topological_order(node_ids, edges)
    assert order.index("A") < order.index("C")
    assert order.index("B") < order.index("C")

    # 2. Instance: pending -> running.
    record_transition(store, "instance", "inst-1", "pending", "running")
    _update_instance_status(store, "inst-1", "running")

    # 3. Orchestration loop.
    completed = set()
    finish_order = []

    while len(completed) < len(node_ids):
        ready = ready_nodes(node_ids, edges, completed)
        assert ready, "deadlock: no ready nodes but not all complete"
        for nid in ready:
            node = store.get_node(nid)
            # pending -> running
            record_transition(store, "node", nid, "pending", "running")
            _update_node_status(store, nid, "running")
            # Execute
            result = _run_coroutine(fake.run(node))
            assert result.success is True
            # running -> succeeded
            record_transition(store, "node", nid, "running", "succeeded")
            _update_node_status(store, nid, "succeeded")
            completed.add(nid)
            finish_order.append(nid)

    # 4. Instance: running -> succeeded.
    record_transition(store, "instance", "inst-1", "running", "succeeded")
    _update_instance_status(store, "inst-1", "succeeded")

    # 5. Assertions.
    # All nodes succeeded.
    for nid in node_ids:
        n = store.get_node(nid)
        assert n.status == "succeeded"

    # Instance succeeded.
    inst = store.get_instance("inst-1")
    assert inst.status == "succeeded"

    # Dependency order respected in finish order.
    assert finish_order.index("A") < finish_order.index("C")
    assert finish_order.index("B") < finish_order.index("C")

    # State-transition events were recorded.
    events = store.conn.execute(
        "SELECT COUNT(*) AS cnt FROM events WHERE source = 'state_transition'",
    ).fetchone()
    assert events["cnt"] > 0


def test_instance_records_transitions_throughout(store):
    """The events table records every state change for nodes and the instance."""
    node_ids = ["A", "B", "C"]
    edges = EDGE_DICTS
    fake = FakeRunner()

    # Instance pending -> running.
    assert record_transition(store, "instance", "inst-1", "pending", "running")
    _update_instance_status(store, "inst-1", "running")

    completed = set()
    while len(completed) < len(node_ids):
        for nid in ready_nodes(node_ids, edges, completed):
            node = store.get_node(nid)
            assert record_transition(store, "node", nid, "pending", "running")
            _update_node_status(store, nid, "running")
            _run_coroutine(fake.run(node))
            assert record_transition(store, "node", nid, "running", "succeeded")
            _update_node_status(store, nid, "succeeded")
            completed.add(nid)

    assert record_transition(store, "instance", "inst-1", "running", "succeeded")
    _update_instance_status(store, "inst-1", "succeeded")

    # Query events: expect 3 node * 2 transitions + 2 instance transitions = 8.
    rows = store.conn.execute(
        "SELECT payload FROM events WHERE source = 'state_transition' ORDER BY id",
    ).fetchall()

    payloads = [json.loads(r["payload"]) for r in rows]

    # 3 nodes x 2 transitions each (pending->running, running->succeeded).
    node_events = [p for p in payloads if p["entity_kind"] == "node"]
    assert len(node_events) == 6

    # Instance: pending->running, running->succeeded.
    inst_events = [p for p in payloads if p["entity_kind"] == "instance"]
    assert len(inst_events) == 2

    # Every node has both transitions.
    for nid in node_ids:
        transitions = [(p["from_status"], p["to_status"])
                       for p in node_events if p["entity_id"] == nid]
        assert ("pending", "running") in transitions
        assert ("running", "succeeded") in transitions

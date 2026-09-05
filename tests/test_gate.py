"""Tests for the gate decision flow (Task 22)."""

import json
import tempfile
import os
from datetime import datetime

from loom.core.gate import GateDecision, record_gate_decision, get_pending_gates
from loom.core.store import Store
from loom.core.models import Node, Instance


def _make_node(node_id: str, instance_id: str, status: str = "waiting_gate",
               gate: str = "approve") -> Node:
    return Node(
        id=node_id,
        instance_id=instance_id,
        template_id="tpl-1",
        title=f"Node {node_id}",
        kind="gate",
        gate=gate,
        status=status,
    )


def _make_instance(inst_id: str, status: str = "running") -> Instance:
    return Instance(
        id=inst_id,
        template_id="tpl-1",
        title=f"Instance {inst_id}",
        status=status,
    )


def test_gate_decision_dataclass():
    """Create a GateDecision and assert all fields."""
    dt = datetime(2026, 9, 5, 12, 0, 0)
    d = GateDecision(
        node_id="n1",
        instance_id="inst1",
        approved=True,
        approver="alice",
        reason="looks good",
        decided_at=dt,
    )
    assert d.node_id == "n1"
    assert d.instance_id == "inst1"
    assert d.approved is True
    assert d.approver == "alice"
    assert d.reason == "looks good"
    assert d.decided_at == dt

    # defaults
    d2 = GateDecision(node_id="n2", instance_id="inst2", approved=False)
    assert d2.approver == "me"
    assert d2.reason == ""
    assert isinstance(d2.decided_at, datetime)


def test_record_gate_decision_approved():
    """Approved decision transitions node to 'running' and records a state_transition event."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(_make_instance("inst1"))
            store.create_node(_make_node("n1", "inst1", status="waiting_gate"))

            decision = GateDecision(
                node_id="n1", instance_id="inst1", approved=True,
                approver="me", reason="ok",
            )
            record_gate_decision(store, decision)

            # Node status should now be 'running'
            node = store.get_node("n1")
            assert node.status == "running"

            # A state_transition event should exist
            rows = store.conn.execute(
                "SELECT * FROM events WHERE source='state_transition'"
            ).fetchall()
            assert len(rows) >= 1
            # Find the one for our node
            found = False
            for r in rows:
                payload = json.loads(r["payload"])
                if (payload.get("entity_kind") == "node"
                        and payload.get("entity_id") == "n1"
                        and payload.get("from_status") == "waiting_gate"
                        and payload.get("to_status") == "running"):
                    found = True
            assert found, "state_transition event for n1 waiting_gate->running not found"

            # gate_decisions table should have the row
            gd = store.conn.execute(
                "SELECT * FROM gate_decisions WHERE node_id='n1'"
            ).fetchone()
            assert gd is not None
            assert gd["approved"] == 1
            assert gd["approver"] == "me"
            assert gd["reason"] == "ok"


def test_record_gate_decision_rejected():
    """Rejected decision transitions node to 'cancelled'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(_make_instance("inst1"))
            store.create_node(_make_node("n1", "inst1", status="waiting_gate"))

            decision = GateDecision(
                node_id="n1", instance_id="inst1", approved=False,
                approver="me", reason="not ready",
            )
            record_gate_decision(store, decision)

            node = store.get_node("n1")
            assert node.status == "cancelled"

            # state_transition event
            rows = store.conn.execute(
                "SELECT * FROM events WHERE source='state_transition'"
            ).fetchall()
            found = False
            for r in rows:
                payload = json.loads(r["payload"])
                if (payload.get("entity_kind") == "node"
                        and payload.get("entity_id") == "n1"
                        and payload.get("from_status") == "waiting_gate"
                        and payload.get("to_status") == "cancelled"):
                    found = True
            assert found, "state_transition event for n1 waiting_gate->cancelled not found"


def test_get_pending_gates():
    """Only nodes with status='waiting_gate' are returned."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(_make_instance("inst1"))
            store.create_node(_make_node("n1", "inst1", status="waiting_gate"))
            store.create_node(_make_node("n2", "inst1", status="running"))
            store.create_node(_make_node("n3", "inst1", status="pending"))
            store.create_node(_make_node("n4", "inst1", status="waiting_gate"))

            pending = get_pending_gates(store)
            pending_ids = {n["id"] for n in pending}
            assert pending_ids == {"n1", "n4"}


def test_get_pending_gates_filters_by_instance():
    """When instance_id is given, only nodes from that instance are returned."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(_make_instance("inst1"))
            store.create_instance(_make_instance("inst2"))
            store.create_node(_make_node("n1", "inst1", status="waiting_gate"))
            store.create_node(_make_node("n2", "inst1", status="waiting_gate"))
            store.create_node(_make_node("n3", "inst2", status="waiting_gate"))

            pending_inst1 = get_pending_gates(store, instance_id="inst1")
            pending_ids = {n["id"] for n in pending_inst1}
            assert pending_ids == {"n1", "n2"}

            pending_inst2 = get_pending_gates(store, instance_id="inst2")
            pending_ids2 = {n["id"] for n in pending_inst2}
            assert pending_ids2 == {"n3"}

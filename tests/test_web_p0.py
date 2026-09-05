"""Tests for Web API gate endpoints (P0-B)."""

import tempfile
import os
import pytest
from fastapi.testclient import TestClient
from loom.core.store import Store
from loom.core.models import Node, Instance
from loom.web.app import create_app


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as s:
            yield s


@pytest.fixture
def client(store):
    app = create_app(store)
    return TestClient(app)


def test_get_gates_empty(client):
    """GET /api/gates should return empty list when no pending gates."""
    response = client.get("/api/gates")
    assert response.status_code == 200
    assert response.json() == []


def test_get_gates_with_pending(client, store):
    """GET /api/gates should return waiting_gate nodes."""
    store.create_instance(Instance(id="i1", template_id="t", status="waiting_gate"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           title="Merge PR", status="waiting_gate", gate="approve"))

    response = client.get("/api/gates")
    assert response.status_code == 200
    gates = response.json()
    assert len(gates) == 1
    assert gates[0]["id"] == "n1"
    assert gates[0]["title"] == "Merge PR"


def test_get_gates_filter_by_instance(client, store):
    """GET /api/gates?instance_id=X should filter by instance."""
    store.create_instance(Instance(id="i1", template_id="t", status="waiting_gate"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           status="waiting_gate", gate="approve"))
    store.create_instance(Instance(id="i2", template_id="t", status="waiting_gate"))
    store.create_node(Node(id="n2", instance_id="i2", template_id="t",
                           status="waiting_gate", gate="approve"))

    response = client.get("/api/gates?instance_id=i1")
    assert response.status_code == 200
    gates = response.json()
    assert len(gates) == 1
    assert gates[0]["id"] == "n1"


def test_approve_gate(client, store):
    """POST /api/gates/{node_id}/approve should approve a gated node."""
    store.create_instance(Instance(id="i1", template_id="t", status="waiting_gate"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           status="waiting_gate", gate="approve"))

    response = client.post("/api/gates/n1/approve", json={"reason": "LGTM"})
    assert response.status_code == 200
    assert response.json()["approved"] is True

    # Verify node transitioned
    node = store.get_node("n1")
    assert node.status == "running"


def test_reject_gate(client, store):
    """POST /api/gates/{node_id}/reject should cancel a gated node."""
    store.create_instance(Instance(id="i1", template_id="t", status="waiting_gate"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           status="waiting_gate", gate="approve"))

    response = client.post("/api/gates/n1/reject", json={"reason": "Not ready"})
    assert response.status_code == 200
    assert response.json()["approved"] is False

    # Verify node transitioned
    node = store.get_node("n1")
    assert node.status == "cancelled"


def test_approve_nonexistent_gate(client):
    """POST /api/gates/{node_id}/approve should 404 for nonexistent node."""
    response = client.post("/api/gates/nonexistent/approve", json={})
    assert response.status_code == 404

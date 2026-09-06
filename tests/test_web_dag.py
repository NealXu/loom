import tempfile
import os
from fastapi.testclient import TestClient
from loom.core.store import Store
from loom.core.models import Node, Instance


def _seed_instance(store, id, title, status="running", cost_usd=0.0, cost_tokens=0):
    store.create_instance(Instance(id=id, title=title, template_id="t",
                                   status=status, cost_usd=cost_usd, cost_tokens=cost_tokens))


def _seed_node(store, id, instance_id, title="n", kind="analysis", status="pending",
               tier="tooling", gate="none"):
    store.create_node(Node(id=id, instance_id=instance_id, template_id="t",
                           title=title, kind=kind, status=status, tier=tier, gate=gate))


def _seed_edge(store, instance_id, from_node, to_node, edge_type="depends"):
    store.conn.execute(
        "INSERT INTO edges (instance_id, from_node, to_node, type) VALUES (?, ?, ?, ?)",
        (instance_id, from_node, to_node, edge_type))
    store.conn.commit()


def test_graph_returns_tier_field():
    """Node should have tier field with correct value."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Test Instance")
            _seed_node(store, "n1", "inst1", tier="orchestration")

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/graph")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["nodes"]) == 1
            node = data["nodes"][0]
            assert "tier" in node
            assert node["tier"] == "orchestration"


def test_graph_returns_gate_field():
    """Node should have gate field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Test Instance")
            _seed_node(store, "n1", "inst1", gate="approval")

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/graph")
            assert resp.status_code == 200
            data = resp.json()
            node = data["nodes"][0]
            assert "gate" in node
            assert node["gate"] == "approval"


def test_graph_returns_spec_field():
    """Node should have spec field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Test Instance")
            _seed_node(store, "n1", "inst1")
            # Update spec directly since seed doesn't set it
            store.conn.execute("UPDATE nodes SET spec = ? WHERE id = ?", ("test spec", "n1"))
            store.conn.commit()

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/graph")
            assert resp.status_code == 200
            data = resp.json()
            node = data["nodes"][0]
            assert "spec" in node
            assert node["spec"] == "test spec"


def test_graph_returns_budget_tokens_field():
    """Node should have budget_tokens field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Test Instance")
            _seed_node(store, "n1", "inst1")
            # Update budget_tokens directly
            store.conn.execute("UPDATE nodes SET budget_tokens = ? WHERE id = ?", (5000, "n1"))
            store.conn.commit()

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/graph")
            assert resp.status_code == 200
            data = resp.json()
            node = data["nodes"][0]
            assert "budget_tokens" in node
            assert node["budget_tokens"] == 5000


def test_graph_returns_instance_template_id():
    """Instance should have template_id field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Test Instance")

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/graph")
            assert resp.status_code == 200
            data = resp.json()
            instance = data["instances"][0]
            assert "template_id" in instance
            assert instance["template_id"] == "t"


def test_graph_edges_include_type():
    """Edge should have type field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Test Instance")
            _seed_node(store, "n1", "inst1")
            _seed_node(store, "n2", "inst1")
            _seed_edge(store, "inst1", "n1", "n2", edge_type="blocks")

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/graph")
            assert resp.status_code == 200
            data = resp.json()
            edge = data["edges"][0]
            assert "type" in edge
            assert edge["type"] == "blocks"


def test_graph_edges_include_instance_id():
    """Edge should have instance_id field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Test Instance")
            _seed_node(store, "n1", "inst1")
            _seed_node(store, "n2", "inst1")
            _seed_edge(store, "inst1", "n1", "n2")

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/graph")
            assert resp.status_code == 200
            data = resp.json()
            edge = data["edges"][0]
            assert "instance_id" in edge
            assert edge["instance_id"] == "inst1"


def test_graph_backward_compat():
    """Original fields should still be present for backward compatibility."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Test Instance", cost_usd=1.5)
            _seed_node(store, "n1", "inst1", title="Node 1", kind="analysis", status="running")
            _seed_node(store, "n2", "inst1")
            _seed_edge(store, "inst1", "n1", "n2")

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/graph")
            assert resp.status_code == 200
            data = resp.json()

            # Check instance has original fields
            instance = data["instances"][0]
            assert "id" in instance
            assert "title" in instance
            assert "status" in instance
            assert "cost_usd" in instance

            # Check nodes have original fields
            node = data["nodes"][0]
            assert "id" in node
            assert "title" in node
            assert "status" in node
            assert "kind" in node
            assert "instance_id" in node

            # Check edges have original fields
            edge = data["edges"][0]
            assert "from_node" in edge
            assert "to_node" in edge

import tempfile
import os
from datetime import datetime
from fastapi.testclient import TestClient
from loom.core.store import Store
from loom.core.models import Node, Instance, Edge


def _seed_instance(store, id="inst1", title="Test Instance", status="pending",
                   cost_usd=0.0, cost_tokens=0):
    inst = Instance(
        id=id,
        template_id="tpl-1",
        title=title,
        status=status,
        cost_usd=cost_usd,
        cost_tokens=cost_tokens,
    )
    store.create_instance(inst)
    return inst


def _seed_node(store, id, instance_id, title="Node", kind="analysis",
               status="pending", tier="tooling", gate="none"):
    node = Node(
        id=id,
        instance_id=instance_id,
        template_id="tpl-1",
        title=title,
        kind=kind,
        tier=tier,
        gate=gate,
        status=status,
    )
    store.create_node(node)
    return node


def _seed_edge(store, instance_id, from_node, to_node, edge_type="depends"):
    store.conn.execute(
        "INSERT INTO edges (instance_id, from_node, to_node, type) VALUES (?, ?, ?, ?)",
        (instance_id, from_node, to_node, edge_type),
    )
    store.conn.commit()


def test_list_instances():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "First")
            _seed_instance(store, "inst2", "Second")

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/instances")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 2
            # Verify lean fields present
            ids = {item["id"] for item in data}
            assert ids == {"inst1", "inst2"}


def test_get_instance_detail():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Detail Test")
            _seed_node(store, "n1", "inst1", "Node A")
            _seed_node(store, "n2", "inst1", "Node B")
            _seed_edge(store, "inst1", "n1", "n2")

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/instances/inst1")
            assert resp.status_code == 200
            data = resp.json()
            assert "instance" in data
            assert "nodes" in data
            assert "edges" in data
            assert data["instance"]["id"] == "inst1"
            assert len(data["nodes"]) == 2
            assert len(data["edges"]) == 1
            assert data["edges"][0]["from_node"] == "n1"


def test_get_instance_404():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/instances/nonexistent")
            assert resp.status_code == 404


def test_get_graph():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Graph Inst 1")
            _seed_instance(store, "inst2", "Graph Inst 2")
            _seed_node(store, "n1", "inst1", "Node 1")
            _seed_node(store, "n2", "inst2", "Node 2")
            _seed_edge(store, "inst1", "n1", "n2")

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)

            resp = client.get("/api/graph")
            assert resp.status_code == 200
            data = resp.json()
            assert "instances" in data
            assert "nodes" in data
            assert "edges" in data
            assert len(data["instances"]) == 2
            assert len(data["nodes"]) == 2
            assert len(data["edges"]) == 1


# ── P2-G: error paths + concurrency ──


def test_corrupted_params_json_survives():
    """An instance row with malformed params JSON must not 500 the detail endpoint."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            _seed_instance(store, "inst1", "Bad Params")
            # Overwrite params with invalid JSON directly.
            store.conn.execute(
                "UPDATE instances SET params = ? WHERE id = ?", ("{not json", "inst1"))
            store.conn.commit()

            from loom.web.app import create_app
            app = create_app(store)
            client = TestClient(app)
            resp = client.get("/api/instances/inst1")
            assert resp.status_code == 200
            assert resp.json()["instance"]["params"] == {}  # degraded to empty


def test_wal_concurrent_reads():
    """WAL mode allows a reader connection while a writer holds a txn."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as writer:
            _seed_instance(writer, "inst1", "W")
            reader = Store(db_path)  # second connection
            try:
                # Begin a write txn without committing.
                writer.conn.execute(
                    "UPDATE instances SET title = ? WHERE id = ?", ("changed", "inst1"))
                # Reader still sees committed state (old title), no error.
                rows = reader.conn.execute("SELECT title FROM instances").fetchall()
                assert len(rows) == 1
            finally:
                reader.close()

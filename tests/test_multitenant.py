"""P6-C: Multi-user support via owner field."""
import os
import pytest
import tempfile
from fastapi.testclient import TestClient
from loom.core.store import Store
from loom.core.models import Instance, Node


def _create_client(owner: str | None = None):
    """Create TestClient with optional owner configured."""
    from loom.web.app import create_app
    tmpdir = tempfile.mkdtemp()
    db = os.path.join(tmpdir, "test.db")
    store = Store(db)
    # Seed instances for three owners
    store.create_instance(Instance(id="alice-1", title="Alice Task", template_id="t", owner="alice"))
    store.create_instance(Instance(id="bob-1", title="Bob Task", template_id="t", owner="bob"))
    store.create_instance(Instance(id="me-1", title="My Task", template_id="t", owner="me"))
    # Seed nodes per owner for graph-filter tests
    store.create_node(Node(id="alice-n1", instance_id="alice-1", template_id="t",
                           owner="alice", title="Alice Node"))
    store.create_node(Node(id="bob-n1", instance_id="bob-1", template_id="t",
                           owner="bob", title="Bob Node"))
    store.create_node(Node(id="me-n1", instance_id="me-1", template_id="t",
                           owner="me", title="Me Node"))
    app = create_app(store)
    if owner:
        app.state.default_owner = owner
    client = TestClient(app)
    return client, tmpdir


def test_list_instances_default_owner():
    """Without owner param, returns only 'me' instances."""
    client, tmpdir = _create_client()
    try:
        resp = client.get("/api/instances")
        assert resp.status_code == 200
        ids = [i["id"] for i in resp.json()]
        assert "me-1" in ids
        assert "alice-1" not in ids
        assert "bob-1" not in ids
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_list_instances_filter_by_owner():
    """?owner=alice returns only alice's instances."""
    client, tmpdir = _create_client()
    try:
        resp = client.get("/api/instances?owner=alice")
        assert resp.status_code == 200
        ids = [i["id"] for i in resp.json()]
        assert ids == ["alice-1"]
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_list_instances_all_owners():
    """?owner=* returns all instances regardless of owner."""
    client, tmpdir = _create_client()
    try:
        resp = client.get("/api/instances?owner=*")
        assert resp.status_code == 200
        ids = [i["id"] for i in resp.json()]
        assert len(ids) == 3
        assert set(ids) == {"alice-1", "bob-1", "me-1"}
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_graph_respects_owner_filter():
    """/api/graph?owner=alice returns only alice's instances and their nodes."""
    client, tmpdir = _create_client()
    try:
        resp = client.get("/api/graph?owner=alice")
        assert resp.status_code == 200
        data = resp.json()
        inst_ids = [i["id"] for i in data["instances"]]
        assert inst_ids == ["alice-1"]
        # nodes should only be alice's
        node_inst_ids = set(n["instance_id"] for n in data["nodes"])
        assert node_inst_ids == {"alice-1"}
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_gates_filter_by_owner():
    """/api/gates?owner=alice only shows alice's gates."""
    client, tmpdir = _create_client()
    try:
        # No gates yet, but endpoint should accept owner param
        resp = client.get("/api/gates?owner=alice")
        assert resp.status_code == 200
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_owner_set_via_env_var():
    """LOOM_OWNER env var sets default owner for new instances."""
    os.environ["LOOM_OWNER"] = "alice"
    try:
        import tempfile
        from loom.web.app import create_app
        tmpdir = tempfile.mkdtemp()
        db = os.path.join(tmpdir, "test.db")
        store = Store(db)
        app = create_app(store)
        owner = getattr(app.state, "default_owner", None)
        assert owner == "alice", f"expected alice, got {owner}"
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)
    finally:
        os.environ.pop("LOOM_OWNER", None)

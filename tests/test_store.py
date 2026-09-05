import tempfile
import os
from loom.core.store import Store
from loom.core.models import Node, Instance, Edge


def test_store_create_and_read_node():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:

            node = Node(
                id="node1",
                instance_id="inst1",
                template_id="test-template",
                title="test node",
                spec="test spec",
                tier="tooling",
                status="pending",
            )
            store.create_node(node)

            retrieved = store.get_node("node1")
            assert retrieved is not None
            assert retrieved.id == "node1"
            assert retrieved.title == "test node"

def test_store_create_and_read_instance():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:

            inst = Instance(
                id="inst1",
                template_id="test-template",
                title="test instance",
                status="pending",
            )
            store.create_instance(inst)

            retrieved = store.get_instance("inst1")
            assert retrieved is not None
            assert retrieved.id == "inst1"


# ---------------------------------------------------------------------------
# New Store methods (P0-A foundation)
# ---------------------------------------------------------------------------

def test_store_list_instances_by_status():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            # Create instances with different statuses
            store.create_instance(Instance(id="i1", template_id="t", status="pending"))
            store.create_instance(Instance(id="i2", template_id="t", status="running"))
            store.create_instance(Instance(id="i3", template_id="t", status="pending"))
            store.create_instance(Instance(id="i4", template_id="t", status="succeeded"))

            pending = store.list_instances_by_status("pending")
            assert len(pending) == 2
            assert {i.id for i in pending} == {"i1", "i3"}

            running = store.list_instances_by_status("running")
            assert len(running) == 1
            assert running[0].id == "i2"

            failed = store.list_instances_by_status("failed")
            assert len(failed) == 0


def test_store_list_nodes():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_node(Node(id="n1", instance_id="inst1", template_id="t", status="pending"))
            store.create_node(Node(id="n2", instance_id="inst1", template_id="t", status="succeeded"))
            store.create_node(Node(id="n3", instance_id="inst2", template_id="t", status="pending"))

            nodes = store.list_nodes("inst1")
            assert len(nodes) == 2
            assert {n.id for n in nodes} == {"n1", "n2"}

            nodes2 = store.list_nodes("inst2")
            assert len(nodes2) == 1
            assert nodes2[0].id == "n3"


def test_store_list_edges():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            # Create edges manually via SQL (no create_edge method yet)
            store.conn.execute(
                "INSERT INTO edges (instance_id, from_node, to_node, type) VALUES (?, ?, ?, ?)",
                ("inst1", "n1", "n2", "depends")
            )
            store.conn.execute(
                "INSERT INTO edges (instance_id, from_node, to_node, type) VALUES (?, ?, ?, ?)",
                ("inst1", "n2", "n3", "depends")
            )
            store.conn.execute(
                "INSERT INTO edges (instance_id, from_node, to_node, type) VALUES (?, ?, ?, ?)",
                ("inst2", "n4", "n5", "depends")
            )
            store.conn.commit()

            edges = store.list_edges("inst1")
            assert len(edges) == 2
            assert edges[0].from_node == "n1"
            assert edges[0].to_node == "n2"
            assert edges[1].from_node == "n2"
            assert edges[1].to_node == "n3"


def test_store_update_node_status():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_node(Node(id="n1", instance_id="inst1", template_id="t", status="pending"))

            store.update_node_status("n1", "running")
            node = store.get_node("n1")
            assert node.status == "running"

            store.update_node_status("n1", "succeeded")
            node = store.get_node("n1")
            assert node.status == "succeeded"


def test_store_update_instance_status():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(Instance(id="i1", template_id="t", status="pending"))

            store.update_instance_status("i1", "running")
            inst = store.get_instance("i1")
            assert inst.status == "running"

            store.update_instance_status("i1", "succeeded")
            inst = store.get_instance("i1")
            assert inst.status == "succeeded"


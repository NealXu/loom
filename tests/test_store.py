import tempfile
import os
from loom.core.store import Store
from loom.core.models import Node, Instance

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

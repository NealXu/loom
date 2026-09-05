"""Tests for step_instance engine (P0-A core)."""

import tempfile
import os
import pytest
from loom.core.store import Store
from loom.core.models import Node, Instance, Edge
from loom.core.engine import step_instance
from loom.adapters.fake import FakeRunner


pytestmark = pytest.mark.asyncio


@pytest.fixture
def store_with_dag():
    """Create a store with a simple 3-node DAG: n1 -> n2 -> n3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            # Instance
            store.create_instance(Instance(id="inst1", template_id="test", status="pending"))

            # Nodes
            store.create_node(Node(id="n1", instance_id="inst1", template_id="test",
                                   title="node1", spec="echo 1", status="pending"))
            store.create_node(Node(id="n2", instance_id="inst1", template_id="test",
                                   title="node2", spec="echo 2", status="pending"))
            store.create_node(Node(id="n3", instance_id="inst1", template_id="test",
                                   title="node3", spec="echo 3", status="pending"))

            # Edges: n1 -> n2 -> n3
            store.conn.execute("INSERT INTO edges (instance_id, from_node, to_node, type, condition) VALUES (?, ?, ?, ?, ?)",
                               ("inst1", "n1", "n2", "depends", ""))
            store.conn.execute("INSERT INTO edges (instance_id, from_node, to_node, type, condition) VALUES (?, ?, ?, ?, ?)",
                               ("inst1", "n2", "n3", "depends", ""))
            store.conn.commit()

            yield store


@pytest.fixture
def store_with_gate():
    """Create a store with a gated node: n1 -> n2(gate) -> n3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(Instance(id="inst1", template_id="test", status="pending"))

            store.create_node(Node(id="n1", instance_id="inst1", template_id="test",
                                   title="node1", spec="echo 1", status="pending", gate="none"))
            store.create_node(Node(id="n2", instance_id="inst1", template_id="test",
                                   title="node2", spec="echo 2", status="pending", gate="approve"))
            store.create_node(Node(id="n3", instance_id="inst1", template_id="test",
                                   title="node3", spec="echo 3", status="pending", gate="none"))

            store.conn.execute("INSERT INTO edges (instance_id, from_node, to_node, type, condition) VALUES (?, ?, ?, ?, ?)",
                               ("inst1", "n1", "n2", "depends", ""))
            store.conn.execute("INSERT INTO edges (instance_id, from_node, to_node, type, condition) VALUES (?, ?, ?, ?, ?)",
                               ("inst1", "n2", "n3", "depends", ""))
            store.conn.commit()

            yield store


async def test_step_runs_ready_nodes(store_with_dag):
    """First step should run n1 (the only ready node)."""
    runner = FakeRunner()
    status = await step_instance(store_with_dag, "inst1", runner)

    # n1 should be succeeded, n2/n3 still pending
    n1 = store_with_dag.get_node("n1")
    n2 = store_with_dag.get_node("n2")
    n3 = store_with_dag.get_node("n3")

    assert n1.status == "succeeded"
    assert n2.status == "pending"
    assert n3.status == "pending"
    assert status == "running"


async def test_step_runs_full_dag(store_with_dag):
    """Multiple steps should run the entire DAG."""
    runner = FakeRunner()

    # Step 1: run n1
    await step_instance(store_with_dag, "inst1", runner)
    assert store_with_dag.get_node("n1").status == "succeeded"

    # Step 2: run n2
    await step_instance(store_with_dag, "inst1", runner)
    assert store_with_dag.get_node("n2").status == "succeeded"

    # Step 3: run n3
    status = await step_instance(store_with_dag, "inst1", runner)
    assert store_with_dag.get_node("n3").status == "succeeded"
    assert status == "succeeded"  # Instance complete


async def test_step_pauses_at_gate(store_with_gate):
    """Step should pause at gated node (n2)."""
    runner = FakeRunner()

    # Step 1: run n1
    status = await step_instance(store_with_gate, "inst1", runner)
    assert store_with_gate.get_node("n1").status == "succeeded"

    # Step 2: should pause at n2 (gate=approve)
    status = await step_instance(store_with_gate, "inst1", runner)
    n2 = store_with_gate.get_node("n2")
    assert n2.status == "waiting_gate"
    assert status == "waiting_gate"

    # n3 should still be pending
    assert store_with_gate.get_node("n3").status == "pending"


async def test_step_resumes_after_gate_approval(store_with_gate):
    """After gate approval, step should continue."""
    from loom.core.gate import GateDecision, record_gate_decision

    runner = FakeRunner()

    # Run until gate
    await step_instance(store_with_gate, "inst1", runner)
    await step_instance(store_with_gate, "inst1", runner)
    assert store_with_gate.get_node("n2").status == "waiting_gate"

    # Approve gate
    decision = GateDecision(node_id="n2", instance_id="inst1", approved=True)
    record_gate_decision(store_with_gate, decision)

    # Step should now run n2 and continue to n3
    await step_instance(store_with_gate, "inst1", runner)
    assert store_with_gate.get_node("n2").status == "succeeded"

    await step_instance(store_with_gate, "inst1", runner)
    assert store_with_gate.get_node("n3").status == "succeeded"


async def test_step_fails_on_node_failure():
    """If a node fails, instance should fail."""
    from loom.adapters.base import RunnerAdapter, Result

    class FailingRunner(RunnerAdapter):
        name = "failing"
        async def run(self, node) -> Result:
            return Result(success=False, output="failed")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(Instance(id="inst1", template_id="test", status="pending"))
            store.create_node(Node(id="n1", instance_id="inst1", template_id="test",
                                   spec="test", status="pending"))

            runner = FailingRunner()
            status = await step_instance(store, "inst1", runner)

            assert store.get_node("n1").status == "failed"
            assert status == "failed"

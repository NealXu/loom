"""Tests for LoomDaemon (P0-A)."""

import tempfile
import os
import asyncio
import pytest
from loom.core.store import Store
from loom.core.models import Node, Instance
from loom.daemon import LoomDaemon
from loom.adapters.fake import FakeRunner


pytestmark = pytest.mark.asyncio


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as s:
            yield s


async def test_daemon_tick_picks_up_pending(store):
    """Daemon tick should execute pending instances."""
    store.create_instance(Instance(id="i1", template_id="t", status="pending"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           spec="test", status="pending"))

    daemon = LoomDaemon(store, FakeRunner())
    await daemon.tick()

    inst = store.get_instance("i1")
    assert inst.status == "succeeded"
    node = store.get_node("n1")
    assert node.status == "succeeded"


async def test_daemon_tick_multiple_instances(store):
    """Daemon should process all active instances in one tick."""
    store.create_instance(Instance(id="i1", template_id="t", status="pending"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           spec="test", status="pending"))
    store.create_instance(Instance(id="i2", template_id="t", status="pending"))
    store.create_node(Node(id="n2", instance_id="i2", template_id="t",
                           spec="test", status="pending"))

    daemon = LoomDaemon(store, FakeRunner())
    await daemon.tick()

    assert store.get_instance("i1").status == "succeeded"
    assert store.get_instance("i2").status == "succeeded"


async def test_daemon_crash_recovery(store):
    """Daemon should reset running nodes/instances to pending on startup."""
    store.create_instance(Instance(id="i1", template_id="t", status="running"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           spec="test", status="running"))

    daemon = LoomDaemon(store, FakeRunner())
    await daemon.tick()

    # Should have been reset and then executed
    inst = store.get_instance("i1")
    assert inst.status == "succeeded"


async def test_daemon_run_forever_and_stop():
    """Daemon should run until stopped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            daemon = LoomDaemon(store, FakeRunner(), tick_interval=0.1)

            # Run daemon in background
            task = asyncio.create_task(daemon.run_forever())

            # Let it run for a bit
            await asyncio.sleep(0.25)

            # Stop it
            daemon.stop()
            await asyncio.wait_for(task, timeout=1.0)

            # Should have completed without error
            assert not daemon.running


async def test_daemon_handles_gates(store):
    """Daemon should pause at gates and wait for approval."""
    from loom.core.gate import GateDecision, record_gate_decision

    store.create_instance(Instance(id="i1", template_id="t", status="pending"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           spec="test", status="pending", gate="approve"))

    daemon = LoomDaemon(store, FakeRunner())

    # First tick: should pause at gate
    await daemon.tick()
    assert store.get_instance("i1").status == "waiting_gate"
    assert store.get_node("n1").status == "waiting_gate"

    # Approve gate
    decision = GateDecision(node_id="n1", instance_id="i1", approved=True)
    record_gate_decision(store, decision)

    # Second tick: should execute and complete
    await daemon.tick()
    assert store.get_instance("i1").status == "succeeded"
    assert store.get_node("n1").status == "succeeded"

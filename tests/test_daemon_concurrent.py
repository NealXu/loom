"""P5-D: Concurrent daemon execution with tier priority."""
import asyncio
import time
import tempfile
import os
import pytest
from loom.core.store import Store
from loom.core.models import Instance, Node
from loom.daemon import LoomDaemon
from loom.adapters.fake import FakeRunner
from loom.adapters.base import Result


pytestmark = pytest.mark.asyncio


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as s:
            yield s


class SlowFakeRunner(FakeRunner):
    """A FakeRunner that sleeps 0.5s per run to simulate slow work."""

    async def run(self, node) -> Result:
        await asyncio.sleep(0.5)
        return Result(success=True, output=f"echo: {node.spec}")


class TrackingRunner(FakeRunner):
    """A runner that tracks how many runs are active simultaneously."""

    def __init__(self):
        super().__init__()
        self.active = 0
        self.peak_active = 0

    async def run(self, node) -> Result:
        self.active += 1
        if self.active > self.peak_active:
            self.peak_active = self.active
        await asyncio.sleep(0.3)
        self.active -= 1
        return Result(success=True, output=f"echo: {node.spec}")


def _seed_instances(store, ids, status="pending", tier="tooling"):
    """Seed multiple instances each with one pending node."""
    for inst_id in ids:
        store.create_instance(Instance(id=inst_id, template_id="t", status=status))
        store.create_node(Node(id=f"n_{inst_id}", instance_id=inst_id,
                               template_id="t", spec="test",
                               status="pending", tier=tier))


# ---- Test 1: Concurrent execution ----

async def test_tick_processes_instances_concurrently(store):
    """3 pending instances with slow runner should finish in ~0.5s not ~1.5s."""
    _seed_instances(store, ["i1", "i2", "i3"])

    daemon = LoomDaemon(store, SlowFakeRunner())

    start = time.monotonic()
    await daemon.tick()
    elapsed = time.monotonic() - start

    # All three should have completed
    for inst_id in ["i1", "i2", "i3"]:
        assert store.get_instance(inst_id).status == "succeeded"

    # With max_concurrent=2 (default), 3 instances at 0.5s each:
    # Concurrent: batch1(2) + batch2(1) = ~1.0s
    # Sequential: 3 * 0.5s = ~1.5s
    assert elapsed < 1.3, f"Expected concurrent execution (<1.3s) but took {elapsed:.2f}s"


# ---- Test 2: max_concurrent bounds parallelism ----

async def test_tick_respects_max_concurrent(store):
    """With max_concurrent=2 and 4 instances, peak active should be <= 2."""
    _seed_instances(store, ["i1", "i2", "i3", "i4"])

    runner = TrackingRunner()
    daemon = LoomDaemon(store, runner, max_concurrent=2)
    await daemon.tick()

    assert runner.peak_active <= 2, (
        f"Peak active {runner.peak_active} exceeded max_concurrent=2"
    )
    for inst_id in ["i1", "i2", "i3", "i4"]:
        assert store.get_instance(inst_id).status == "succeeded"


# ---- Test 3: Tier priority ordering ----

async def test_tier_priority_ordering(store):
    """Critical-tier instances should be processed before bulk-tier ones."""
    # Create 4 instances with different tiers
    for inst_id, tier in [("i_crit", "critical"), ("i_heavy", "heavy"),
                          ("i_tool", "tooling"), ("i_bulk", "bulk")]:
        store.create_instance(Instance(id=inst_id, template_id="t", status="pending"))
        store.create_node(Node(id=f"n_{inst_id}", instance_id=inst_id,
                               template_id="t", spec="test",
                               status="pending", tier=tier))

    # Use a slow runner so we can verify ordering by completion time
    # The ordering is soft priority: we just verify the sorted order
    # by checking that the daemon's internal sort puts critical first.
    # We verify by checking the instance processing order via a tracker.
    order = []

    class OrderTrackingRunner(FakeRunner):
        async def run(self, node) -> Result:
            order.append(node.instance_id)
            return Result(success=True, output="ok")

    daemon = LoomDaemon(store, OrderTrackingRunner())
    await daemon.tick()

    # All should have succeeded
    for inst_id in ["i_crit", "i_heavy", "i_tool", "i_bulk"]:
        assert store.get_instance(inst_id).status == "succeeded"

    # Critical should come before bulk (soft priority check)
    assert order.index("i_crit") < order.index("i_bulk"), (
        f"Critical should be processed before bulk, but order was {order}"
    )


# ---- Test 4: waiting_gate instances also concurrent ----

async def test_waiting_gate_instances_also_concurrent(store):
    """waiting_gate instances should be processed concurrently too."""
    # We create instances that are already in waiting_gate with nodes that
    # have been approved (status=running so step_instance will resume them).
    for inst_id in ["i1", "i2", "i3"]:
        store.create_instance(Instance(id=inst_id, template_id="t",
                                       status="waiting_gate"))
        store.create_node(Node(id=f"n_{inst_id}", instance_id=inst_id,
                               template_id="t", spec="test",
                               status="running", tier="tooling"))

    daemon = LoomDaemon(store, SlowFakeRunner())

    start = time.monotonic()
    await daemon.tick()
    elapsed = time.monotonic() - start

    # With max_concurrent=2 (default), 3 instances at 0.5s each:
    # Concurrent: batch1(2) + batch2(1) = ~1.0s
    # Sequential: 3 * 0.5s = ~1.5s
    assert elapsed < 1.3, (
        f"Expected concurrent execution of waiting_gate (<1.3s) "
        f"but took {elapsed:.2f}s"
    )


# ---- Test 5: Concurrency config ----

async def test_concurrency_config_from_config(store):
    """LoomDaemon accepts max_concurrent parameter; default is 2."""
    daemon_default = LoomDaemon(store, FakeRunner())
    assert daemon_default.max_concurrent == 2

    daemon_custom = LoomDaemon(store, FakeRunner(), max_concurrent=5)
    assert daemon_custom.max_concurrent == 5

    daemon_one = LoomDaemon(store, FakeRunner(), max_concurrent=1)
    assert daemon_one.max_concurrent == 1

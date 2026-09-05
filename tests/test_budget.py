"""Tests for budget enforcement + cost aggregation (P1-C)."""
import tempfile
import os
import asyncio
import pytest
from loom.core.store import Store
from loom.core.models import Node, Instance
from loom.core.engine import step_instance
from loom.adapters.base import RunnerAdapter, Result


class _CostRunner(RunnerAdapter):
    """Runner that reports a cost on each run."""
    name = "cost"
    def __init__(self, tokens=1000, usd=0.5):
        self.tokens = tokens
        self.usd = usd

    async def run(self, node) -> Result:
        return Result(success=True, output="ok", cost_tokens=self.tokens, cost_usd=self.usd)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as s:
            yield s


async def test_cost_aggregates_to_instance(store):
    """Result cost must accumulate into instance.cost_tokens/cost_usd."""
    store.create_instance(Instance(id="i1", template_id="t", status="pending"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           spec="x", status="pending", budget_tokens=50000))
    store.create_node(Node(id="n2", instance_id="i1", template_id="t",
                           spec="y", status="pending", budget_tokens=50000))
    store.conn.execute("INSERT INTO edges (instance_id, from_node, to_node, type, condition) VALUES (?,?,?,?,?)",
                       ("i1", "n1", "n2", "depends", ""))
    store.conn.commit()

    runner = _CostRunner(tokens=1000, usd=0.5)
    await step_instance(store, "i1", runner)   # runs n1
    await step_instance(store, "i1", runner)   # runs n2

    inst = store.get_instance("i1")
    assert inst.cost_tokens == 2000
    assert inst.cost_usd == pytest.approx(1.0)


async def test_budget_exceeded_blocks_instance(store):
    """When accumulated cost reaches a pending node's budget, instance blocks."""
    store.create_instance(Instance(id="i1", template_id="t", status="pending"))
    store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                           spec="x", status="pending", budget_tokens=50000))
    store.create_node(Node(id="n2", instance_id="i1", template_id="t",
                           spec="y", status="pending", budget_tokens=1000))
    store.conn.execute("INSERT INTO edges (instance_id, from_node, to_node, type, condition) VALUES (?,?,?,?,?)",
                       ("i1", "n1", "n2", "depends", ""))
    store.conn.commit()

    runner = _CostRunner(tokens=1000, usd=0.5)
    status = await step_instance(store, "i1", runner)  # runs n1, cost=1000
    assert status == "running"

    # n2 is ready but instance cost (1000) >= n2 budget (1000)
    status = await step_instance(store, "i1", runner)
    assert status == "blocked"

    inst = store.get_instance("i1")
    assert inst.status == "blocked"
    assert "budget" in inst.blocked_reason.lower()

    # n2 untouched, still pending
    assert store.get_node("n2").status == "pending"


def test_store_add_instance_cost(store):
    store.create_instance(Instance(id="i1", template_id="t", status="running"))
    store.add_instance_cost("i1", 500, 0.25)
    store.add_instance_cost("i1", 300, 0.10)
    inst = store.get_instance("i1")
    assert inst.cost_tokens == 800
    assert inst.cost_usd == pytest.approx(0.35)

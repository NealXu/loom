"""Tests for the Click CLI (loom/cli.py)."""
import asyncio
import json
import os
import tempfile

import pytest
from click.testing import CliRunner

from loom.cli import _run_instance, main
from loom.adapters.base import Result
from loom.core.loader import instantiate, load_template
from loom.core.models import Instance, Node
from loom.core.store import Store


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test.db")


def _seed_instance(db_path, inst_id="abc123"):
    """Helper: create a store file with one instance."""
    with Store(db_path) as store:
        inst = Instance(id=inst_id, template_id="tpl", title="Test instance")
        store.create_instance(inst)
    return inst_id


def _seed_instance_and_node(db_path, inst_id="abc123", node_id="node1"):
    """Helper: create a store file with one instance and one node."""
    with Store(db_path) as store:
        inst = Instance(id=inst_id, template_id="tpl", title="Test instance")
        store.create_instance(inst)
        node = Node(
            id=node_id,
            instance_id=inst_id,
            template_id="tpl",
            title="Analyze step",
            kind="analysis",
        )
        store.create_node(node)
    return inst_id, node_id


def test_cli_list_instances(runner, tmp_db):
    """list command should show seeded instance id."""
    inst_id = _seed_instance(tmp_db)
    result = runner.invoke(main, ["list", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert inst_id in result.output


def test_cli_status_shows_nodes(runner, tmp_db):
    """status command should show node title and kind."""
    inst_id, node_id = _seed_instance_and_node(tmp_db)
    result = runner.invoke(main, ["status", inst_id, "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Analyze step" in result.output
    assert "analysis" in result.output


def test_cli_run_creates_and_executes(runner, tmp_path):
    """run command should create an instance and execute all 3 nodes."""
    db_path = str(tmp_path / "run.db")
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "loom", "templates", "handoff-refresh.yaml"
    )
    params = json.dumps({"project_path": str(tmp_path)})

    result = runner.invoke(
        main,
        ["run", template_path, "--db", db_path, "--params", params, "--runner", "fake"],
    )
    assert result.exit_code == 0, result.output

    # Re-open store and verify
    with Store(db_path) as store:
        rows = store.conn.execute("SELECT * FROM instances").fetchall()
        assert len(rows) == 1
        inst_row = rows[0]
        assert inst_row["status"] == "succeeded"

        node_rows = store.conn.execute(
            "SELECT * FROM nodes WHERE status = 'succeeded'"
        ).fetchall()
        assert len(node_rows) == 3


class _FailingRunner:
    """Stub runner that always returns failure -- used to catch infinite loops."""
    name = "failing"

    async def run(self, node):
        return Result(success=False, error="simulated failure")


def test_run_instance_terminates_on_node_failure(tmp_path):
    """Regression: _run_instance must not infinite-loop when a node fails.

    Without the fail-fast break, the failed node is never added to `completed`,
    so ready_nodes returns it forever.  This test would hang without the fix.
    """
    db_path = str(tmp_path / "fail.db")
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "loom", "templates", "handoff-refresh.yaml"
    )
    tpl = load_template(template_path)
    instance, nodes, edges = instantiate(tpl, {"project_path": str(tmp_path)})

    with Store(db_path) as store:
        store.create_instance(instance)
        for n in nodes:
            store.create_node(n)

        # This must return promptly; a 5-second safety net prevents a true hang.
        try:
            asyncio.run(
                asyncio.wait_for(
                    _run_instance(store, instance, nodes, edges, _FailingRunner()),
                    timeout=5.0,
                )
            )
        except asyncio.TimeoutError:
            pytest.fail("_run_instance hung -- infinite loop on node failure")

        # Instance should be marked failed.
        inst = store.get_instance(instance.id)
        assert inst.status == "failed"

        # Exactly one node should be failed (the first/root one); others remain pending.
        failed_nodes = store.conn.execute(
            "SELECT * FROM nodes WHERE status = 'failed'"
        ).fetchall()
        assert len(failed_nodes) >= 1

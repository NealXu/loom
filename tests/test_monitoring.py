"""Tests for monitoring CLI commands (stats, health, cost)."""

import pytest
from click.testing import CliRunner

from loom.cli import main
from loom.core.models import Instance, Node
from loom.core.store import Store


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "monitoring.db")


def _seed(db_path, instances=None, nodes=None, events=None, gate_decisions=None):
    """Helper: seed a store with arbitrary test data."""
    with Store(db_path) as store:
        for inst in instances or []:
            store.create_instance(inst)
        for node in nodes or []:
            store.create_node(node)
        for ev in events or []:
            store.conn.execute(
                "INSERT INTO events (source, payload, received_at, consumed_by_instance) "
                "VALUES (?, ?, ?, ?)",
                (ev.get("source"), ev.get("payload"), ev.get("received_at"),
                 ev.get("consumed_by_instance")),
            )
        for gd in gate_decisions or []:
            store.conn.execute(
                "INSERT INTO gate_decisions "
                "(node_id, instance_id, approved, approver, reason, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gd.get("node_id"), gd.get("instance_id"), gd.get("approved"),
                 gd.get("approver"), gd.get("reason"), gd.get("decided_at")),
            )
        store.conn.commit()


def _inst(inst_id, status="succeeded", cost_usd=0.0):
    from datetime import datetime
    return Instance(
        id=inst_id, template_id="tpl", title=f"inst-{inst_id}",
        status=status, cost_usd=cost_usd,
    )


def _node(node_id, instance_id, status="succeeded"):
    from datetime import datetime
    return Node(
        id=node_id, instance_id=instance_id, template_id="tpl",
        title=f"node-{node_id}", kind="analysis", status=status,
    )


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def test_stats_displays_instance_and_node_counts(runner, tmp_db):
    """stats should show instance/node totals and by-status breakdowns."""
    _seed(
        tmp_db,
        instances=[
            _inst("i1", status="succeeded"),
            _inst("i2", status="succeeded"),
            _inst("i3", status="failed"),
        ],
        nodes=[
            _node("n1", "i1", status="succeeded"),
            _node("n2", "i1", status="succeeded"),
            _node("n3", "i2", status="running"),
            _node("n4", "i3", status="pending"),
        ],
        events=[
            {"source": "test", "payload": "{}", "received_at": "2026-09-05T00:00:00"},
        ],
        gate_decisions=[
            {"node_id": "n1", "instance_id": "i1", "approved": 1, "approver": "user",
             "reason": "ok", "decided_at": "2026-09-05T00:00:00"},
        ],
    )
    result = runner.invoke(main, ["stats", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Instances (3)" in result.output
    assert "succeeded: 2" in result.output
    assert "failed: 1" in result.output
    assert "Nodes (4)" in result.output
    assert "running: 1" in result.output
    assert "pending: 1" in result.output
    assert "Events:         1" in result.output
    assert "Gate decisions: 1" in result.output


def test_stats_empty_store(runner, tmp_db):
    """stats on an empty store should show zero totals."""
    result = runner.invoke(main, ["stats", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Instances (0)" in result.output
    assert "Nodes (0)" in result.output
    assert "Events:         0" in result.output


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

def test_health_displays_recent_success_rate(runner, tmp_db):
    """health should compute success rate from the last 10 instances."""
    instances = [
        _inst(f"i{i}", status="succeeded", cost_usd=0.10) for i in range(5)
    ] + [
        _inst(f"i{i + 5}", status="failed", cost_usd=0.0) for i in range(3)
    ]
    _seed(tmp_db, instances=instances)
    result = runner.invoke(main, ["health", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    # 5 succeeded out of 8 total -> 62.5%
    assert "62.5%" in result.output
    assert "5 succeeded" in result.output
    assert "3 failed" in result.output


def test_health_no_instances(runner, tmp_db):
    """health on an empty store should handle the 'no instances' case gracefully."""
    result = runner.invoke(main, ["health", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "No instances recorded yet." in result.output


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------

def test_cost_for_specific_instance(runner, tmp_db):
    """cost <instance_id> should show the cost breakdown for that instance."""
    _seed(tmp_db, instances=[_inst("i1", status="succeeded", cost_usd=0.0042)])
    result = runner.invoke(main, ["cost", "i1", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Instance i1" in result.output
    assert "$0.004200" in result.output


def test_cost_aggregate(runner, tmp_db):
    """cost (no arg) should show aggregate costs across all instances."""
    _seed(
        tmp_db,
        instances=[
            _inst("i1", status="succeeded", cost_usd=0.01),
            _inst("i2", status="succeeded", cost_usd=0.02),
            _inst("i3", status="failed", cost_usd=0.005),
        ],
    )
    result = runner.invoke(main, ["cost", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Aggregate costs" in result.output
    assert "instances:    3" in result.output
    assert "$0.035000" in result.output


def test_cost_missing_instance(runner, tmp_db):
    """cost <missing_id> should error with a clear message."""
    result = runner.invoke(main, ["cost", "missing", "--db", tmp_db])
    assert result.exit_code != 0
    assert "no instance or template found" in result.output.lower()

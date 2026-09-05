"""Tests for cost, history, and audit CLI commands (Task 26)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from loom.cli import main
from loom.core.models import Instance, Node
from loom.core.state import record_transition
from loom.core.store import Store


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def tmp_db(tmp_path):
    return str(tmp_path / "test.db")


def _seed(db_path, instances, *, gate_decisions=None, transitions=None):
    """Populate the store with instances and optional gate/transition rows."""
    with Store(db_path) as store:
        for inst in instances:
            store.create_instance(inst)

        if gate_decisions:
            for gd in gate_decisions:
                store.conn.execute(
                    """INSERT INTO gate_decisions
                       (node_id, instance_id, approved, approver, reason, decided_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        gd["node_id"],
                        gd["instance_id"],
                        gd["approved"],
                        gd.get("approver"),
                        gd.get("reason"),
                        gd["decided_at"],
                    ),
                )
            store.conn.commit()

        if transitions:
            for tr in transitions:
                record_transition(
                    store,
                    tr["entity_kind"],
                    tr["entity_id"],
                    tr["from_status"],
                    tr["to_status"],
                )


# ------------------------------------------------------------------ cost ---


def test_cost_aggregate(runner, tmp_db):
    """cost (no args) should show aggregate totals across all instances."""
    _seed(
        tmp_db,
        [
            Instance(id="i1", template_id="tpl_a", cost_tokens=100, cost_usd=0.01),
            Instance(id="i2", template_id="tpl_b", cost_tokens=200, cost_usd=0.02),
        ],
    )

    result = runner.invoke(main, ["cost", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Aggregate costs" in result.output
    assert "instances:    2" in result.output
    assert "total_tokens: 300" in result.output
    assert "0.030000" in result.output  # total_usd
    assert "avg_usd:" in result.output


def test_cost_by_template(runner, tmp_db):
    """cost <template_id> should show costs for instances of that template."""
    _seed(
        tmp_db,
        [
            Instance(id="i1", template_id="tpl_a", cost_tokens=100, cost_usd=0.01),
            Instance(id="i2", template_id="tpl_a", cost_tokens=200, cost_usd=0.02),
            Instance(id="i3", template_id="tpl_b", cost_tokens=500, cost_usd=0.05),
        ],
    )

    result = runner.invoke(main, ["cost", "tpl_a", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Template tpl_a" in result.output
    assert "instances:     2" in result.output
    assert "total_tokens:  300" in result.output
    assert "0.030000" in result.output
    # avg = 0.03 / 2 = 0.015
    assert "0.015000" in result.output


def test_cost_by_instance(runner, tmp_db):
    """cost <instance_id> should show cost for that specific instance."""
    _seed(
        tmp_db,
        [Instance(id="i1", template_id="tpl", cost_tokens=42, cost_usd=0.0042)],
    )

    result = runner.invoke(main, ["cost", "i1", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Instance i1" in result.output
    assert "cost_tokens: 42" in result.output
    assert "0.004200" in result.output


def test_cost_unknown_entity(runner, tmp_db):
    """cost <unknown> should exit with an error."""
    _seed(tmp_db, [])
    result = runner.invoke(main, ["cost", "nonexistent", "--db", tmp_db])
    assert result.exit_code != 0
    assert "No instance or template found" in result.output


# -------------------------------------------------------------- history ---


def test_history_default(runner, tmp_db):
    """history (no args) should list recent instances, most recent first."""
    _seed(
        tmp_db,
        [
            Instance(id="i1", template_id="tpl", status="succeeded", cost_usd=0.01),
            Instance(id="i2", template_id="tpl", status="failed", cost_usd=0.02),
        ],
    )

    result = runner.invoke(main, ["history", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    # i2 was created after i1 (same template, but inserted later), so i2 first.
    assert "i2" in result.output
    assert "i1" in result.output
    # Both should appear.
    lines = [ln for ln in result.output.splitlines() if ln.startswith("i")]
    assert len(lines) == 2


def test_history_filter_by_status(runner, tmp_db):
    """history --status <s> should only show instances with that status."""
    _seed(
        tmp_db,
        [
            Instance(id="i1", template_id="tpl", status="succeeded"),
            Instance(id="i2", template_id="tpl", status="failed"),
            Instance(id="i3", template_id="tpl", status="succeeded"),
        ],
    )

    result = runner.invoke(main, ["history", "--status", "succeeded", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "i1" in result.output
    assert "i3" in result.output
    assert "i2" not in result.output


def test_history_filter_by_template(runner, tmp_db):
    """history --template <t> should only show instances of that template."""
    _seed(
        tmp_db,
        [
            Instance(id="i1", template_id="alpha"),
            Instance(id="i2", template_id="beta"),
        ],
    )

    result = runner.invoke(main, ["history", "--template", "alpha", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "i1" in result.output
    assert "i2" not in result.output


def test_history_empty(runner, tmp_db):
    """history on empty store should print a helpful message."""
    _seed(tmp_db, [])
    result = runner.invoke(main, ["history", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "No instances found" in result.output


# ---------------------------------------------------------------- audit ---


def test_audit_no_args_shows_gate_decisions(runner, tmp_db):
    """audit (no args) should list all gate decisions, most recent first."""
    _seed(
        tmp_db,
        [Instance(id="i1", template_id="tpl")],
        gate_decisions=[
            {
                "node_id": "n1",
                "instance_id": "i1",
                "approved": 1,
                "approver": "user",
                "reason": "looks good",
                "decided_at": "2026-01-01T10:00:00",
            },
            {
                "node_id": "n2",
                "instance_id": "i1",
                "approved": 0,
                "approver": "user",
                "reason": "too risky",
                "decided_at": "2026-01-01T11:00:00",
            },
        ],
    )

    result = runner.invoke(main, ["audit", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Gate decisions" in result.output
    assert "n1" in result.output
    assert "n2" in result.output
    assert "approved" in result.output
    assert "denied" in result.output


def test_audit_by_instance(runner, tmp_db):
    """audit <instance_id> should show gate decisions + state transitions."""
    _seed(
        tmp_db,
        [Instance(id="i1", template_id="tpl")],
        gate_decisions=[
            {
                "node_id": "n1",
                "instance_id": "i1",
                "approved": 1,
                "approver": "user",
                "reason": "ok",
                "decided_at": "2026-01-01T10:00:00",
            },
        ],
        transitions=[
            {
                "entity_kind": "instance",
                "entity_id": "i1",
                "from_status": "pending",
                "to_status": "running",
            },
        ],
    )

    result = runner.invoke(main, ["audit", "i1", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "Audit trail for instance i1" in result.output
    assert "Gate decisions:" in result.output
    assert "n1" in result.output
    assert "State transitions:" in result.output
    assert "pending->running" in result.output


def test_audit_unknown_instance(runner, tmp_db):
    """audit <unknown> should exit with an error."""
    _seed(tmp_db, [])
    result = runner.invoke(main, ["audit", "nonexistent", "--db", tmp_db])
    assert result.exit_code != 0
    assert "Instance not found" in result.output


def test_audit_empty(runner, tmp_db):
    """audit on empty store should print a helpful message."""
    _seed(tmp_db, [])
    result = runner.invoke(main, ["audit", "--db", tmp_db])
    assert result.exit_code == 0, result.output
    assert "No gate decisions recorded" in result.output

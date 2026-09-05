"""Tests for CLI commands (P0-B gate + serve)."""

import tempfile
import os
import pytest
from click.testing import CliRunner
from loom.cli import main
from loom.core.store import Store
from loom.core.models import Node, Instance


def test_gate_list_empty():
    """loom gate list should show message when no pending gates."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        result = runner.invoke(main, ["gate", "list", "--db", db_path])
        assert result.exit_code == 0
        assert "No pending gates" in result.output


def test_gate_list_with_pending():
    """loom gate list should show waiting_gate nodes."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(Instance(id="i1", template_id="t", status="waiting_gate"))
            store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                                   title="Merge PR", status="waiting_gate", gate="approve"))

        result = runner.invoke(main, ["gate", "list", "--db", db_path])
        assert result.exit_code == 0
        assert "n1" in result.output
        assert "Merge PR" in result.output


def test_gate_approve():
    """loom gate approve should approve a waiting_gate node."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(Instance(id="i1", template_id="t", status="waiting_gate"))
            store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                                   status="waiting_gate", gate="approve"))

        result = runner.invoke(main, ["gate", "approve", "n1", "--db", db_path])
        assert result.exit_code == 0
        assert "approved" in result.output.lower()

        # Verify node transitioned
        with Store(db_path) as store:
            node = store.get_node("n1")
            assert node.status == "running"


def test_gate_reject():
    """loom gate reject should cancel a waiting_gate node."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            store.create_instance(Instance(id="i1", template_id="t", status="waiting_gate"))
            store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                                   status="waiting_gate", gate="approve"))

        result = runner.invoke(main, ["gate", "reject", "n1", "--reason", "Not ready", "--db", db_path])
        assert result.exit_code == 0
        assert "rejected" in result.output.lower()

        # Verify node transitioned
        with Store(db_path) as store:
            node = store.get_node("n1")
            assert node.status == "cancelled"


def test_run_bg_mode():
    """loom run --bg should create instance without executing."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        # Create a minimal template
        template_path = os.path.join(tmpdir, "test.yaml")
        with open(template_path, "w") as f:
            f.write("""
id: test-template
version: 1
trigger: [cli]
provenance: manual
params: {}
nodes:
  - id: n1
    kind: analysis
    spec: echo test
    depends_on: []
""")

        result = runner.invoke(main, ["run", template_path, "--db", db_path, "--bg", "--runner", "fake"])
        assert result.exit_code == 0
        assert "created" in result.output.lower() or "pending" in result.output.lower()

        # Verify instance created but not executed
        with Store(db_path) as store:
            instances = store.list_instances_by_status("pending")
            assert len(instances) == 1

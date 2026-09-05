"""M2 end-to-end integration test.

Proves the full pipeline works with real components:
  load_template -> instantiate -> Store (persist) -> scheduler -> FakeRunner -> state

Uses the handoff-refresh.yaml template (3 nodes: analyze -> refresh -> commit).
The commit node has gate=approve; for this integration test the gate is bypassed
(auto-approved) because the gate-decision flow is Task 22.  The simpler correct
option is to treat the gate node like any other and transition it straight through
running -> succeeded, which is what we do here.
"""
import asyncio
import os
import tempfile

from loom.core.loader import load_template, instantiate
from loom.core.store import Store
from loom.core.scheduler import ready_nodes, topological_order
from loom.core.state import record_transition
from loom.adapters.fake import FakeRunner


# -- helpers -----------------------------------------------------------------

def _edge_dicts(edges):
    """Convert Edge model objects to the plain dicts the scheduler expects."""
    return [{"from_node": e.from_node, "to_node": e.to_node} for e in edges]


def _update_node_status(store, node_id, status):
    store.conn.execute("UPDATE nodes SET status = ? WHERE id = ?", (status, node_id))
    store.conn.commit()


def _update_instance_status(store, inst_id, status):
    store.conn.execute("UPDATE instances SET status = ? WHERE id = ?", (status, inst_id))
    store.conn.commit()


# -- tests -------------------------------------------------------------------

def test_m2_full_pipeline():
    """End-to-end: load template, instantiate, persist, schedule, run, verify."""
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "loom", "templates", "handoff-refresh.yaml",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "integration.db")

        # 1. Load & instantiate (real loader + template).
        template = load_template(template_path)
        assert template.id == "handoff-refresh"

        params = {"project_path": tmpdir}
        instance, nodes, edges = instantiate(template, params)
        assert len(nodes) == 3
        assert len(edges) == 2

        # Build a mapping from template-node-id to generated node id,
        # so we can verify execution order against the template DAG.
        node_by_id = {n.id: n for n in nodes}
        # Map template-id -> generated id for order assertions.
        title_to_gen_id = {n.title: n.id for n in nodes}

        edge_ds = _edge_dicts(edges)

        # 2. Persist to Store.
        with Store(db_path) as store:
            store.create_instance(instance)
            for node in nodes:
                store.create_node(node)

            # 3. Verify topological order before running.
            topo = topological_order([n.id for n in nodes], edge_ds)
            # analyze must precede refresh; refresh must precede commit.
            analyze_id = title_to_gen_id["analyze"]
            refresh_id = title_to_gen_id["refresh"]
            commit_id = title_to_gen_id["commit"]
            assert topo.index(analyze_id) < topo.index(refresh_id)
            assert topo.index(refresh_id) < topo.index(commit_id)

            # 4. Execute the DAG with FakeRunner.
            fake = FakeRunner()
            completed: set[str] = set()
            finish_order: list[str] = []

            # Instance: pending -> running.
            record_transition(store, "instance", instance.id, "pending", "running")
            _update_instance_status(store, instance.id, "running")

            node_ids = [n.id for n in nodes]

            while len(completed) < len(node_ids):
                ready = ready_nodes(node_ids, edge_ds, completed)
                assert ready, "deadlock: no ready nodes but not all complete"
                for nid in ready:
                    node = store.get_node(nid)

                    # pending -> running
                    assert record_transition(store, "node", nid, "pending", "running")
                    _update_node_status(store, nid, "running")

                    # Execute via FakeRunner (async).
                    result = asyncio.run(fake.run(node))
                    assert result.success is True

                    # Gate bypass: the commit node has gate=approve.
                    # For M2 integration we auto-approve and go straight to
                    # succeeded.  The full gate-decision flow is Task 22.
                    # running -> succeeded
                    assert record_transition(store, "node", nid, "running", "succeeded")
                    _update_node_status(store, nid, "succeeded")
                    completed.add(nid)
                    finish_order.append(nid)

            # Instance: running -> succeeded.
            record_transition(store, "instance", instance.id, "running", "succeeded")
            _update_instance_status(store, instance.id, "succeeded")

            # 5. Assertions.

            # All 3 nodes are succeeded in the Store.
            for n in nodes:
                persisted = store.get_node(n.id)
                assert persisted.status == "succeeded", (
                    f"node {n.title} ({n.id}) should be succeeded, got {persisted.status}"
                )

            # Instance is succeeded in the Store.
            persisted_inst = store.get_instance(instance.id)
            assert persisted_inst.status == "succeeded"

            # Execution order respects dependencies:
            # analyze before refresh before commit.
            assert finish_order.index(analyze_id) < finish_order.index(refresh_id)
            assert finish_order.index(refresh_id) < finish_order.index(commit_id)

            # State-transition events were recorded (count > 0).
            row = store.conn.execute(
                "SELECT COUNT(*) AS cnt FROM events WHERE source = 'state_transition'",
            ).fetchone()
            assert row["cnt"] > 0

            # Expect: 3 nodes * 2 transitions + 2 instance transitions = 8.
            assert row["cnt"] == 8


def test_m2_loader_rejects_bad_template(tmp_path):
    """load_template raises on a structurally invalid YAML file."""
    import pytest

    bad = tmp_path / "bad.yaml"
    bad.write_text("id: oops\n")  # missing required keys
    with pytest.raises(ValueError, match="missing required key"):
        load_template(str(bad))

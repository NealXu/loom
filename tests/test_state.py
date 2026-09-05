import tempfile
import os
from loom.core.state import (
    can_transition,
    record_transition,
    INSTANCE_TRANSITIONS,
    NODE_TRANSITIONS,
)
from loom.core.store import Store

def test_valid_instance_transition():
    # pending -> running is allowed
    assert can_transition("instance", "pending", "running") is True

def test_invalid_instance_transition():
    # succeeded -> running is not allowed (no retry from terminal success)
    assert can_transition("instance", "succeeded", "running") is False

def test_instance_running_destinations():
    # running can go to waiting_gate / succeeded / failed / blocked
    assert can_transition("instance", "running", "waiting_gate") is True
    assert can_transition("instance", "running", "succeeded") is True
    assert can_transition("instance", "running", "failed") is True
    assert can_transition("instance", "running", "blocked") is True

def test_node_retry_from_failed():
    # a failed node may be retried
    assert can_transition("node", "failed", "running") is True

def test_record_transition_writes_event():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            ok = record_transition(store, "instance", "inst1", "pending", "running")
            assert ok is True
            row = store.conn.execute(
                "SELECT * FROM events WHERE source='state_transition'"
            ).fetchone()
            assert row is not None
            assert row["consumed_by_instance"] == "inst1"

def test_record_transition_rejects_invalid():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with Store(db_path) as store:
            ok = record_transition(store, "instance", "inst1", "succeeded", "running")
            assert ok is False
            count = store.conn.execute(
                "SELECT COUNT(*) AS c FROM events WHERE source='state_transition'"
            ).fetchone()["c"]
            assert count == 0

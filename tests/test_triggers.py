"""Tests for loom.triggers.hooks — CC hooks HTTP receiver."""

import json
import pytest
from loom.core.store import Store
from loom.triggers.hooks import process_hook, create_app


@pytest.fixture
def store(tmp_path):
    with Store(str(tmp_path / "test.db")) as s:
        yield s


# --- process_hook tests ---


def test_process_hook_records_event(store):
    payload = {"session_id": "sess-42", "action": "edit", "file": "foo.py"}
    event = process_hook(store, payload)

    assert event.source == "hook"
    assert event.payload == payload
    assert event.consumed_by_instance == "sess-42"

    row = store.conn.execute("SELECT * FROM events WHERE source='hook'").fetchone()
    assert row is not None
    assert row["source"] == "hook"
    assert json.loads(row["payload"]) == payload
    assert row["consumed_by_instance"] == "sess-42"
    assert row["received_at"] is not None


def test_process_hook_rejects_empty(store):
    with pytest.raises(ValueError):
        process_hook(store, {})
    row = store.conn.execute("SELECT COUNT(*) AS c FROM events WHERE source='hook'").fetchone()
    assert row["c"] == 0


def test_process_hook_rejects_non_dict(store):
    with pytest.raises(ValueError):
        process_hook(store, "not-a-dict")


# --- create_app tests ---


def test_create_app_has_hook_route(store):
    app = create_app(store)
    paths = {resource.canonical for resource in app.router.resources()}
    assert "/hook" in paths

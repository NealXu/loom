"""Tests for event -> template dispatch (P2-K)."""
import json
import os
import tempfile
import pytest
from loom.core.store import Store
from loom.core.models import Event
from loom.core.dispatcher import dispatch_events

TPL = """
id: {id}
version: 1
trigger: {trigger}
provenance: manual
params:
  project_path: {{type: string, required: true}}
nodes:
  - id: step1
    kind: analysis
    spec: "do {{project_path}}"
    depends_on: []
"""


@pytest.fixture
def env(tmp_path):
    """Store + templates dir with an inbox-triggered template."""
    tdir = tmp_path / "templates"
    tdir.mkdir()
    (tdir / "inbox-work.yaml").write_text(
        TPL.format(id="inbox-work", trigger="[inbox]"), encoding="utf-8")
    db = str(tmp_path / "test.db")
    with Store(db) as store:
        yield store, str(tdir)


def _mk_event(store, source, payload):
    store.conn.execute(
        "INSERT INTO events (source, payload, received_at, consumed_by_instance) VALUES (?,?,?,?)",
        (source, json.dumps(payload), "2026-09-05T00:00:00", ""),
    )
    store.conn.commit()


def test_inbox_event_creates_instance(env):
    store, tdir = env
    _mk_event(store, "inbox", {"params": {"project_path": "/x"}})
    created = dispatch_events(store, tdir)
    assert len(created) == 1
    inst = store.get_instance(created[0])
    assert inst.template_id == "inbox-work"
    assert inst.status == "pending"
    assert inst.params.get("project_path") == "/x"


def test_event_marked_dispatched(env):
    store, tdir = env
    _mk_event(store, "inbox", {"params": {"project_path": "/x"}})
    dispatch_events(store, tdir)
    row = store.conn.execute("SELECT dispatched FROM events").fetchone()
    assert row["dispatched"] != ""  # consumed, will not re-dispatch


def test_no_dispatch_twice(env):
    store, tdir = env
    _mk_event(store, "inbox", {"params": {"project_path": "/x"}})
    assert len(dispatch_events(store, tdir)) == 1
    assert dispatch_events(store, tdir) == []  # second run is a no-op


def test_nomatch_source_ignored(env):
    store, tdir = env
    _mk_event(store, "cron", {"params": {}})  # no cron-triggered template here
    assert dispatch_events(store, tdir) == []
    row = store.conn.execute("SELECT dispatched FROM events").fetchone()
    assert row["dispatched"] == "nomatch"


def test_state_transition_events_skipped(env):
    store, tdir = env
    from loom.core.state import record_transition
    record_transition(store, "node", "x", "pending", "running")  # writes event
    before = store.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    dispatch_events(store, tdir)
    after = store.conn.execute(
        "SELECT COUNT(*) FROM events WHERE source='state_transition' AND dispatched != ''").fetchone()[0]
    assert before == 1
    assert after == 0  # internal events never dispatched


def test_missing_required_params_marks_error(env):
    store, tdir = env
    _mk_event(store, "inbox", {})  # no params -> instantiate raises
    created = dispatch_events(store, tdir)
    assert created == []
    row = store.conn.execute("SELECT dispatched FROM events").fetchone()
    assert row["dispatched"].startswith("error")


def test_daemon_tick_dispatches(env):
    import asyncio
    from loom.daemon import LoomDaemon
    from loom.adapters.fake import FakeRunner
    store, tdir = env
    _mk_event(store, "inbox", {"params": {"project_path": "/x"}})
    daemon = LoomDaemon(store, FakeRunner(), templates_dir=tdir)

    async def _two_ticks():
        await daemon.tick()   # dispatch + start instance
        await daemon.tick()   # continue if needed

    asyncio.run(_two_ticks())
    insts = store.list_instances_by_status("succeeded")
    assert len(insts) == 1

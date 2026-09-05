"""Tests for the cron scheduler + template-targeted dispatch (P2-L)."""
import json
import pytest
from loom.core.store import Store
from loom.core.models import Event
from loom.core.schedule import CronScheduler
from loom.core.dispatcher import dispatch_events

TPL = """
id: daily-digest
version: 1
trigger: [cli]
provenance: manual
params: {}
nodes:
  - id: s1
    kind: report
    spec: "digest"
    depends_on: []
"""


@pytest.fixture
def env(tmp_path):
    tdir = tmp_path / "templates"
    tdir.mkdir()
    (tdir / "daily-digest.yaml").write_text(TPL, encoding="utf-8")
    with Store(str(tmp_path / "t.db")) as store:
        yield store, str(tdir)


JOBS = [{"template": "daily-digest", "every_seconds": 100, "params": {}}]


def test_scheduler_fires_when_due(env):
    store, tdir = env
    sched = CronScheduler(JOBS)
    events = sched.maybe_fire(store, now=1000.0)
    assert len(events) == 1
    assert events[0].source == "cron"
    assert events[0].payload["template"] == "daily-digest"


def test_scheduler_no_refire_within_interval(env):
    store, tdir = env
    sched = CronScheduler(JOBS)
    assert len(sched.maybe_fire(store, now=1000.0)) == 1
    assert sched.maybe_fire(store, now=1050.0) == []      # not due yet
    assert len(sched.maybe_fire(store, now=1101.0)) == 1  # due again


def test_cron_event_dispatched_by_template_name(env):
    """payload['template'] targets by name even if source isn't in trigger."""
    store, tdir = env
    store.create_event(Event(source="cron",
                             payload={"template": "daily-digest", "params": {}}))
    created = dispatch_events(store, tdir)
    assert len(created) == 1
    assert store.get_instance(created[0]).template_id == "daily-digest"


def test_unknown_template_marks_error(env):
    store, tdir = env
    store.create_event(Event(source="cron", payload={"template": "ghost"}))
    assert dispatch_events(store, tdir) == []
    row = store.conn.execute("SELECT dispatched FROM events").fetchone()
    assert row["dispatched"].startswith("error")


def test_load_schedule_from_config(tmp_path):
    from loom.core.schedule import load_jobs
    cfg = tmp_path / "loom.toml"
    cfg.write_text("""
[[schedule.jobs]]
template = "daily-digest"
every_seconds = 86400
params = { project_path = "/x" }
""", encoding="utf-8")
    from loom.core.router import load_config
    jobs = load_jobs(load_config(str(cfg)))
    assert jobs == [{"template": "daily-digest", "every_seconds": 86400,
                     "params": {"project_path": "/x"}}]
    assert load_jobs({}) == []

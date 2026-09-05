"""P4-B: scheduler state persists across daemon restarts."""
import pytest
from loom.core.store import Store
from loom.core.schedule import CronScheduler

JOBS = [{"template": "daily", "every_seconds": 100, "params": {}}]


@pytest.fixture
def store(tmp_path):
    with Store(str(tmp_path / "t.db")) as s:
        yield s


def test_fire_persists_state(store):
    sched = CronScheduler(JOBS)
    sched.maybe_fire(store, now=1000.0)
    row = store.conn.execute(
        "SELECT last_fire_at FROM schedule_state WHERE template_id = 'daily'").fetchone()
    assert row is not None and float(row["last_fire_at"]) == pytest.approx(1000.0)


def test_restart_respects_persisted_state(store):
    """A fresh scheduler on the same store must NOT immediately re-fire."""
    CronScheduler(JOBS).maybe_fire(store, now=1000.0)

    restarted = CronScheduler(JOBS)
    assert restarted.maybe_fire(store, now=1050.0) == []     # still within interval
    assert len(restarted.maybe_fire(store, now=1101.0)) == 1  # due again


def test_first_ever_fire_still_immediate(store):
    """No prior state -> fires at once (daemon fresh install)."""
    sched = CronScheduler(JOBS)
    assert len(sched.maybe_fire(store, now=5000.0)) == 1


def test_upsert_not_duplicate_rows(store):
    sched = CronScheduler(JOBS)
    sched.maybe_fire(store, now=1000.0)
    sched.maybe_fire(store, now=1101.0)
    n = store.conn.execute("SELECT COUNT(*) c FROM schedule_state").fetchone()["c"]
    assert n == 1

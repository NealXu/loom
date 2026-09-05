"""Lightweight interval scheduler (P2-L).

Turns ``[[schedule.jobs]]`` entries from ``loom.toml`` into periodic
``cron`` events on the store. The daemon calls :meth:`CronScheduler.maybe_fire`
each tick; when a job is due it emits an event whose payload carries
``{"template": ..., "params": ...}``, which the dispatcher targets by name.

Interval-only by design (no cron expression parsing) to stay thin; state is
in-memory per daemon process — a restart re-arms all jobs.
"""
from __future__ import annotations

from loom.core.models import Event


def load_jobs(config: dict) -> list[dict]:
    """Extract the schedule jobs list from a loaded loom.toml config."""
    return list(config.get("schedule", {}).get("jobs", []))


class CronScheduler:
    """Fires due jobs as cron events, tracking last-run per template."""

    def __init__(self, jobs: list[dict]):
        self._jobs = [j for j in jobs if j.get("template")]
        self._last_fire: dict[str, float] = {}

    def maybe_fire(self, store, now: float) -> list[Event]:
        """Emit events for every job whose interval has elapsed. Returns events.

        Last-fire time is persisted in the ``schedule_state`` table so a daemon
        restart neither double-fires nor loses track of a job's cadence. *now*
        is a wall-clock epoch (``time.time()``), meaningful across processes.
        """
        fired: list[Event] = []
        for job in self._jobs:
            tpl = job["template"]
            interval = float(job.get("every_seconds", 86400))
            row = store.conn.execute(
                "SELECT last_fire_at FROM schedule_state WHERE template_id = ?",
                (tpl,)).fetchone()
            last = float(row["last_fire_at"]) if row and row["last_fire_at"] else None
            if last is not None and (now - last) < interval:
                continue
            store.conn.execute(
                """INSERT INTO schedule_state (template_id, last_fire_at)
                   VALUES (?, ?)
                   ON CONFLICT(template_id) DO UPDATE SET last_fire_at = excluded.last_fire_at""",
                (tpl, str(now)),
            )
            store.conn.commit()
            event = Event(source="cron",
                          payload={"template": tpl, "params": job.get("params", {})})
            store.create_event(event)
            fired.append(event)
        return fired

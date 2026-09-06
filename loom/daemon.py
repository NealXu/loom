"""Loom Daemon — async tick loop for instance orchestration (P0-A).

The daemon runs in a single asyncio event loop alongside the FastAPI web server.
Each tick:
1. Crash recovery: reset running nodes/instances to pending
2. Find all active instances (pending, running, waiting_gate)
3. For waiting_gate: check if gates were approved, resume nodes
4. For pending/running: call step_instance to advance
"""

import asyncio
import logging
import time
from datetime import datetime
from loom.core.engine import step_instance
from loom.core.state import record_transition

logger = logging.getLogger(__name__)


class LoomDaemon:
    """Async daemon that orchestrates instance execution."""

    TIER_PRIORITY = {"critical": 0, "heavy": 1, "tooling": 2, "bulk": 3}

    def __init__(self, store, runner, tick_interval: float = 2.0,
                 templates_dir: str | None = None, schedule_jobs: list[dict] | None = None,
                 vault_dir: str | None = None, max_concurrent: int = 2):
        self.store = store
        self.runner = runner
        self.tick_interval = tick_interval
        self.templates_dir = templates_dir
        self.vault_dir = vault_dir
        self.max_concurrent = max_concurrent
        self.scheduler = None
        if schedule_jobs:
            from loom.core.schedule import CronScheduler
            self.scheduler = CronScheduler(schedule_jobs)
        self.running = False
        self._initial_recovery_done = False

    async def tick(self):
        """Single tick: recover crashes, fire schedule, dispatch events, process instances."""
        # Crash recovery: only on first tick (daemon startup)
        if not self._initial_recovery_done:
            await self._crash_recovery()
            self._initial_recovery_done = True

        # P2-L: fire due scheduled jobs as cron events (wall-clock for
        # persisted state to survive restarts).
        if self.scheduler is not None:
            try:
                self.scheduler.maybe_fire(self.store, now=time.time())
            except Exception as e:
                logger.error(f"schedule fire failed: {e}")

        # P2-K: convert trigger events into new instances
        if self.templates_dir is not None:
            from loom.core.dispatcher import dispatch_events
            try:
                created = dispatch_events(self.store, self.templates_dir)
                if created:
                    logger.info(f"dispatched {len(created)} new instance(s)")
            except Exception as e:
                logger.error(f"event dispatch failed: {e}")

        # Find all active instances
        pending = self.store.list_instances_by_status("pending")
        running = self.store.list_instances_by_status("running")
        waiting = self.store.list_instances_by_status("waiting_gate")

        # Order by tier priority (critical first) — soft priority, not strict sequencing
        waiting.sort(key=self._tier_sort_key)
        active = sorted(pending + running, key=self._tier_sort_key)

        sem = asyncio.Semaphore(self.max_concurrent)

        async def _step_with_sem(inst):
            async with sem:
                try:
                    status = await step_instance(
                        self.store, inst.id, self.runner, vault_dir=self.vault_dir
                    )
                    logger.debug(f"Instance {inst.id} -> {status}")
                except Exception as e:
                    logger.error(f"Error processing instance {inst.id}: {e}")
                    # Mark as failed to prevent infinite retries
                    try:
                        record_transition(
                            self.store, "instance", inst.id,
                            self.store.get_instance(inst.id).status, "failed",
                        )
                        self.store.update_instance_status(
                            inst.id, "failed",
                            finished_at=datetime.now().isoformat(),
                        )
                    except Exception:
                        pass

        # Process waiting_gate instances: check for approved gates, then step concurrently
        async def _step_waiting(inst):
            await self._check_gate_resumption(inst.id)
            await _step_with_sem(inst)

        if waiting:
            await asyncio.gather(*[_step_waiting(inst) for inst in waiting])

        # Process pending and running instances concurrently
        if active:
            await asyncio.gather(*[_step_with_sem(inst) for inst in active])

    def _tier_sort_key(self, inst) -> int:
        """Return the highest-priority tier among the instance's nodes (lower = higher priority)."""
        try:
            nodes = self.store.list_nodes(inst.id)
        except Exception:
            return 999
        if not nodes:
            return 999
        return min(self.TIER_PRIORITY.get(n.tier, 99) for n in nodes)

    async def _crash_recovery(self):
        """Reset running nodes/instances to pending (crash recovery)."""
        # Reset running nodes to pending
        self.store.conn.execute(
            "UPDATE nodes SET status = 'pending' WHERE status = 'running'"
        )
        # Reset running instances to pending
        self.store.conn.execute(
            "UPDATE instances SET status = 'pending' WHERE status = 'running'"
        )
        self.store.conn.commit()

    async def _check_gate_resumption(self, instance_id: str):
        """Check if any gates were approved and resume nodes."""
        # Find nodes in waiting_gate for this instance
        nodes = self.store.list_nodes(instance_id)
        for node in nodes:
            if node.status == "waiting_gate":
                # Check if there's an approved gate decision
                row = self.store.conn.execute(
                    "SELECT approved FROM gate_decisions WHERE node_id = ? ORDER BY decided_at DESC LIMIT 1",
                    (node.id,)
                ).fetchone()
                if row and row["approved"]:
                    # Gate was approved, node should already be in running state
                    # (record_gate_decision handles the transition)
                    pass

    async def run_forever(self):
        """Main loop: tick until stopped."""
        self.running = True
        logger.info(f"Daemon started (tick_interval={self.tick_interval}s)")
        try:
            while self.running:
                await self.tick()
                await asyncio.sleep(self.tick_interval)
        except asyncio.CancelledError:
            logger.info("Daemon cancelled")
        finally:
            self.running = False
            logger.info("Daemon stopped")

    def stop(self):
        """Signal the daemon to stop."""
        self.running = False
        logger.info("Daemon stop requested")

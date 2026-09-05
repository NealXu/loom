"""Click CLI for Loom instance management.

Entry point: ``main`` (matches pyproject ``loom = "loom.cli:main"``).

Commands
--------
run     Instantiate a template and execute the DAG.
list    List all instances in the store.
status  Show detail for a single instance.

Gate handling (v1)
------------------
Nodes with ``gate=approve`` (e.g. the *commit* node in handoff-refresh) are
auto-approved: the CLI treats them like ordinary nodes and runs them without
waiting for human confirmation.  Full gate-flow (pause / waiting_gate) is
deferred to Task 22.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

import click

from loom.adapters.cc import CCAdapter
from loom.adapters.fake import FakeRunner
from loom.adapters.pi import PIAdapter
from loom.core.loader import instantiate, load_template
from loom.core.scheduler import ready_nodes
from loom.core.state import record_transition
from loom.core.store import Store

_RUNNERS = {
    "fake": FakeRunner,
    "cc": CCAdapter,
    "pi": PIAdapter,
}


# ---------------------------------------------------------------------------
# Async orchestration helper
# ---------------------------------------------------------------------------

async def _run_instance(store, instance, nodes, edges, runner) -> None:
    """Execute the DAG for *instance* using *runner*.

    Drives the instance through pending -> running -> succeeded/failed and
    each node through pending -> running -> succeeded/failed.  Edge dicts
    are derived from the stored Edge objects on the fly.
    """
    # Build edge dicts the scheduler understands.
    edge_dicts = [{"from_node": e.from_node, "to_node": e.to_node} for e in edges]
    node_map = {n.id: n for n in nodes}

    # pending -> running (instance)
    record_transition(store, "instance", instance.id, "pending", "running")
    store.conn.execute(
        "UPDATE instances SET status = 'running', started_at = ? WHERE id = ?",
        (datetime.now().isoformat(), instance.id),
    )
    store.conn.commit()

    completed: set[str] = set()
    all_node_ids = [n.id for n in nodes]
    failed = False

    while True:
        ready = ready_nodes(all_node_ids, edge_dicts, completed)
        if not ready:
            break
        for nid in ready:
            node_obj = node_map[nid]
            # pending -> running (node)
            record_transition(store, "node", nid, "pending", "running")
            store.conn.execute(
                "UPDATE nodes SET status = 'running', started_at = ? WHERE id = ?",
                (datetime.now().isoformat(), nid),
            )
            store.conn.commit()

            result = await runner.run(node_obj)

            if result.success:
                # running -> succeeded (node)
                record_transition(store, "node", nid, "running", "succeeded")
                store.conn.execute(
                    "UPDATE nodes SET status = 'succeeded', finished_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), nid),
                )
                store.conn.commit()
                completed.add(nid)
            else:
                # running -> failed (node)
                record_transition(store, "node", nid, "running", "failed")
                store.conn.execute(
                    "UPDATE nodes SET status = 'failed', finished_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), nid),
                )
                store.conn.commit()
                failed = True
                break  # fail-fast: stop scheduling; dependents will never become ready.
        if failed:
            break

    # Finalise instance status.
    final_status = "failed" if failed else "succeeded"
    record_transition(store, "instance", instance.id, "running", final_status)
    store.conn.execute(
        "UPDATE instances SET status = ?, finished_at = ? WHERE id = ?",
        (final_status, datetime.now().isoformat(), instance.id),
    )
    store.conn.commit()


# ---------------------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------------------

@click.group()
def main():
    """Loom CLI -- instance management."""


@main.command()
@click.argument("template")
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
@click.option(
    "--params",
    default="{}",
    help="JSON params, e.g. {'project_path': '/x'}",
)
@click.option(
    "--runner",
    "runner_name",
    default="fake",
    help="Runner adapter: fake|cc|pi",
)
def run(template: str, db: str, params: str, runner_name: str) -> None:
    """Instantiate TEMPLATE and execute the DAG."""
    tpl = load_template(template)
    params_dict = json.loads(params)
    instance, nodes, edges = instantiate(tpl, params_dict)

    runner_cls = _RUNNERS.get(runner_name)
    if runner_cls is None:
        raise click.BadParameter(f"Unknown runner: {runner_name}", param_hint="--runner")
    runner_inst = runner_cls()

    with Store(db) as store:
        store.create_instance(instance)
        for n in nodes:
            store.create_node(n)

        asyncio.run(_run_instance(store, instance, nodes, edges, runner_inst))

        # Refresh from DB for summary.
        inst = store.get_instance(instance.id)
        node_count = store.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE instance_id = ?", (instance.id,)
        ).fetchone()[0]

    click.echo(f"Instance {inst.id} | status={inst.status} | nodes={node_count}")


@main.command(name="list")
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def list_cmd(db: str) -> None:
    """List all instances."""
    with Store(db) as store:
        rows = store.conn.execute(
            "SELECT id, template_id, title, status, cost_usd FROM instances"
        ).fetchall()

    if not rows:
        click.echo("No instances found.")
        return

    for row in rows:
        click.echo(
            f"{row['id']}  template={row['template_id']}  "
            f"title={row['title']}  status={row['status']}  "
            f"cost_usd={row['cost_usd']}"
        )


@main.command()
@click.argument("instance_id", required=False)
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def cost(instance_id: str | None, db: str) -> None:
    """Display cost breakdown.

    If INSTANCE_ID is given, show cost for that instance only.
    Otherwise, show aggregate costs across all instances.
    """
    with Store(db) as store:
        if instance_id is not None:
            inst = store.get_instance(instance_id)
            if inst is None:
                raise click.UsageError(f"Instance not found: {instance_id}")
            click.echo(f"Instance {inst.id}")
            click.echo(f"  cost_tokens: {inst.cost_tokens}")
            click.echo(f"  cost_usd:    ${inst.cost_usd:.6f}")
        else:
            row = store.conn.execute(
                "SELECT COUNT(*) AS cnt, "
                "COALESCE(SUM(cost_tokens), 0) AS total_tokens, "
                "COALESCE(SUM(cost_usd), 0.0) AS total_usd "
                "FROM instances"
            ).fetchone()
            click.echo("Aggregate costs")
            click.echo(f"  instances:    {row['cnt']}")
            click.echo(f"  total_tokens: {row['total_tokens']}")
            click.echo(f"  total_usd:    ${row['total_usd']:.6f}")


@main.command()
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def stats(db: str) -> None:
    """Display system-wide statistics."""
    with Store(db) as store:
        # Instance counts by status.
        inst_rows = store.conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM instances GROUP BY status"
        ).fetchall()
        inst_by_status = {r["status"]: r["cnt"] for r in inst_rows}
        total_instances = sum(inst_by_status.values())

        # Node counts by status.
        node_rows = store.conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM nodes GROUP BY status"
        ).fetchall()
        node_by_status = {r["status"]: r["cnt"] for r in node_rows}
        total_nodes = sum(node_by_status.values())

        # Total events.
        event_count = store.conn.execute(
            "SELECT COUNT(*) AS cnt FROM events"
        ).fetchone()["cnt"]

        # Total gate decisions.
        gate_count = store.conn.execute(
            "SELECT COUNT(*) AS cnt FROM gate_decisions"
        ).fetchone()["cnt"]

    click.echo("System statistics")
    click.echo(f"  Instances ({total_instances}):")
    for status in ("pending", "running", "succeeded", "failed"):
        if status in inst_by_status:
            click.echo(f"    {status}: {inst_by_status[status]}")

    click.echo(f"  Nodes ({total_nodes}):")
    for status in ("pending", "running", "succeeded", "failed"):
        if status in node_by_status:
            click.echo(f"    {status}: {node_by_status[status]}")

    click.echo(f"  Events:         {event_count}")
    click.echo(f"  Gate decisions: {gate_count}")


@main.command()
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def health(db: str) -> None:
    """Display system health summary."""
    with Store(db) as store:
        # Recent instances (last 10 by created_at).
        recent = store.conn.execute(
            "SELECT status FROM instances ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        recent_count = len(recent)
        recent_succeeded = sum(1 for r in recent if r["status"] == "succeeded")
        recent_failed = sum(1 for r in recent if r["status"] == "failed")
        if recent_succeeded > 0:
            success_rate = recent_succeeded / recent_count * 100
        else:
            success_rate = 0.0

        # Average cost per succeeded instance.
        cost_row = store.conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(cost_usd), 0.0) AS total "
            "FROM instances WHERE status = 'succeeded'"
        ).fetchone()
        if cost_row["cnt"] > 0:
            avg_cost = cost_row["total"] / cost_row["cnt"]
        else:
            avg_cost = 0.0

        # Pending gate approvals (approved IS NULL means undecided).
        pending_gates = store.conn.execute(
            "SELECT COUNT(*) AS cnt FROM gate_decisions WHERE approved IS NULL OR approved = 0"
        ).fetchone()["cnt"]

        # Last event timestamp.
        last_event = store.conn.execute(
            "SELECT received_at FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_event_ts = last_event["received_at"] if last_event else "n/a"

    click.echo("System health")
    if recent_count == 0:
        click.echo("  No instances recorded yet.")
    else:
        click.echo(
            f"  Recent instances (last {recent_count}): "
            f"{recent_succeeded} succeeded, {recent_failed} failed "
            f"({success_rate:.1f}% success rate)"
        )
    click.echo(f"  Avg cost per succeeded instance: ${avg_cost:.6f}")
    click.echo(f"  Pending gate approvals:          {pending_gates}")
    click.echo(f"  Last event:                      {last_event_ts}")


@main.command()
@click.argument("instance_id")
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def status(instance_id: str, db: str) -> None:
    """Show detail for INSTANCE_ID."""
    with Store(db) as store:
        inst = store.get_instance(instance_id)
        if inst is None:
            raise click.UsageError(f"Instance not found: {instance_id}")

        node_rows = store.conn.execute(
            "SELECT id, title, kind, status FROM nodes WHERE instance_id = ?",
            (instance_id,),
        ).fetchall()

    click.echo(f"Instance {inst.id} | status={inst.status} | cost_usd={inst.cost_usd}")
    for nr in node_rows:
        click.echo(f"  Node {nr['id']} | {nr['title']} | kind={nr['kind']} | status={nr['status']}")

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

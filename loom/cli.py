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
from loom.adapters.codex import CodexAdapter
from loom.adapters.dsh import DshAdapter
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
    "codex": CodexAdapter,
    "dsh": DshAdapter,
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
@click.option(
    "--bg",
    is_flag=True,
    default=False,
    help="Background mode: create instance and let daemon execute.",
)
def run(template: str, db: str, params: str, runner_name: str, bg: bool) -> None:
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
        for e in edges:
            store.conn.execute(
                "INSERT INTO edges (instance_id, from_node, to_node, type, condition) VALUES (?, ?, ?, ?, ?)",
                (e.instance_id, e.from_node, e.to_node, e.type, e.condition or "")
            )
        store.conn.commit()

        if bg:
            # Background mode: just create instance, daemon will pick it up
            click.echo(f"Instance {instance.id} created (pending). Daemon will execute.")
            return

        # Synchronous mode: execute with gate support
        from loom.core.engine import step_instance
        asyncio.run(_run_with_gates(store, instance, runner_inst))

        # Refresh from DB for summary.
        inst = store.get_instance(instance.id)
        node_count = store.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE instance_id = ?", (instance.id,)
        ).fetchone()[0]

    click.echo(f"Instance {inst.id} | status={inst.status} | nodes={node_count}")


async def _run_with_gates(store, instance, runner) -> None:
    """Execute instance with gate support (sync mode)."""
    from loom.core.engine import step_instance

    while True:
        status = await step_instance(store, instance.id, runner)

        if status == "waiting_gate":
            # Paused at gate — inform user and exit
            click.echo(f"Instance {instance.id} paused at gate. Use 'loom gate list' to see pending gates.")
            click.echo("After approval, run 'loom serve' to resume, or use 'loom run' again.")
            return

        if status in ("succeeded", "failed", "cancelled"):
            # Done
            return

        # Still running, continue


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
@click.argument("entity_id", required=False)
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def cost(entity_id: str | None, db: str) -> None:
    """Display cost breakdown.

    With no arguments, show aggregate costs across all instances.
    If ENTITY_ID matches an instance, show cost for that instance.
    Otherwise, treat ENTITY_ID as a template_id and show costs for all
    instances of that template.
    """
    with Store(db) as store:
        if entity_id is not None:
            # Try as instance first.
            inst = store.get_instance(entity_id)
            if inst is not None:
                click.echo(f"Instance {inst.id}")
                click.echo(f"  cost_tokens: {inst.cost_tokens}")
                click.echo(f"  cost_usd:    ${inst.cost_usd:.6f}")
                return

            # Try as template_id.
            row = store.conn.execute(
                "SELECT COUNT(*) AS cnt, "
                "COALESCE(SUM(cost_tokens), 0) AS total_tokens, "
                "COALESCE(SUM(cost_usd), 0.0) AS total_usd "
                "FROM instances WHERE template_id = ?",
                (entity_id,),
            ).fetchone()
            if row["cnt"] == 0:
                raise click.UsageError(
                    f"No instance or template found: {entity_id}"
                )
            avg_usd = row["total_usd"] / row["cnt"] if row["cnt"] else 0.0
            click.echo(f"Template {entity_id}")
            click.echo(f"  instances:     {row['cnt']}")
            click.echo(f"  total_tokens:  {row['total_tokens']}")
            click.echo(f"  total_usd:     ${row['total_usd']:.6f}")
            click.echo(f"  avg_usd:       ${avg_usd:.6f}")
        else:
            row = store.conn.execute(
                "SELECT COUNT(*) AS cnt, "
                "COALESCE(SUM(cost_tokens), 0) AS total_tokens, "
                "COALESCE(SUM(cost_usd), 0.0) AS total_usd "
                "FROM instances"
            ).fetchone()
            avg_usd = row["total_usd"] / row["cnt"] if row["cnt"] else 0.0
            click.echo("Aggregate costs")
            click.echo(f"  instances:    {row['cnt']}")
            click.echo(f"  total_tokens: {row['total_tokens']}")
            click.echo(f"  total_usd:    ${row['total_usd']:.6f}")
            click.echo(f"  avg_usd:      ${avg_usd:.6f}")


@main.command()
@click.option("--template", "template_id", default=None, help="Filter by template_id.")
@click.option("--status", "status_filter", default=None, help="Filter by status.")
@click.option("--limit", default=20, type=int, help="Max rows to show (default 20).")
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def history(template_id: str | None, status_filter: str | None, limit: int, db: str) -> None:
    """Show instance execution history.

    Displays recent instances, most recent first.  Use --template or --status
    to filter.
    """
    query = "SELECT id, template_id, status, cost_usd, created_at, finished_at FROM instances"
    clauses: list[str] = []
    params: list[object] = []

    if template_id is not None:
        clauses.append("template_id = ?")
        params.append(template_id)
    if status_filter is not None:
        clauses.append("status = ?")
        params.append(status_filter)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with Store(db) as store:
        rows = store.conn.execute(query, params).fetchall()

    if not rows:
        click.echo("No instances found.")
        return

    for row in rows:
        finished = row["finished_at"] or "-"
        click.echo(
            f"{row['id']}  template={row['template_id']}  "
            f"status={row['status']}  cost_usd=${row['cost_usd']:.6f}  "
            f"created={row['created_at']}  finished={finished}"
        )


@main.command()
@click.argument("instance_id", required=False)
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def audit(instance_id: str | None, db: str) -> None:
    """Show audit trail (gate decisions and state transitions).

    With no arguments, show all gate decisions (most recent first).
    If INSTANCE_ID is given, show gate decisions and state transitions
    for that specific instance.
    """
    with Store(db) as store:
        if instance_id is not None:
            # Verify instance exists.
            inst = store.get_instance(instance_id)
            if inst is None:
                raise click.UsageError(f"Instance not found: {instance_id}")

            # Gate decisions for this instance.
            gates = store.conn.execute(
                "SELECT node_id, approved, approver, reason, decided_at "
                "FROM gate_decisions WHERE instance_id = ? "
                "ORDER BY decided_at DESC",
                (instance_id,),
            ).fetchall()

            # State transitions for this instance.
            transitions = store.conn.execute(
                "SELECT id, payload, received_at FROM events "
                "WHERE source = 'state_transition' "
                "AND consumed_by_instance = ? "
                "ORDER BY received_at DESC",
                (instance_id,),
            ).fetchall()

            if not gates and not transitions:
                click.echo(f"No audit events for instance {instance_id}.")
                return

            click.echo(f"Audit trail for instance {instance_id}")
            click.echo("")

            if gates:
                click.echo("Gate decisions:")
                for g in gates:
                    approved_str = (
                        "approved" if g["approved"] else
                        "denied" if g["approved"] is not None else "pending"
                    )
                    click.echo(
                        f"  {g['decided_at']}  gate_decision  "
                        f"node={g['node_id']}  {approved_str}  "
                        f"by={g['approver'] or '-'}  reason={g['reason'] or '-'}"
                    )

            if transitions:
                click.echo("State transitions:")
                import json as _json
                for t in transitions:
                    payload = _json.loads(t["payload"]) if t["payload"] else {}
                    click.echo(
                        f"  {t['received_at']}  state_transition  "
                        f"{payload.get('entity_kind', '?')}={payload.get('entity_id', '?')}  "
                        f"{payload.get('from_status', '?')}->{payload.get('to_status', '?')}"
                    )
        else:
            # All gate decisions, most recent first.
            gates = store.conn.execute(
                "SELECT node_id, instance_id, approved, approver, reason, decided_at "
                "FROM gate_decisions ORDER BY decided_at DESC"
            ).fetchall()

            if not gates:
                click.echo("No gate decisions recorded.")
                return

            click.echo("Gate decisions (most recent first)")
            for g in gates:
                approved_str = (
                    "approved" if g["approved"] else
                    "denied" if g["approved"] is not None else "pending"
                )
                click.echo(
                    f"  {g['decided_at']}  gate_decision  "
                    f"instance={g['instance_id']}  node={g['node_id']}  "
                    f"{approved_str}  by={g['approver'] or '-'}  "
                    f"reason={g['reason'] or '-'}"
                )


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


# ---------------------------------------------------------------------------
# P0-B: Gate commands
# ---------------------------------------------------------------------------

@main.group()
def gate():
    """Gate approval commands."""
    pass


@gate.command(name="list")
@click.option("--instance", "instance_id", default=None, help="Filter by instance ID.")
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def gate_list(instance_id: str | None, db: str) -> None:
    """List pending gate approvals."""
    from loom.core.gate import get_pending_gates

    with Store(db) as store:
        gates = get_pending_gates(store, instance_id)

    if not gates:
        click.echo("No pending gates.")
        return

    click.echo(f"Pending gates ({len(gates)}):")
    for g in gates:
        click.echo(f"  {g['id']}  instance={g['instance_id']}  title={g['title']}  kind={g['kind']}")


@gate.command()
@click.argument("node_id")
@click.option("--reason", default="", help="Approval reason.")
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def approve(node_id: str, reason: str, db: str) -> None:
    """Approve a gated node."""
    from loom.core.gate import GateDecision, record_gate_decision

    with Store(db) as store:
        node = store.get_node(node_id)
        if node is None:
            raise click.UsageError(f"Node not found: {node_id}")

        decision = GateDecision(
            node_id=node_id,
            instance_id=node.instance_id,
            approved=True,
            reason=reason,
        )
        ok = record_gate_decision(store, decision)

    if ok:
        click.echo(f"Node {node_id} approved.")
    else:
        click.echo(f"Failed to approve node {node_id} (invalid transition).")


@gate.command()
@click.argument("node_id")
@click.option("--reason", required=True, help="Rejection reason.")
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
def reject(node_id: str, reason: str, db: str) -> None:
    """Reject a gated node."""
    from loom.core.gate import GateDecision, record_gate_decision

    with Store(db) as store:
        node = store.get_node(node_id)
        if node is None:
            raise click.UsageError(f"Node not found: {node_id}")

        decision = GateDecision(
            node_id=node_id,
            instance_id=node.instance_id,
            approved=False,
            reason=reason,
        )
        ok = record_gate_decision(store, decision)

    if ok:
        click.echo(f"Node {node_id} rejected.")
    else:
        click.echo(f"Failed to reject node {node_id} (invalid transition).")


# ---------------------------------------------------------------------------
# P0-A: Serve command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--db", default="loom.db", help="Path to the SQLite store.")
@click.option("--host", default="127.0.0.1", help="Host to bind.")
@click.option("--port", default=8000, type=int, help="Port to bind.")
@click.option("--runner", "runner_name", default="fake", help="Runner adapter: fake|cc|pi|codex|dsh")
@click.option("--tick", default=2.0, type=float, help="Daemon tick interval (seconds).")
def serve(db: str, host: str, port: int, runner_name: str, tick: float) -> None:
    """Start the Loom daemon and web server."""
    import uvicorn
    from loom.web.app import create_app
    from loom.daemon import LoomDaemon

    runner_cls = _RUNNERS.get(runner_name)
    if runner_cls is None:
        raise click.BadParameter(f"Unknown runner: {runner_name}", param_hint="--runner")

    store = Store(db)
    runner_inst = runner_cls()
    daemon = LoomDaemon(store, runner_inst, tick_interval=tick)

    # Create FastAPI app with store
    app = create_app(store)

    # Start daemon in background
    async def start_daemon():
        await daemon.run_forever()

    click.echo(f"Starting Loom server on {host}:{port} (tick={tick}s, runner={runner_name})")
    click.echo("Press Ctrl+C to stop.")

    try:
        # Run daemon and uvicorn together
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Start daemon task
        daemon_task = loop.create_task(start_daemon())

        # Start uvicorn
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)

        # Run both
        loop.run_until_complete(asyncio.gather(
            daemon_task,
            server.serve(),
        ))
    except KeyboardInterrupt:
        click.echo("\nShutting down...")
        daemon.stop()
    finally:
        store.close()

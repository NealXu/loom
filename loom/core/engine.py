"""Core orchestration engine for Loom (P0-A).

Extracted from cli.py:_run_instance to support both synchronous execution
and daemon-driven async execution. Key difference: completed set is computed
from DB (not in-memory) to support daemon restarts.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from loom.core.models import Artifact
from loom.core.scheduler import ready_nodes
from loom.core.state import record_transition


def _write_artifact(store, vault_dir: str, instance_id: str, node_id: str, result) -> None:
    """Write a node's output to the Vault and register it as an Artifact."""
    target_dir = Path(vault_dir) / instance_id
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{node_id}.md"
    body = result.output or ""
    path.write_text(f"# {node_id}\n\n{body}\n", encoding="utf-8")
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    store.create_artifact(Artifact(node_id=node_id, kind="md",
                                   path=str(path), sha256=sha, vault_link=path.name))
    node = store.get_node(node_id)
    if node is not None:
        paths = list(node.artifact_paths)
        if str(path) not in paths:
            paths.append(str(path))
            store.conn.execute("UPDATE nodes SET artifact_paths = ? WHERE id = ?",
                               (__import__("json").dumps(paths), node_id))
            store.conn.commit()


async def step_instance(store, instance_id: str, runner, vault_dir: str | None = None) -> str:
    """Execute one tick of instance orchestration.

    Loads instance state from DB, runs ready nodes, handles gates.
    Returns the instance's current status after the step.

    Gate handling: if a ready node has gate=approve, transition it to
    waiting_gate and pause the instance. The daemon (or CLI) will resume
    after external approval.

    When *vault_dir* is set, each successful node's output is written to
    ``<vault_dir>/<instance_id>/<node_id>.md`` and registered as an Artifact.
    """
    # Load instance
    instance = store.get_instance(instance_id)
    if instance is None:
        raise ValueError(f"Instance not found: {instance_id}")

    # If instance is in terminal state, return immediately
    if instance.status in ("succeeded", "failed", "cancelled"):
        return instance.status

    # Blocked instances stay blocked until manually resumed
    if instance.status == "blocked":
        return "blocked"

    # If instance is waiting_gate, check if any gates were approved → resume
    if instance.status == "waiting_gate":
        nodes = store.list_nodes(instance_id)
        # Check if any waiting_gate nodes were approved (now in running state)
        running_nodes = [n for n in nodes if n.status == "running"]
        if running_nodes:
            # Resume instance
            record_transition(store, "instance", instance_id, "waiting_gate", "running")
            store.update_instance_status(instance_id, "running")
            instance = store.get_instance(instance_id)  # Refresh

    # Load nodes and edges
    nodes = store.list_nodes(instance_id)
    edges = store.list_edges(instance_id)

    if not nodes:
        # No nodes = instance is done (edge case)
        if instance.status == "pending":
            store.update_instance_status(instance_id, "running",
                                         started_at=datetime.now().isoformat())
        store.update_instance_status(instance_id, "succeeded",
                                     finished_at=datetime.now().isoformat())
        return "succeeded"

    node_map = {n.id: n for n in nodes}
    all_node_ids = [n.id for n in nodes]
    edge_dicts = [{"from_node": e.from_node, "to_node": e.to_node} for e in edges]

    # Compute completed set from DB (supports restart)
    completed = {n.id for n in nodes if n.status == "succeeded"}

    # Transition instance to running if pending
    if instance.status == "pending":
        record_transition(store, "instance", instance_id, "pending", "running")
        store.update_instance_status(instance_id, "running",
                                     started_at=datetime.now().isoformat())
        instance = store.get_instance(instance_id)  # Refresh

    # Check for gated nodes that are ready → transition to waiting_gate
    ready = ready_nodes(all_node_ids, edge_dicts, completed)
    for nid in ready:
        node_obj = node_map[nid]
        if node_obj.gate == "approve" and node_obj.status == "pending":
            # Pause at gate
            record_transition(store, "node", nid, "pending", "waiting_gate")
            store.update_node_status(nid, "waiting_gate")
            # Also pause instance
            if instance.status == "running":
                record_transition(store, "instance", instance_id, "running", "waiting_gate")
                store.update_instance_status(instance_id, "waiting_gate")
            return "waiting_gate"

    # Re-compute ready nodes (excluding any that just transitioned to waiting_gate)
    ready = ready_nodes(all_node_ids, edge_dicts, completed)
    # Include nodes in "pending" (normal) or "running" (just approved from gate)
    ready = [nid for nid in ready if node_map[nid].status in ("pending", "running")]

    if not ready:
        # No ready nodes — check if we're done or just waiting
        waiting = any(n.status == "waiting_gate" for n in nodes)
        if waiting:
            return "waiting_gate"
        # All done or failed
        failed = any(n.status == "failed" for n in nodes)
        if failed:
            if instance.status == "running":
                record_transition(store, "instance", instance_id, "running", "failed")
                store.update_instance_status(instance_id, "failed",
                                             finished_at=datetime.now().isoformat())
            return "failed"
        # Should not reach here if DAG is well-formed
        return instance.status

    # Execute ready nodes (serial for now)
    for nid in ready:
        node_obj = node_map[nid]

        # Budget hard ceiling: block the instance if accumulated cost has
        # already reached this node's token budget (do not spend more).
        if node_obj.budget_tokens and instance.cost_tokens >= node_obj.budget_tokens:
            reason = (f"budget exceeded: cost_tokens={instance.cost_tokens} "
                      f">= node {nid} budget {node_obj.budget_tokens}")
            if instance.status == "running":
                record_transition(store, "instance", instance_id, "running", "blocked")
                store.update_instance_status(instance_id, "blocked", blocked_reason=reason)
            return "blocked"

        # Only transition if still pending (may already be running from gate approval)
        if node_obj.status == "pending":
            record_transition(store, "node", nid, "pending", "running")
            store.update_node_status(nid, "running", started_at=datetime.now().isoformat())

        result = await runner.run(node_obj)

        # Accumulate cost regardless of outcome (cost was already spent).
        store.add_instance_cost(instance_id, result.cost_tokens, result.cost_usd)
        instance = store.get_instance(instance_id)  # refresh for next budget check

        if result.success:
            # running -> succeeded
            record_transition(store, "node", nid, "running", "succeeded")
            store.update_node_status(nid, "succeeded", finished_at=datetime.now().isoformat())
            completed.add(nid)
            # P4-E: persist output to Vault + register artifact (best-effort).
            if vault_dir:
                try:
                    _write_artifact(store, vault_dir, instance_id, nid, result)
                except Exception:
                    pass  # artifact write must never fail a node
        else:
            # running -> failed
            record_transition(store, "node", nid, "running", "failed")
            store.update_node_status(nid, "failed", finished_at=datetime.now().isoformat())
            # Fail instance immediately
            record_transition(store, "instance", instance_id, "running", "failed")
            store.update_instance_status(instance_id, "failed",
                                         finished_at=datetime.now().isoformat())
            return "failed"

    # Check if all nodes are done
    all_done = all(n.status in ("succeeded", "failed", "cancelled") for n in store.list_nodes(instance_id))
    if all_done:
        failed = any(n.status == "failed" for n in store.list_nodes(instance_id))
        final_status = "failed" if failed else "succeeded"
        if instance.status == "running":
            record_transition(store, "instance", instance_id, "running", final_status)
            store.update_instance_status(instance_id, final_status,
                                         finished_at=datetime.now().isoformat())
        return final_status

    # Instance still running
    return "running"

"""Evolution channel: weekly template discovery.

Analyzes completed instances to discover recurring patterns that could be
extracted as new templates. v1 uses simple template_id clustering; real LLM
clustering and summarization are deferred (out of scope for the kernel milestone).
"""

from collections import Counter

from loom.core.models import Instance
from loom.core.store import Store


def discover_template_candidates(store: Store, min_frequency: int = 3) -> list[dict]:
    """Return completed-instance templates whose frequency >= min_frequency.

    Each result: {"template_id": str, "frequency": int, "instance_ids": list[str]},
    sorted by frequency descending.
    """
    rows = store.conn.execute(
        "SELECT id, template_id FROM instances WHERE status = 'succeeded' "
        "ORDER BY template_id, id"
    ).fetchall()

    by_template: dict[str, list[str]] = {}
    for row in rows:
        by_template.setdefault(row["template_id"], []).append(row["id"])

    candidates = [
        {"template_id": tid, "frequency": len(ids), "instance_ids": ids}
        for tid, ids in by_template.items()
        if len(ids) >= min_frequency
    ]
    candidates.sort(key=lambda c: -c["frequency"])
    return candidates


def cluster_instances(instances: list[Instance], embeddings: list[dict]) -> list[list[str]]:
    """Cluster instances into groups of ids.

    v1: simple clustering by template_id (embeddings are ignored — a placeholder
    for future LLM-based similarity clustering). Returns a list of clusters, each
    cluster a list of instance ids sharing a template.
    """
    by_template: dict[str, list[str]] = {}
    for inst in instances:
        by_template.setdefault(inst.template_id, []).append(inst.id)
    return [sorted(ids) for ids in by_template.values()]


def propose_template_from_cluster(instance_ids: list[str], store: Store) -> dict:
    """Propose a new template from a cluster of instance ids.

    v1: deterministic concatenation of node titles/specs from the cluster's
    first instance, plus the observed trigger. Real LLM summarization deferred.
    Returns a proposal dict: {"id", "trigger", "nodes"}.
    """
    if not instance_ids:
        raise ValueError("cannot propose a template from an empty cluster")

    first_id = instance_ids[0]
    row = store.conn.execute(
        "SELECT template_id FROM instances WHERE id = ?", (first_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown instance: {first_id}")
    template_id = row["template_id"]

    node_rows = store.conn.execute(
        "SELECT title, kind, spec, tier FROM nodes WHERE instance_id = ? ORDER BY created_at, id",
        (first_id,),
    ).fetchall()

    nodes = [
        {
            "id": (n["title"] or f"step{i}") + "-proposed",
            "kind": n["kind"] or "analysis",
            "tier": n["tier"] or "tooling",
            "spec": n["spec"] or "",
            "depends_on": [],
        }
        for i, n in enumerate(node_rows)
    ]

    return {
        "id": f"discovered-{template_id}",
        "trigger": ["cli"],
        "nodes": nodes,
    }

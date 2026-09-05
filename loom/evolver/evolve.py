"""Evolution channel: weekly template discovery.

Analyzes completed instances to discover recurring patterns and turn them into
candidate templates. :func:`evolve` (P4-D) closes the loop: for each cluster it
builds an evidence prompt, runs it through a runner (e.g. Claude Code) to get a
YAML template proposal, and writes a loadable ``provenance: discovered`` file.
If the LLM output is unusable it falls back to the deterministic
:func:`propose_template_from_cluster`, so the sweep never yields broken files.
"""

from __future__ import annotations

import os
import re
from collections import Counter

import yaml

from loom.core.models import Instance, Node
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


# ---------------------------------------------------------------------------
# P4-D: LLM-driven discovery loop
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:yaml|yml)?\s*(.+?)```", re.DOTALL)


def _cluster_evidence(store: Store, instance_ids: list[str]) -> str:
    """Render a cluster's node kinds/specs as prompt evidence."""
    lines: list[str] = []
    for iid in instance_ids[:5]:
        for n in store.list_nodes(iid):
            lines.append(f"- [{n.kind}/{n.tier}] {n.spec}")
    return "\n".join(lines)


def _extract_yaml(text: str) -> dict | None:
    """Pull a YAML mapping out of LLM output (raw, fenced, or embedded)."""
    candidates = [text]
    candidates += _FENCE_RE.findall(text)
    # Fallback: substring from first top-level 'id:' / 'version:' line.
    m = re.search(r"(?m)^(id|version):", text)
    if m:
        candidates.append(text[m.start():])
    for cand in candidates:
        try:
            obj = yaml.safe_load(cand)
        except yaml.YAMLError:
            continue
        if isinstance(obj, dict) and "nodes" in obj:
            return obj
    return None


def _normalize(proposal: dict) -> dict:
    """Coerce a proposal mapping into the shape load_template requires."""
    proposal = dict(proposal)
    proposal["version"] = proposal.get("version", 1)
    proposal["trigger"] = proposal.get("trigger") or ["cli"]
    proposal["params"] = proposal.get("params") or {}
    proposal["provenance"] = "discovered"  # always mark as machine-found
    seen: set[str] = set()
    nodes = []
    for i, n in enumerate(proposal.get("nodes") or []):
        n = dict(n)
        n["id"] = str(n.get("id") or f"step{i}")
        if n["id"] in seen:
            n["id"] = f"{n['id']}-{i}"
        seen.add(n["id"])
        n["kind"] = n.get("kind") or "analysis"
        n["spec"] = n.get("spec") or ""
        # only keep deps that survived dedup
        n["depends_on"] = [d for d in (n.get("depends_on") or []) if d in seen and d != n["id"]]
        n["tier"] = n.get("tier") or "tooling"
        nodes.append(n)
    proposal["nodes"] = nodes
    if not nodes:
        raise ValueError("no valid nodes")
    return proposal


def _proposal_prompt(template_id: str, evidence: str) -> str:
    return (
        "You are a workflow template distiller. From these recurring successful "
        f"runs of '{template_id}', propose a reusable SOP as a YAML template with "
        "keys: id, version, trigger, params, nodes (each node: id, kind, tier, "
        "spec, depends_on). Return ONLY the YAML, no prose.\n\n"
        f"Evidence:\n{evidence}"
    )


async def evolve(store: Store, runner, out_dir: str,
                 min_frequency: int = 3) -> list[str]:
    """Discover candidate templates and write loadable YAML files.

    Returns the list of written file paths (one per qualifying cluster).
    LLM output is validated; clusters whose LLM proposal is unusable fall
    back to a deterministic proposal so a file is still produced.
    """
    from loom.core.loader import load_template
    from loom.core.models import Node as _Node  # ensure import stays used

    os.makedirs(out_dir, exist_ok=True)
    written: list[str] = []

    for cand in discover_template_candidates(store, min_frequency=min_frequency):
        tid = cand["template_id"]
        evidence = _cluster_evidence(store, cand["instance_ids"])
        proposal = None
        try:
            probe = _Node(id=f"evolve-{tid}", instance_id="-", template_id=tid,
                          spec=_proposal_prompt(tid, evidence), kind="analysis")
            result = await runner.run(probe)
            if result.success:
                raw = _extract_yaml(result.output)
                if raw is not None:
                    proposal = _normalize(raw)
        except Exception:
            proposal = None

        if proposal is None:  # deterministic fallback
            try:
                proposal = _normalize(
                    propose_template_from_cluster(cand["instance_ids"], store))
            except Exception:
                continue

        path = os.path.join(out_dir, f"{proposal['id']}.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(proposal, f, allow_unicode=True, sort_keys=False)
        try:
            load_template(path)  # must be loadable to count as a candidate
        except Exception:
            os.remove(path)
            continue
        written.append(path)

    return written

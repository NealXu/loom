"""Template loader and instantiator for Loom.

Parses a YAML template into a Template dataclass, then instantiates it
with concrete params into an Instance + list of Nodes + list of Edges.
"""

import re
import uuid

import yaml

from loom.core.models import Template, Instance, Node, Edge

VALID_TIERS = {"critical", "heavy", "tooling", "bulk"}
VALID_GATES = {"none", "approve"}
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def load_template(path: str) -> Template:
    """Load a YAML template file and return a validated Template."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError("Template file must contain a YAML mapping")

    # --- required top-level keys ---
    for key in ("id", "version", "trigger", "params", "nodes", "provenance"):
        if key not in data:
            raise ValueError(f"Template missing required key: {key}")

    nodes = data["nodes"]
    if not isinstance(nodes, list) or len(nodes) == 0:
        raise ValueError("Template 'nodes' must be a non-empty list")

    # --- per-node validation ---
    seen_ids: set[str] = set()
    for node in nodes:
        for nk in ("id", "kind", "spec", "depends_on"):
            if nk not in node:
                raise ValueError(f"Node missing required key: {nk}")

        nid = node["id"]
        if nid in seen_ids:
            raise ValueError(f"Duplicate node id (not unique): {nid}")
        seen_ids.add(nid)

        tier = node.get("tier", "tooling")
        if tier not in VALID_TIERS:
            raise ValueError(
                f"Invalid tier '{tier}' on node '{nid}'. Must be one of {VALID_TIERS}"
            )

        gate = node.get("gate", "none")
        if gate not in VALID_GATES:
            raise ValueError(
                f"Invalid gate '{gate}' on node '{nid}'. Must be one of {VALID_GATES}"
            )

    # depends_on references must exist
    all_node_ids = {n["id"] for n in nodes}
    for node in nodes:
        for dep in node["depends_on"]:
            if dep not in all_node_ids:
                raise ValueError(
                    f"Node '{node['id']}' depends_on '{dep}' which does not exist"
                )

    return Template(
        id=data["id"],
        version=data["version"],
        trigger=data["trigger"],
        params=data["params"],
        nodes=nodes,
        provenance=data["provenance"],
    )


def _render_spec(spec: str, params: dict) -> str:
    """Replace {{param}} placeholders with values from params; skip unknowns."""

    def _replace(m: re.Match) -> str:
        key = m.group(1)
        if key in params:
            return str(params[key])
        return m.group(0)  # leave unknown placeholders as-is

    return _PLACEHOLDER_RE.sub(_replace, spec)


def instantiate(
    template: Template, params: dict
) -> tuple[Instance, list[Node], list[Edge]]:
    """Instantiate a template with concrete params.

    Returns (instance, nodes, edges) — all in-memory, not persisted.
    """
    instance_id = uuid.uuid4().hex[:12]
    project_path = params.get("project_path", "")

    instance = Instance(
        id=instance_id,
        template_id=template.id,
        owner="me",
        title=f"{template.id} instance",
        project_path=project_path,
        status="pending",
        params=params,
    )

    # template node id -> generated Node.id
    id_map: dict[str, str] = {}
    nodes: list[Node] = []
    edges: list[Edge] = []

    for tnode in template.nodes:
        node_id = uuid.uuid4().hex[:12]
        id_map[tnode["id"]] = node_id

        rendered_spec = _render_spec(tnode["spec"], params)

        node = Node(
            id=node_id,
            instance_id=instance_id,
            template_id=template.id,
            owner="me",
            title=tnode.get("title", tnode["id"]),
            kind=tnode["kind"],
            spec=rendered_spec,
            tier=tnode.get("tier", "tooling"),
            gate=tnode.get("gate", "none"),
            status="pending",
            project_path=project_path,
            budget_tokens=tnode.get("budget_tokens", 50000),
        )
        nodes.append(node)

    # Build edges from depends_on relationships
    for tnode in template.nodes:
        to_node_id = id_map[tnode["id"]]
        for dep_id in tnode["depends_on"]:
            from_node_id = id_map[dep_id]
            edges.append(
                Edge(
                    instance_id=instance_id,
                    from_node=from_node_id,
                    to_node=to_node_id,
                    type="depends",
                )
            )

    return instance, nodes, edges

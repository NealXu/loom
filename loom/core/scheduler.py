"""DAG scheduler: topological ordering and ready-node selection.

The scheduler works at the id level (node ids + edge dicts) so it stays
independent of the Store and of any runner. The main loop repeatedly selects
ready nodes whose dependencies are all complete, runs them, and marks them done.

Edge representation (matches the models.Edge relationship): a minimal dict with
`from_node` and `to_node` keys is sufficient here.
"""

from typing import Iterable, Sequence


def _deps_and_dependents(node_ids: Iterable[str], edges: Sequence[dict]):
    """Return (deps, dependents) maps over the given nodes.

    deps[node] = set of node ids that must complete before `node`.
    dependents[node] = set of node ids that depend on `node`.
    """
    deps = {n: set() for n in node_ids}
    dependents = {n: set() for n in node_ids}
    for edge in edges:
        dep = edge["from_node"]
        node = edge["to_node"]
        if dep in deps and node in deps:
            deps[node].add(dep)
            dependents[dep].add(node)
    return deps, dependents


def topological_order(node_ids: Iterable[str], edges: Sequence[dict]) -> list[str]:
    """Return node ids in a valid execution order via Kahn's algorithm.

    Raises ValueError if the graph contains a cycle.
    """
    node_ids = list(node_ids)
    deps, dependents = _deps_and_dependents(node_ids, edges)

    # Seed: nodes with no unsatisfied dependencies.
    ready = [n for n in node_ids if not deps[n]]
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for dependent in sorted(dependents[node]):
            deps[dependent].discard(node)
            if not deps[dependent]:
                ready.append(dependent)

    if len(order) != len(node_ids):
        raise ValueError("graph contains a cycle; cannot topologically order")

    return order


def ready_nodes(node_ids: Iterable[str], edges: Sequence[dict],
                completed: set[str]) -> list[str]:
    """Return the undone nodes whose dependencies are all in `completed`.

    A node is ready when every dependency is complete and the node is not
    itself already complete.
    """
    node_ids = list(node_ids)
    deps, _ = _deps_and_dependents(node_ids, edges)
    ready = [
        n for n in node_ids
        if n not in completed and deps[n].issubset(completed)
    ]
    return sorted(ready)

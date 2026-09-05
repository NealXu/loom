import pytest
from loom.core.scheduler import topological_order, ready_nodes

def make_edge(from_node, to_node):
    return {"from_node": from_node, "to_node": to_node}


def test_topological_order_respects_dependencies():
    nodes = ["a", "b", "c", "d"]
    # a -> b -> c ; a -> d -> c  (c depends on b and d)
    edges = [make_edge("a", "b"), make_edge("b", "c"), make_edge("a", "d"), make_edge("d", "c")]
    order = topological_order(nodes, edges)
    assert order.index("a") < order.index("b")
    assert order.index("b") < order.index("c")
    assert order.index("d") < order.index("c")
    assert set(order) == set(nodes)


def test_topological_order_detects_cycle():
    nodes = ["a", "b", "c"]
    edges = [make_edge("a", "b"), make_edge("b", "c"), make_edge("c", "a")]
    with pytest.raises(ValueError):
        topological_order(nodes, edges)


def test_ready_nodes_returns_undone_nodes_with_all_deps_done():
    nodes = ["a", "b", "c"]
    edges = [make_edge("a", "c"), make_edge("b", "c")]
    # only a and b done -> c is ready, a/b already completed
    ready = ready_nodes(nodes, edges, completed={"a", "b"})
    assert ready == ["c"]


def test_ready_nodes_respects_incomplete_deps():
    nodes = ["a", "b", "c"]
    edges = [make_edge("a", "c"), make_edge("b", "c")]
    # only a done -> b has no deps so is ready; c is NOT ready (b not done)
    ready = ready_nodes(nodes, edges, completed={"a"})
    assert "b" in ready
    assert "c" not in ready

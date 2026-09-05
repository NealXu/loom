"""Tests for the evolution channel (loom/evolver/evolve.py)."""

import pytest
from datetime import datetime

from loom.core.models import Instance, Node
from loom.core.store import Store
from loom.evolver.evolve import (
    discover_template_candidates,
    cluster_instances,
    propose_template_from_cluster,
)


def _make_instance(id_: str, template_id: str, status: str = "succeeded") -> Instance:
    return Instance(
        id=id_,
        template_id=template_id,
        status=status,
        created_at=datetime.now(),
    )


def _make_node(
    id_: str,
    instance_id: str,
    title: str,
    spec: str,
    kind: str = "analysis",
    tier: str = "tooling",
) -> Node:
    return Node(
        id=id_,
        instance_id=instance_id,
        template_id="test-template",
        title=title,
        spec=spec,
        kind=kind,
        tier=tier,
        gate="none",
        status="succeeded",
        budget_tokens=50000,
        created_at=datetime.now(),
    )


def test_discover_template_candidates_finds_high_frequency(tmp_path):
    """Templates with frequency >= min_frequency are returned, sorted descending."""
    db_path = tmp_path / "test.db"
    store = Store(str(db_path))

    # 3 instances of "handoff", 2 of "review", 1 of "deploy"
    store.create_instance(_make_instance("i1", "handoff"))
    store.create_instance(_make_instance("i2", "handoff"))
    store.create_instance(_make_instance("i3", "handoff"))
    store.create_instance(_make_instance("i4", "review"))
    store.create_instance(_make_instance("i5", "review"))
    store.create_instance(_make_instance("i6", "deploy"))

    candidates = discover_template_candidates(store, min_frequency=2)

    assert len(candidates) == 2
    assert candidates[0]["template_id"] == "handoff"
    assert candidates[0]["frequency"] == 3
    assert set(candidates[0]["instance_ids"]) == {"i1", "i2", "i3"}
    assert candidates[1]["template_id"] == "review"
    assert candidates[1]["frequency"] == 2

    store.close()


def test_discover_template_candidates_filters_by_min_frequency(tmp_path):
    """Only templates meeting min_frequency threshold are returned."""
    db_path = tmp_path / "test.db"
    store = Store(str(db_path))

    store.create_instance(_make_instance("i1", "handoff"))
    store.create_instance(_make_instance("i2", "handoff"))

    # min_frequency=3: nothing qualifies
    candidates = discover_template_candidates(store, min_frequency=3)
    assert candidates == []

    # min_frequency=2: handoff qualifies
    candidates = discover_template_candidates(store, min_frequency=2)
    assert len(candidates) == 1
    assert candidates[0]["template_id"] == "handoff"

    store.close()


def test_cluster_instances_groups_by_template_id(tmp_path):
    """cluster_instances groups instance IDs by template_id."""
    db_path = tmp_path / "test.db"
    store = Store(str(db_path))

    instances = [
        _make_instance("i1", "handoff"),
        _make_instance("i2", "review"),
        _make_instance("i3", "handoff"),
    ]

    # embeddings are ignored in v1
    embeddings = [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}]

    clusters = cluster_instances(instances, embeddings)

    # Should have 2 clusters: handoff (i1, i3) and review (i2)
    assert len(clusters) == 2
    cluster_sets = [set(c) for c in clusters]
    assert {"i1", "i3"} in cluster_sets
    assert {"i2"} in cluster_sets

    store.close()


def test_propose_template_from_cluster_builds_proposal(tmp_path):
    """propose_template_from_cluster generates a template proposal from instance nodes."""
    db_path = tmp_path / "test.db"
    store = Store(str(db_path))

    store.create_instance(_make_instance("i1", "handoff"))
    store.create_node(
        _make_node("n1", "i1", "analyze-code", "Analyze the codebase")
    )
    store.create_node(_make_node("n2", "i1", "run-tests", "Run the test suite"))

    proposal = propose_template_from_cluster(["i1"], store)

    assert proposal["id"] == "discovered-handoff"
    assert proposal["trigger"] == ["cli"]
    assert len(proposal["nodes"]) == 2
    assert proposal["nodes"][0]["id"] == "analyze-code-proposed"
    assert proposal["nodes"][0]["spec"] == "Analyze the codebase"
    assert proposal["nodes"][1]["id"] == "run-tests-proposed"

    store.close()


def test_propose_template_from_cluster_raises_on_empty(tmp_path):
    """propose_template_from_cluster raises ValueError on empty cluster."""
    db_path = tmp_path / "test.db"
    store = Store(str(db_path))

    with pytest.raises(ValueError, match="empty cluster"):
        propose_template_from_cluster([], store)

    store.close()

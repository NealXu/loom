"""Tests for loom.core.loader — template loading and instantiation."""

import os
import re

import pytest
import yaml

from loom.core.loader import load_template, instantiate
from loom.core.models import Template, Instance, Node, Edge

TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "loom", "templates", "handoff-refresh.yaml"
)


def test_load_template_parses():
    """Load handoff-refresh.yaml and assert id/version/3 nodes."""
    tpl = load_template(TEMPLATE_PATH)
    assert tpl.id == "handoff-refresh"
    assert tpl.version == 1
    assert len(tpl.nodes) == 3


def test_load_template_empty_depends_on_ok():
    """A valid node may have depends_on: []."""
    tpl = load_template(TEMPLATE_PATH)
    analyze_node = tpl.nodes[0]
    assert analyze_node["id"] == "analyze"
    assert analyze_node["depends_on"] == []


def test_instantiate_makes_instance_pending():
    """Instantiate with project_path; instance status is pending, params contain the path."""
    tpl = load_template(TEMPLATE_PATH)
    instance, nodes, edges = instantiate(tpl, {"project_path": "/tmp/x"})
    assert isinstance(instance, Instance)
    assert instance.status == "pending"
    assert instance.params["project_path"] == "/tmp/x"
    assert instance.template_id == tpl.id


def test_instantiate_renders_spec_placeholders():
    """The refresh node's spec contains the substituted project_path, no leftover {{...}}."""
    tpl = load_template(TEMPLATE_PATH)
    instance, nodes, edges = instantiate(tpl, {"project_path": "/tmp/x"})
    # Find the node whose template id is "refresh"
    refresh_node = next(n for n in nodes if n.kind == "coding" and "handoff.md" in n.spec and "Rewrite" in n.spec)
    assert "/tmp/x" in refresh_node.spec
    assert not re.search(r"\{\{.*?\}\}", refresh_node.spec)


def test_instantiate_builds_edges_with_generated_ids():
    """Edges reference generated (non-template) node ids; 2 edges for handoff-refresh."""
    tpl = load_template(TEMPLATE_PATH)
    instance, nodes, edges = instantiate(tpl, {"project_path": "/tmp/x"})
    assert len(edges) == 2

    template_node_ids = {n["id"] for n in tpl.nodes}
    generated_node_ids = {n.id for n in nodes}

    # Generated ids must differ from template ids
    assert generated_node_ids.isdisjoint(template_node_ids)

    # All edge endpoints must be generated ids
    for edge in edges:
        assert edge.from_node in generated_node_ids
        assert edge.to_node in generated_node_ids
        assert edge.instance_id == instance.id


def test_instantiate_unique_node_ids():
    """All node ids are unique across the instance."""
    tpl = load_template(TEMPLATE_PATH)
    instance, nodes, edges = instantiate(tpl, {"project_path": "/tmp/x"})
    all_ids = [n.id for n in nodes]
    assert len(all_ids) == len(set(all_ids))


# --- Validation helpers & tests ---

def _write_bad_yaml(data: dict) -> str:
    """Write data to a temp YAML file, return its path (caller must unlink)."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(data, f)
    return path


def test_load_template_missing_key_raises():
    """A template missing required top-level keys raises ValueError."""
    path = _write_bad_yaml({"id": "bad"})
    try:
        with pytest.raises(ValueError):
            load_template(path)
    finally:
        os.unlink(path)


def test_load_template_duplicate_node_ids_raises():
    """Duplicate node ids raise ValueError."""
    bad = {
        "id": "dup", "version": 1, "trigger": [], "provenance": "manual",
        "params": {},
        "nodes": [
            {"id": "a", "kind": "analysis", "spec": "x", "depends_on": [], "tier": "heavy"},
            {"id": "a", "kind": "coding", "spec": "y", "depends_on": [], "tier": "tooling"},
        ],
    }
    path = _write_bad_yaml(bad)
    try:
        with pytest.raises(ValueError, match="[Uu]nique"):
            load_template(path)
    finally:
        os.unlink(path)


def test_load_template_bad_depends_on_raises():
    """depends_on referencing non-existent node raises ValueError."""
    bad = {
        "id": "bad-dep", "version": 1, "trigger": [], "provenance": "manual",
        "params": {},
        "nodes": [
            {"id": "a", "kind": "analysis", "spec": "x", "depends_on": ["ghost"], "tier": "heavy"},
        ],
    }
    path = _write_bad_yaml(bad)
    try:
        with pytest.raises(ValueError, match="depends_on"):
            load_template(path)
    finally:
        os.unlink(path)


def test_load_template_invalid_gate_raises():
    """An invalid gate value raises ValueError."""
    bad = {
        "id": "bad-gate", "version": 1, "trigger": [], "provenance": "manual",
        "params": {},
        "nodes": [
            {"id": "a", "kind": "analysis", "spec": "x", "depends_on": [], "tier": "heavy", "gate": "maybe"},
        ],
    }
    path = _write_bad_yaml(bad)
    try:
        with pytest.raises(ValueError, match="[Gg]ate"):
            load_template(path)
    finally:
        os.unlink(path)


def test_load_template_invalid_tier_raises():
    """An invalid tier value raises ValueError."""
    bad = {
        "id": "bad-tier", "version": 1, "trigger": [], "provenance": "manual",
        "params": {},
        "nodes": [
            {"id": "a", "kind": "analysis", "spec": "x", "depends_on": [], "tier": "mega"},
        ],
    }
    path = _write_bad_yaml(bad)
    try:
        with pytest.raises(ValueError, match="[Tt]ier"):
            load_template(path)
    finally:
        os.unlink(path)

"""Tests for the handoff-refresh workflow template (Task 10)."""

import pathlib

import yaml

_TEMPLATE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "loom"
    / "templates"
    / "handoff-refresh.yaml"
)


def _load_template():
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Test 1: YAML parses and has all required top-level keys ──


def test_template_has_required_top_level_keys():
    tpl = _load_template()
    for key in ("id", "version", "trigger", "params", "nodes", "provenance"):
        assert key in tpl, f"missing top-level key: {key}"


# ── Test 2: Exactly 3 nodes, unique ids, commit has gate=approve ──


def test_three_nodes_unique_ids_commit_gate():
    tpl = _load_template()
    nodes = tpl["nodes"]
    assert len(nodes) == 3, f"expected 3 nodes, got {len(nodes)}"

    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids)), f"node ids not unique: {ids}"

    commit_nodes = [n for n in nodes if n["id"] == "commit"]
    assert len(commit_nodes) == 1, "expected exactly one node with id='commit'"
    assert commit_nodes[0].get("gate") == "approve", (
        "commit node must have gate=approve"
    )


# ── Test 3: Dependency chain analyze → refresh → commit ──


def test_dependency_chain_analyze_refresh_commit():
    tpl = _load_template()
    nodes = tpl["nodes"]
    by_id = {n["id"]: n for n in nodes}

    # analyze has no dependencies (root of the chain)
    assert by_id["analyze"].get("depends_on", []) == []

    # refresh depends on analyze
    assert "analyze" in by_id["refresh"].get("depends_on", [])

    # commit depends on refresh
    assert "refresh" in by_id["commit"].get("depends_on", [])

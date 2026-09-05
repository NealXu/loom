"""Tests for workflow templates (Task 10: handoff-refresh, Task 20: feature-loop)."""

import pathlib

import yaml

_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent.parent / "loom" / "templates"


def _load_template(name: str):
    with open(_TEMPLATE_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Test 1: YAML parses and has all required top-level keys ──


def test_template_has_required_top_level_keys():
    tpl = _load_template("handoff-refresh.yaml")
    for key in ("id", "version", "trigger", "params", "nodes", "provenance"):
        assert key in tpl, f"missing top-level key: {key}"


# ── Test 2: Exactly 3 nodes, unique ids, commit has gate=approve ──


def test_three_nodes_unique_ids_commit_gate():
    tpl = _load_template("handoff-refresh.yaml")
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
    tpl = _load_template("handoff-refresh.yaml")
    nodes = tpl["nodes"]
    by_id = {n["id"]: n for n in nodes}

    # analyze has no dependencies (root of the chain)
    assert by_id["analyze"].get("depends_on", []) == []

    # refresh depends on analyze
    assert "analyze" in by_id["refresh"].get("depends_on", [])

    # commit depends on refresh
    assert "refresh" in by_id["commit"].get("depends_on", [])


# ── Task 20: feature-loop template tests ──


# ── Test 4: feature-loop parses and has id/version/4 nodes ──


def test_feature_loop_parses():
    tpl = _load_template("feature-loop.yaml")
    assert tpl["id"] == "feature-loop"
    assert tpl["version"] == 1
    assert len(tpl["nodes"]) == 4, f"expected 4 nodes, got {len(tpl['nodes'])}"

    ids = [n["id"] for n in tpl["nodes"]]
    assert len(ids) == len(set(ids)), f"node ids not unique: {ids}"


# ── Test 5: merge node has mandatory gate=approve ──


def test_feature_loop_has_mandatory_merge_gate():
    tpl = _load_template("feature-loop.yaml")
    nodes = tpl["nodes"]

    merge_nodes = [n for n in nodes if n["id"] == "merge"]
    assert len(merge_nodes) == 1, "expected exactly one node with id='merge'"
    assert merge_nodes[0].get("gate") == "approve", (
        "merge node must have gate=approve"
    )


# ── Test 6: Dependency chain implement → test → review → merge ──


def test_feature_loop_dependency_chain():
    tpl = _load_template("feature-loop.yaml")
    nodes = tpl["nodes"]
    by_id = {n["id"]: n for n in nodes}

    # implement is the root (no dependencies)
    assert by_id["implement"].get("depends_on", []) == []

    # test depends on implement
    assert "implement" in by_id["test"].get("depends_on", [])

    # review depends on test
    assert "test" in by_id["review"].get("depends_on", [])

    # merge depends on review
    assert "review" in by_id["merge"].get("depends_on", [])


# ── Task 21: repo-analysis template tests ──


# ── Test 7: repo-analysis parses and has id/version/3 nodes ──


def test_repo_analysis_parses():
    tpl = _load_template("repo-analysis.yaml")
    assert tpl["id"] == "repo-analysis"
    assert tpl["version"] == 1
    assert len(tpl["nodes"]) == 3, f"expected 3 nodes, got {len(tpl['nodes'])}"


# ── Test 8: repo-analysis node ids are unique ──


def test_repo_analysis_node_ids_unique():
    tpl = _load_template("repo-analysis.yaml")
    ids = [n["id"] for n in tpl["nodes"]]
    assert len(ids) == len(set(ids)), f"node ids not unique: {ids}"
    assert set(ids) == {"scan", "analyze", "report"}


# ── Test 9: repo-analysis dependency chain scan → analyze → report ──


def test_repo_analysis_dependency_chain():
    tpl = _load_template("repo-analysis.yaml")
    nodes = tpl["nodes"]
    by_id = {n["id"]: n for n in nodes}

    # scan is the root (no dependencies)
    assert by_id["scan"].get("depends_on", []) == []

    # analyze depends on scan
    assert "scan" in by_id["analyze"].get("depends_on", [])

    # report depends on analyze
    assert "analyze" in by_id["report"].get("depends_on", [])

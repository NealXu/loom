"""P5-C: Evolver smoke -- realistic LLM outputs + CLI integration + multi-cluster."""
import asyncio
import os

import pytest
import yaml
from click.testing import CliRunner

from loom.adapters.base import Result, RunnerAdapter
from loom.cli import main
from loom.core.loader import load_template
from loom.core.models import Instance, Node
from loom.core.store import Store
from loom.evolver.evolve import evolve

# Valid YAML template used as the "core" that LLM output wraps around.
_CORE_YAML = """\
id: discovered-report
version: 1
trigger: [cli]
provenance: discovered
params: {}
nodes:
  - id: draft
    kind: report
    tier: tooling
    spec: "Draft a report"
    depends_on: []
  - id: ship
    kind: review
    tier: tooling
    spec: "Review the report"
    depends_on: [draft]
"""


class _StubRunner(RunnerAdapter):
    """Stub runner that returns a canned string."""

    name = "stub"

    def __init__(self, output: str):
        self._output = output
        self.prompts: list[str] = []

    async def run(self, node) -> Result:
        self.prompts.append(node.spec)
        return Result(success=True, output=self._output)


# ---------------------------------------------------------------------------
# Fixture: store with 4 succeeded instances sharing template_id "report-job"
# ---------------------------------------------------------------------------

@pytest.fixture()
def store_with_cluster(tmp_path):
    db = str(tmp_path / "t.db")
    with Store(db) as store:
        for i in range(4):
            iid = f"i{i}"
            store.create_instance(
                Instance(id=iid, template_id="report-job", status="succeeded")
            )
            store.create_node(
                Node(
                    id=f"{iid}-a",
                    instance_id=iid,
                    template_id="report-job",
                    title="draft",
                    kind="report",
                    spec="draft x",
                    status="succeeded",
                )
            )
        yield store


# ---------------------------------------------------------------------------
# 1. LLM output wrapped in ```yaml fences
# ---------------------------------------------------------------------------

def test_llm_output_with_markdown_fencing(tmp_path, store_with_cluster):
    """LLM often wraps YAML in ```yaml ... ``` fences. Should still parse."""
    fenced = f"Here is the template:\n\n```yaml\n{_CORE_YAML}```\n"
    runner = _StubRunner(fenced)
    out = tmp_path / "discovered"
    written = asyncio.run(
        evolve(store_with_cluster, runner, str(out), min_frequency=3)
    )
    assert len(written) == 1
    tpl = load_template(written[0])
    assert tpl.id == "discovered-report"
    assert tpl.provenance == "discovered"


# ---------------------------------------------------------------------------
# 2. LLM output with explanatory prose surrounding the YAML
# ---------------------------------------------------------------------------

def test_llm_output_with_explanatory_text(tmp_path, store_with_cluster):
    """LLM produces prose before and after the YAML block. Should extract."""
    messy = (
        "Sure! Here's a template based on the evidence:\n\n"
        f"```yaml\n{_CORE_YAML}```\n\n"
        "Let me know if you need any changes to this template."
    )
    runner = _StubRunner(messy)
    out = tmp_path / "discovered"
    written = asyncio.run(
        evolve(store_with_cluster, runner, str(out), min_frequency=3)
    )
    assert len(written) == 1
    tpl = load_template(written[0])
    assert tpl.id == "discovered-report"
    assert tpl.provenance == "discovered"
    assert len(tpl.nodes) == 2


# ---------------------------------------------------------------------------
# 3. CLI integration: `loom evolve` via CliRunner
# ---------------------------------------------------------------------------

def test_cli_evolve_command_integration(tmp_path):
    """Exercise the real CLI command end-to-end with --runner fake."""
    db_path = str(tmp_path / "cli.db")
    out_dir = str(tmp_path / "discovered")

    # Seed the store with a qualifying cluster (4 >= min_frequency 3).
    with Store(db_path) as store:
        for i in range(4):
            iid = f"cli-i{i}"
            store.create_instance(
                Instance(id=iid, template_id="report-job", status="succeeded")
            )
            store.create_node(
                Node(
                    id=f"{iid}-n1",
                    instance_id=iid,
                    template_id="report-job",
                    title="draft",
                    kind="report",
                    spec="draft report",
                    tier="tooling",
                    status="succeeded",
                )
            )

    cli_runner = CliRunner()
    result = cli_runner.invoke(
        main,
        [
            "evolve",
            "--db", db_path,
            "--out", out_dir,
            "--runner", "fake",
            "--min-frequency", "3",
        ],
    )
    assert result.exit_code == 0, result.output
    # FakeRunner output is not valid YAML, so evolver uses deterministic fallback.
    # Either way, a discovered template file should appear.
    files = os.listdir(out_dir)
    assert len(files) == 1
    assert files[0].endswith(".yaml")
    tpl = load_template(os.path.join(out_dir, files[0]))
    assert tpl.provenance == "discovered"


# ---------------------------------------------------------------------------
# 4. Multi-cluster: only frequent clusters produce candidates
# ---------------------------------------------------------------------------

def test_multi_cluster_only_frequent_emitted(tmp_path):
    """3 clusters: report(4), draft(2), review(1). min_frequency=3 -> only report."""
    db = str(tmp_path / "multi.db")
    with Store(db) as store:
        # Cluster 1: 4 instances of "report" -> frequent
        for i in range(4):
            iid = f"rpt-{i}"
            store.create_instance(
                Instance(id=iid, template_id="report", status="succeeded")
            )
            store.create_node(
                Node(
                    id=f"{iid}-n",
                    instance_id=iid,
                    template_id="report",
                    title="step",
                    kind="report",
                    spec="report step",
                    status="succeeded",
                )
            )
        # Cluster 2: 2 instances of "draft" -> below threshold
        for i in range(2):
            iid = f"dft-{i}"
            store.create_instance(
                Instance(id=iid, template_id="draft", status="succeeded")
            )
            store.create_node(
                Node(
                    id=f"{iid}-n",
                    instance_id=iid,
                    template_id="draft",
                    title="step",
                    kind="coding",
                    spec="draft step",
                    status="succeeded",
                )
            )
        # Cluster 3: 1 instance of "review" -> below threshold
        store.create_instance(
            Instance(id="rvw-0", template_id="review", status="succeeded")
        )
        store.create_node(
            Node(
                id="rvw-0-n",
                instance_id="rvw-0",
                template_id="review",
                title="step",
                kind="review",
                spec="review step",
                status="succeeded",
            )
        )

        out = tmp_path / "discovered"
        runner = _StubRunner("not valid yaml at all")  # force fallback for all
        written = asyncio.run(evolve(store, runner, str(out), min_frequency=3))

        # Only the "report" cluster should produce a candidate.
        assert len(written) == 1
        tpl = load_template(written[0])
        assert "report" in tpl.id


# ---------------------------------------------------------------------------
# 5. Fallback template has valid structure
# ---------------------------------------------------------------------------

VALID_KINDS = {"analysis", "coding", "review", "deploy", "report"}
VALID_TIERS = {"critical", "heavy", "tooling", "bulk"}


def test_fallback_template_structure(tmp_path):
    """Deterministic fallback must have all required fields and valid node kinds/tiers."""
    db = str(tmp_path / "fb.db")
    with Store(db) as store:
        for i in range(3):
            iid = f"fb-{i}"
            store.create_instance(
                Instance(id=iid, template_id="mytpl", status="succeeded")
            )
            store.create_node(
                Node(
                    id=f"{iid}-a",
                    instance_id=iid,
                    template_id="mytpl",
                    title="analyze",
                    kind="analysis",
                    spec="analyze stuff",
                    tier="critical",
                    status="succeeded",
                )
            )
            store.create_node(
                Node(
                    id=f"{iid}-b",
                    instance_id=iid,
                    template_id="mytpl",
                    title="code",
                    kind="coding",
                    spec="write code",
                    tier="heavy",
                    status="succeeded",
                )
            )

        out = tmp_path / "discovered"
        # Runner returns garbage -> triggers deterministic fallback
        runner = _StubRunner("???")
        written = asyncio.run(evolve(store, runner, str(out), min_frequency=3))
        assert len(written) == 1

        # Load and validate structure
        tpl = load_template(written[0])
        assert tpl.id is not None and len(tpl.id) > 0
        assert tpl.version >= 1
        assert isinstance(tpl.trigger, list) and len(tpl.trigger) > 0
        assert tpl.provenance == "discovered"
        assert isinstance(tpl.params, dict)
        assert len(tpl.nodes) >= 1

        for node in tpl.nodes:
            assert "id" in node and len(node["id"]) > 0
            assert node["kind"] in VALID_KINDS, f"bad kind: {node['kind']}"
            assert node["tier"] in VALID_TIERS, f"bad tier: {node['tier']}"
            assert "spec" in node
            assert "depends_on" in node

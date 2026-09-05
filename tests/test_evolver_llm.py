"""P4-D: evolver LLM channel — cluster -> runner -> discovered template."""
import asyncio
import pytest
import yaml
from loom.core.store import Store
from loom.core.models import Instance, Node
from loom.core.loader import load_template
from loom.evolver.evolve import evolve
from loom.adapters.base import RunnerAdapter, Result

VALID_YAML = """
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
    name = "stub"
    def __init__(self, output):
        self._output = output
        self.prompts = []
    async def run(self, node) -> Result:
        self.prompts.append(node.spec)
        return Result(success=True, output=self._output)


@pytest.fixture
def store_with_cluster(tmp_path):
    db = str(tmp_path / "t.db")
    with Store(db) as store:
        for i in range(4):
            iid = f"i{i}"
            store.create_instance(Instance(id=iid, template_id="report-job", status="succeeded"))
            store.create_node(Node(id=f"{iid}-a", instance_id=iid, template_id="report-job",
                                   title="draft", kind="report", spec="draft x", status="succeeded"))
        yield store


def test_evolve_writes_llm_proposal(tmp_path, store_with_cluster):
    out = tmp_path / "discovered"
    runner = _StubRunner(VALID_YAML)
    written = asyncio.run(evolve(store_with_cluster, runner, str(out), min_frequency=3))

    assert len(written) == 1
    path = written[0]
    assert path.endswith(".yaml")
    tpl = load_template(path)  # must be a valid, loadable template
    assert tpl.provenance == "discovered"
    assert tpl.id == "discovered-report"
    # the prompt contained the cluster evidence
    assert "report-job" in runner.prompts[0]


def test_evolve_falls_back_on_garbage(tmp_path, store_with_cluster):
    """Unparseable LLM output still yields a valid deterministic candidate."""
    out = tmp_path / "discovered"
    runner = _StubRunner("sorry, I can't produce YAML today")
    written = asyncio.run(evolve(store_with_cluster, runner, str(out), min_frequency=3))

    assert len(written) == 1
    tpl = load_template(written[0])  # valid regardless
    assert tpl.provenance == "discovered"


def test_evolve_respects_min_frequency(tmp_path, store_with_cluster):
    out = tmp_path / "discovered"
    runner = _StubRunner(VALID_YAML)
    written = asyncio.run(evolve(store_with_cluster, runner, str(out), min_frequency=10))
    assert written == []


def test_evolve_runs_failed_is_skipped(tmp_path, store_with_cluster):
    """A runner error on one cluster must not abort the whole sweep."""
    class _Boom(RunnerAdapter):
        name = "boom"
        async def run(self, node): return Result(success=False, error="down")
    out = tmp_path / "discovered"
    written = asyncio.run(evolve(store_with_cluster, _Boom(), str(out), min_frequency=3))
    # falls back to deterministic proposal -> still valid
    assert len(written) == 1
    assert load_template(written[0]).provenance == "discovered"

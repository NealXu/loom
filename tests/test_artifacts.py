"""P4-E: node outputs land in the Vault and are registered as Artifacts."""
import asyncio
import json
import pytest
from pathlib import Path
from loom.core.store import Store
from loom.core.models import Node, Instance
from loom.core.engine import step_instance
from loom.adapters.fake import FakeRunner


def test_success_writes_artifact_to_vault(tmp_path):
    vault = tmp_path / "vault"
    db = str(tmp_path / "t.db")
    with Store(db) as store:
        store.create_instance(Instance(id="i1", template_id="t", status="pending"))
        store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                               spec="hello out", status="pending", budget_tokens=50000))
        asyncio.run(step_instance(store, "i1", FakeRunner(), vault_dir=str(vault)))

        art_file = vault / "i1" / "n1.md"
        assert art_file.exists()
        assert "hello out" in art_file.read_text(encoding="utf-8")

        arts = store.list_artifacts("n1")
        assert len(arts) == 1
        assert arts[0].kind == "md"
        assert len(arts[0].sha256) == 64

        node = store.get_node("n1")
        assert str(art_file) in node.artifact_paths


def test_no_vault_dir_skips_artifacts(tmp_path):
    db = str(tmp_path / "t.db")
    with Store(db) as store:
        store.create_instance(Instance(id="i1", template_id="t", status="pending"))
        store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                               spec="x", status="pending"))
        asyncio.run(step_instance(store, "i1", FakeRunner()))
        assert store.list_artifacts("n1") == []


def test_failed_node_writes_no_artifact(tmp_path):
    from loom.adapters.base import RunnerAdapter, Result
    class _Fail(RunnerAdapter):
        name = "fail"
        async def run(self, node): return Result(success=False)
    vault = tmp_path / "vault"
    db = str(tmp_path / "t.db")
    with Store(db) as store:
        store.create_instance(Instance(id="i1", template_id="t", status="pending"))
        store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                               spec="x", status="pending"))
        asyncio.run(step_instance(store, "i1", _Fail(), vault_dir=str(vault)))
        assert store.list_artifacts("n1") == []

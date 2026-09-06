"""P5-A: Vault artifact persistence end-to-end."""
import asyncio
from loom.core.store import Store
from loom.core.models import Instance, Node
from loom.core.engine import step_instance
from loom.adapters.fake import FakeRunner


def test_vault_writes_artifact_end_to_end(tmp_path):
    db = tmp_path / "test.db"
    vault = tmp_path / "vault"
    with Store(str(db)) as store:
        store.create_instance(Instance(id="i1", title="Vault Test", template_id="t"))
        store.create_node(Node(id="n1", instance_id="i1", template_id="t",
                               spec="do it", status="pending"))
        # Drive the engine with a fake runner and vault enabled
        result_status = asyncio.run(
            step_instance(store, "i1", FakeRunner(), vault_dir=str(vault)))
        # Node should succeed
        node = store.get_node("n1")
        assert node.status == "succeeded", f"expected succeeded, got {node.status} ({result_status})"
        # Artifact file should exist on disk
        artifact_file = vault / "i1" / "n1.md"
        assert artifact_file.exists(), f"expected {artifact_file} to exist"
        assert artifact_file.read_text(encoding="utf-8").strip() != ""
        # Artifact row should be registered in the store
        artifacts = store.list_artifacts("n1")
        assert len(artifacts) == 1
        assert artifacts[0].path.endswith("n1.md") or "n1.md" in artifacts[0].path


def test_vault_disabled_writes_nothing(tmp_path):
    db = tmp_path / "test.db"
    with Store(str(db)) as store:
        store.create_instance(Instance(id="i2", title="No Vault", template_id="t"))
        store.create_node(Node(id="n2", instance_id="i2", template_id="t",
                               spec="do it", status="pending"))
        asyncio.run(step_instance(store, "i2", FakeRunner(), vault_dir=None))
        assert store.list_artifacts("n2") == []

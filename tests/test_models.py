from loom.core.models import Node, Instance

def test_node_creation():
    node = Node(
        id="abc123",
        instance_id="inst1",
        template_id="handoff-refresh",
        owner="me",
        title="inventory",
        kind="analysis",
        spec="Inventory {{project_path}}",
        tier="tooling",
        gate="none",
        status="pending",
        project_path="/path/to/repo",
        budget_tokens=50000,
    )
    assert node.id == "abc123"
    assert node.status == "pending"

def test_instance_creation():
    inst = Instance(
        id="inst1",
        template_id="handoff-refresh",
        owner="me",
        title="handoff for inkwell",
        project_path="/path/to/inkwell",
        status="pending",
        params={"project_path": "/path/to/inkwell"},
    )
    assert inst.id == "inst1"
    assert inst.cost_tokens == 0
    assert inst.cost_usd == 0.0

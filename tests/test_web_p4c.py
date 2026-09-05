"""P4-C: web pagination, POST /api/run, SSE stream."""
import json
import tempfile
import os
import pytest
from fastapi.testclient import TestClient
from loom.core.store import Store
from loom.core.models import Instance
from loom.web.app import create_app

TPL = """
id: web-run
version: 1
trigger: [cli]
provenance: manual
params:
  topic: {type: string, required: true}
nodes:
  - id: s1
    kind: analysis
    spec: "work on {{topic}}"
    depends_on: []
"""


@pytest.fixture
def client(tmp_path):
    tpl_path = tmp_path / "web-run.yaml"
    tpl_path.write_text(TPL, encoding="utf-8")
    db = str(tmp_path / "t.db")
    with Store(db) as store:
        app = create_app(store)
        c = TestClient(app)
        c.tpl_path = str(tpl_path)
        c.store = store
        c.db = db
        yield c


def test_pagination(client):
    store = client.store
    for i in range(12):
        store.create_instance(Instance(id=f"i{i}", template_id="t", status="pending"))
    data = client.get("/api/instances?limit=5&offset=0").json()
    assert len(data) == 5
    data2 = client.get("/api/instances?limit=5&offset=10").json()
    assert len(data2) == 2
    # ids don't overlap
    assert {d["id"] for d in data}.isdisjoint({d["id"] for d in data2})


def test_run_creates_pending_instance(client):
    resp = client.post("/api/run", json={
        "template": client.tpl_path,
        "params": {"topic": "hello"},
    })
    assert resp.status_code == 201
    inst_id = resp.json()["instance_id"]
    with Store(client.db) as store:
        inst = store.get_instance(inst_id)
        assert inst.status == "pending"
        assert inst.params["topic"] == "hello"
        assert len(store.list_nodes(inst_id)) == 1


def test_run_validates_params(client):
    resp = client.post("/api/run", json={"template": client.tpl_path, "params": {}})
    assert resp.status_code == 400


def test_run_missing_template_404(client):
    resp = client.post("/api/run", json={"template": "no-such-file.yaml", "params": {}})
    assert resp.status_code == 404


def test_sse_stream_emits_new_events(client, tmp_path):
    from loom.web.sse import event_stream
    from loom.core.models import Event

    async def collect():
        store = Store(str(tmp_path / "t.db"))
        store.create_event(Event(source="inbox", payload={"a": 1}))
        store.create_event(Event(source="hook", payload={"b": 2}))
        lines = []
        async for chunk in event_stream(store, max_events=2, poll_interval=0.01):
            lines.append(chunk)
        store.close()
        return lines

    import asyncio
    lines = asyncio.run(collect())
    payloads = [json.loads(l.split("data: ", 1)[1]) for l in lines]
    assert payloads[0]["source"] == "inbox"
    assert payloads[1]["payload"] == {"b": 2}

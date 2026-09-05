import tempfile
import os
from datetime import datetime, timedelta
from loom.core.store import Store
from loom.core.models import Instance
from loom.triggers.cron import build_digest, render_digest


def _make_store():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    return Store(db_path)


def test_build_digest_counts_and_totals():
    store = _make_store()
    try:
        store.create_instance(Instance(id="i1", template_id="t1", title="A", status="succeeded", cost_usd=1.0, cost_tokens=100))
        store.create_instance(Instance(id="i2", template_id="t1", title="B", status="succeeded", cost_usd=2.5, cost_tokens=200))
        store.create_instance(Instance(id="i3", template_id="t2", title="C", status="running", cost_usd=0.5, cost_tokens=50))

        digest = build_digest(store)
        assert digest["total"] == 3
        assert digest["by_status"] == {"succeeded": 2, "running": 1}
        assert abs(digest["total_cost_usd"] - 4.0) < 1e-9
        assert len(digest["instances"]) == 3
    finally:
        store.close()


def test_build_digest_flags_over_budget():
    store = _make_store()
    try:
        store.create_instance(Instance(id="i1", template_id="t1", title="Expensive", status="succeeded", cost_usd=6.0))
        store.create_instance(Instance(id="i2", template_id="t1", title="Cheap", status="succeeded", cost_usd=2.0))

        digest = build_digest(store)
        over_ids = [inst["id"] for inst in digest["over_budget"]]
        assert "i1" in over_ids
        assert "i2" not in over_ids
    finally:
        store.close()


def test_render_digest_highlights_over_budget_red():
    digest = {
        "total": 2,
        "by_status": {"succeeded": 2},
        "total_cost_usd": 8.0,
        "over_budget": [{"id": "i1", "title": "Expensive", "status": "succeeded", "cost_usd": 6.0, "template_id": "t1"}],
        "instances": [
            {"id": "i1", "title": "Expensive", "status": "succeeded", "cost_usd": 6.0, "template_id": "t1"},
            {"id": "i2", "title": "Cheap", "status": "succeeded", "cost_usd": 2.0, "template_id": "t1"},
        ],
    }
    rendered = render_digest(digest)
    # Over-budget instance must have red marker
    assert "(OVER BUDGET" in rendered and "i1" in rendered
    # The rendered text for i1 line should contain the red marker
    # The cheap instance line should NOT contain the red marker
    lines = rendered.splitlines()
    over_lines = [l for l in lines if "i1" in l]
    cheap_lines = [l for l in lines if "i2" in l]
    assert any("OVER BUDGET" in l for l in over_lines)
    assert not any("OVER BUDGET" in l for l in cheap_lines)


def test_build_digest_respects_since():
    store = _make_store()
    try:
        now = datetime.now()
        store.create_instance(Instance(id="old", template_id="t1", title="Old", status="succeeded",
                                      created_at=now - timedelta(days=2), cost_usd=1.0))
        store.create_instance(Instance(id="new", template_id="t1", title="New", status="succeeded",
                                      created_at=now - timedelta(hours=1), cost_usd=1.0))

        since = (now - timedelta(days=1)).isoformat()
        digest = build_digest(store, since=since)
        assert digest["total"] == 1
        assert digest["instances"][0]["id"] == "new"
    finally:
        store.close()

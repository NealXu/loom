"""P7 — Backend API contract tests for the Loom web UI.

These cover the endpoints that back the redesigned UI pages:
  /api/templates  — Run + Templates pages
  /api/stats      — Dashboard KPI cards
  /api/health     — Dashboard health badge
  /api/audit      — Audit timeline
  /api/digest     — Daily digest page
  /api/cost       — Cost analysis page

Test-first ("red") contract for those new endpoints.
"""
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from loom.core.store import Store
from loom.core.models import Node, Instance, Event

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_instance(store, id, title, status="succeeded", cost_usd=0.0,
                   cost_tokens=0, template_id="repo-analysis", owner="me"):
    store.create_instance(Instance(id=id, title=title, template_id=template_id,
                                   status=status, cost_usd=cost_usd,
                                   cost_tokens=cost_tokens, owner=owner))


def _seed_node(store, id, instance_id, title="n", kind="analysis",
               status="succeeded", tier="tooling", gate="none"):
    store.create_node(Node(id=id, instance_id=instance_id, template_id="t",
                           title=title, kind=kind, status=status, tier=tier,
                           gate=gate))


def _seed_event(store, source, payload, instance_id=None):
    store.create_event(Event(source=source, payload=payload,
                             consumed_by_instance=instance_id))


def _seed_gate(store, node_id, instance_id, approved=True, approver="me",
               reason="LGTM"):
    store.conn.execute(
        "INSERT INTO gate_decisions (node_id, instance_id, approved, approver, reason, decided_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (node_id, instance_id, int(approved), approver, reason,
         datetime.now().isoformat()))
    store.conn.commit()


def _write_template(tmpdir: str, filename: str, data: dict) -> Path:
    tdir = Path(tmpdir) / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / filename).write_text(
        __import__("json").dumps(data), encoding="utf-8")
    return tdir


@contextmanager
def _client(db_path: str, templates_dir: str, **kwargs):
    store = Store(db_path)
    try:
        from loom.web.app import create_app
        app = create_app(store, templates_dir=templates_dir, **kwargs)
        client = TestClient(app)
        yield client
    finally:
        store.close()


# ---------------------------------------------------------------------------
# /api/templates
# ---------------------------------------------------------------------------


class TestTemplates:
    def test_templates_returns_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            tdir = _write_template(tmpdir, "repo-analysis.yaml", {
                "id": "repo-analysis", "version": 1, "trigger": ["cli"],
                "params": {}, "nodes": [], "provenance": "manual"})
            with _client(db, str(tdir)) as client:
                resp = client.get("/api/templates")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1

    def test_template_has_required_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            tdir = _write_template(tmpdir, "repo-analysis.yaml", {
                "id": "repo-analysis", "version": 1, "trigger": ["cli", "cron"],
                "params": {}, "nodes": [{"id": "n1"}], "provenance": "manual"})
            with _client(db, str(tdir)) as client:
                data = client.get("/api/templates").json()
            tpl = next(t for t in data if t["id"] == "repo-analysis")
            for key in ("id", "version", "trigger", "provenance"):
                assert key in tpl, f"template missing field: {key}"
            assert "cli" in tpl["trigger"]
            assert tpl["provenance"] == "manual"

    def test_templates_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            tdir = Path(tmpdir) / "templates"
            tdir.mkdir()
            with _client(db, str(tdir)) as client:
                data = client.get("/api/templates").json()
            assert data == []


# ---------------------------------------------------------------------------
# /api/stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", status="succeeded")
                _seed_instance(store, "i2", "B", status="failed")
            with _client(db, tmpdir) as client:
                resp = client.get("/api/stats")
            assert resp.status_code == 200
            data = resp.json()
            assert "instances" in data and "nodes" in data
            assert "events" in data and "gate_decisions" in data

    def test_stats_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", status="succeeded")
                _seed_instance(store, "i2", "B", status="succeeded")
                _seed_instance(store, "i3", "C", status="failed")
                _seed_node(store, "n1", "i1")
                _seed_node(store, "n2", "i1")
                _seed_event(store, "cli", {"x": 1})
                _seed_event(store, "cli", {"x": 2})
                _seed_gate(store, "n1", "i1")
            with _client(db, tmpdir) as client:
                data = client.get("/api/stats").json()
            assert data["instances"]["total"] == 3
            assert data["instances"]["by_status"]["succeeded"] == 2
            assert data["nodes"]["total"] == 2
            assert data["events"] == 2
            assert data["gate_decisions"] == 1


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", status="succeeded", cost_usd=2.0)
                _seed_instance(store, "i2", "B", status="succeeded", cost_usd=4.0)
            with _client(db, tmpdir) as client:
                resp = client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            for key in ("recent_instances", "succeeded", "failed", "success_rate",
                        "avg_cost_usd", "pending_gates", "last_event"):
                assert key in data, f"health missing field: {key}"

    def test_health_rates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", status="succeeded", cost_usd=2.0)
                _seed_instance(store, "i2", "B", status="succeeded", cost_usd=4.0)
            with _client(db, tmpdir) as client:
                data = client.get("/api/health").json()
            assert data["success_rate"] == 100.0
            assert round(data["avg_cost_usd"], 2) == 3.0

    def test_health_pending_gates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A")
                store.conn.execute(
                    "INSERT INTO gate_decisions (node_id, instance_id, approved, approver, reason, decided_at) "
                    "VALUES ('n1', 'i1', NULL, NULL, NULL, NULL)")
                store.conn.commit()
            with _client(db, tmpdir) as client:
                data = client.get("/api/health").json()
            assert data["pending_gates"] == 1


# ---------------------------------------------------------------------------
# /api/audit
# ---------------------------------------------------------------------------


class TestAudit:
    def test_audit_returns_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_event(store, "state_transition",
                            {"entity_kind": "node", "entity_id": "n1",
                             "from_status": "pending", "to_status": "running"},
                            instance_id="i1")
                _seed_gate(store, "n1", "i1")
            with _client(db, tmpdir) as client:
                resp = client.get("/api/audit")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 2

    def test_audit_items_have_type_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_event(store, "state_transition",
                            {"entity_kind": "node", "entity_id": "n1",
                             "from_status": "pending", "to_status": "running"},
                            instance_id="i1")
                _seed_gate(store, "n1", "i1")
            with _client(db, tmpdir) as client:
                items = client.get("/api/audit").json()
            for item in items:
                assert "timestamp" in item
                assert "type" in item
                assert item["type"] in ("gate", "transition")

    def test_audit_filter_by_type_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_event(store, "state_transition",
                            {"entity_kind": "node", "entity_id": "n1",
                             "from_status": "pending", "to_status": "running"},
                            instance_id="i1")
                _seed_gate(store, "n1", "i1")
            with _client(db, tmpdir) as client:
                data = client.get("/api/audit", params={"type": "gate"}).json()
            assert all(item["type"] == "gate" for item in data)

    def test_audit_filter_by_instance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_gate(store, "n1", "i1")
                _seed_gate(store, "n2", "i2")
            with _client(db, tmpdir) as client:
                data = client.get("/api/audit", params={"instance_id": "i2"}).json()
            assert all(item.get("instance_id") == "i2" for item in data)


# ---------------------------------------------------------------------------
# /api/digest
# ---------------------------------------------------------------------------


class TestDigest:
    def test_digest_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", status="succeeded", cost_usd=1.0)
            with _client(db, tmpdir, red_line_usd=5.0) as client:
                resp = client.get("/api/digest")
            assert resp.status_code == 200
            data = resp.json()
            for key in ("date", "total_instances", "total_cost_usd", "succeeded",
                        "failed", "success_rate", "red_line_usd", "over_budget",
                        "recent"):
                assert key in data, f"digest missing field: {key}"

    def test_digest_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", status="succeeded", cost_usd=1.0)
                _seed_instance(store, "i2", "B", status="failed", cost_usd=6.0)
            with _client(db, tmpdir, red_line_usd=5.0) as client:
                data = client.get("/api/digest").json()
            assert data["total_instances"] == 2
            assert data["succeeded"] == 1
            assert data["failed"] == 1
            assert round(data["total_cost_usd"], 2) == 7.0

    def test_digest_over_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", status="succeeded", cost_usd=6.0)
                _seed_instance(store, "i2", "B", status="succeeded", cost_usd=1.0)
            with _client(db, tmpdir, red_line_usd=5.0) as client:
                data = client.get("/api/digest").json()
            ids = [x["id"] for x in data["over_budget"]]
            assert ids == ["i1"]


# ---------------------------------------------------------------------------
# /api/cost
# ---------------------------------------------------------------------------


class TestCost:
    def test_cost_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", cost_usd=1.5, cost_tokens=100,
                               template_id="repo-analysis")
                _seed_instance(store, "i2", "B", cost_usd=2.5, cost_tokens=200,
                               template_id="ops-deploy")
            with _client(db, tmpdir) as client:
                resp = client.get("/api/cost")
            assert resp.status_code == 200
            data = resp.json()
            for key in ("total_usd", "total_tokens", "avg_usd", "instance_count",
                        "by_template", "by_instance"):
                assert key in data, f"cost missing field: {key}"

    def test_cost_totals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", cost_usd=1.5, cost_tokens=100,
                               template_id="repo-analysis")
                _seed_instance(store, "i2", "B", cost_usd=2.5, cost_tokens=200,
                               template_id="repo-analysis")
            with _client(db, tmpdir) as client:
                data = client.get("/api/cost").json()
            assert round(data["total_usd"], 2) == 4.0
            assert data["total_tokens"] == 300
            assert data["instance_count"] == 2

    def test_cost_by_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "t.db")
            with Store(db) as store:
                _seed_instance(store, "i1", "A", cost_usd=1.5, template_id="repo-analysis")
                _seed_instance(store, "i2", "B", cost_usd=2.5, template_id="ops-deploy")
            with _client(db, tmpdir) as client:
                data = client.get("/api/cost").json()
            assert "repo-analysis" in data["by_template"]
            assert "ops-deploy" in data["by_template"]
            assert data["by_template"]["repo-analysis"]["instances"] == 1

"""FastAPI web backend for Loom — read-only REST API over the graph store."""

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

import yaml


class GateSummary(BaseModel):
    """A node currently awaiting gate approval."""
    id: str
    instance_id: str
    title: str = ""
    kind: str = ""
    gate: str = ""
    status: str


class GateDecisionResult(BaseModel):
    """Result of an approve/reject decision."""
    approved: bool
    node_id: str


class GateRequestBody(BaseModel):
    """Optional reason for an approve/reject call."""
    reason: str = ""


class RunRequestBody(BaseModel):
    """Template path + params for POST /api/run."""
    template: str
    params: dict = {}


def create_app(store, templates_dir: str = "loom/templates", red_line_usd: float = 5.0) -> FastAPI:
    """Pure app factory. No uvicorn.run."""
    app = FastAPI(title="Loom", version="0.1.0")

    # --- P6-B: Token authentication -------------------------------------------
    _auth_token = os.environ.get("LOOM_AUTH_TOKEN") or None
    app.state.auth_token = _auth_token

    # --- P6-C: Multi-user owner support ---------------------------------------
    _default_owner = os.environ.get("LOOM_OWNER", "me")
    app.state.default_owner = _default_owner

    bearer = HTTPBearer(auto_error=False)

    async def verify_auth(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        """Dependency: require valid bearer token when auth is configured."""
        token = getattr(app.state, "auth_token", None)
        if token is None:
            return None  # no auth configured, allow all
        if credentials is None or credentials.credentials != token:
            raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing token")
        return credentials
    # --------------------------------------------------------------------------

    _INDEX_HTML = Path(__file__).resolve().parent / "static" / "index.html"

    @app.get("/")
    def index():
        return FileResponse(str(_INDEX_HTML), media_type="text/html")

    @app.post("/api/auth")
    def auth_validate(body: dict):
        """Validate a token (for frontend login forms)."""
        token = getattr(app.state, "auth_token", None)
        if token is None:
            return {"ok": True, "auth_required": False}
        provided = body.get("token", "")
        return {"ok": provided == token, "auth_required": True}

    @app.get("/api/instances")
    def list_instances(limit: Optional[int] = None, offset: int = 0,
                       owner: Optional[str] = None, _auth=Depends(verify_auth)):
        effective_owner = owner if owner is not None else getattr(app.state, "default_owner", "me")
        sql = ("SELECT id, template_id, title, status, cost_usd, cost_tokens, "
               "created_at, finished_at FROM instances")
        params: list = []
        if effective_owner != "*":
            sql += " WHERE owner = ?"
            params.append(effective_owner)
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        rows = store.conn.execute(sql, params).fetchall()
        return [_row_to_instance_summary(r) for r in rows]

    @app.get("/api/instances/{instance_id}")
    def get_instance(instance_id: str, _auth=Depends(verify_auth)):
        row = store.conn.execute(
            "SELECT id, template_id, title, status, cost_usd, cost_tokens, "
            "created_at, finished_at, blocked_reason, params "
            "FROM instances WHERE id = ?",
            (instance_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Instance not found")
        instance = _row_to_instance_detail(row)

        node_rows = store.conn.execute(
            "SELECT id, title, kind, status, tier, gate FROM nodes "
            "WHERE instance_id = ?",
            (instance_id,),
        ).fetchall()
        nodes = [
            {"id": r["id"], "title": r["title"], "kind": r["kind"],
             "status": r["status"], "tier": r["tier"], "gate": r["gate"]}
            for r in node_rows
        ]

        edge_rows = store.conn.execute(
            "SELECT from_node, to_node, type FROM edges WHERE instance_id = ?",
            (instance_id,),
        ).fetchall()
        edges = [
            {"from_node": r["from_node"], "to_node": r["to_node"], "type": r["type"]}
            for r in edge_rows
        ]

        return {"instance": instance, "nodes": nodes, "edges": edges}

    @app.get("/api/graph")
    def get_graph(owner: Optional[str] = None, _auth=Depends(verify_auth)):
        data = store.get_graph()
        effective_owner = owner if owner is not None else getattr(app.state, "default_owner", "me")
        if effective_owner == "*":
            return data
        # Filter graph to only the requested owner's instances/nodes/edges.
        owner_rows = store.conn.execute("SELECT id, owner FROM instances").fetchall()
        allowed_ids = {r["id"] for r in owner_rows if r["owner"] == effective_owner}
        data["instances"] = [i for i in data["instances"] if i["id"] in allowed_ids]
        data["nodes"] = [n for n in data["nodes"] if n["instance_id"] in allowed_ids]
        data["edges"] = [e for e in data["edges"] if e["instance_id"] in allowed_ids]
        return data

    # -----------------------------------------------------------------------
    # P0-B: Gate API endpoints
    # -----------------------------------------------------------------------

    @app.get("/api/gates", response_model=list[GateSummary])
    def get_gates(instance_id: Optional[str] = None, owner: Optional[str] = None,
                  _auth=Depends(verify_auth)):
        """List pending gate approvals."""
        from loom.core.gate import get_pending_gates
        gates = get_pending_gates(store, instance_id)
        return gates

    @app.post("/api/gates/{node_id}/approve", response_model=GateDecisionResult)
    def approve_gate(node_id: str, body: Optional[GateRequestBody] = None, _auth=Depends(verify_auth)):
        """Approve a gated node."""
        from loom.core.gate import GateDecision, record_gate_decision

        node = store.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")

        decision = GateDecision(
            node_id=node_id,
            instance_id=node.instance_id,
            approved=True,
            reason=(body.reason if body else ""),
        )
        ok = record_gate_decision(store, decision)
        if not ok:
            raise HTTPException(status_code=400, detail="Invalid gate transition")

        return GateDecisionResult(approved=True, node_id=node_id)

    @app.post("/api/gates/{node_id}/reject", response_model=GateDecisionResult)
    def reject_gate(node_id: str, body: Optional[GateRequestBody] = None, _auth=Depends(verify_auth)):
        """Reject a gated node."""
        from loom.core.gate import GateDecision, record_gate_decision

        node = store.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")

        decision = GateDecision(
            node_id=node_id,
            instance_id=node.instance_id,
            approved=False,
            reason=(body.reason if body else ""),
        )
        ok = record_gate_decision(store, decision)
        if not ok:
            raise HTTPException(status_code=400, detail="Invalid gate transition")

        return GateDecisionResult(approved=False, node_id=node_id)

    # -----------------------------------------------------------------------
    # P4-C: run trigger + SSE event stream
    # -----------------------------------------------------------------------

    @app.post("/api/run", status_code=201)
    def run_instance(body: RunRequestBody, _auth=Depends(verify_auth)):
        """Instantiate a template into a pending instance (daemon executes it)."""
        from pathlib import Path
        from loom.core.loader import load_template, instantiate

        if not Path(body.template).exists():
            raise HTTPException(status_code=404, detail="Template not found")
        try:
            tpl = load_template(body.template)
            for key, spec in (tpl.params or {}).items():
                if isinstance(spec, dict) and spec.get("required") and key not in body.params:
                    raise ValueError(f"missing required param: {key}")
            instance, nodes, edges = instantiate(tpl, body.params)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        store.create_instance(instance)
        for n in nodes:
            store.create_node(n)
        for e in edges:
            store.create_edge(e)
        return {"instance_id": instance.id, "status": instance.status}

    @app.get("/api/events/stream")
    async def stream_events(_auth=Depends(verify_auth)):
        """Server-Sent Events: new rows in the events table."""
        from starlette.responses import StreamingResponse
        from loom.web.sse import event_stream
        return StreamingResponse(event_stream(store), media_type="text/event-stream")

    # -----------------------------------------------------------------------
    # P7: Web UI backend endpoints
    # -----------------------------------------------------------------------

    @app.get("/api/templates")
    def list_templates(_auth=Depends(verify_auth)):
        """List available templates from the templates directory."""
        templates = []
        tdir = Path(templates_dir)
        if not tdir.is_dir():
            return templates
        for fpath in sorted(tdir.glob("*.yaml")):
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if not isinstance(data, dict):
                    continue
                templates.append({
                    "id": data["id"],
                    "version": data["version"],
                    "trigger": data.get("trigger", []),
                    "provenance": data.get("provenance", "manual"),
                    "nodes": len(data.get("nodes", [])),
                    "file": fpath.name,
                })
            except Exception:
                continue
        return templates

    @app.get("/api/stats")
    def get_stats(_auth=Depends(verify_auth)):
        """Dashboard KPI card data."""
        # Instance stats
        inst_rows = store.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM instances GROUP BY status"
        ).fetchall()
        inst_total = sum(r["cnt"] for r in inst_rows)
        inst_by_status = {r["status"]: r["cnt"] for r in inst_rows}

        # Node stats
        node_rows = store.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM nodes GROUP BY status"
        ).fetchall()
        node_total = sum(r["cnt"] for r in node_rows)
        node_by_status = {r["status"]: r["cnt"] for r in node_rows}

        # Event count
        event_count = store.conn.execute(
            "SELECT COUNT(*) as cnt FROM events"
        ).fetchone()["cnt"]

        # Gate decision count
        gate_count = store.conn.execute(
            "SELECT COUNT(*) as cnt FROM gate_decisions"
        ).fetchone()["cnt"]

        return {
            "instances": {"total": inst_total, "by_status": inst_by_status},
            "nodes": {"total": node_total, "by_status": node_by_status},
            "events": event_count,
            "gate_decisions": gate_count,
        }

    @app.get("/api/health")
    def get_health(_auth=Depends(verify_auth)):
        """Dashboard health badge data."""
        rows = store.conn.execute(
            "SELECT status, cost_usd FROM instances ORDER BY created_at DESC LIMIT 10"
        ).fetchall()

        recent_instances = len(rows)
        succeeded = sum(1 for r in rows if r["status"] == "succeeded")
        failed = sum(1 for r in rows if r["status"] == "failed")
        success_rate = round(succeeded / recent_instances * 100, 1) if recent_instances > 0 else 0.0

        succeeded_costs = [r["cost_usd"] for r in rows if r["status"] == "succeeded"]
        avg_cost_usd = round(
            sum(succeeded_costs) / len(succeeded_costs), 2
        ) if succeeded_costs else 0.0

        pending_gates_row = store.conn.execute(
            "SELECT COUNT(*) as cnt FROM gate_decisions WHERE approved IS NULL OR approved = 0"
        ).fetchone()
        pending_gates = pending_gates_row["cnt"]

        last_event_row = store.conn.execute(
            "SELECT received_at FROM events ORDER BY received_at DESC LIMIT 1"
        ).fetchone()
        last_event = last_event_row["received_at"] if last_event_row else "n/a"

        return {
            "recent_instances": recent_instances,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": success_rate,
            "avg_cost_usd": avg_cost_usd,
            "pending_gates": pending_gates,
            "last_event": last_event,
        }

    @app.get("/api/audit")
    def get_audit(instance_id: Optional[str] = None, type: Optional[str] = None,
                  _auth=Depends(verify_auth)):
        """Audit timeline: gate decisions + state transitions."""
        items = []

        # Gate decisions
        if type is None or type == "gate":
            sql = "SELECT decided_at, node_id, instance_id, approved, approver, reason FROM gate_decisions"
            params: list = []
            if instance_id is not None:
                sql += " WHERE instance_id = ?"
                params.append(instance_id)
            sql += " ORDER BY decided_at DESC"
            gate_rows = store.conn.execute(sql, params).fetchall()
            for r in gate_rows:
                items.append({
                    "timestamp": r["decided_at"],
                    "type": "gate",
                    "node_id": r["node_id"],
                    "instance_id": r["instance_id"],
                    "approved": bool(r["approved"]) if r["approved"] is not None else False,
                    "actor": r["approver"],
                    "reason": r["reason"],
                })

        # State transition events
        if type is None or type == "transition":
            sql = ("SELECT received_at, consumed_by_instance, payload FROM events "
                   "WHERE source = 'state_transition'")
            params = []
            if instance_id is not None:
                sql += " AND consumed_by_instance = ?"
                params.append(instance_id)
            sql += " ORDER BY received_at DESC"
            event_rows = store.conn.execute(sql, params).fetchall()
            for r in event_rows:
                payload = _safe_json_loads(r["payload"])
                items.append({
                    "timestamp": r["received_at"],
                    "type": "transition",
                    "instance_id": r["consumed_by_instance"],
                    "entity_kind": payload.get("entity_kind", ""),
                    "entity_id": payload.get("entity_id", ""),
                    "from": payload.get("from_status", ""),
                    "to": payload.get("to_status", ""),
                })

        items.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        return items

    @app.get("/api/digest")
    def get_digest(_auth=Depends(verify_auth)):
        """Daily digest with budget tracking."""
        today = date.today().isoformat()

        rows = store.conn.execute(
            "SELECT id, template_id, title, status, cost_usd, cost_tokens, "
            "created_at, finished_at FROM instances ORDER BY created_at DESC"
        ).fetchall()

        total_instances = len(rows)
        total_cost_usd = sum(r["cost_usd"] for r in rows)
        total_tokens = sum(r["cost_tokens"] for r in rows)
        succeeded = sum(1 for r in rows if r["status"] == "succeeded")
        failed = sum(1 for r in rows if r["status"] == "failed")
        success_rate = round(succeeded / total_instances * 100, 1) if total_instances > 0 else 0.0

        over_budget = [
            {"id": r["id"], "template_id": r["template_id"], "title": r["title"],
             "status": r["status"], "cost_usd": r["cost_usd"]}
            for r in rows if r["cost_usd"] >= red_line_usd
        ]

        recent = [
            {"id": r["id"], "template_id": r["template_id"], "title": r["title"],
             "status": r["status"], "cost_usd": r["cost_usd"], "created_at": r["created_at"]}
            for r in rows[:10]
        ]

        return {
            "date": today,
            "total_instances": total_instances,
            "total_cost_usd": total_cost_usd,
            "total_tokens": total_tokens,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": success_rate,
            "red_line_usd": red_line_usd,
            "over_budget": over_budget,
            "recent": recent,
        }

    @app.get("/api/cost")
    def get_cost(_auth=Depends(verify_auth)):
        """Cost analysis data."""
        rows = store.conn.execute(
            "SELECT id, template_id, status, cost_usd, cost_tokens FROM instances"
        ).fetchall()

        total_usd = sum(r["cost_usd"] for r in rows)
        total_tokens = sum(r["cost_tokens"] for r in rows)
        instance_count = len(rows)
        avg_usd = round(total_usd / instance_count, 2) if instance_count > 0 else 0.0

        by_template = {}
        for r in rows:
            tid = r["template_id"]
            if tid not in by_template:
                by_template[tid] = {"instances": 0, "total_usd": 0.0, "total_tokens": 0}
            by_template[tid]["instances"] += 1
            by_template[tid]["total_usd"] += r["cost_usd"]
            by_template[tid]["total_tokens"] += r["cost_tokens"]

        by_instance = [
            {"id": r["id"], "template_id": r["template_id"], "status": r["status"],
             "cost_usd": r["cost_usd"], "cost_tokens": r["cost_tokens"]}
            for r in rows
        ]

        return {
            "total_usd": total_usd,
            "total_tokens": total_tokens,
            "avg_usd": avg_usd,
            "instance_count": instance_count,
            "by_template": by_template,
            "by_instance": by_instance,
        }

    return app


def _row_to_instance_summary(row) -> dict:
    return {
        "id": row["id"],
        "template_id": row["template_id"],
        "title": row["title"],
        "status": row["status"],
        "cost_usd": row["cost_usd"],
        "cost_tokens": row["cost_tokens"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def _row_to_instance_detail(row) -> dict:
    return {
        "id": row["id"],
        "template_id": row["template_id"],
        "title": row["title"],
        "status": row["status"],
        "cost_usd": row["cost_usd"],
        "cost_tokens": row["cost_tokens"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
        "blocked_reason": row["blocked_reason"],
        "params": _safe_json_loads(row["params"]),
    }


def _safe_json_loads(value: str) -> dict:
    """Parse JSON string, returning {} on failure."""
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}

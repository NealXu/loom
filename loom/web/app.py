"""FastAPI web backend for Loom — read-only REST API over the graph store."""

import json
import os
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


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


def create_app(store) -> FastAPI:
    """Pure app factory. No uvicorn.run."""
    app = FastAPI(title="Loom", version="0.1.0")

    _INDEX_HTML = Path(__file__).resolve().parent / "static" / "index.html"

    @app.get("/")
    def index():
        return FileResponse(str(_INDEX_HTML), media_type="text/html")

    @app.get("/api/instances")
    def list_instances(limit: Optional[int] = None, offset: int = 0):
        sql = ("SELECT id, template_id, title, status, cost_usd, cost_tokens, "
               "created_at, finished_at FROM instances ORDER BY created_at DESC")
        params: list = []
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        rows = store.conn.execute(sql, params).fetchall()
        return [_row_to_instance_summary(r) for r in rows]

    @app.get("/api/instances/{instance_id}")
    def get_instance(instance_id: str):
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
    def get_graph():
        return store.get_graph()

    # -----------------------------------------------------------------------
    # P0-B: Gate API endpoints
    # -----------------------------------------------------------------------

    @app.get("/api/gates", response_model=list[GateSummary])
    def get_gates(instance_id: Optional[str] = None):
        """List pending gate approvals."""
        from loom.core.gate import get_pending_gates
        gates = get_pending_gates(store, instance_id)
        return gates

    @app.post("/api/gates/{node_id}/approve", response_model=GateDecisionResult)
    def approve_gate(node_id: str, body: Optional[GateRequestBody] = None):
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
    def reject_gate(node_id: str, body: Optional[GateRequestBody] = None):
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
    def run_instance(body: RunRequestBody):
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
    async def stream_events():
        """Server-Sent Events: new rows in the events table."""
        from starlette.responses import StreamingResponse
        from loom.web.sse import event_stream
        return StreamingResponse(event_stream(store), media_type="text/event-stream")

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

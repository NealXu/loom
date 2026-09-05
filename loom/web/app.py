"""FastAPI web backend for Loom — read-only REST API over the graph store."""

import json
from fastapi import FastAPI, HTTPException


def create_app(store) -> FastAPI:
    """Pure app factory. No uvicorn.run."""
    app = FastAPI(title="Loom", version="0.1.0")

    @app.get("/api/instances")
    def list_instances():
        rows = store.conn.execute(
            "SELECT id, template_id, title, status, cost_usd, cost_tokens, "
            "created_at, finished_at FROM instances"
        ).fetchall()
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
        inst_rows = store.conn.execute(
            "SELECT id, title, status, cost_usd FROM instances"
        ).fetchall()
        instances = [
            {"id": r["id"], "title": r["title"], "status": r["status"],
             "cost_usd": r["cost_usd"]}
            for r in inst_rows
        ]

        node_rows = store.conn.execute(
            "SELECT id, instance_id, title, kind, status FROM nodes"
        ).fetchall()
        nodes = [
            {"id": r["id"], "instance_id": r["instance_id"], "title": r["title"],
             "kind": r["kind"], "status": r["status"]}
            for r in node_rows
        ]

        edge_rows = store.conn.execute(
            "SELECT from_node, to_node FROM edges"
        ).fetchall()
        edges = [
            {"from_node": r["from_node"], "to_node": r["to_node"]}
            for r in edge_rows
        ]

        return {"instances": instances, "nodes": nodes, "edges": edges}

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
        "params": json.loads(row["params"]) if row["params"] else {},
    }

import sqlite3
from pathlib import Path
from typing import Optional
from .models import Node, Instance, Edge, Artifact, Event

class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def close(self):
        """Close the underlying connection. Safe to call multiple times."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                instance_id TEXT,
                template_id TEXT,
                owner TEXT DEFAULT 'me',
                title TEXT,
                kind TEXT,
                spec TEXT,
                tier TEXT,
                gate TEXT,
                status TEXT,
                project_path TEXT,
                budget_tokens INTEGER,
                created_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                artifact_paths TEXT,
                session_ref TEXT
            );

            CREATE TABLE IF NOT EXISTS instances (
                id TEXT PRIMARY KEY,
                template_id TEXT,
                owner TEXT DEFAULT 'me',
                title TEXT,
                project_path TEXT,
                status TEXT,
                created_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                cost_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                blocked_reason TEXT,
                params TEXT
            );

            CREATE TABLE IF NOT EXISTS edges (
                instance_id TEXT,
                from_node TEXT,
                to_node TEXT,
                type TEXT DEFAULT 'depends',
                condition TEXT
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                node_id TEXT,
                kind TEXT,
                path TEXT,
                sha256 TEXT,
                vault_link TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                payload TEXT,
                received_at TEXT,
                consumed_by_instance TEXT
            );

            CREATE TABLE IF NOT EXISTS gate_decisions (
                node_id TEXT,
                instance_id TEXT,
                approved INTEGER,
                approver TEXT,
                reason TEXT,
                decided_at TEXT
            );
        """)
        self.conn.commit()

    def create_node(self, node: Node):
        import json
        self.conn.execute(
            """INSERT INTO nodes
            (id, instance_id, template_id, owner, title, kind, spec, tier, gate, status,
             project_path, budget_tokens, created_at, started_at, finished_at, artifact_paths, session_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (node.id, node.instance_id, node.template_id, node.owner, node.title,
             node.kind, node.spec, node.tier, node.gate, node.status, node.project_path,
             node.budget_tokens, node.created_at.isoformat(),
             node.started_at.isoformat() if node.started_at else None,
             node.finished_at.isoformat() if node.finished_at else None,
             json.dumps(node.artifact_paths), node.session_ref)
        )
        self.conn.commit()

    def get_node(self, node_id: str) -> Optional[Node]:
        row = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            return None
        return self._row_to_node(row)

    def create_instance(self, inst: Instance):
        import json
        self.conn.execute(
            """INSERT INTO instances
            (id, template_id, owner, title, project_path, status, created_at, started_at,
             finished_at, cost_tokens, cost_usd, blocked_reason, params)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (inst.id, inst.template_id, inst.owner, inst.title, inst.project_path,
             inst.status, inst.created_at.isoformat(),
             inst.started_at.isoformat() if inst.started_at else None,
             inst.finished_at.isoformat() if inst.finished_at else None,
             inst.cost_tokens, inst.cost_usd, inst.blocked_reason, json.dumps(inst.params))
        )
        self.conn.commit()

    def get_instance(self, inst_id: str) -> Optional[Instance]:
        row = self.conn.execute("SELECT * FROM instances WHERE id = ?", (inst_id,)).fetchone()
        if not row:
            return None
        return self._row_to_instance(row)

    # -----------------------------------------------------------------------
    # P0-A: List and update methods for daemon support
    # -----------------------------------------------------------------------

    def list_instances_by_status(self, status: str) -> list[Instance]:
        """Return all instances with the given status."""
        rows = self.conn.execute(
            "SELECT * FROM instances WHERE status = ?", (status,)
        ).fetchall()
        return [self._row_to_instance(r) for r in rows]

    def list_nodes(self, instance_id: str) -> list[Node]:
        """Return all nodes belonging to the given instance."""
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE instance_id = ?", (instance_id,)
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def list_edges(self, instance_id: str) -> list[Edge]:
        """Return all edges belonging to the given instance."""
        rows = self.conn.execute(
            "SELECT * FROM edges WHERE instance_id = ?", (instance_id,)
        ).fetchall()
        return [
            Edge(
                instance_id=r["instance_id"],
                from_node=r["from_node"],
                to_node=r["to_node"],
                type=r["type"],
                condition=r["condition"] or "",
            )
            for r in rows
        ]

    def update_node_status(self, node_id: str, status: str, **fields) -> None:
        """Update node status and optional fields (started_at, finished_at, etc.)."""
        set_clauses = ["status = ?"]
        values: list = [status]
        for key, val in fields.items():
            set_clauses.append(f"{key} = ?")
            values.append(val)
        values.append(node_id)
        self.conn.execute(
            f"UPDATE nodes SET {', '.join(set_clauses)} WHERE id = ?", values
        )
        self.conn.commit()

    def update_instance_status(self, instance_id: str, status: str, **fields) -> None:
        """Update instance status and optional fields (started_at, finished_at, etc.)."""
        set_clauses = ["status = ?"]
        values: list = [status]
        for key, val in fields.items():
            set_clauses.append(f"{key} = ?")
            values.append(val)
        values.append(instance_id)
        self.conn.execute(
            f"UPDATE instances SET {', '.join(set_clauses)} WHERE id = ?", values
        )
        self.conn.commit()

    # -----------------------------------------------------------------------
    # Row-to-dataclass helpers
    # -----------------------------------------------------------------------

    def _row_to_node(self, row) -> Node:
        import json
        from datetime import datetime
        return Node(
            id=row["id"],
            instance_id=row["instance_id"],
            template_id=row["template_id"],
            owner=row["owner"],
            title=row["title"],
            kind=row["kind"],
            spec=row["spec"],
            tier=row["tier"],
            gate=row["gate"],
            status=row["status"],
            project_path=row["project_path"],
            budget_tokens=row["budget_tokens"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            artifact_paths=json.loads(row["artifact_paths"]) if row["artifact_paths"] else [],
            session_ref=row["session_ref"],
        )

    def _row_to_instance(self, row) -> Instance:
        import json
        from datetime import datetime
        return Instance(
            id=row["id"],
            template_id=row["template_id"],
            owner=row["owner"],
            title=row["title"],
            project_path=row["project_path"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            cost_tokens=row["cost_tokens"],
            cost_usd=row["cost_usd"],
            blocked_reason=row["blocked_reason"],
            params=json.loads(row["params"]) if row["params"] else {},
        )

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
        import json
        from datetime import datetime
        row = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            return None
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
        import json
        from datetime import datetime
        row = self.conn.execute("SELECT * FROM instances WHERE id = ?", (inst_id,)).fetchone()
        if not row:
            return None
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

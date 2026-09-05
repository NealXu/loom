from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass
class Node:
    id: str
    instance_id: str
    template_id: str
    owner: str = "me"
    title: str = ""
    kind: str = "analysis"  # analysis | coding | review | deploy | report | gate
    spec: str = ""
    tier: str = "tooling"  # critical | heavy | tooling | bulk
    gate: str = "none"  # none | approve
    status: str = "pending"  # see state machine
    project_path: str = ""
    budget_tokens: int = 50000
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    artifact_paths: list[str] = field(default_factory=list)
    session_ref: str = ""

@dataclass
class Instance:
    id: str
    template_id: str
    owner: str = "me"
    title: str = ""
    project_path: str = ""
    status: str = "pending"  # pending | running | waiting_gate | succeeded | failed | blocked | cancelled
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    cost_tokens: int = 0
    cost_usd: float = 0.0
    blocked_reason: str = ""
    params: dict = field(default_factory=dict)

@dataclass
class Edge:
    instance_id: str
    from_node: str
    to_node: str
    type: str = "depends"
    condition: str = ""

@dataclass
class Artifact:
    node_id: str
    kind: str  # report | summary | md | log
    path: str
    sha256: str = ""
    vault_link: str = ""

@dataclass
class Event:
    source: str  # hook | cron | cli | inbox | state_transition
    payload: dict = field(default_factory=dict)
    received_at: datetime = field(default_factory=datetime.now)
    consumed_by_instance: str = ""

@dataclass
class Template:
    id: str
    version: int = 1
    trigger: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    nodes: list[dict] = field(default_factory=list)
    provenance: str = "manual"  # manual | discovered

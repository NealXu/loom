"""RunnerAdapter interface and adapter dataclasses."""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import abc


@dataclass
class Handle:
    """Handle to a running session/subprocess."""
    session_ref: str
    pid: Optional[int] = None
    started_at: datetime = field(default_factory=datetime.now)


@dataclass
class Event:
    """An adapter-emitted event (distinct from core.models.Event)."""
    kind: str  # stdout | stderr | completion | error
    message: str
    at: datetime = field(default_factory=datetime.now)


@dataclass
class Result:
    """Result returned by a RunnerAdapter after executing a node."""
    success: bool = False
    output: str = ""
    artifacts: list[str] = field(default_factory=list)
    exit_code: int = 0
    error: str = ""
    cost_tokens: int = 0
    cost_usd: float = 0.0


class RunnerAdapter(abc.ABC):
    """Abstract base class for all runner adapters."""
    name: str = "base"

    @abc.abstractmethod
    async def run(self, node) -> Result:
        """Execute the given node and return a Result."""
        ...

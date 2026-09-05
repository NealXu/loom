"""FakeRunner adapter for testing."""
from loom.adapters.base import RunnerAdapter, Result


class FakeRunner(RunnerAdapter):
    """A fake runner that echoes the node spec. Used for testing."""
    name = "fake"

    async def run(self, node) -> Result:
        return Result(success=True, output=f"echo: {node.spec}")

"""Tests for RunnerAdapter interface, FakeRunner, and CCAdapter."""
import asyncio
import sys
import pytest

from loom.core.models import Node
from loom.adapters.base import RunnerAdapter, Handle, Event, Result
from loom.adapters.fake import FakeRunner


def test_fake_runner_returns_success():
    """FakeRunner.run on a Node returns Result with success=True and output containing the node's spec."""
    node = Node(id="n1", instance_id="inst1", template_id="t1", spec="hello world")
    runner = FakeRunner()
    result = asyncio.run(runner.run(node))
    assert result.success is True
    assert "hello world" in result.output


def test_result_defaults():
    """Result() defaults: success=False, output="", exit_code=0, cost_tokens=0, cost_usd=0.0."""
    r = Result()
    assert r.success is False
    assert r.output == ""
    assert r.exit_code == 0
    assert r.cost_tokens == 0
    assert r.cost_usd == 0.0


def test_runner_adapter_is_abstract():
    """RunnerAdapter cannot be instantiated (raises TypeError)."""
    with pytest.raises(TypeError):
        RunnerAdapter()


# ---------------------------------------------------------------------------
# CCAdapter tests
# ---------------------------------------------------------------------------

# Stubs: Python one-liners invoked via [sys.executable, -c, code, ...]
_CC_ECHO_CODE = "import sys; i=sys.argv.index('-p'); print(sys.argv[i+1])"
_CC_FAIL_CODE = "import sys; sys.exit(42)"


class TestCCAdapter:
    """Tests for the Claude Code runner adapter."""

    def test_cc_adapter_returns_success_output(self, tmp_path):
        """CCAdapter with echo stub returns success=True and node.spec in output."""
        from loom.adapters.cc import CCAdapter

        adapter = CCAdapter(binary=[sys.executable, "-c", _CC_ECHO_CODE], cwd=str(tmp_path))
        node = Node(id="n1", instance_id="i1", template_id="t1", spec="hello cc", project_path=str(tmp_path))

        result = asyncio.run(adapter.run(node))

        assert result.success is True
        assert "hello cc" in result.output
        assert result.exit_code == 0

    def test_cc_adapter_maps_exit_code(self, tmp_path):
        """CCAdapter with failing stub returns success=False and correct exit_code."""
        from loom.adapters.cc import CCAdapter

        adapter = CCAdapter(binary=[sys.executable, "-c", _CC_FAIL_CODE], cwd=str(tmp_path))
        node = Node(id="n2", instance_id="i1", template_id="t1", spec="will fail", project_path=str(tmp_path))

        result = asyncio.run(adapter.run(node))

        assert result.success is False
        assert result.exit_code == 42

    def test_cc_adapter_defaults_name(self):
        """CCAdapter().name == 'cc'."""
        from loom.adapters.cc import CCAdapter

        adapter = CCAdapter()
        assert adapter.name == "cc"


# ---------------------------------------------------------------------------
# PIAdapter tests
# ---------------------------------------------------------------------------

# Stubs: Python one-liners invoked via [sys.executable, -c, code, ...]
_PI_ECHO_CODE = "import sys; i=sys.argv.index('-p'); print(sys.argv[i+1])"
_PI_FAIL_CODE = "import sys; sys.exit(42)"


class TestPIAdapter:
    """Tests for the Pi runner adapter."""

    def test_pi_adapter_returns_success_output(self, tmp_path):
        """PIAdapter with echo stub returns success=True and node.spec in output."""
        from loom.adapters.pi import PIAdapter

        adapter = PIAdapter(binary=[sys.executable, "-c", _PI_ECHO_CODE], cwd=str(tmp_path))
        node = Node(id="n1", instance_id="i1", template_id="t1", spec="hello pi", project_path=str(tmp_path))

        result = asyncio.run(adapter.run(node))

        assert result.success is True
        assert "hello pi" in result.output
        assert result.exit_code == 0

    def test_pi_adapter_maps_exit_code(self, tmp_path):
        """PIAdapter with failing stub returns success=False and correct exit_code."""
        from loom.adapters.pi import PIAdapter

        adapter = PIAdapter(binary=[sys.executable, "-c", _PI_FAIL_CODE], cwd=str(tmp_path))
        node = Node(id="n2", instance_id="i1", template_id="t1", spec="will fail", project_path=str(tmp_path))

        result = asyncio.run(adapter.run(node))

        assert result.success is False
        assert result.exit_code == 42

    def test_pi_adapter_defaults_name(self):
        """PIAdapter().name == 'pi'."""
        from loom.adapters.pi import PIAdapter

        adapter = PIAdapter()
        assert adapter.name == "pi"


# ---------------------------------------------------------------------------
# CodexAdapter tests
# ---------------------------------------------------------------------------

# Stubs: Python one-liners invoked via [sys.executable, -c, code, ...]
_CODEX_ECHO_CODE = "import sys; i=sys.argv.index('-p'); print(sys.argv[i+1])"
_CODEX_FAIL_CODE = "import sys; sys.exit(42)"


class TestCodexAdapter:
    """Tests for the Codex runner adapter."""

    def test_codex_adapter_returns_success_output(self, tmp_path):
        """CodexAdapter with echo stub returns success=True and node.spec in output."""
        from loom.adapters.codex import CodexAdapter

        adapter = CodexAdapter(binary=[sys.executable, "-c", _CODEX_ECHO_CODE], cwd=str(tmp_path))
        node = Node(id="n1", instance_id="i1", template_id="t1", spec="hello codex", project_path=str(tmp_path))

        result = asyncio.run(adapter.run(node))

        assert result.success is True
        assert "hello codex" in result.output
        assert result.exit_code == 0

    def test_codex_adapter_maps_exit_code(self, tmp_path):
        """CodexAdapter with failing stub returns success=False and correct exit_code."""
        from loom.adapters.codex import CodexAdapter

        adapter = CodexAdapter(binary=[sys.executable, "-c", _CODEX_FAIL_CODE], cwd=str(tmp_path))
        node = Node(id="n2", instance_id="i1", template_id="t1", spec="will fail", project_path=str(tmp_path))

        result = asyncio.run(adapter.run(node))

        assert result.success is False
        assert result.exit_code == 42

    def test_codex_adapter_defaults_name(self):
        """CodexAdapter().name == 'codex'."""
        from loom.adapters.codex import CodexAdapter

        adapter = CodexAdapter()
        assert adapter.name == "codex"

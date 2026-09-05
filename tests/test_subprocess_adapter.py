"""Tests for SubprocessAdapter base class (P1-D: dedup + timeout)."""
import asyncio
import sys
import time
import pytest

from loom.core.models import Node
from loom.adapters.subprocess_base import SubprocessAdapter
from loom.adapters.base import Result


# Stub codes injected via [sys.executable, -c, code, ...]
_ECHO_CODE = "import sys; i=sys.argv.index('-p'); print(sys.argv[i+1])"
_SLOW_CODE = "import time; time.sleep(30)"
_FAIL_CODE = "import sys; sys.exit(42)"


class _TestAdapter(SubprocessAdapter):
    name = "testsub"
    default_binary = "testsub"
    print_flag = "-p"


def test_subprocess_adapter_success():
    """Base class runs the binary and captures stdout."""
    adapter = _TestAdapter(binary=[sys.executable, "-c", _ECHO_CODE])
    node = Node(id="n1", instance_id="i1", template_id="t1", spec="hello base")
    result = asyncio.run(adapter.run(node))
    assert result.success is True
    assert "hello base" in result.output
    assert result.exit_code == 0


def test_subprocess_adapter_fail():
    """Non-zero exit code returns success=False with exit_code preserved."""
    adapter = _TestAdapter(binary=[sys.executable, "-c", _FAIL_CODE])
    node = Node(id="n1", instance_id="i1", template_id="t1", spec="x")
    result = asyncio.run(adapter.run(node))
    assert result.success is False
    assert result.exit_code == 42


def test_subprocess_adapter_timeout_kills_process():
    """A hanging subprocess is killed after timeout and returns failed Result."""
    adapter = _TestAdapter(binary=[sys.executable, "-c", _SLOW_CODE], timeout=1.0)
    node = Node(id="n1", instance_id="i1", template_id="t1", spec="hang")

    start = time.monotonic()
    result = asyncio.run(adapter.run(node))
    elapsed = time.monotonic() - start

    assert result.success is False
    assert "timeout" in result.error.lower()
    # Must return promptly after the timeout, not wait for the 30s sleep
    assert elapsed < 10


def test_subprocess_adapter_default_timeout_none_waits():
    """timeout=None means no time limit (backward compatible)."""
    adapter = _TestAdapter(binary=[sys.executable, "-c", _ECHO_CODE], timeout=None)
    node = Node(id="n1", instance_id="i1", template_id="t1", spec="no timeout")
    result = asyncio.run(adapter.run(node))
    assert result.success is True


def test_cc_pi_codex_dsh_share_base():
    """All four real adapters subclass SubprocessAdapter and keep their name/binary."""
    from loom.adapters.cc import CCAdapter
    from loom.adapters.pi import PIAdapter
    from loom.adapters.codex import CodexAdapter
    from loom.adapters.dsh import DshAdapter

    for cls, name, binary in [
        (CCAdapter, "cc", "claude"),
        (PIAdapter, "pi", "pi"),
        (CodexAdapter, "codex", "codex"),
        (DshAdapter, "dsh", "dsh"),
    ]:
        assert issubclass(cls, SubprocessAdapter), cls
        inst = cls()
        assert inst.name == name
        assert inst._binary == binary
        assert inst._print_flag == "-p"

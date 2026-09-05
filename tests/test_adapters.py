"""Tests for RunnerAdapter interface and FakeRunner."""
import asyncio
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

"""Tests for cost extraction from agent CLI JSON output (P3-J)."""
import asyncio
import json
import sys
from loom.core.models import Node
from loom.adapters.cost_parsing import extract_cost
from loom.adapters.cc import CCAdapter


def test_extract_whole_stdout_json():
    out = json.dumps({
        "result": "done",
        "usage": {"input_tokens": 120, "output_tokens": 30},
        "total_cost_usd": 0.0045,
    })
    tokens, usd = extract_cost(out)
    assert tokens == 150
    assert usd == 0.0045


def test_extract_json_from_trailing_line():
    out = "some log line\n" + json.dumps({"usage": {"total_tokens": 500}, "cost_usd": 0.10})
    tokens, usd = extract_cost(out)
    assert tokens == 500
    assert usd == 0.10


def test_extract_plain_text_returns_zero():
    assert extract_cost("no json here") == (0, 0.0)


def test_extract_partial_fields():
    out = json.dumps({"usage": {"input_tokens": 7}})  # no cost
    tokens, usd = extract_cost(out)
    assert tokens == 7
    assert usd == 0.0


def test_cc_adapter_populates_cost_from_json_output(tmp_path):
    """CCAdapter with a stub binary emitting claude-style JSON gets cost fields."""
    code = (
        "import json,sys; "
        "print(json.dumps({'result':'ok','usage':{'input_tokens':10,'output_tokens':5},"
        "'total_cost_usd':0.02}))"
    )
    adapter = CCAdapter(binary=[sys.executable, "-c", code], cwd=str(tmp_path))
    node = Node(id="n1", instance_id="i1", template_id="t", spec="hi",
                project_path=str(tmp_path))
    result = asyncio.run(adapter.run(node))
    assert result.success is True
    assert result.cost_tokens == 15
    assert result.cost_usd == 0.02

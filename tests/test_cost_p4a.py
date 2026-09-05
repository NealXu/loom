"""P4-A: codex/pi cost adaptation — command shapes + JSONL extraction."""
import asyncio
import json
import sys
from loom.core.models import Node
from loom.adapters.cost_parsing import extract_cost
from loom.adapters.codex import CodexAdapter
from loom.adapters.pi import PIAdapter


def test_extract_jsonl_picks_total_usage():
    """codex-style JSONL: token_count events report cumulative totals."""
    lines = [
        json.dumps({"type": "session_start"}),
        json.dumps({"type": "token_count",
                    "payload": {"total_token_usage": {"input_tokens": 100, "output_tokens": 40},
                                "total_cost_usd": 0.003}}),
        json.dumps({"type": "token_count",
                    "payload": {"total_token_usage": {"input_tokens": 260, "output_tokens": 90},
                                "total_cost_usd": 0.008}}),
    ]
    tokens, usd = extract_cost("\n".join(lines))
    # Later event has larger totals -> wins (cumulative reporting)
    assert tokens == 350
    assert usd == 0.008


def test_extract_pi_style_single_json():
    out = json.dumps({"role": "assistant", "content": "done",
                      "usage": {"input_tokens": 12, "output_tokens": 5},
                      "cost_usd": 0.0007})
    assert extract_cost(out) == (17, 0.0007)


def test_codex_command_shape():
    """CodexAdapter builds `codex exec --json <spec>` (not the generic -p form)."""
    adapter = CodexAdapter()
    cmd = adapter.build_command("do the thing")
    assert cmd == ["codex", "exec", "--json", "do the thing"]


def test_codex_injected_binary_appends_prompt():
    code = "import sys; print(json.dumps({'total_cost_usd': 0.01, 'usage': {'input_tokens': 3, 'output_tokens': 2}})) if False else None"
    # Echo-style stub that ignores flags and prints spec; verifies prompt position
    code = "import sys; print(' '.join(sys.argv[1:]))"
    adapter = CodexAdapter(binary=[sys.executable, "-c", code])
    node = Node(id="n1", instance_id="i1", template_id="t", spec="hello codex")
    result = asyncio.run(adapter.run(node))
    assert result.success
    # prompt arrives last, after the exec/--json flags
    out = result.output.strip()
    assert out.endswith("hello codex")
    assert "exec" in out and "--json" in out


def test_pi_command_shape():
    adapter = PIAdapter()
    cmd = adapter.build_command("spec text")
    assert cmd == ["pi", "--mode", "json", "-p", "spec text"]
    assert adapter.parse_cost is True

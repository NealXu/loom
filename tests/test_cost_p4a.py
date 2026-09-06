"""P4-A: codex/pi cost adaptation — command shapes + JSONL extraction.

Tests include both synthetic schemas (original P4-A scope) and REAL schemas
captured live from codex-cli v0.153.2, pi v0.84.4, and claude v2.1.247
on 2026-09-06.
"""
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


# ---------------------------------------------------------------------------
# Real-schema validation (captured 2026-09-06 from codex-cli v0.153.2 / pi v0.84.4)
# ---------------------------------------------------------------------------

# Real codex `exec --json` output for spec "reply with the single word 'hello'"
_REAL_CODEX_STDOUT = "\n".join([
    '{"type":"thread.started","thread_id":"01a075c8-7b06-75f0-9cca-02028ef8ad52"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hello"}}',
    '{"type":"turn.completed","usage":{"input_tokens":7174,"cached_input_tokens":0,'
    '"cache_write_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":0}}',
])

# Real pi `--mode json` output (abridged: session + message_end with final usage)
_REAL_PI_STDOUT = "\n".join([
    json.dumps({"type": "session", "version": 3,
                "id": "01a075c8-bbd6-7f8d-8334-87ca809c620d"}),
    json.dumps({"type": "agent_start"}),
    json.dumps({"type": "turn_start"}),
    json.dumps({"type": "message_start", "message": {"role": "user",
                "content": [{"type": "text", "text": "reply hello"}]}}),
    json.dumps({"type": "message_end", "message": {
        "role": "assistant",
        "content": [{"type": "text", "text": "hello"}],
        "api": "anthropic-messages", "provider": "dashscope",
        "model": "qwen3.7-plus",
        "usage": {
            "input": 6, "output": 18,
            "cacheRead": 0, "cacheWrite": 25816,
            "totalTokens": 25840,
            "cost": {"input": 0.001, "output": 0.002,
                     "cacheRead": 0, "cacheWrite": 0, "total": 0.003},
        },
        "stopReason": "stop",
    }}),
    json.dumps({"type": "turn_end"}),
    json.dumps({"type": "agent_end", "messages": [], "willRetry": False}),
    json.dumps({"type": "agent_settled"}),
])


def test_real_codex_extracts_tokens_no_cost():
    """Real codex output reports input_tokens/output_tokens, no cost field."""
    tokens, usd = extract_cost(_REAL_CODEX_STDOUT)
    assert tokens == 7174 + 2  # input + output from turn.completed
    assert usd == 0.0          # codex CLI does not emit cost


def test_real_pi_extracts_tokens_and_cost():
    """Real pi output uses camelCase totalTokens and nested cost.total."""
    tokens, usd = extract_cost(_REAL_PI_STDOUT)
    assert tokens == 25840   # totalTokens (camelCase) from message.usage
    assert usd == 0.003      # cost.total (nested dict)


def test_real_pi_agent_end_also_extracts():
    """pi agent_end carries the same usage block; should also parse."""
    agent_end = json.dumps({
        "type": "agent_end",
        "messages": [{
            "role": "assistant",
            "usage": {
                "input": 6, "output": 18,
                "totalTokens": 25840,
                "cost": {"input": 0.001, "output": 0.002,
                         "cacheRead": 0, "cacheWrite": 0, "total": 0.003},
            },
        }],
    })
    tokens, usd = extract_cost(agent_end)
    assert tokens == 25840
    assert usd == 0.003


def test_real_pi_cost_dict_sum_fallback():
    """When cost dict has no 'total' key, fall back to input+output sum."""
    out = json.dumps({
        "type": "message_end",
        "message": {"role": "assistant", "usage": {
            "input": 10, "output": 5, "totalTokens": 15,
            "cost": {"input": 0.01, "output": 0.02},  # no 'total'
        }},
    })
    tokens, usd = extract_cost(out)
    assert tokens == 15
    assert usd == 0.03  # 0.01 + 0.02


# ---------------------------------------------------------------------------
# Real claude schema (captured 2026-09-06 from claude-code v2.1.247)
# ---------------------------------------------------------------------------

# Real claude `-p <spec> --output-format json` output for "reply with 'hello'"
# Includes the non-JSON system diagnostic line before the actual JSON result.
_REAL_CLAUDE_STDOUT = "\n".join([
    '[claude-code:unrecognized_model] {"model":"dashscope/qwen3.7-plus[1m]"}',
    json.dumps({
        "is_error": False,
        "total_cost_usd": 0.30811,
        "usage": {
            "input_tokens": 13797,
            "cache_creation_input_tokens": 38188,
            "cache_read_input_tokens": 0,
            "output_tokens": 18,
        },
        "modelUsage": {
            "dashscope/qwen3.7-plus[1m]": {
                "inputTokens": 13797,
                "outputTokens": 18,
                "costUSD": 0.30811,
            }
        },
        "result": "hello",
        "type": "result",
    }),
])


def test_real_claude_extracts_tokens_and_cost():
    """Real claude output: top-level total_cost_usd + usage.input/output_tokens.

    The non-JSON system diagnostic line is ignored by extract_cost (only lines
    starting with '{' are parsed as JSON).
    """
    tokens, usd = extract_cost(_REAL_CLAUDE_STDOUT)
    assert tokens == 13797 + 18  # input_tokens + output_tokens
    assert usd == 0.30811        # total_cost_usd (top-level float)

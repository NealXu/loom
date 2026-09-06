# Loom

A two-layer graph system for automating daily work. Loom combines a knowledge graph (SQLite) with DAG-based task orchestration to schedule, execute, and audit multi-step workflows driven by AI agent CLIs.

## Key Features

- **DAG scheduling** with topological ordering and dependency resolution
- **Persistent daemon** (`loom serve`) with async tick loop; survives restarts with crash recovery and persisted schedule state
- **Event-driven dispatch**: triggers (hooks/inbox/cron) → template matching → automatic instance creation
- **Tier-based runner routing** with fallback chains and binary-missing degradation (`--runner auto`)
- **Cost tracking**: real token/cost parsed from JSON/JSONL agent output (claude, codex, pi); hard budget enforcement at `node.budget_tokens`
- **Interactive gate approvals** for high-risk operations via CLI (`loom gate approve/reject`) and Web panel
- **Timeout protection**: hung agent CLI processes are killed after configurable timeout
- **Vault artifact persistence**: successful node outputs written to Vault markdown + registered as Artifacts
- **Template-driven workflows** defined in YAML with parameterized specs (5 built-in + `loom evolve` LLM discovery)
- **Multiple triggers**: HTTP hooks, cron scheduler, inbox file watchers, CLI, and `POST /api/run`
- **Web UI** with FastAPI + SSE real-time event stream, pagination, and gate approval panel
- **Full audit trail** with event logging for every state transition

## Quick Start

### Prerequisites

- Python 3.12+
- Git
- Agent CLIs: `claude`, `codex`, `pi`, `dsh` (any or all, optional)

### Installation

```bash
git clone <repository-url>
cd loom
pip install -e ".[dev]"
```

### Basic Usage

**Start the daemon** (recommended — enables triggers, gates, SSE, scheduled jobs):

```bash
loom serve --runner auto --config loom.toml --templates loom/templates
# Daemon runs on port 8000; Web UI at http://127.0.0.1:8000
# Triggers write events → daemon dispatches → instances execute → gates pause → approve via CLI/Web
```

**Run a template synchronously**:

```bash
# Run repo-analysis with Claude Code
loom run repo-analysis --runner cc --params '{"project_path": "."}'

# Run feature-loop in background (daemon executes)
loom run feature-loop --runner codex --params '{"branch": "feat/x"}' --bg

# List instances, check status, view history
loom list
loom status <instance_id>
loom history --limit 10
```

**Gate approval** (when a node with `gate: approve` pauses):

```bash
loom gate list                           # see pending gates
loom gate approve <node_id> --reason LGTM
loom gate reject <node_id> --reason "Not ready"
```

**Morning digest & evolution**:

```bash
loom digest                             # rollup with cost red line from loom.toml
loom evolve --runner cc --out loom/templates/discovered
```

## Architecture Overview

### Two-Layer Graph

Loom operates on two complementary graph layers:

1. **Knowledge graph** (SQLite, WAL mode) stores instances, nodes, edges, events, and artifacts as a single source of truth with concurrent read support.
2. **DAG orchestration** layer uses Kahn's algorithm for topological ordering, scheduling nodes whose dependencies are satisfied.

### Runners

Four adapter types execute node specs via subprocess with timeout and cost parsing:

| Runner | Command | Cost Parsing |
|--------|---------|--------------|
| `cc` | `claude -p <spec> --output-format json` | JSON, top-level `total_cost_usd` + `usage.{input,output}_tokens` ✅ verified |
| `pi` | `pi --mode json -p <spec>` | JSONL, `totalTokens` (camelCase) + nested `cost.total` ✅ verified |
| `codex` | `codex exec --json <spec>` | JSONL, `usage.{input,output}_tokens`, no cost ✅ verified |
| `dsh` | `dsh -p <spec>` | Not actively used; adapter retained for future use |

A `fake` runner is also available for testing.

### State Machine

Nodes transition through states:

```
pending -> running -> succeeded
                   -> waiting_gate -> succeeded (after gate approval)
                                   -> failed (after gate rejection)
                   -> failed
                   -> blocked
                   -> cancelled
```

Instances aggregate node states. All transitions are recorded in the events table for full auditability.

### Gate Approval Flow

Nodes with `gate: approve` pause execution until a human approves or rejects via CLI or Web:

```bash
# See pending gates
loom gate list

# Approve with reason
loom gate approve <node_id> --reason "LGTM"

# Reject with reason
loom gate reject <node_id> --reason "Not ready"
```

High-risk node kinds (`deploy`, `review`) automatically require gates. When a gate pauses an instance, the daemon stops advancing it until approval. In sync mode (`loom run` without `--bg`), the CLI prints a message and exits; run `loom serve` or `loom gate approve` to resume.

### Tier-Based Routing

Nodes are assigned tiers that influence scheduling priority:

- **critical** -- highest priority, fails fast
- **heavy** -- resource-intensive operations
- **tooling** -- supporting tool invocations
- **bulk** -- batch/low-priority work

## CLI Commands

| Command | Description |
|---------|-------------|
| `loom run <template>` | Instantiate a template and execute the DAG (sync or `--bg` daemon) |
| `loom list` | List all instances |
| `loom status <id>` | Show instance detail (nodes, status, cost) |
| `loom stats` | System-wide statistics (instances, nodes, events, gates) |
| `loom health` | System health summary (success rate, avg cost, pending gates) |
| `loom cost [id]` | Cost breakdown (aggregate, per-instance, or per-template) |
| `loom history` | Instance execution history |
| `loom audit [id]` | Audit trail (gate decisions and state transitions) |
| `loom serve` | Start daemon + web server (triggers, gates, SSE, scheduled jobs) |
| `loom gate list/approve/reject` | Interactive gate approval commands |
| `loom digest` | Render morning digest (instance rollup + cost red line) |
| `loom evolve` | Discover recurring patterns and write candidate templates (LLM channel) |

### Run Options

```bash
loom run <template> [OPTIONS]

  --db PATH         Path to SQLite database
  --params JSON     Template parameters as JSON string
  --runner NAME     Runner adapter: fake, cc, pi, codex, dsh
```

## Web UI

Start the daemon with web server:

```bash
loom serve --runner auto --config loom.toml
# Web UI at http://127.0.0.1:8000
```

The Web UI provides:

**REST API** (read + write):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/instances` | GET | List instances with pagination (`?limit=&offset=`) |
| `/api/instances/{id}` | GET | Instance detail with nodes and edges |
| `/api/graph` | GET | Full graph (instances, nodes, edges) |
| `/api/gates` | GET | List pending gate approvals |
| `/api/gates/{node_id}/approve` | POST | Approve a gated node |
| `/api/gates/{node_id}/reject` | POST | Reject a gated node |
| `/api/run` | POST | Trigger instance creation (daemon executes) |
| `/api/events/stream` | GET | SSE real-time event stream |

**Frontend** at `loom/web/static/index.html`:
- Instance list with cost breakdown
- Pending gates panel with approve/reject buttons
- Real-time event stream (SSE)
- Graph visualization (instances, nodes, edges)

## Templates

Templates are YAML files that define reusable workflows. Each template specifies triggers, parameters, and a DAG of nodes.

### Built-in Templates

| Template | Triggers | Description |
|----------|----------|-------------|
| `handoff-refresh` | inbox, cron | Scans a project and rewrites `handoff.md` |
| `feature-loop` | inbox, cli | Implements a feature on a branch with testing and review (gate on merge) |
| `repo-analysis` | inbox, cron | Comprehensive repository structure and code analysis |
| `content-pipeline` | inbox, cli | Research → draft → polish → publish (gate on publish) |
| `ops-deploy` | cli | Preflight → build → deploy (gate) → verify |

Run `loom evolve --runner cc` to discover additional templates from successful instance clusters.

### Template Structure

```yaml
id: my-template
version: 1
trigger: [inbox, cron]
provenance: manual
params:
  target: {type: string, required: true}
nodes:
  - id: step-one
    kind: analysis
    tier: heavy
    spec: "Analyze {{target}} and produce a summary."
    depends_on: []
  - id: step-two
    kind: coding
    tier: tooling
    gate: approve
    spec: "Apply changes based on the analysis of {{target}}."
    depends_on: [step-one]
```

### Node Kinds

- `analysis` -- scanning, parsing, evaluation
- `coding` -- file generation, code modification
- `review` -- quality checks, audits
- `deploy` -- publishing, committing
- `report` -- output generation

### Creating Custom Templates

1. Create a YAML file in `loom/templates/` following the structure above.
2. Reference parameters with `{{param_name}}` in node specs.
3. Run with `loom run <template-id> --params '{"param_name": "value"}'`.

## Development

### Running Tests

```bash
# Run all 206 tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_scheduler.py
```

### Project Structure

```
loom/
  cli.py              # Click-based CLI entry point (13 commands)
  daemon.py           # Persistent daemon with async tick loop
  core/
    models.py         # Dataclasses: Node, Instance, Edge, Artifact, Event, Template
    store.py          # SQLite CRUD operations (WAL mode)
    state.py          # State machines for nodes and instances
    scheduler.py      # DAG scheduler (Kahn's algorithm)
    loader.py         # YAML template parser and instantiator
    gate.py           # Gate decision flow
    engine.py         # step_instance orchestration + budget check + artifact writing
    router.py         # Tier-based runner routing with fallback chains
    dispatcher.py     # Event → template matching and instance creation
    schedule.py       # Cron scheduler with persistent state
  adapters/
    base.py           # Abstract RunnerAdapter interface
    subprocess_base.py # SubprocessAdapter with timeout + build_command hook
    cost_parsing.py   # JSON/JSONL cost extraction (tokens + USD)
    fake.py           # FakeRunner for testing
    cc.py             # Claude Code adapter (parse_cost enabled)
    pi.py             # Pi CLI adapter (parse_cost enabled, --mode json)
    codex.py          # Codex adapter (codex exec --json, parse_cost enabled)
    dsh.py            # DSH adapter (no stable JSON surface)
  triggers/
    hooks.py          # HTTP webhook server for CC hook events
    cron.py           # Morning digest generator
    inbox.py          # File watcher for inbox directory
  evolver/
    evolve.py         # LLM-driven template discovery (evolve + loom evolve command)
  web/
    app.py            # FastAPI REST API (instances, gates, run, SSE stream)
    sse.py            # Server-Sent Events event stream
    static/
      index.html      # Web UI frontend (gates panel, SSE, graph viz)
  templates/
    handoff-refresh.yaml
    feature-loop.yaml
    repo-analysis.yaml
    content-pipeline.yaml
    ops-deploy.yaml
tests/
  30 test files       # 206 tests total
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `click>=8.1` | CLI framework |
| `pyyaml>=6.0` | YAML template parsing |
| `fastapi>=0.115` | Web API |
| `uvicorn>=0.32` | ASGI server |
| `aiohttp>=3.10` | Async HTTP for webhooks |
| `watchdog>=5.0` | File system monitoring |
| `pytest>=8.0` | Testing framework |
| `pytest-asyncio>=0.24` | Async test support |
| `httpx>=0.27` | HTTP client for testing |

Dev dependencies installed via `pip install -e ".[dev]"`.

## License

See [LICENSE](LICENSE) for details.

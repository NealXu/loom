# Loom

A two-layer graph system for automating daily work. Loom combines a knowledge graph (SQLite) with DAG-based task orchestration to schedule, execute, and audit multi-step workflows driven by AI agent CLIs.

## Key Features

- **DAG scheduling** with topological ordering and dependency resolution
- **Multiple runner adapters** for different AI agent CLIs (Claude Code, Pi, Codex, DSH)
- **Gate approvals** requiring human sign-off for high-risk operations (merge, deploy, publish, delete)
- **Template-driven workflows** defined in YAML with parameterized specs
- **Multiple triggers** including HTTP hooks, cron schedules, inbox file watchers, and CLI
- **Web UI** for read-only graph visualization and instance inspection
- **Full audit trail** with event logging for every state transition

## Quick Start

### Prerequisites

- Python 3.12+
- Git

### Installation

```bash
git clone <repository-url>
cd loom
pip install -e .
```

### Basic Usage

Run a template from the CLI:

```bash
# Run the repo-analysis template
loom run repo-analysis --params '{"repo_url": "https://github.com/user/repo"}'

# Run with a specific runner (cc = Claude Code, pi = Pi CLI, codex, dsh)
loom run feature-loop --runner cc --params '{"branch": "feat/new-thing", "spec": "Add login page"}'

# List all instances
loom list

# Check status of a specific instance
loom status <instance_id>

# View system statistics
loom stats
```

## Architecture Overview

### Two-Layer Graph

Loom operates on two complementary graph layers:

1. **Knowledge graph** (SQLite, WAL mode) stores instances, nodes, edges, events, and artifacts as a single source of truth with concurrent read support.
2. **DAG orchestration** layer uses Kahn's algorithm for topological ordering, scheduling nodes whose dependencies are satisfied.

### Runners

Four adapter types execute node specs via subprocess:

| Runner | CLI | Description |
|--------|-----|-------------|
| `cc` | `claude -p <spec>` | Claude Code CLI |
| `pi` | `pi -p <spec>` | Pi CLI |
| `codex` | `codex -p <spec>` | Codex CLI |
| `dsh` | `dsh -p <spec>` | DSH CLI |

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

Nodes with `gate: approve` pause execution until a human approves or rejects via:

```bash
# Approve a gated node
loom status <instance_id>   # identify the waiting gate
# (gate decisions are recorded via the audit trail)
```

High-risk node kinds (`deploy`, `review`) automatically require gates.

### Tier-Based Routing

Nodes are assigned tiers that influence scheduling priority:

- **critical** -- highest priority, fails fast
- **heavy** -- resource-intensive operations
- **tooling** -- supporting tool invocations
- **bulk** -- batch/low-priority work

## CLI Commands

| Command | Description |
|---------|-------------|
| `loom run <template>` | Instantiate a template and execute the DAG |
| `loom list` | List all instances |
| `loom status <id>` | Show instance detail (nodes, status, cost) |
| `loom stats` | System-wide statistics (instances, nodes, events, gates) |
| `loom health` | System health summary (success rate, avg cost, pending gates) |
| `loom cost [id]` | Cost breakdown (aggregate, per-instance, or per-template) |
| `loom history` | Instance execution history |
| `loom audit [id]` | Audit trail (gate decisions and state transitions) |

### Run Options

```bash
loom run <template> [OPTIONS]

  --db PATH         Path to SQLite database
  --params JSON     Template parameters as JSON string
  --runner NAME     Runner adapter: fake, cc, pi, codex, dsh
```

## Web UI

Start the web server with uvicorn:

```bash
uvicorn loom.web.app:create_app --factory --host 0.0.0.0 --port 8000
```

The web UI provides a read-only REST API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/instances` | GET | List all instances with summary data |
| `/api/instances/{id}` | GET | Instance detail with nodes and edges |
| `/api/graph` | GET | Full graph (instances, nodes, edges) |

The static HTML frontend at `loom/web/static/index.html` visualizes instance and graph data.

## Templates

Templates are YAML files that define reusable workflows. Each template specifies triggers, parameters, and a DAG of nodes.

### Built-in Templates

| Template | Triggers | Description |
|----------|----------|-------------|
| `handoff-refresh` | inbox, cron | Scans a project and rewrites `handoff.md` |
| `feature-loop` | inbox, cli | Implements a feature on a branch with testing and review |
| `repo-analysis` | inbox, cron | Comprehensive repository structure and code analysis |

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
# Run all 106 tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_scheduler.py
```

### Project Structure

```
loom/
  cli.py              # Click-based CLI entry point
  core/
    models.py         # Dataclasses: Node, Instance, Edge, Artifact, Event, Template
    store.py          # SQLite CRUD operations (WAL mode)
    state.py          # State machines for nodes and instances
    scheduler.py      # DAG scheduler (Kahn's algorithm)
    loader.py         # YAML template parser and instantiator
    gate.py           # Gate decision flow
  adapters/
    base.py           # Abstract RunnerAdapter interface
    fake.py           # FakeRunner for testing
    cc.py             # Claude Code adapter
    pi.py             # Pi CLI adapter
    codex.py          # Codex adapter
    dsh.py            # DSH adapter
  triggers/
    hooks.py          # HTTP webhook server for CC hook events
    cron.py           # Morning digest generator
    inbox.py          # File watcher for inbox directory
  evolver/
    evolve.py         # Template discovery and evolution
  web/
    app.py            # FastAPI REST API
    static/
      index.html      # Web UI frontend
  templates/
    handoff-refresh.yaml
    feature-loop.yaml
    repo-analysis.yaml
tests/
  test_models.py      test_store.py       test_state.py
  test_scheduler.py   test_loader.py      test_adapters.py
  test_templates.py   test_cli.py         test_gate.py
  test_cron.py        test_inbox.py       test_triggers.py
  test_evolver.py     test_web.py         test_integration.py
  test_smoke.py       test_cost_history.py test_monitoring.py
  test_frontend.py
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

## License

See [LICENSE](LICENSE) for details.

# Loom Design Spec

**Status:** draft  
**Date:** 2026-09-05  
**System name:** Loom（织机）  
**CLI command:** `loom` / daemon `loomd`  
**Repository:** `graph-engineering`

## Summary

Loom is a **two-layer graph system** for automating and intelligently assisting daily work:

- **Layer 1: Knowledge Graph (Memory)** — a SQLite-backed work graph that tracks projects, tasks, artifacts, decisions, and their relationships; serves as the single source of truth for work state.
- **Layer 2: DAG Orchestration (Execution)** — executes work items as directed acyclic graphs, routing each node to the appropriate coding agent CLI (Claude Code / Codex / pi / dsh) based on task tier, with risk-tiered human gates for irreversible actions.

The system is built **on top of** four heterogeneous agent CLIs (cc, codex, pi, dsh), not inside any one of them. The orchestration kernel is an independent Python daemon with a thin CLI and a minimal web panel.

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Graph semantics | Two-layer: knowledge graph + DAG orchestration | Knowledge graph = state & memory; DAG = execution engine. They share the same graph; "graph" is both data and control flow. |
| Node source | Hybrid: manual SOP templates first, auto-discovery later | Immediate value from high-frequency workflows; low-frequency evolution channel avoids "extracting a knowledge graph" becoming an endless research project. |
| CLI selection | Dedicated tier-based routing | Critical → cc, heavy engineering → codex, tooling/batch → pi, cheap bulk → dsh. Fallback chain per tier. |
| Autonomy boundary | Risk-tiered gates | Read/analysis/draft fully automatic; merge to master, deploy, publish (e.g., Xiaohongshu), delete data require mandatory human approval. |
| Storage | SQLite single source of truth + artifacts written to Vault | Local-first, zero-ops, backup = copy file; Vault remains the knowledge base for human reading; graph doesn't replace it. |
| Trigger surface | Four-way: CC hooks + daily cron + manual CLI + inbox | Hooks catch events without leaving current toolchain; cron covers periodic rituals; CLI for ad-hoc; inbox for external signals. |
| Service target | Single user, multi-user slot reserved | Single-machine, no login, no concurrency design; but data model has `owner` field defaulting to `'me'`. |
| Kernel implementation | Self-built thin Python kernel | DAG semantics (gates, tier routing, template evolution) are the hardest-to-replace value; DAG executor itself is small (~2000 LOC); Python stack aligns with existing projects. |

## Architecture

```ascii
+----------------------------------------------------------------+
|TRIGGERS                                                        |
|  cc-hooks    cron(daily report)   loom CLI    inbox            |
+----------------------------------------------------------------+
      |              |                |                |
      ---------------+----------------------------------
                     v
+----------------------------------------------------------------+
|LOOM KERNEL (python daemon)                                     |
|                                                                |
|  Event Bus --> Graph Store (SQLite) <-- DAG Scheduler          |
|                  ^      |                   |                  |
|                  |      v                   v                  |
|           Template Lib(YAML)          Runner Router            |
|           Evolver (weekly LLM)   tier: cc/codex/pi/dsh         |
+----------------------------------------------------------------+

          |              |              |              |
          v              v              v              v
      +--------+     +--------+     +--------+     +--------+
      |   cc   |     | codex  |     |   pi   |     |  dsh   |
      +--------+     +--------+     +--------+     +--------+

          |              |              |              |
          -----------+----------------------------------
                     ^
+----------------------------------------------------------------+
|ARTIFACTS + REPORTS (md/jsonl)                                  |
|  --> Obsidian Vault      --> Web UI (gate approve)             |
+----------------------------------------------------------------+
```

### Six Components

| Component | What | How used | Depends on |
|---|---|---|---|
| **loom CLI** | Entry point (`loom plan/run/approve/inbox/status`) | Manual operation; also called by hooks and cron | kernel HTTP/socket |
| **Event Bus + Inbox** | Event receiver: CC hook POST events, morning cron, `loom inbox <url/screenshot>` | Triggers graph instances or advances nodes | None (ingest only) |
| **Graph Store** | SQLite: nodes/edges/runs/events/artifacts tables + owner field | Single source of truth; Web UI and CLI read from it | File lock, WAL mode |
| **Template Lib** | YAML templates (initial 5 SOPs distilled from session patterns) + instantiator | `loom run <template> --param x` instantiates a graph | Graph Store |
| **DAG Scheduler + Runner Router** | Daemon main loop: ready nodes → select CLI by tier → subprocess headless execution → collect results → gate suspension | System heart | Adapters |
| **Web UI** | Single-page panel: instance list (filter/sort), instance detail (DAG visualization with node colors + gate icons + expandable spec/logs/artifacts), metrics dashboard (cost/duration/failure rate), gate approval buttons | Browser for progress viewing, instance management, click to approve | Graph Store read + approve API |

**Key design constraint:** The kernel imports no CLI's private protocol — all four runners are driven uniformly via subprocess + structured output (stream-json / exit code / artifact files). If any CLI upgrades or disappears, Loom only loses one adapter layer.

### Repository Skeleton

```
loom/
  core/        # graph store, scheduler, router, gate policy
  adapters/    # cc.py codex.py pi.py dsh.py (unified RunnerAdapter interface)
  triggers/    # hooks receiver, daily report job, inbox watcher
  templates/   # *.yaml SOP templates (initial 5)
  evolver/     # session clustering → template candidate nomination
  web/         # panel (FastAPI + single page)
  tests/
loom.toml      # routing table, gate policy, Vault path, etc.
```

## Data Model

### Core Tables (SQLite, all with `owner` column default `'me'` — multi-user slot)

```
nodes        Work items
  id, instance_id, template_id, owner, title
  kind            # analysis | coding | review | deploy | report | gate ...
  spec            # prompt/task spec for runner (with parameter substitution)
  tier            # critical | heavy | tooling | bulk   -> routing basis
  gate            # none | approve    -> gate policy
  status          # see state machine
  project_path    # associated local repo (e.g., D:/Codes/inkwell)
  budget_tokens   # per-node cost cap; exceeded → kill runner, mark overflow
  created/started/finished_at, artifact_paths(json), session_ref

edges        Dependency edges
  instance_id, from_node, to_node, type(depends), condition(optional)

events       Trigger event ledger (hooks/cron/inbox all land here first)
  source, payload(json), received_at, consumed_by_instance

artifacts    Artifact registry
  node_id, kind(report|summary|md|log), path, sha256, vault_link

templates    Template registry (YAML body + version + provenance: manual|discovered)

instances    DAG instance lifecycle (the "graph run" itself, above nodes)
  id, template_id, owner, title, project_path
  status          # see Instance State Machine
  created_at, started_at, finished_at
  cost_tokens, cost_usd
  blocked_reason  # if status=blocked, record why
  params          # instantiation parameters JSON
```

### Node State Machine

```
pending -> ready -> dispatched -> running -> succeeded
                       |             |            ^
                       |             v            |
                       +-------> waiting_gate ----+ (approve)
                                     |
                                 rejected/cancelled
              running -> failed -> retry(n times, exponential backoff) -> degraded(switch runner, re-dispatch) -> still fail -> blocked + morning report highlight
```

### Instance State Machine

Instance-level state aggregates node states into a DAG-level view:

```
pending -> running -> succeeded
            |            |
            |            +-> failed (all terminal nodes failed)
            |            +-> cancelled (user manual cancel)
            v
        waiting_gate -> running (after approval)
            |
            +-> blocked (long-term no approval, morning report highlight)

any state -> cancelled (user `loom cancel <instance_id>`)
```

**Instance state aggregation rules:**
- `running` = at least one node in `running`/`dispatched`/`ready`/`pending`
- `waiting_gate` = all `running`/`dispatched` nodes completed, but `waiting_gate` node exists
- `blocked` = all non-terminal nodes are `blocked` (upstream failed)
- `succeeded` = all nodes are `succeeded` or `skipped` (downstream skipped due to gate rejection)
- `failed` = at least one node terminal state is `failed` and no more retries possible

### Initial 5 Templates ↔ Real Work Mapping

| # | Template | Graph shape | Trigger | Gate |
|---|---|---|---|---|
| 1 | `repo-analysis` open-source repo → implementation evaluation | clone/read repo → deep analysis(pi/codex·bulk) → commercialization path(cc·critical) → report to Vault → **next:立项?** | `loom inbox <gh-url>` | Only "立项" node |
| 2 | `feature-loop` worktree full flow | plan(cc) → worktree dev(codex) → self-test → review(cc·critical) → **merge→master** → clean worktree → deploy check | Manual/morning report | merge, deploy |
| 3 | `handoff-refresh` handoff & planning | inventory git dirty/worktrees(pi·tooling) → read last handoff doc → update handoff md(cc) → generate next-day plan → morning push | CC Stop hook + cron 07:5x | None |
| 4 | `content-pipeline` Xiaohongshu content line | material/screenshot → draft(codex) → humanize rewrite(cc+existing humanize skill) → compliance check(pi) → **publish** | inbox screenshot/link | Publish (mandatory) |
| 5 | `ops-deploy` deployment & ops | health check → build → force deploy → smoke test → report | Manual `loom run ops-deploy --proj inkwell` | Deploy (mandatory) |

### Template YAML Example (`handoff-refresh`)

```yaml
id: handoff-refresh
version: 1
trigger: [cc-stop-hook, cron:57 7 * * *, manual]
params: { project_path: {required: true} }
nodes:
  - id: inventory
    kind: analysis
    tier: tooling          # -> pi
    spec: |
      Inventory {{project_path}}: git status, unmerged worktrees,
      last 20 commits, pending tasks. Output inventory.json
  - id: handoff-doc
    kind: report
    tier: critical         # -> cc
    needs: [inventory]
    spec: |
      Read existing handoff doc + inventory.json, update handoff doc
      and propose next work plan, markdown to {{vault_out}}
  - id: digest
    kind: report
    tier: bulk             # -> dsh
    needs: [handoff-doc]
    spec: Compress to one-screen morning report for `loom digest`
```

## Execution Engine

### Unified RunnerAdapter Interface

```python
class RunnerAdapter:
    def available(self) -> bool          # CLI exists + login/quota self-check
    def launch(self, node, workdir) -> Handle   # start subprocess headless mode
    def stream(self, handle) -> Iter[Event]     # normalized event stream
    def collect(self, handle) -> Result          # exit code + artifacts + token usage
    def kill(self, handle) -> None
```

### Four Adapters

| Runner | Headless command | Output parsing | Notes |
|---|---|---|---|
| cc | `claude -p --output-format stream-json --permission-mode acceptEdits` | Native JSON event stream, best parsing | Post-gate execution can add `--allowedTools` whitelist |
| codex | `codex exec --json "<spec>"` | JSON event stream | Default for complex engineering nodes |
| pi | `pi -p --mode json` or via TS extension in-process call | JSON | Also serves as Loom's own "tooling" lightweight tasks |
| dsh | `dsh` non-interactive mode | **rc.2 output format TBD → adapter allows fallback to "plain text collection + exit code judgment"** | Failure handled by degradation rules |

Each adapter: one implementation + one contract test (feed the same toy node, assert five-interface behavior consistency). CLI upgrade changes command parameters only in this one file.

### Routing & Degradation Table (configurable in `loom.toml`)

```
tier=critical  -> cc    -> (cc unavailable) codex    -> suspend + alert
tier=heavy     -> codex -> (fail 2x)  cc       -> suspend
tier=tooling   -> pi    -> (fail 2x)  dsh -> cc
tier=bulk      -> dsh   -> (fail 2x)  pi  -> cc
```

Rules: Within same tier, switch CLI first; after 2 failures, escalate tier (cost increases but must report to you — morning report logs "escalation cost"). `budget_tokens` exceeded → immediate kill, mark overflow, no auto-retry.

### Gate Implementation

1. Nodes with `gate: approve` are not run directly by the scheduler; set to `waiting_gate` and generate a **decision package**: node spec + upstream artifact diff summary (e.g., worktree vs master `git diff --stat` + risk point list);
2. Three equivalent approval methods: Web UI button click / `loom approve <node_id>` / mobile self-message (YAGNI, defer to v2);
3. After approval, execution is **constrained within workdir + permission whitelist**: merge nodes run only in target repo with git command whitelist; deploy nodes only with deployment script path; publish nodes only with publisher CLI — **runners never get wildcard permissions**, this is the fundamental difference from raw CLI usage;
4. Rejection → node `rejected`, downstream `blocked`, reason written back to graph (evolution channel learns rejection reason distribution).

### Complete Data Flow Walkthrough

Example: `loom inbox https://github.com/foo/bar`

```
inbox command -> events table record
  -> instantiate repo-analysis graph (6 nodes) -> nodes state evolution:
     clone(pi·tooling) ✓ -> structure analysis(codex·heavy, read repo + previous node artifact) ✓
     -> commercialization assessment(cc·critical, consumes structure analysis md) ✓ -> report to Vault + artifacts registration ✓
     -> gate node waiting_gate: morning report push "report ready, 立项?" -> you `loom approve` -> build sub-project graph / end
  Throughout: each node stdout to runs/<id>.log, token count into nodes, Web UI real-time color progress
```

## Instance Management & Monitoring

### Instance Management CLI

```bash
# View all active instances (running + waiting_gate + blocked)
loom status
# Output:
# ID          TEMPLATE         STATUS         COST    BLOCKED_REASON
# abc123      handoff-refresh  running        1.2k    
# def456      feature-loop     waiting_gate   8.7k    merge approval
# ghi789      repo-analysis    blocked        3.4k    upstream node failed

# View single instance details (node status, artifacts, log paths)
loom status <instance_id>

# Cancel instance (kill all running nodes, downstream marked cancelled)
loom cancel <instance_id>

# Retry failed nodes (only for failed/blocked instances)
loom retry <instance_id> [--node <node_id>]

# View historical instances (default last 7 days)
loom history [--days 30] [--template repo-analysis] [--status succeeded]

# Full state transition timeline (audit trail)
loom audit <instance_id>

# Cost report (grouped by template/runner)
loom cost [--days 7]
```

### Monitoring & Alerting

**Cost monitoring:**
- Per-node `budget_tokens` hard limit (already defined)
- Per-instance `cost_usd` cumulative, threshold (e.g., $5) → morning report red highlight + `loom status` highlight
- Daily/weekly cost summary: `loom cost [--days 7]` → grouped by template/runner statistics

**Duration monitoring:**
- Node-level `timeout` (already defined, 15 min heartbeat)
- Instance-level SLA: template can declare `expected_duration_minutes`, overdu → morning report prompt "this instance duration is abnormal"

**Alert trigger conditions:**
- Instance `blocked` for over 24 hours → morning report red highlight
- Node `failed` then degraded to higher tier → morning report log "escalation cost"
- CLI quota exhausted → immediate notification (future can connect Webhook, v1 only record to `loom status`)

**Logs & audit:**
- All state changes recorded in `events` table (already defined), add `state_transition` type
- `loom audit <instance_id>` → output complete state transition timeline (pending→ready→...)

### Web UI Enhancements

**Instance list page:**
- Filter by status, filter by template, sort by cost
- Quick actions: approve (for waiting_gate), cancel, retry

**Instance detail page:**
- DAG visualization (node color-coded, edge arrow direction, gate nodes with special icon)
- Node click to expand spec/logs/artifacts
- Cost breakdown per node

**Metrics dashboard:**
- Today's running instances, total cost, average duration, gate waiting count, failure rate
- Trend charts: cost over time, success rate by template

## Trigger Surface

### CC Hooks (Event-Driven Surface)

You already have a mature hooks ecosystem (ECC etc.). Loom only adds two lightweight hooks, both "fire-and-forget" (curl local port, 2s timeout, failure doesn't block CC exit):

```
Stop hook     -> POST localhost:7741/event {type: cc.stop, project, session_id, transcript}
                 If project is in loom.toml's handoff_watch list -> auto-trigger/advance handoff-refresh
PostToolUse(git merge) -> Detect worktree merge complete -> trigger feature-loop cleanup+deploy segment
```

Morning report cron uses Windows Task Scheduler to call `loom digest --push` (no need for persistent Python scheduler dependency APScheduler — daemon itself has timers, cron is just a fallback wake-up). Inbox watcher monitors `Vault/00-inbox/` for new files (watchdog library, polling fallback).

### Evolution Channel (Auto-Discovery, Low-Cost Implementation)

Not online mining. Every Sunday daemon runs an `evolve` graph (itself also a DAG!):

```
Scan last 7 days session JSONL prompt sequences (pi·tooling)
  -> LLM cluster "repeated behavior patterns" (cc·critical)
  -> Output template candidate YAML draft + overlap analysis with existing templates
  -> waiting_gate: you review, adopt → enter templates table (provenance=discovered), reject → record reason
```

Zero risk of false positives: candidates always pass through manual gate before entering the library. This is where "summarize and extract from cc's historical session information" lands — **manual templates are v1's automation, evolution channel is v2's intelligence**.

## Error Handling

| Failure | Strategy |
|---|---|
| Daemon crash | After restart, scan `running` state nodes → check if subprocess is alive → orphan process kill, node re-dispatch (idempotent contract: node spec must be re-runnable) |
| Runner hangs | Node-level `timeout` + heartbeat: no stream events in 15 min → judged dead, kill |
| CLI quota exhausted/login expired | `available()` pre-check failure → go directly to degradation table, no wasted dispatch |
| SQLite lock | WAL mode; all writes converge in daemon single writer, CLI/UI read-only |
| Artifact lost/interrupted | Artifacts registered based on landed files, runs.log retained for 90 days |

## Testing Strategy

- **Adapter contract test:** `FakeRunner` (echo script) drives unified interface assertions; real CLI smoke tests marked `@slow` manually triggered;
- **Scheduler:** Pure functional state machine, table-driven unit tests (one case per state transition, including gates/degradation/overflow);
- **End-to-end:** `loom run hello-graph` (3 nodes, all using FakeRunner, temporary SQLite) as regression;
- **Template YAML:** JSON Schema validation + `loom template lint`.

## v1 Milestones

```
M1  Kernel skeleton: schema + scheduler + FakeRunner E2E green            ~2 days
M2  cc+pi two adapters truly run, handoff-refresh template online          ~2 days
M3  Stop hook wiring + morning digest + Web UI minimal (view+approve)      ~2 days
M4  codex/dsh adapters + feature-loop (merge gate) + repo-analysis         ~2 days
M5  Inbox watcher + evolution channel (can be deferred)                    ~1 day
```

## Non-Goals (Explicit)

- **No multi-user support in v1.** Architecture reserves the slot but doesn't build it.
- **No online learning / real-time pattern mining.** Evolution channel is weekly batch, manual gate.
- **No mobile push / external notification.** Web UI + CLI approval only.
- **No custom graph database.** SQLite edges are sufficient for the scale (thousands of nodes); Neo4j/KuzuDB deferred until real multi-hop relationship analytics are needed.
- **No temporal workflow engine borrowing.** DAG semantics are too specific; borrowing Temporal/Prefect creates friction without proportional benefit.

## Future Work

- Multi-user authentication, permission model, concurrent execution limits
- Real-time pattern mining from session streams (online clustering)
- Mobile push for gate approvals
- Graph visualization enhancements (interactive node expansion, cost heatmaps)
- Template marketplace (share SOPs across users/organizations)
- Integration with external task systems (Jira, Linear, Obsidian Tasks plugin)

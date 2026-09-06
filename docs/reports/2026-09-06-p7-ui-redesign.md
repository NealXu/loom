# P7 — Web UI Redesign + Backend Endpoints

**Date:** 2026-09-06 · **Branch:** master · **Status:** Completed

## Goal

Extend Loom's web UI from a single dashboard into a sidebar-navigated, multi-view
application covering the same surface as the CLI, so stages 2–6 of the user flow are
reachable from both CLI and UI.

## What was built

### Backend (6 new endpoints in `loom/web/app.py`)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/templates` | Scan the templates dir (`templates_dir`) and list available templates (id, version, trigger, provenance, nodes, file) |
| `GET /api/stats` | System-wide counts: instances/nodes by status, total events, gate decisions |
| `GET /api/health` | Success rate, avg cost per succeeded instance, pending gates, last event |
| `GET /api/audit` | Merged audit timeline (gate decisions + state transitions), filterable by `instance_id` / `type` |
| `GET /api/digest` | Daily digest: totals, success rate, red-line `over_budget` list, recent instances |
| `GET /api/cost` | Cost aggregation: totals, per-template, per-instance |

`create_app(store)` gained two backward-compatible kwargs: `templates_dir`
(default `"loom/templates"`) and `red_line_usd` (default `5.0`).

### Frontend (`loom/web/static/index.html`, rewritten as a multi-view SPA)

Sidebar navigation (SVG icons + labels) with 7 views:

- **Dashboard** — KPI cards from `/api/stats` + `/api/health`; instances list with
  over-budget red highlight; pending-gates approve/reject; SSE live refresh; Cytoscape DAG.
- **Run** — template `<select>` (`/api/templates`), param inputs with bound labels,
  runner select, sync/async mode, POST `/api/run`.
- **History** — sortable table (`aria-sort`) with template/status filters, expandable rows.
- **Audit** — vertical timeline of gate decisions + state transitions (`/api/audit`).
- **Cost** — per-template bar chart with over-budget highlight, View-as-Table toggle (`/api/cost`).
- **Digest** — totals summary + over-budget alert (`/api/digest`).
- **Templates** — install from URL/path form + installed-templates list (`/api/templates`).

Accessibility: SVG nav icons (no emoji), `aria-label` on icon buttons, bound form
labels, `aria-live` toasts, visible focus, `@media (prefers-reduced-motion)`.
Loading skeleton/spinner and empty states are present throughout.

### Acceptance bugs fixed during verification

1. Dashboard KPI cards read top-level `stats.running/...` but data is nested under
   `instances.by_status.*` → corrected path; `waiting_gate` counts toward pending.
2. Cost view read `data.items || data` (an object has no `.length`) → switched to
   `data.by_instance` and mapped `template_id`/`cost_tokens` fields.
3. Digest read `digest.total_cost` (actual `total_cost_usd`) and treated the
   `over_budget` array as a count → corrected fields + `.length`; added
   `total_tokens` to the backend `/api/digest` response.
4. Audit timeline read `entry.message/action/event` (absent) → built a human
   description from `type` (gate approved/rejected + node/actor/reason; transition
   `from → to`).

## Verification

- **Tests:** 317 passed, 0 failed (was 265 baseline).
- New contract tests: `tests/test_web_ui.py` (18) and
  `tests/test_frontend_sections.py` (34), written test-first (Red → Green).
- Existing frontend tests (DAG/SSE/vendored) and backend tests all still pass.
- **Browser acceptance:** all 7 views rendered and populated against real endpoints.

## Files

```
loom/web/app.py                  # 6 endpoints + create_app kwargs
loom/web/static/index.html       # multi-view SPA
tests/test_web_ui.py             # backend contract (18)
tests/test_frontend_sections.py  # frontend contract (34)
README.md                        # feature + Web UI section updated
```

## Notes

- CLI remains the operation center (trigger/approve/audit/config); the UI is the
  monitoring + point-and-click surface. Both now cover stages 2–6.
- The deployment at `D:\Deploys\loom` was synced with this code.

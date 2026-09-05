# Loom 项目交接文档（Handoff）

> 交接日期：2026-09-05 　分支/基准：`master` @ `c6a9ea7`
> 用途：让下一位（人或 agent）无需重读整段历史即可安全续作。
> 恢复提示：本计划 SDD 工作区（`.superpowers/sdd/2026-09-05-loom/`）与账本已按流程删除；以 `git log` + 本文为准。

## 1. 一句话现状

Loom 计划的全部 28 项任务（M1–M5 + 终审）已实施并合并到 `master`；106 个测试全绿。当前是**一次性 `loom run` 编排的静态内核**，尚未成为计划设想的**常驻事件驱动 daemon**。

## 2. 度量

- 提交：`master` 33 条（28 实现 + 1 计划文档 + 2 设计/交接类文档）
- 测试：106 passed，无警告（`python -m pytest tests/ -q`）
- 规模：`loom/` 包 ~1846 行，`tests/` ~2305 行
- 运行环境：Python 3.12.10 / Windows；依赖已 `pip install`（aiohttp/fastapi/uvicorn/watchdog/click/pyyaml/pytest）

## 3. 已实现分层

| 层 | 文件 | 说明 |
|----|------|------|
| 数据模型 | `loom/core/models.py` | Node/Instance/Edge/Artifact/Event/Template dataclass |
| 存储 | `loom/core/store.py` | SQLite WAL；node/instance CRUD；`Store` 支持 `with`（Windows 需关连接） |
| 状态机 | `loom/core/state.py` | 7 态转换校验 + `record_transition` 写 `events`（source=`state_transition`） |
| 调度器 | `loom/core/scheduler.py` | Kahn 拓扑排序 + `ready_nodes`；纯 id 级，无持久化耦合 |
| 模板加载 | `loom/core/loader.py` | `load_template`（校验）+ `instantiate`（占位符渲染 + 生成 id + 边映射） |
| 门禁 | `loom/core/gate.py` | `GateDecision` + `record_gate_decision`（approve→running / reject→cancelled）+ `get_pending_gates` |
| 适配器 | `loom/adapters/` | `RunnerAdapter` ABC + cc/pi/codex/dsh/fake；均 subprocess + 结构化输出 |
| 触发器 | `loom/triggers/` | `hooks`(aiohttp /hook)、`cron`(晨报 build/render, cost_usd>=5 红线)、`inbox`(watchdog) |
| Web | `loom/web/` | `app.py`(FastAPI 只读: instances/detail/graph) + `static/index.html`(vanilla, XSS 安全) |
| CLI | `loom/cli.py` | `run/list/status/stats/health/cost/history/audit`；`_RUNNERS` 含 5 个 runner |
| 进化 | `loom/evolver/evolve.py` | 模板发现 v1（template_id 聚类；LLM 部分留白） |

模板：`loom/templates/{handoff-refresh,feature-loop,repo-analysis}.yaml`。`feature-loop` 的 `merge` 节点带 `gate: approve`。

## 4. 关键缺口（相对计划"独立 daemon 自动化"的愿景）

1. **无 daemon/服务启动**：`create_app` 未接 `loom serve`；hooks/inbox/cron 三触发器写入 `events` 但无常驻循环消费并推进实例。今日编排只在单次 `loom run` 中内联发生（`_run_instance`）。
2. **门禁非交互**：CLI/Web 无 approve/reject 入口，`_run_instance` 对 `gate=approve` 自动放行 → `feature-loop` merge 门禁运行时形同虚设。
3. **无 tier 路由**：计划列了 `router.py` + `loom.toml`（tier→runner 降级表），均未实现；`tier` 仅元数据。
4. **预算未硬执行**：`budget_tokens` 存而不拦；`cost_usd` 累计未接通到 $5 晨报警线全链路（仅 cron 渲染时判断）。
5. **适配器无超时**：`proc.communicate()` 无 `wait_for`，挂起 CLI 会永久阻塞调度器。
6. **Store API 不全**：edge/artifact/event 无 CRUD 方法，全库 8+ 处裸 SQL。
7. 未建 `content-pipeline.yaml`、`ops-deploy.yaml`。
8. 风格项：4 个真实适配器近重复（可抽 `SubprocessAdapter` 基类）；`returncode or 0`；函数内 `import json`；若干测试未用导入。

## 5. 下一步工作计划（优先级）

- **P0-A｜daemon + 事件循环**：`loom serve`(uvicorn 拉起 web) + `loom daemon`(读 `events` → 就绪实例 → `ready_nodes` → 适配器 → 状态推进；单写者约束下触发器只写 events)。最高杠杆。
- **P0-B｜交互门禁**：`loom gate list/approve/reject` 接 `record_gate_decision`；Web 待批面板；让 merge 门禁真正阻塞。
- **P1-C｜tier 路由 + 预算**：`router.py` + `loom.toml`；`budget_tokens` 硬上限；cost 累计贯通到晨报红线。
- **P1-D｜适配器重构 + 超时**：`SubprocessAdapter` 基类去重；加超时。
- **P2-E｜Store 数据访问层**：补 `create_edge/create_event/create_artifact` + 查询，收敛裸 SQL。
- **P2-F｜剩余模板**：`content-pipeline.yaml`、`ops-deploy.yaml`。
- **P2-G｜加固**：web `response_model`、corrupted-JSON 错误路径测试、WAL 并发读测试、风格项清理。
- **P3-H｜工程化**：git 远程 + CI；`pip install -e .` 验证入口；对真实 cc/pi/codex/dsh CLI 端到端冒烟。

## 6. 如何续作（恢复清单）

- 读本文 + `docs/superpowers/plans/2026-09-05-loom.md`（计划）+ `docs/superpowers/specs/2026-09-05-loom-design.md`（设计）。
- `git log --oneline` 是进度权威来源。
- 跑测试建立基线：`python -m pytest tests/ -q`（预期 106 passed）。
- 建议续作方式：新任务用 `superpowers:brainstorming` → 出 plan → `superpowers:subagent-driven-development` 执行。P0-A 先做设计（事件消费语义、进程模型、崩溃恢复）。
- 在隔离 worktree 内开发（`using-git-worktrees`）。

## 7. 本会话环境备忘（可能仍适用）

- **子代理模型固定**：`~/.claude/settings.json` 里 `CLAUDE_CODE_SUBAGENT_MODEL` 早期固定到会 429 的 provider；切到 `deepseek/DeepSeek-V4-Flash-Vision-Exp[1m]` 后子代理恢复。若再遇子代理 429，优先检查此变量并更换 provider。
- **GateGuard 事实门禁**：本会话用 `ECC_GATEGUARD=off` 关闭了"每个文件创建前陈述事实"的门禁（用户批准）。若不希望继续关闭，可移除该 env。
- **平台**：Windows，Bash 工具为 Git Bash；测试须 `with Store(...)` 关连接，否则临时目录清理报 WinError 32。
- 本仓库无 git 远程（`git remote -v` 空）；`main` 分支不存在，基准是 `master`。

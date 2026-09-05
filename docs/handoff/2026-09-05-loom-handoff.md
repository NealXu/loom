# Loom 项目交接文档（Handoff）

> 交接日期：2026-09-05 　分支/基准：`master` @ `3f920e7`
> 用途：让下一位（人或 agent）无需重读整段历史即可安全续作。
> 恢复提示：本计划 SDD 工作区（`.superpowers/sdd/2026-09-05-loom/`）与账本已按流程删除；以 `git log` + 本文为准。
> 详细进展：`docs/reports/2026-09-05-overview.md`（P0 前快照）→ `docs/reports/2026-09-05-p0-daemon-gate-complete.md`（P0 完成报告）。

## 1. 一句话现状

M1–M5（28 任务）与 P0-A（daemon 事件循环）、P0-B（交互式门禁）均已合并到 `master`；132 个测试全绿。`loom serve` 可启动常驻 daemon + web，门禁节点真正阻塞并支持 CLI/Web 审批。**尚无**：tier 路由、预算硬执行、适配器超时、触发器 events→模板自动派发。

## 2. 度量

- 提交：`master` 35 条（28 实现 + 1 终审修复 + P0-A/B feat + 4 文档）
- 测试：132 passed，无警告（`python -m pytest tests/ -q`；含 pytest-asyncio）
- 规模：`loom/` 包 ~2407 行，`tests/` ~2907 行
- 运行环境：Python 3.12.10 / Windows；依赖已 `pip install`（aiohttp/fastapi/uvicorn/watchdog/click/pyyaml/pytest/pytest-asyncio）

## 3. 已实现分层

| 层 | 文件 | 说明 |
|----|------|------|
| 数据模型 | `loom/core/models.py` | Node/Instance/Edge/Artifact/Event/Template dataclass |
| 存储 | `loom/core/store.py` | SQLite WAL；node/instance CRUD；`Store` 支持 `with`（Windows 需关连接） |
| 状态机 | `loom/core/state.py` | 7 态转换校验 + `record_transition` 写 `events`（source=`state_transition`） |
| 调度器 | `loom/core/scheduler.py` | Kahn 拓扑排序 + `ready_nodes`；纯 id 级，无持久化耦合 |
| 模板加载 | `loom/core/loader.py` | `load_template`（校验）+ `instantiate`（占位符渲染 + 生成 id + 边映射） |
| 编排引擎 | `loom/core/engine.py` | `step_instance`：从 DB 算 completed 集合、执行就绪节点、遇 gate 挂起 waiting_gate（P0-A） |
| Daemon | `loom/daemon.py` | `LoomDaemon` 异步 tick loop（2s）；启动首 tick 崩溃恢复 running→pending（P0-A） |
| 适配器 | `loom/adapters/` | `RunnerAdapter` ABC + cc/pi/codex/dsh/fake；均 subprocess + 结构化输出 |
| 触发器 | `loom/triggers/` | `hooks`(aiohttp /hook)、`cron`(晨报 build/render, cost_usd>=5 红线)、`inbox`(watchdog) |
| Web | `loom/web/` | `app.py`(FastAPI: instances/detail/graph + **gates GET/POST approve/reject**) + `static/index.html`(**含 Pending Gates 面板**, XSS 安全) |
| CLI | `loom/cli.py` | `run[--bg]/list/status/gate list|approve|reject/serve/stats/health/cost/history/audit`；`_RUNNERS` 含 5 个 runner |
| 进化 | `loom/evolver/evolve.py` | 模板发现 v1（template_id 聚类；LLM 部分留白） |

模板：`loom/templates/{handoff-refresh,feature-loop,repo-analysis}.yaml`。`feature-loop` 的 `merge` 节点带 `gate: approve`，运行时已真正阻塞。

## 4. 关键缺口（P0 完成后更新）

1. ~~无 daemon~~ ✅ 已实现 `loom serve` + `LoomDaemon`（P0-A）。
2. ~~门禁非交互~~ ✅ CLI `loom gate` + Web 面板（P0-B）。
3. **触发器 events 无人派发**：hooks/inbox 写入的 events 仍不会被转换为模板实例（`Template.trigger` 字段已定义未使用）——需要 event→template 匹配逻辑。
4. **无 tier 路由**：`router.py` + `loom.toml`（tier→runner 降级表）未实现；`tier` 仅元数据。⬅ P1-C
5. **预算未硬执行**：`budget_tokens` 存而不拦；适配器 `Result` 的 cost 字段未回写聚合到 `instance.cost_*`；$5 晨报红线未全链路贯通。⬅ P1-C
6. **适配器无超时**：`proc.communicate()` 无 timeout，挂起 CLI 会永久阻塞调度器。⬅ P1-D
7. **Store API 不全**：已补 list/update（P0）；仍缺 `create_edge/create_event/create_artifact`，全库仍有裸 SQL。⬅ P2-E
8. 未建 `content-pipeline.yaml`、`ops-deploy.yaml`。⬅ P2-F
9. 风格项：4 个真实适配器近重复（可抽 `SubprocessAdapter` 基类）；`returncode or 0`；函数内 `import json`；若干测试未用导入。⬅ P1-D/P2-G

## 5. 下一步工作计划（优先级）

- **P1-C｜tier 路由 + 预算**：`router.py` + `loom.toml`（critical→cc / heavy→codex / tooling→pi / bulk→dsh 降级表）；`budget_tokens` 硬上限；cost 累计贯通到晨报红线。⬅ 当前
- **P1-D｜适配器重构 + 超时**：`SubprocessAdapter` 基类去重；加超时。⬅ 当前
- **P2-E｜Store 数据访问层**：补 `create_edge/create_event/create_artifact`，收敛裸 SQL。
- **P2-F｜剩余模板**：`content-pipeline.yaml`、`ops-deploy.yaml`。
- **P2-G｜加固**：web `response_model`、corrupted-JSON 错误路径测试、WAL 并发读测试、风格项清理。
- **P2-K｜event→template 派发**：让 hooks/inbox/cron 触发的事件自动实例化匹配模板（补第 4 节缺口 3）。
- **P3-H｜工程化**：git 远程 + CI；`pip install -e .` 验证入口；对真实 cc/pi/codex/dsh CLI 端到端冒烟。

## 6. 如何续作（恢复清单）

- 读本文 + `docs/superpowers/plans/2026-09-05-loom.md`（计划）+ `docs/superpowers/specs/2026-09-05-loom-design.md`（设计）。
- `git log --oneline` 是进度权威来源。
- 跑测试建立基线：`python -m pytest tests/ -q`（预期 132 passed）。
- 建议续作方式：新任务用 `superpowers:brainstorming` → 出 plan → `superpowers:subagent-driven-development` 执行。
- 在隔离 worktree 内开发（`using-git-worktrees`）。P0-A/B 即按此流程（worktree `loom-p0-daemon-gate`，已合并清理）。

## 7. 本会话环境备忘（可能仍适用）

- **子代理模型固定**：`~/.claude/settings.json` 里 `CLAUDE_CODE_SUBAGENT_MODEL` 早期固定到会 429 的 provider；切到 `deepseek/DeepSeek-V4-Flash-Vision-Exp[1m]` 后子代理恢复。若再遇子代理 429，优先检查此变量并更换 provider。
- **GateGuard 事实门禁**：本会话用 `ECC_GATEGUARD=off` 关闭了"每个文件创建前陈述事实"的门禁（用户批准）。若不希望继续关闭，可移除该 env。
- **平台**：Windows，Bash 工具为 Git Bash；测试须 `with Store(...)` 关连接，否则临时目录清理报 WinError 32。
- 本仓库无 git 远程（`git remote -v` 空）；`main` 分支不存在，基准是 `master`。

# Loom 项目交接文档（Handoff）

> 交接日期：2026-09-05 　分支/基准：`master` @ `7f4c18b`
> 用途：让下一位（人或 agent）无需重读整段历史即可安全续作。
> 恢复提示：本计划 SDD 工作区（`.superpowers/sdd/2026-09-05-loom/`）与账本已按流程删除；以 `git log` + 本文为准。
> 详细进展：`docs/reports/2026-09-05-overview.md`（P0 前快照）→ `docs/reports/2026-09-05-p0-daemon-gate-complete.md`（P0）→ 本文第 4/5 节（P1 现状）。

## 1. 一句话现状

M1–M5（28 任务）+ P0-A（daemon 事件循环）+ P0-B（交互式门禁）+ P1-C（tier 路由 + 预算硬执行）+ P1-D（适配器重构 + 超时）均已合并到 `master`；153 个测试全绿。`loom serve` 启动常驻 daemon + web，门禁阻塞可 CLI/Web 审批，节点按 tier 路由并有二进制缺失降级链，累计成本触达 `budget_tokens` 会 block 实例，挂起 CLI 会被超时杀掉。**尚无**：触发器 events→模板自动派发、剩余 2 个模板、Store 写方法补全。

## 2. 度量

- 提交：`master` 38 条（P0/P1 各 feat + 文档 + P1-D refactor + P1-C feat）
- 测试：153 passed（`python -m pytest tests/ -q`；pytest asyncio_mode=auto）
- 规模：`loom/` 包 ~2700 行，`tests/` ~3300 行
- 运行环境：Python 3.12.10 / Windows；依赖已 `pip install`（aiohttp/fastapi/uvicorn/watchdog/click/pyyaml/pytest/pytest-asyncio/httpx）

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
| 适配器 | `loom/adapters/` | `RunnerAdapter` ABC + `SubprocessAdapter` 基类（超时杀进程，P1-D）+ cc/pi/codex/dsh 薄子类 + fake |
| 路由 | `loom/core/router.py` | `RunnerRouter`（按 tier 选 runner，缺失二进制降级；`--runner auto` + `loom.toml [routing]`，P1-C） |
| 触发器 | `loom/triggers/` | `hooks`(aiohttp /hook)、`cron`(晨报 build/render，`threshold` 可配，P1-C)、`inbox`(watchdog) |
| Web | `loom/web/` | `app.py`(FastAPI: instances/detail/graph + **gates GET/POST approve/reject**) + `static/index.html`(**含 Pending Gates 面板**, XSS 安全) |
| CLI | `loom/cli.py` | `run[--bg][--runner auto]/list/status/gate list|approve|reject/serve/stats/health/cost/history/audit`；`_make_runner` 工厂 |
| 配置 | `loom.toml` | `[routing]` tier→runner 降级链 + `[budget] red_line_usd`（P1-C） |
| 进化 | `loom/evolver/evolve.py` | 模板发现 v1（template_id 聚类；LLM 部分留白） |

模板：`loom/templates/{handoff-refresh,feature-loop,repo-analysis}.yaml`。`feature-loop` 的 `merge` 节点带 `gate: approve`，运行时已真正阻塞。

## 4. 关键缺口（P1 完成后更新）

1. ~~无 daemon~~ ✅ `loom serve` + `LoomDaemon`（P0-A）。
2. ~~门禁非交互~~ ✅ CLI `loom gate` + Web 面板（P0-B）。
3. ~~无 tier 路由~~ ✅ `router.py` + `loom.toml` + `--runner auto`（P1-C）。
4. ~~预算未硬执行~~ ✅ 累计成本触达 `node.budget_tokens` → 实例 blocked（P1-C）；cost 经 `add_instance_cost` 回写。
5. ~~适配器无超时~~ ✅ `SubprocessAdapter` 基类 + `asyncio.wait_for`，默认 600s（P1-D）。
6. **触发器 events 无人派发**：hooks/inbox 写入的 events 仍不会被转换为模板实例（`Template.trigger` 字段已定义未使用）——需 event→template 匹配。⬅ P2-K
7. **预算红线未接 CLI/daemon 默认**：`--runner auto` 与 `red_line_usd` 已可用，但 `loom run` 默认仍是 `fake`；`loom serve` 未自动读 config 阈值传给晨报（晨报暂无 CLI 子命令，仅 `build_digest` 库函数）。⬅ P2-G
8. **真实适配器 cost 恒 0**：cc/pi/codex/dsh 的 `Result.cost_*` 未从 CLI 输出解析——预算/红线链路真实数据依赖各 CLI 的用量输出格式。⬅ P3-J
9. **Store 写方法不全**：仍缺 `create_edge/create_event/create_artifact`，全库仍有裸 SQL。⬅ P2-E
10. 未建 `content-pipeline.yaml`、`ops-deploy.yaml`。⬅ P2-F

## 5. 下一步工作计划（优先级）

- **P2-K｜event→template 派发**：让 hooks/inbox/cron 触发的事件按 `Template.trigger` 自动实例化并交给 daemon（补第 4 节缺口 6）。**最高剩余杠杆**。
- **P2-E｜Store 数据访问层**：补 `create_edge/create_event/create_artifact`，收敛裸 SQL。
- **P2-F｜剩余模板**：`content-pipeline.yaml`、`ops-deploy.yaml`。
- **P2-G｜加固 + 配置贯通**：`loom serve`/晨报读 `loom.toml` 阈值；`--runner` 默认策略；web `response_model`、corrupted-JSON 测试、WAL 并发读、风格清理。
- **P3-H｜工程化**：git 远程 + CI；`pip install -e .` 验证入口。
- **P3-J｜端到端冒烟**：对真实 cc/pi/codex/dsh CLI 跑通；从输出解析 token/cost 回写（补第 4 节缺口 8）。

## 6. 如何续作（恢复清单）

- 读本文 + `docs/superpowers/plans/2026-09-05-loom.md`（计划）+ `docs/superpowers/specs/2026-09-05-loom-design.md`（设计）。
- `git log --oneline` 是进度权威来源。
- 跑测试建立基线：`python -m pytest tests/ -q`（预期 153 passed）。
- 建议续作方式：新任务用 `superpowers:brainstorming` → 出 plan → `superpowers:subagent-driven-development` 执行。
- 在隔离 worktree 内开发（`using-git-worktrees`）。P0-A/B（worktree `loom-p0-daemon-gate`）、P1-C/D（worktree `loom-p1-router-budget`）均按此流程合并回 `master` 并清理。

## 7. 本会话环境备忘（可能仍适用）

- **子代理模型固定**：`~/.claude/settings.json` 里 `CLAUDE_CODE_SUBAGENT_MODEL` 早期固定到会 429 的 provider；切到 `deepseek/DeepSeek-V4-Flash-Vision-Exp[1m]` 后子代理恢复。若再遇子代理 429，优先检查此变量并更换 provider。
- **GateGuard 事实门禁**：本会话用 `ECC_GATEGUARD=off` 关闭了"每个文件创建前陈述事实"的门禁（用户批准）。若不希望继续关闭，可移除该 env。
- **平台**：Windows，Bash 工具为 Git Bash；测试须 `with Store(...)` 关连接，否则临时目录清理报 WinError 32。
- 本仓库无 git 远程（`git remote -v` 空）；`main` 分支不存在，基准是 `master`。

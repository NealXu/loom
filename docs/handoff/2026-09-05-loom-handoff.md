# Loom 项目交接文档（Handoff）

> 交接日期：2026-09-05 　分支/基准：`master` @ `a39add4`
> 用途：让下一位（人或 agent）无需重读整段历史即可安全续作。
> 恢复提示：本计划 SDD 工作区（`.superpowers/sdd/2026-09-05-loom/`）与账本已按流程删除；以 `git log` + 本文为准。
> 详细进展：`docs/reports/2026-09-05-overview.md`（P0 前快照）→ `docs/reports/2026-09-05-p0-daemon-gate-complete.md`（P0）→ 本文第 4/5 节（P1 现状）。

## 1. 一句话现状

M1–M5（28 任务）+ P0-A/B（daemon + 门禁）+ P1-C/D（路由 + 预算 + 超时）+ P2-K（event→template 派发）+ P2-L（cron 调度器）+ P2-E（Store 写方法）+ P2-F（5 模板全）+ P2-G（digest 命令 + web response_model）+ P3-H（CI）+ P3-J（cost 解析，真实 claude CLI 冒烟通过）**全部合并到 `master`；179 测试全绿**。系统端到端可用：定时/钩子触发 → 派发实例化 → tier 路由（含二进制缺失降级）→ 执行（超时保护 + 预算硬顶 + 真实 token/cost 回写）→ 门禁阻塞 → CLI/Web 审批 → 晨报红线。**计划设计的功能面已完整落地**，余下均为运维/多用户/检索类增强。

## 2. 度量

- 提交：`master` 46 条（28 实现 + P0/P1/P2/P3 各批 + 文档）
- 测试：179 passed（`python -m pytest tests/ -q`；pytest asyncio_mode=auto）
- 模板：5/5 全部就位（handoff-refresh, feature-loop, repo-analysis, content-pipeline, ops-deploy）
- 规模：`loom/` 包 ~3000 行，`tests/` ~3600 行
- CI：`.github/workflows/ci.yml`（py 3.12/3.13 矩阵）——**待推远程才生效**
- 运行环境：Python 3.12.10 / Windows；依赖已 `pip install -e ".[dev]"`；`loom --help` 入口 11 命令可用；claude/codex/pi/dsh 四 CLI 本机均在 PATH

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
| 派发 | `loom/core/dispatcher.py` | `dispatch_events`：events→`Template.trigger` 匹配→实例化（P2-K）；支持 `payload["template"]` 定向派发；`events.dispatched` 标记列；daemon tick 接入；`serve --templates` |
| 定时 | `loom/core/schedule.py` | `CronScheduler` + `load_jobs`（P2-L）：`loom.toml [schedule.jobs]` 每 `every_seconds` 产生 cron 事件 |
| 成本 | `loom/adapters/cost_parsing.py` | `extract_cost`（P3-J）：从 CLI JSON stdout 解析 tokens/cost，`SubprocessAdapter` 经 `parse_cost`+`extra_args` 启用（CCAdapter 已开） |
| 触发器 | `loom/triggers/` | `hooks`(aiohttp /hook)、`cron`(晨报 build/render，`threshold` 可配，P1-C)、`inbox`(watchdog) |
| Web | `loom/web/` | `app.py`(FastAPI: instances/detail/graph + **gates GET/POST approve/reject**) + `static/index.html`(**含 Pending Gates 面板**, XSS 安全) |
| CLI | `loom/cli.py` | `run[--bg][--runner auto]/list/status/gate list|approve|reject/serve/stats/health/cost/history/audit`；`_make_runner` 工厂 |
| 配置 | `loom.toml` | `[routing]` tier→runner 降级链 + `[budget] red_line_usd`（P1-C） |
| 进化 | `loom/evolver/evolve.py` | 模板发现 v1（template_id 聚类；LLM 部分留白） |

模板 5/5：`{handoff-refresh, feature-loop, repo-analysis, content-pipeline, ops-deploy}.yaml`。高风险节点（merge/publish/deploy）均带 `gate: approve`，运行时真正阻塞。

## 4. 缺口状态（P2/P3 后：设计功能面已闭环）

原 P0/P1/P2/P3 计划项**全部 ✅**：daemon、门禁交互、tier 路由+降级、预算硬顶+超时、event 派发、cron 调度、Store 写方法、5 模板、digest 命令+web response_model、CI、cost 解析（真实 claude CLI 冒烟通过）。

剩余为**增强/运维类**（非计划核心功能）：
1. **git 远程未建**：CI workflow 已就位但需推 GitHub 才跑；`git remote -v` 仍空。⬅ 运维
2. **多 runner cost 格式各异**：仅 CCAdapter 开了 `parse_cost`（claude JSON）；codex/pi/dsh 的真实输出格式未采样，需各自适配 `extra_args`+解析器。⬅ P4
3. **调度器重启重臂**：`CronScheduler` 状态在内存，daemon 重启后所有 job 重新计时（可能重复/漏跑一次）。⬅ P4
4. **evolver LLM 留白**：`evolve.py` 只做 template_id 聚类，会话→模板候选的 LLM 归纳未接。⬅ P4
5. **Web 只读面窄**：无实时推送（SSE/WS）、无分页、graph 无布局；`POST /api/run` 未做（仅前端读 + gate 写）。⬅ P4
6. **Vault 产物落盘**：`Artifact`/`artifacts` 表已定义，执行结果未写文件/未链 Obsidian。⬅ P4

## 5. 可选后续（均为增强，按需）

- **P4-A｜多 runner cost 适配**：为 codex/pi/dsh 采样真实 JSON 输出，补各自 `extra_args` + 解析别名。
- **P4-B｜调度器持久化**：cron 上次触发时间落库（如复用 events），重启不重复/漏跑。
- **P4-C｜Web 增强**：SSE 实时刷新 + 列表分页 + `POST /api/run` 触发。
- **P4-D｜evolver LLM 通道**：会话聚类→LLM 归纳→模板候选（补设计文档的进化环）。
- **P4-E｜产物落盘**：执行结果写 Vault markdown + `create_artifact` 登记。
- **运维｜推远程**：建 GitHub 仓库 + push master，CI 自动生效。

## 6. 如何续作（恢复清单）

- 读本文 + `docs/superpowers/plans/2026-09-05-loom.md`（计划）+ `docs/superpowers/specs/2026-09-05-loom-design.md`（设计）。
- `git log --oneline` 是进度权威来源。
- 跑测试建立基线：`python -m pytest tests/ -q`（预期 **179 passed**）。
- 建议续作方式：新任务用 `superpowers:brainstorming` → 出 plan → `superpowers:subagent-driven-development` 执行；在隔离 worktree 内开发（`using-git-worktrees`）。
- 已完成批次（均 fast-forward 合并回 `master` 并清理 worktree/分支）：`loom-p0-daemon-gate`(P0-A/B) → `loom-p1-router-budget`(P1-C/D) → `loom-p2k-dispatch`(P2-K) → `loom-p2-batch`(P2-E/F/G/L + P3-H/J)。

## 7. 本会话环境备忘（可能仍适用）

- **子代理模型固定**：`~/.claude/settings.json` 里 `CLAUDE_CODE_SUBAGENT_MODEL` 早期固定到会 429 的 provider；切到 `deepseek/DeepSeek-V4-Flash-Vision-Exp[1m]` 后子代理恢复。若再遇子代理 429，优先检查此变量并更换 provider。
- **GateGuard 事实门禁**：本会话用 `ECC_GATEGUARD=off` 关闭了"每个文件创建前陈述事实"的门禁（用户批准）。若不希望继续关闭，可移除该 env。
- **平台**：Windows，Bash 工具为 Git Bash；测试须 `with Store(...)` 关连接，否则临时目录清理报 WinError 32。
- 本仓库无 git 远程（`git remote -v` 空）；`main` 分支不存在，基准是 `master`。

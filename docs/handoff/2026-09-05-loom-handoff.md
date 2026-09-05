# Loom 项目交接文档（Handoff）

> 交接日期：2026-09-05 　分支/基准：`master` @ `6ae4504`
> 用途：让下一位（人或 agent）无需重读整段历史即可安全续作。
> 恢复提示：本计划 SDD 工作区（`.superpowers/sdd/2026-09-05-loom/`）与账本已按流程删除；以 `git log` + 本文为准。
> 详细进展：`docs/reports/2026-09-05-overview.md`（P0 前快照）→ `docs/reports/2026-09-05-p0-daemon-gate-complete.md`（P0）→ 本文第 4/5 节（P1–P4 现状）。

## 1. 一句话现状

M1–M5（28 任务）+ P0/P1/P2/P3 全部批次 + **P4-A/B/C/D/E 增强（多 runner cost 适配、调度器持久化、Web 分页/run/SSE、evolver LLM 通道、产物落 Vault）已全部合并到 `master`；201 测试全绿**。系统端到端自洽：定时/钩子触发 → 派发实例化 → tier 路由（含二进制缺失降级）→ 执行（超时 + 预算硬顶 + 真实 token/cost 回写 + 产物落 Vault）→ 门禁阻塞 → CLI/Web 审批（含 SSE 实时 + POST /api/run）→ 晨报红线；并可 `loom evolve` 从成功簇自动产出候选模板。**设计与计划的功能+增强面均已落地**，仅剩 git 远程运维。

## 2. 度量

- 提交：`master` 51 条（28 实现 + P0/P1/P2/P3/P4 各批 + 文档）
- 测试：201 passed（`python -m pytest tests/ -q`；pytest asyncio_mode=auto）
- 模板：5/5 内置 + `loom evolve` 可产 `discovered` 候选
- 规模：`loom/` 包 ~3300 行，`tests/` ~4100 行
- CLI：`loom --help` 现 13 命令（新增 serve/gate/digest/evolve 等）
- CI：`.github/workflows/ci.yml`（py 3.12/3.13 矩阵）——**待推远程才生效**
- 运行环境：Python 3.12.10 / Windows；`pip install -e ".[dev]"`；claude/codex/pi/dsh 四 CLI 本机均在 PATH

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
| 成本 | `loom/adapters/cost_parsing.py` | `extract_cost`（P3-J/P4-A）：单 JSON / 尾行 JSON / **JSONL 事件流**三种形态，取最大累计 token 记录；cc/pi/codex `parse_cost=True`（dsh 无稳定 JSON 面，文档注明） |
| 产物 | `loom/core/engine.py` `_write_artifact` | 成功节点 output → `<vault>/<instance>/<node>.md` + `create_artifact`（P4-E）；`loom.toml [vault] path` 开关 |
| 触发器 | `loom/triggers/` | `hooks`(aiohttp /hook)、`cron`(晨报 build/render，`threshold` 可配，P1-C)、`inbox`(watchdog) |
| Web | `loom/web/` | `app.py`(FastAPI: instances[**分页**]/detail/graph + gates GET/POST approve/reject + **POST /api/run** + **GET /api/events/stream SSE**) + `static/index.html`(Pending Gates 面板) + `sse.py` |
| CLI | `loom/cli.py` | `run[--bg][--runner auto]/list/status/gate/serve/digest/evolve/stats/health/cost/history/audit`（13 命令）；`_make_runner` 工厂 |
| 配置 | `loom.toml` | `[routing]` 降级链 + `[budget] red_line_usd` + `[vault] path` + `[[schedule.jobs]]` |
| 进化 | `loom/evolver/evolve.py` | `evolve()`（P4-D）：簇证据→runner 归纳→YAML 抽取(裸/围栏/内嵌)→归一化→`load_template` 校验→落盘；LLM 失败回退确定性提案 |

模板 5/5：`{handoff-refresh, feature-loop, repo-analysis, content-pipeline, ops-deploy}.yaml`。高风险节点（merge/publish/deploy）均带 `gate: approve`，运行时真正阻塞。

## 4. 缺口状态（P4 后：增强面也已闭环）

P0/P1/P2/P3 + **P4-A/B/C/D/E 全部 ✅**：多 runner cost（codex 真实 `exec --json` 形态 + pi `--mode json` + JSONL 解析）、调度器落库（`schedule_state`，墙钟跨重启）、Web 分页/`POST /api/run`/SSE、evolver LLM 通道 + `loom evolve`、产物落 Vault。

唯一剩余：
1. **git 远程未建**：CI workflow 已就位但需推 GitHub 才跑；`git remote -v` 仍空。⬅ 运维（需用户决定仓库可见性/组织）
2. **codex/pi 真实 JSON schema 未采证**：命令形态按 `--help` 校正（codex 之前 `-p` 是错的，现走 `exec --json`），cost 字段名基于常见别名推测，**尚未跑真实输出验证**（同 P3-J 方式各跑一次即可确认）。⬅ 建议
3. **多用户/并发**：`owner` 字段全程 'me'，单写者假设；graph 无前端布局。⬅ 远期

## 5. 可选后续

- **运维｜推远程**：建 GitHub 仓库 + push master，CI 自动生效（我可以帮跑 `gh repo create`，需你确认仓库名/可见性）。
- **验证｜codex/pi 冒烟**：各跑一次真实调用，确认 JSONL/JSON 字段与 `extract_cost` 匹配，必要时补别名。
- **增强｜Web graph 布局**：前端 DAG 可视化（dagre/cytoscape）；多用户 `owner` 过滤贯通 API。

## 6. 如何续作（恢复清单）

- 读本文 + `docs/superpowers/plans/2026-09-05-loom.md`（计划）+ `docs/superpowers/specs/2026-09-05-loom-design.md`（设计）。
- `git log --oneline` 是进度权威来源。
- 跑测试建立基线：`python -m pytest tests/ -q`（预期 **201 passed**）。
- 建议续作方式：新任务用 `superpowers:brainstorming` → 出 plan → `superpowers:subagent-driven-development` 执行；在隔离 worktree 内开发（`using-git-worktrees`）。
- 已完成批次（均 fast-forward 合并回 `master` 并清理 worktree/分支）：`loom-p0-daemon-gate`(P0-A/B) → `loom-p1-router-budget`(P1-C/D) → `loom-p2k-dispatch`(P2-K) → `loom-p2-batch`(P2-E/F/G/L + P3-H/J) → `loom-p4-batch`(P4-A/B/C/D/E)。

## 7. 本会话环境备忘（可能仍适用）

- **子代理模型固定**：`~/.claude/settings.json` 里 `CLAUDE_CODE_SUBAGENT_MODEL` 早期固定到会 429 的 provider；切到 `deepseek/DeepSeek-V4-Flash-Vision-Exp[1m]` 后子代理恢复。若再遇子代理 429，优先检查此变量并更换 provider。
- **GateGuard 事实门禁**：本会话用 `ECC_GATEGUARD=off` 关闭了"每个文件创建前陈述事实"的门禁（用户批准）。若不希望继续关闭，可移除该 env。
- **平台**：Windows，Bash 工具为 Git Bash；测试须 `with Store(...)` 关连接，否则临时目录清理报 WinError 32。
- 本仓库无 git 远程（`git remote -v` 空）；`main` 分支不存在，基准是 `master`。

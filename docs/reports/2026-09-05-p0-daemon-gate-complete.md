# P0-A + P0-B 完成报告：Daemon 事件循环 + 交互式门禁

> 日期：2026-09-05 | 提交：`3f920e7`（fast-forward 合并至 `master`）
> 前置文档：`2026-09-05-next-steps.md`（P0 定义）、`2026-09-05-overview.md`（完成前快照）

## 一句话结论

Loom 已从「一次性 `loom run` 脚本」升级为「常驻事件驱动系统」：`loom serve` 同进程运行 daemon + web，门禁节点真正阻塞并支持 CLI / Web 双通道审批。

## 实现明细

### P0-A: Daemon 事件循环

| 组件 | 文件 | 说明 |
|------|------|------|
| 编排引擎 | `loom/core/engine.py` | `step_instance(store, instance_id, runner)`：从 DB 加载状态、计算 completed 集合（支持重启）、执行就绪节点、遇 `gate=approve` 挂起为 `waiting_gate` |
| Daemon | `loom/daemon.py` | `LoomDaemon` 异步 tick loop（默认 2s）：启动时崩溃恢复（running→pending）→ 处理 pending/running/waiting_gate 实例 |
| serve 命令 | `loom/cli.py` | `loom serve`：单进程 asyncio 同时跑 uvicorn + daemon，Ctrl+C graceful shutdown |
| run 改造 | `loom/cli.py` | `loom run` 默认同步执行但遇门禁暂停并提示；`--bg` 只建实例交 daemon 接管 |
| Store 补全 | `loom/core/store.py` | 新增 `list_instances_by_status` / `list_nodes` / `list_edges` / `update_node_status` / `update_instance_status`，并抽取 `_row_to_node` / `_row_to_instance` helper 去重 |

### P0-B: 交互式门禁

| 通道 | 入口 | 说明 |
|------|------|------|
| CLI | `loom gate list [--instance ID]` | 列出 `waiting_gate` 节点 |
| CLI | `loom gate approve <node_id> [--reason]` | 批准：`waiting_gate → running`，daemon 下个 tick 恢复执行 |
| CLI | `loom gate reject <node_id> --reason` | 拒绝：`waiting_gate → cancelled` |
| Web API | `GET /api/gates[?instance_id=X]` | 待批列表 |
| Web API | `POST /api/gates/{node_id}/approve` / `reject` | 审批决策 |
| 前端 | Pending Gates 面板 | Approve / Reject 按钮，Reject 弹出理由输入 |

## 关键设计决策（落地版）

| 决策 | 选择 | 理由 |
|------|------|------|
| 进程模型 | 单进程 asyncio（uvicorn + daemon） | SQLite 单写者天然匹配，零运维 |
| 调度策略 | 2s 轮询 tick | SQLite 无 push 能力；轮询简单可靠 |
| completed 追踪 | 从 DB 查 `status='succeeded'` | daemon 重启不丢状态 |
| 崩溃恢复 | 仅 daemon 启动首 tick 重置 running→pending | 避免每次 tick 覆盖刚审批的 gate |
| `loom run` 兼容 | 默认同步（+门禁暂停），`--bg` 委托 daemon | 不破坏既有用法 |

## 度量变化

| 指标 | P0 前 | P0 后 |
|------|-------|-------|
| 提交 | 33 | 35（+1 feat +1 merge 前快进） |
| 测试 | 106 | **132**（+26：store 5 / engine 5 / daemon 5 / cli-gate 5 / web-gate 6） |
| `loom/` 规模 | ~1846 行 | 2407 行 |
| `tests/` 规模 | ~2305 行 | 2907 行 |

## 剩余缺口（更新自 overview）

```
Daemon 常驻事件循环   ████████████████████  100%  ✅ (本次完成)
交互式门禁审批       ████████████████████  100%  ✅ (本次完成)
Tier 路由 + 预算      ░░░░░░░░░░░░░░░░░░░░   0%  ⬅ P1-C
适配器重构+超时       ░░░░░░░░░░░░░░░░░░░░   0%  ⬅ P1-D
触发器→实例自动派发    ░░░░░░░░░░░░░░░░░░░░   0%  🔴 事件仍无人消费转换
剩余模板             ░░░░░░░░░░░░░░░░░░░░   0%     P2-F
```

注：触发器（hooks/inbox）写入的 events 目前仍只是记录，尚未映射为「自动实例化模板」——需要 `event → template` 匹配逻辑（`Template.trigger` 字段已定义未使用）。

## 验证方式（已执行）

- `python -m pytest tests/ -q` → 132 passed
- 手动流程：`loom serve` + 另开终端 `loom run feature-loop --bg` → `loom gate list` → `loom gate approve <id>` → daemon 恢复并跑完

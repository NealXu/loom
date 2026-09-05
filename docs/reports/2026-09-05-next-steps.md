# Loom 下步工作推荐

> 日期：2026-09-05 | 基于：`2026-09-05-overview.md`

## P0 — 最高杠杆，立即做

| # | 工作 | 为什么 | 预估 |
|---|------|--------|------|
| **P0-A** | **Daemon + 事件循环** | 当前 `loom run` 是一次性内联编排；没有常驻进程消费 events、推进节点。这是从"脚本"到"系统"的分水岭。 | 2-3天 |
| **P0-B** | **交互式门禁** | `feature-loop` 的 merge 门禁当前自动放行，高风险操作无保护。需 `loom gate list/approve/reject` + Web 待批面板。 | 1天 |

### P0-A 设计要点

- `loom serve` — uvicorn 拉起 FastAPI web + daemon 事件循环
- `loom daemon` — 单写者事件消费：读 `events` → 找就绪实例 → `ready_nodes` → 适配器执行 → 状态推进
- 进程模型：单进程 asyncio 还是 multi-process？建议先单进程
- 崩溃恢复：重启后扫描 `running` 实例，重置为 `pending` 或标记 `blocked`

### P0-B 设计要点

- CLI: `loom gate list` / `loom gate approve <node_id>` / `loom gate reject <node_id> [--reason]`
- Web: 待批面板 + approve/reject 按钮（POST `/api/gate/{node_id}/decide`）
- `_run_instance` 遇到 `gate=approve` 时挂起实例，等待外部决策

## P1 — 核心能力补全

| # | 工作 | 说明 |
|---|------|------|
| P1-C | **Tier 路由 + 预算硬执行** | `router.py` + `loom.toml` 降级表（critical→cc, heavy→codex, tooling→pi, bulk→dsh）；`budget_tokens` 超限阻断；cost 累计贯通晨报 $5 红线 |
| P1-D | **适配器重构 + 超时** | 抽 `SubprocessAdapter` 基类去重 4 个近重复适配器；加 `asyncio.wait_for(timeout)` 防死锁 |

## P2 — 加固与补齐

| # | 工作 | 说明 |
|---|------|------|
| P2-E | **Store 数据访问层** | 补 `create_edge/create_event/create_artifact` + 查询方法，收敛 8 处裸 SQL |
| P2-F | **剩余 2 个模板** | `content-pipeline.yaml`, `ops-deploy.yaml` |
| P2-G | **加固** | web `response_model`、corrupted-JSON 错误路径测试、WAL 并发读测试、风格项清理（`returncode or 0`、函数内 `import json`、未用导入） |

## P3 — 工程化

| # | 工作 | 说明 |
|---|------|------|
| P3-H | **git remote + CI** | 建远程仓库、推 master、CI 跑 pytest |
| P3-I | **pip 入口验证** | `pip install -e .` 后 `loom --help` 可用 |
| P3-J | **端到端冒烟** | 对真实 cc/pi/codex/dsh CLI 跑 `loom run repo-analysis` 全链路 |

## 推荐执行顺序

```
P0-A (daemon)  ──▶  P0-B (门禁)  ──▶  P1-C (路由+预算)
                                       P1-D (适配器重构)
                                       P2-E (Store 补全)
                                       P2-F (剩余模板)
                                       P2-G (加固)
                                       P3-H/I/J (工程化)
```

P0-A 是最高杠杆项，建议先做设计再动手——事件消费语义、进程模型、崩溃恢复需要想清楚。

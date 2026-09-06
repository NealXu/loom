# Loom 项目最终状态报告

> 日期：2026-09-06  
> 分支：master @ `60abf94`  
> 测试：206 passed  
> 状态：**全部设计功能 + 增强面已闭环**

## 项目愿景

Loom 是一个两层图系统，将知识图谱（SQLite）与 DAG 编排结合，用于自动化日常工作流。核心理念：

1. **事件驱动**：触发器（hooks/inbox/cron）→ 事件派发 → 模板匹配 → 实例创建
2. **Tier 路由**：节点按 tier（critical/heavy/tooling/bulk）选择 runner，支持降级链
3. **预算硬顶**：累计成本触达 `node.budget_tokens` → 实例 blocked
4. **门禁审批**：高风险操作（deploy/merge/publish）需人工批准
5. **成本追踪**：从 agent CLI 真实输出解析 token/cost（claude/codex/pi）
6. **产物持久化**：成功节点输出写入 Vault markdown + 注册 Artifact
7. **LLM 进化**：`loom evolve` 从成功簇自动产出候选模板

## 完成度一览

```
核心功能（P0-P3）                    增强（P4）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ P0-A Daemon 事件循环              ✅ P4-A 多 runner cost 适配
✅ P0-B 交互式门禁                   ✅ P4-B 调度器持久化
✅ P1-C Tier 路由 + 预算硬执行        ✅ P4-C Web 增强（分页/SSE/POST run）
✅ P1-D 适配器重构 + 超时             ✅ P4-D Evolver LLM 通道
✅ P2-K Event→template 派发          ✅ P4-E 产物落 Vault
✅ P2-L Cron 调度器
✅ P2-E Store 写方法                 生产就绪（P5）
✅ P2-F 剩余模板（5/5）              ✅ P5-A Vault 启用 + e2e 验证
✅ P2-G 加固 + 配置贯通              ✅ P5-B SSE 前端 EventSource 消费
✅ P3-H 工程化（CI + 入口验证）       ✅ P5-C Evolver LLM 冒烟
✅ P3-J Cost 解析（真实 claude 冒烟） ✅ P5-D 多实例并发执行（tier 优先）
                                     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
运维                                  增强（P6）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Git 远程已建                       ✅ P6-A DAG 布局 dagre + CDN vendoring
   (github.com/NealXu/loom,          ✅ P6-B Web token 认证
    public, CI passing)              ✅ P6-C 多用户 owner 过滤
✅ cc/codex/pi 真实 schema 验证       ✅ P6-D Webhook 通知渠道
   (dsh 不使用)                      ✅ P6-E 模板市场 loom install
✅ Web DAG 可视化
```

## 架构全景

```
┌─────────────────────────────────────────────────────────────────┐
│                        触发器层                                  │
│  HTTP hooks (aiohttp) │ inbox (watchdog) │ cron │ POST /api/run │
└──────────────────────┼──────────────────┼──────┼───────────────┘
                       │                  │      │
                       ▼                  ▼      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Dispatcher (P2-K)                             │
│  Event → Template.trigger 匹配 → instantiate → 持久化实例        │
└─────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              Daemon (P0-A) + Scheduler (P2-L/P4-B)              │
│  异步 tick loop (2s) │ 崩溃恢复 │ schedule_state 持久化          │
│  CronScheduler → 定时产生 cron 事件 → dispatcher 派发            │
└─────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              step_instance Engine (P0-A/P1-C/P4-E)              │
│  Ready nodes │ gate 挂起 │ 预算检查 │ 成本回写 │ 产物落 Vault    │
└─────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              Router (P1-C) + Adapters (P1-D/P3-J/P4-A)          │
│  Tier→runner 选择 │ 二进制缺失降级 │ 超时杀进程 │ JSON/JSONL 解析 │
└─────────────────────────────────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┬──────────────┐
        ▼              ▼              ▼              ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │ claude  │   │ codex   │   │   pi    │   │   dsh   │
   │ cc CLI  │   │ exec    │   │ --mode  │   │ profile │
   │ -p JSON │   │ --json  │   │  json   │   │  boot   │
   └─────────┘   └─────────┘   └─────────┘   └─────────┘
        │              │              │              │
        └──────────────┴──────────────┴──────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────
│              Web UI + CLI (P0-B/P2-G/P4-C)                      │
│  门禁审批 │ 实例查询 │ 成本统计 │ SSE 实时 │ loom digest/evolve  │
│  **Cytoscape DAG 可视化**：节点按 instance 分组，状态着色，         │
│  有向箭头表示依赖，点击节点显示详情面板                             │
└─────────────────────────────────────────────────────────────────┘
```

## 度量统计

| 指标 | 数值 |
|------|------|
| 提交数 | ~65（P0-P6 全阶段） |
| 测试数 | **265 passed**（220 基线 + 45 P5/P6） |
| 代码行数 | `loom/` ~3600 行，`tests/` ~4800 行 |
| CLI 命令 | 14（+install） |
| 模板数 | 5 内置 + `discovered` 候选通道 + 远程安装 |
| 适配器 | 5（cc/pi/codex/dsh/fake） |
| 配置节 | `loom.toml` 7 节：`[routing]` `[budget]` `[vault]` `[[schedule.jobs]]` `[web]` `[user]` `[[notifications.webhooks]]` |

## 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 进程模型 | 单进程 asyncio（uvicorn + daemon） | SQLite 单写者天然匹配，零运维 |
| 调度策略 | 2s 轮询 tick | SQLite 无 push 能力；轮询简单可靠 |
| 状态持久化 | `schedule_state` 表（墙钟 time.time()） | 重启不重复触发/不丢节奏 |
| 已完成节点追踪 | 从 DB 查 `status='succeeded'` | daemon 重启不丢状态 |
| 成本解析 | JSON/JSONL 通用 walker（取最大累计记录） | 覆盖 claude/codex/pi 三种形态 |
| 门禁流 | `waiting_gate` 状态 + daemon tick 恢复 | 无需轮询，事件驱动 |
| DAG 可视化 | Cytoscape.js (vendor/) + dagre 拓扑布局 | compound nodes 支持 instance 分组；本地 vendored 消除 CDN 依赖 |
| 产物持久化 | `<vault>/<instance>/<node>.md` + `create_artifact` | best-effort，永不拖垮节点 |
| Evolver | LLM 归纳 → YAML 抽取 → `load_template` 校验 → 落盘 | LLM 失败自动回退确定性提案 |
| 并发执行 | asyncio.gather + Semaphore(max_concurrent=2) + tier 排序 | 单线程 asyncio 内安全并发；tier 保证 critical 优先 |
| 通知系统 | Webhook POST + daemon 内触发 | 零外部依赖；失败日志不阻断流程 |
| 模板市场 | `loom install <url|path>` + overwrite 保护 | 社区共享入口；--force 安全覆盖 |

## 使用场景

### 场景 1：每日晨报（定时触发）

```yaml
# loom.toml
[[schedule.jobs]]
template = "handoff-refresh"
every_seconds = 86400
params = { project_path = "." }
```

```bash
loom serve --runner auto
# 每日 0 点自动：扫描项目 → 重写 handoff.md → 门禁等待 → approve → 提交
```

### 场景 2：特性开发（CLI 触发 + 门禁）

```bash
loom run feature-loop --runner cc --params '{"branch": "feat/auth"}' --bg
# daemon 执行：实现 → 测试 → 审查 → merge 门禁 → approve → 合并
loom gate list
loom gate approve <node_id> --reason "Tests pass"
```

### 场景 3：内容发布（收件箱触发 + 门禁）

```bash
# inbox 目录放入 task.txt
# daemon 自动匹配 content-pipeline 模板
# 研究 → 草稿 → 润色 → publish 门禁 → approve → 发布
```

### 场景 4：成本监控

```bash
loom cost              # 聚合成本
loom cost <instance>   # 实例级
loom digest            # 晨报（成本超 $5 标红）
```

### 场景 5：模板进化

```bash
loom evolve --runner cc --out loom/templates/discovered
# 从成功簇自动产出候选模板 → 人工审查 → 纳入模板库
```

## 状态总结

### P0-P6 全部闭环

| 阶段 | 状态 | 说明 |
|------|------|------|
| P0 | ✅ | Daemon + 门禁 |
| P1 | ✅ | 路由 + 预算 + 超时 |
| P2 | ✅ | 派发 + 调度 + 模板 |
| P3 | ✅ | CI + 成本解析 |
| P4 | ✅ | Web + Evolver + Vault |
| P5 | ✅ | Vault 启用 + SSE + Evolver 冒烟 + 并发 |
| P6 | ✅ | DAG vendoring + 认证 + 多用户 + 通知 + 模板市场 |

### 运维事项

1. ✅ **Git 远程**：`github.com/NealXu/loom` (public)，CI passing (3.12+3.13)。
2. ✅ **真实 schema 验证**：cc/codex/pi 已验证，dsh 不使用。
3. ✅ **CDN vendoring**：Cytoscape/graphlib/dagre 本地化，零外部依赖。

### 未来增强（可选 backlog）

- **技术债**：Store 裸 SQL 统一收敛 → Store 方法；mypy 类型注解扫描
- **体验**：前端 login 表单（配合 /api/auth）；SSE 实时 DAG 增量更新
- **平台**：多租户隔离（owner 贯穿 DB 查询）；模板版本管理
| T1 | **CDN 降级** | Cytoscape CDN 不可达时 fallback 到文本模式；或 vendoring 到 `static/vendor/` |
| T2 | **Store 抽象统一** | `/api/graph` 已用 `store.get_graph()`，但 `/api/instances/{id}` 仍用裸 SQL |
| T3 | **类型注解补全** | 部分函数缺少类型提示，可用 mypy 扫描 |

## 技术栈

- **Python 3.12+**
- **SQLite** (WAL mode) — 知识图谱
- **FastAPI** + **uvicorn** — Web 服务
- **Click** — CLI
- **aiohttp** — 异步 HTTP（webhooks）
- **watchdog** — 文件系统监控
- **pytest** + **pytest-asyncio** — 测试

## 许可证

See [LICENSE](LICENSE) for details.

---

**Loom 至此：设计与计划的功能面 + 增强面全部闭环。** 从最初的静态内核，到现在的完整事件驱动系统。

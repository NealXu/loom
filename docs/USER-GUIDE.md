# Loom 使用指南

**工作流编排器 — 让 AI Agent 自动完成你的日常工作**

Loom 是一个两层图系统，将**知识图谱**（SQLite）与**DAG 任务编排**结合，用于调度、执行和审计由 AI Agent CLI（Claude Code / Codex / Pi）驱动的多步骤工作流。

---

## 目录

1. [系统概览](#1-系统概览)
2. [安装与启动](#2-安装与启动)
3. [Web UI 总览](#3-web-ui-总览)
4. [仪表盘（Dashboard）](#4-仪表盘dashboard)
5. [运行模板（Run）](#5-运行模板run)
6. [历史记录（History）](#6-历史记录history)
7. [审计时间线（Audit）](#7-审计时间线audit)
8. [成本分析（Cost）](#8-成本分析cost)
9. [每日摘要（Digest）](#9-每日摘要digest)
10. [模板管理（Templates）](#10-模板管理templates)
11. [CLI 常用命令](#11-cli-常用命令)
12. [门控审批（Gate）](#12-门控审批gate)
13. [常见问题](#13-常见问题)

---

## 1. 系统概览

### 架构全景

```
┌─────────────────────────────────────────────────────────────┐
│                      触发源 (Triggers)                       │
│   HTTP Hooks   │   Cron 定时   │   Inbox 文件   │   CLI     │
└───────┬────────┴───────┬───────┴───────┬────────┴─────┬────┘
        │                │               │              │
        ▼                ▼               ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Dispatcher (事件分发)                       │
│            匹配模板 → 创建 Instance → 入队                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Scheduler (调度器)                         │
│   Kahn 拓扑排序 → 按依赖顺序解锁节点 → 按 Tier 优先级调度      │
│                                                           │
│   Tier: critical > heavy > tooling > bulk                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
     ┌──────────┐   ┌──────────┐   ┌──────────┐
     │ Claude   │   │  Codex   │   │   Pi     │   ← Runners
     │  Code    │   │          │   │          │
     └────┬─────┘   └────┬─────┘   └────┬─────┘
          │              │              │
          ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Knowledge Graph (SQLite)                   │
│   Instances · Nodes · Edges · Events · Artifacts            │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                  Web UI (http://127.0.0.1:8000)             │
│   Dashboard · Run · History · Audit · Cost · Digest         │
└─────────────────────────────────────────────────────────────┘
```

### 核心概念

| 概念 | 说明 |
|------|------|
| **Template** | YAML 定义的工作流模板，包含节点和依赖关系 |
| **Instance** | 模板的一次运行实例 |
| **Node** | 实例中的一个执行步骤，有状态（pending → running → succeeded/failed） |
| **Gate** | 需要人工审批的高风险节点，暂停执行直到 Approve/Reject |
| **Runner** | 执行 Agent CLI 的适配器（cc / codex / pi / dsh） |
| **Tier** | 节点优先级：critical → heavy → tooling → bulk |

### 状态机

```
  pending ──▶ running ──▶ succeeded
                │
                ├──▶ waiting_gate ──▶ succeeded (approved)
                │                  ──▶ failed    (rejected)
                │
                ├──▶ failed
                ├──▶ blocked
                └──▶ cancelled
```

---

## 2. 安装与启动

### 前置条件

- Python 3.12+
- Git
- 可选：Agent CLI 工具（`claude` / `codex` / `pi` / `dsh`）

### 安装

```bash
git clone git@github.com:NealXu/loom.git
cd loom
pip install -e ".[dev]"
```

### 启动守护进程

```bash
loom serve --runner auto --config loom.toml --templates loom/templates
```

启动后：
- **Web UI** → http://127.0.0.1:8000
- **SSE 实时事件流** → `/api/events/stream`
- **所有 REST API** → `/api/*`

### 配置（loom.toml）

```toml
[routing]            # Tier → Runner 路由链
critical = ["cc"]    # 关键任务只用 Claude Code
heavy    = ["codex", "cc"]
tooling  = ["pi", "dsh"]
bulk     = ["dsh", "pi"]

[budget]
red_line_usd = 5.0   # 超过此金额标红告警

[vault]
path = "./vault_out"  # 成功节点输出持久化到此目录

[web]
# auth_token = "your-secret"  # 可选：Bearer Token 认证
```

---

## 3. Web UI 总览

打开 http://127.0.0.1:8000，你会看到左侧导航栏 + 右侧内容区的布局：

```
┌──────────────────────────────────────────────────────────┐
│ ┌──────────┐ ┌─────────────────────────────────────────┐ │
│ │          │ │                                         │ │
│ │  Loom    │ │    [状态栏: Loaded 3 instances, ...]    │ │
│ │ 工作流   │ │                                         │ │
│ │ 编排器   │ │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐      │ │
│ │          │ │  │  2  │ │  1  │ │  5  │ │  0  │      │ │
│ │ ─────── │ │  │运行中│ │ 失败 │ │ 成功 │ │待处理│      │ │
│ │ [中][EN] │ │  └─────┘ └─────┘ └─────┘ └─────┘      │ │
│ │          │ │                                         │ │
│ │ 📊 仪表盘│ │  ┌──────────────┐ ┌──────────────────┐  │ │
│ │ ▶ 运行   │ │  │  实例列表     │ │  待处理门控       │  │ │
│ │   历史   │ │  │              │ │                  │  │ │
│ │   审计   │ │  │ ▸ inst-abc.. │ │  (无待处理门控)   │  │ │
│ │   成本   │ │  │ ▸ inst-def.. │ │                  │  │ │
│ │   摘要   │ │  │ ▸ inst-ghi.. │ │                  │  │ │
│ │   模板   │ │  └──────────────┘ └──────────────────┘  │ │
│ │          │ │                                         │ │
│ │          │ │  ┌─────────────────────────────────────┐│ │
│ │          │ │  │         依赖图 (DAG)                ││ │
│ │          │ │  │   [scan] → [analyze] → [report]     ││ │
│ │          │ │  └─────────────────────────────────────┘│ │
│ └──────────┘ └─────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### 侧边导航栏

| 图标 | 页面 | 功能 |
|------|------|------|
| 📊 | **仪表盘** | KPI 概览 + 实例列表 + 门控 + DAG 图 |
| ▶ | **运行** | 选择模板并启动工作流 |
| 🕐 | **历史** | 所有实例的可排序表格 |
| ✓ | **审计** | 状态变更与门控决策的时间线 |
| 💰 | **成本** | 按模板/实例的费用分析 |
| 📋 | **摘要** | 每日汇总 + 超预算告警 |
| 📦 | **模板** | 查看/安装模板 |

### 语言切换

侧边栏顶部有 **中文 / EN** 切换按钮，默认中文，选择会保存到浏览器 localStorage。

---

## 4. 仪表盘（Dashboard）

仪表盘是首页，展示系统全局状态。

### KPI 卡片

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│    2     │  │    1     │  │    5     │  │    0     │
│  运行中   │  │   失败   │  │   成功   │  │  待处理   │
└──────────┘  └──────────┘  └──────────┘  └──────────┘
```

- **运行中**（蓝色）：当前正在执行的实例数
- **失败**（红色）：执行失败的实例数
- **成功**（绿色）：已完成的实例数
- **待处理**（黄色）：等待调度或等待门控审批的实例数

### 实例列表面板

左侧面板展示最近的实例，每个实例显示：

```
┌─────────────────────────────┐
│  repo-analysis-20260908     │
│  ● succeeded    $0.1234     │
├─────────────────────────────┤
│  content-pipeline-abc       │
│  ● running      $2.5678     │
├─────────────────────────────┤
│  ops-deploy-xyz             │
│  ● failed       $5.1000     │  ← 超预算标红
└─────────────────────────────┘
```

- **颜色徽章**：succeeded（绿）/ running（蓝）/ failed（红）/ pending（黄）/ blocked（紫）
- **金额**：实例累计消耗的 Agent 费用（USD）
- **红色金额**：超过 $5 预算红线的实例

### 门控面板

右侧面板展示等待人工审批的节点：

```
┌──────────────────────────────────┐
│  🔒 publish-node                 │
│  Instance: inst-abc | Kind: deploy │
│                                  │
│  [✓ Approve]  [✗ Reject]        │
└──────────────────────────────────┘
```

- 点击 **Approve** → 节点继续执行
- 点击 **Reject** → 弹出对话框输入原因，节点标记为 failed

### DAG 依赖图

底部面板展示所有实例的 DAG 图，使用 Cytoscape.js 渲染：

```
┌─────────────────────────────────────────────┐
│                                             │
│   ┌──────── repo-analysis ────────┐        │
│   │                               │        │
│   │  [scan] ──▶ [analyze] ──▶ [report]    │
│   │    ●          ●            ●           │
│   │  succeeded   running     pending       │
│   └───────────────────────────────┘        │
│                                             │
│   ┌──── content-pipeline ─────────┐        │
│   │                               │        │
│   │  [research] ──▶ [draft] ──▶ [polish]   │
│   │      ●           ●           ●        │
│   │   succeeded    succeeded   waiting_gate│
│   │                    │                    │
│   │                  [publish]              │
│   │                     ●                   │
│   │              waiting_gate               │
│   └───────────────────────────────┘        │
│                                             │
└─────────────────────────────────────────────┘
```

**节点颜色**：
- 🟢 绿色 = succeeded
- 🔵 蓝色 = running
- 🟡 黄色 = waiting_gate（等待审批）
- 🔴 红色 = failed
- ⚪ 灰色 = pending / cancelled

**交互**：点击任意节点 → 底部弹出节点详情面板，显示 id、kind、status、tier、gate、spec、budget_tokens 等字段。

### 实时更新

仪表盘通过 **SSE (Server-Sent Events)** 自动接收后端事件推送。每当有实例状态变化，页面会在 2 秒内自动刷新数据，无需手动操作。

---

## 5. 运行模板（Run）

点击侧边栏的 **▶ 运行**，进入模板运行页面：

```
┌──────────────────────────────────────┐
│  运行模板                             │
│                                      │
│  模板                                │
│  ┌──────────────────────────────┐   │
│  │ ▼ repo-analysis              │   │
│  └──────────────────────────────┘   │
│                                      │
│  项目路径                             │
│  ┌──────────────────────────────┐   │
│  │ D:/Codes/innovation/loom     │   │
│  └──────────────────────────────┘   │
│                                      │
│  参数 (JSON)                          │
│  ┌──────────────────────────────┐   │
│  │ {"key": "value"}             │   │
│  └──────────────────────────────┘   │
│                                      │
│  执行器                              │
│  ┌──────────────────────────────┐   │
│  │ ▼ Default Runner             │   │
│  └──────────────────────────────┘   │
│                                      │
│  执行模式                             │
│  ○ 异步   ● 同步                     │
│                                      │
│  [▶ 运行模板]                         │
└──────────────────────────────────────┘
```

### 操作步骤

1. **选择模板** — 从下拉菜单选择要运行的工作流模板
2. **填写项目路径** — 指定工作目录（绝对路径）
3. **填写参数**（可选） — JSON 格式的额外参数
4. **选择执行器**（可选） — Default / Local / Remote
5. **选择执行模式**：
   - **异步**（推荐） — 提交后由守护进程后台执行，页面立即返回
   - **同步** — 阻塞等待执行完成
6. **点击「运行模板」** — 提交到 `/api/run`，右上角弹出绿色成功提示

### 内置模板

| 模板 | 说明 | 所需参数 |
|------|------|----------|
| `repo-analysis` | 扫描仓库结构、分析代码架构 | `project_path` |
| `content-pipeline` | 调研 → 起草 → 润色 → 发布（发布需门控审批） | `topic` |
| `feature-loop` | 在分支上实现功能、测试、评审（合并需门控） | `branch` |
| `handoff-refresh` | 扫描项目并重写 handoff.md | `project_path` |
| `ops-deploy` | 预检 → 构建 → 部署（需门控）→ 验证 | `target` |

---

## 6. 历史记录（History）

点击 **🕐 历史** 查看所有实例的执行记录：

```
┌──────────────────────────────────────────────────────────────┐
│  实例历史                                                     │
│                                                              │
│  模板: [▼ repo-analysis ▾]   状态: [▼ 全部状态 ▾]             │
│                                                              │
│  ┌────────┬───────────────┬───────────┬──────┬────────┬─────┐
│  │   ID   │    模板       │   状态    │ 执行器│  费用  │ 创建时间│
│  ├────────┼───────────────┼───────────┼──────┼────────┼─────┤
│  │ abc... │ repo-analysis │ succeeded │  cc  │ $0.12  │ 9/8 │
│  │ def... │ content-pipe  │ running   │ codex│ $2.56  │ 9/8 │
│  │ ghi... │ ops-deploy    │ failed    │  cc  │ $5.10  │ 9/7 │
│  └────────┴───────────────┴───────────┴──────┴────────┴─────┘
└──────────────────────────────────────────────────────────────┘
```

### 功能

- **排序** — 点击任意列标题（ID / 模板 / 状态 / 执行器 / 费用 / 创建时间）切换升序/降序
- **筛选** — 按模板名称或状态过滤
- **费用高亮** — 超过 $5 的费用以红色粗体显示

---

## 7. 审计时间线（Audit）

点击 **✓ 审计** 查看系统所有状态变更的门控决策记录：

```
┌──────────────────────────────────────┐
│  审计时间线                           │
│                                      │
│  ● 2026-09-08 10:30                 │
│  │ node scan: pending → running     │
│  │ · instance inst-abc              │
│  │                                   │
│  ● 2026-09-08 10:32                 │
│  │ node scan: running → succeeded   │
│  │ · instance inst-abc              │
│  │                                   │
│  ● 2026-09-08 10:35                 │
│  │ Gate Approved · node publish     │
│  │ · instance inst-def              │
│  │ · by user (LGTM)                 │
│  │                                   │
│  ● 2026-09-08 10:40                 │
│  │ node analyze: running → failed   │
│  │ · instance inst-ghi              │
└──────────────────────────────────────┘
```

每条记录包含：
- **时间戳** — 精确到秒
- **事件类型** — 状态转换（`entity: from → to`）或门控决策（`Gate Approved/Rejected`）
- **关联实例** — instance ID
- **操作者** — 门控决策的审批人/拒绝人
- **原因** — Reject 时填写的原因

---

## 8. 成本分析（Cost）

点击 **💰 成本** 查看 AI Agent 执行费用：

### 图表视图

```
┌──────────────────────────────────────┐
│  成本分析                             │
│  [ 表格视图 ]                         │
│                                      │
│  repo-analysis  ████████████  $0.12  │
│  content-pipe   ████████████████████ $2.56 │
│  ops-deploy     ████████████████████████████ $5.10 │ ← 红色=超预算
│  feature-loop   ████████  $0.89      │
└──────────────────────────────────────┘
```

### 表格视图

点击「表格视图」按钮切换到表格：

| Instance | Template | Cost (USD) | Tokens |
|----------|----------|-----------|--------|
| inst-abc | repo-analysis | $0.1234 | 15,200 |
| inst-def | content-pipeline | $2.5678 | 42,800 |
| inst-ghi | ops-deploy | **$5.1000** | 98,500 |

- **红色条目** = 超过预算红线（$5）
- 图表和表格可一键切换

---

## 9. 每日摘要（Digest）

点击 **📋 摘要** 查看当天汇总：

```
┌──────────────────────────────────────────────────────┐
│  ⚠ 警告：部分实例超出预算红线                           │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │  总费用       │  │  总实例数     │  │  总 Token  │ │
│  │  $12.3456    │  │     8        │  │   256,000  │ │
│  └──────────────┘  └──────────────┘  └────────────┘ │
│                                                      │
│  ┌──────────────┐                                    │
│  │  超预算实例   │                                    │
│  │      2       │                                    │
│  └──────────────┘                                    │
└──────────────────────────────────────────────────────┘
```

- **总费用** — 当日所有实例累计 USD 费用
- **总实例数** — 当日运行的实例总数
- **总 Token** — 消耗的 AI Token 总量
- **超预算实例** — 费用超过 `red_line_usd`（默认 $5）的实例数
- 当存在超预算实例时，顶部显示红色告警横幅

CLI 也可查看：`loom digest`

---

## 10. 模板管理（Templates）

点击 **📦 模板** 查看和安装模板：

### 安装模板

```
┌──────────────────────────────────────┐
│  安装模板                             │
│                                      │
│  来源 URL                             │
│  ┌──────────────────────────────┐   │
│  │ https://example.com/tpl.yaml │   │
│  └──────────────────────────────┘   │
│                                      │
│  [ 安装模板 ]                         │
└──────────────────────────────────────┘
```

- 支持从 URL 或本地路径安装社区模板
- CLI: `loom install <url-or-path>`

### 已安装模板列表

下方展示当前系统中所有可用模板，每个模板显示名称和描述。

### 自定义模板

在 `loom/templates/` 目录创建 YAML 文件即可：

```yaml
id: my-workflow
version: 1
trigger: [cli]
params:
  target: {type: string, required: true}
nodes:
  - id: step-one
    kind: analysis
    tier: heavy
    spec: "分析 {{target}} 并生成摘要"
    depends_on: []
  - id: step-two
    kind: coding
    tier: tooling
    gate: approve            # 需要人工审批
    spec: "根据分析结果执行修改"
    depends_on: [step-one]
```

参数用 `{{param_name}}` 在 spec 中引用。

---

## 11. CLI 常用命令

除了 Web UI，Loom 还提供完整的 CLI 界面：

```
$ loom --help

Usage: loom [COMMAND]

Commands:
  serve      启动守护进程 + Web 服务器
  run        运行一个模板
  list       列出所有实例
  status     查看实例详情
  stats      系统统计
  health     健康检查
  cost       费用分析
  history    执行历史
  audit      审计日志
  gate       门控管理 (list / approve / reject)
  digest     每日摘要
  evolve     LLM 驱动的模板发现
  install    安装社区模板
```

### 常用场景

```bash
# 启动守护进程
loom serve --runner auto --config loom.toml

# 运行分析模板
loom run repo-analysis --runner cc --params '{"project_path": "."}'

# 后台运行
loom run feature-loop --runner codex --params '{"branch": "feat/x"}' --bg

# 查看系统状态
loom list
loom status <instance_id>
loom stats
loom health

# 费用查看
loom cost                  # 总览
loom cost <instance_id>    # 按实例

# 门控审批
loom gate list
loom gate approve <node_id> --reason "LGTM"
loom gate reject <node_id> --reason "需要修改"
```

---

## 12. 门控审批（Gate）

门控是 Loom 的安全机制，用于在高风险操作前暂停等待人工确认。

### 何时触发

- 节点 YAML 中配置了 `gate: approve`
- 节点 kind 为 `deploy` 或 `review`（自动要求门控）

### 审批方式

**方式一：Web UI**

在仪表盘的「待处理门控」面板，点击 Approve 或 Reject 按钮。

**方式二：CLI**

```bash
# 查看待审批门控
loom gate list

# 批准
loom gate approve <node_id> --reason "LGTM"

# 拒绝
loom gate reject <node_id> --reason "测试未通过"
```

### 流程图

```
  节点执行到 gate ──▶ 状态变为 waiting_gate ──▶ 暂停
                                                   │
                              ┌─────────────────────┘
                              │
                     ┌────────▼────────┐
                     │  人工审批        │
                     │                 │
                ┌────┴────┐       ┌────┴────┐
                │ Approve │       │ Reject  │
                └────┬────┘       └────┬────┘
                     │                 │
                     ▼                 ▼
               succeeded            failed
               继续执行             实例终止
```

---

## 13. 常见问题

### Q: Web UI 打不开？

确认 `loom serve` 正在运行，默认端口 8000。如果被占用，检查终端输出中的实际端口。

### Q: 图表没有渲染？

确认浏览器能加载 `/static/vendor/` 下的 JS 文件（cytoscape、dagre 等）。这些文件已本地打包，无需联网。

### Q: 如何修改预算红线？

编辑 `loom.toml` 中的 `[budget]` 段：

```toml
[budget]
red_line_usd = 10.0   # 改为 $10
```

重启 `loom serve` 生效。

### Q: 如何开启 API 认证？

在 `loom.toml` 中设置：

```toml
[web]
auth_token = "your-secret-token"
```

或通过环境变量 `LOOM_AUTH_TOKEN=your-secret`。设置后所有 `/api/` 端点需要 Bearer Token。

### Q: 节点输出保存在哪里？

成功节点的输出会写入 `loom.toml` 中 `[vault]` 配置的路径：

```
vault_out/
  └── <instance_id>/
      ├── <node_id>.md
      └── ...
```

每个输出同时注册为 Artifact 记录在数据库中。

### Q: 如何发现新模板？

```bash
loom evolve --runner cc --out loom/templates/discovered
```

LLM 会分析历史成功实例的聚类模式，自动生成候选模板 YAML。

---

## 附录：REST API 速查

| Endpoint | Method | 说明 |
|----------|--------|------|
| `/api/instances` | GET | 实例列表（分页） |
| `/api/instances/{id}` | GET | 实例详情 |
| `/api/graph` | GET | 全量图数据 |
| `/api/gates` | GET | 待审批门控 |
| `/api/gates/{id}/approve` | POST | 批准门控 |
| `/api/gates/{id}/reject` | POST | 拒绝门控 |
| `/api/run` | POST | 启动工作流 |
| `/api/events/stream` | GET | SSE 实时事件 |
| `/api/templates` | GET | 模板列表 |
| `/api/stats` | GET | 系统统计 |
| `/api/health` | GET | 健康摘要 |
| `/api/audit` | GET | 审计时间线 |
| `/api/digest` | GET | 每日摘要 |
| `/api/cost` | GET | 成本分析 |
| `/api/auth` | POST | Token 验证 |

---

*Loom — 让工作流自己编织自己。*

# Loom 文档索引

> 本目录是 Loom 项目所有非代码文档的根。

## 目录结构

```
docs/
├── README.md              ← 本文件，目录索引
├── handoff/               ← 交接文档
│   └── YYYY-MM-DD-*.md       给人或 agent 的快速恢复指南，含现状、缺口、续作方式
├── reports/               ← 进展报告与全景快照
│   └── YYYY-MM-DD-*.md       项目状态总结、完成度、下步计划
└── superpowers/           ← superpowers 工具链产出物
    ├── plans/                实施计划（task breakdown）
    └── specs/                设计规格（architecture, data model, decisions）
```

## 各子目录用途

| 目录 | 用途 | 谁写 | 何时写 |
|------|------|------|--------|
| `handoff/` | 交接文档 — 给下一位（人或 agent）无需重读历史即可续作 | 会话结束前 / 里程碑完成时 | 按命名 `YYYY-MM-DD-<topic>-handoff.md` |
| `reports/` | 进展报告 — 全景快照、完成度、下步推荐 | 按需 / 用户请求时 | 按命名 `YYYY-MM-DD-<topic>.md` |
| `superpowers/plans/` | superpowers 生成的实施计划 | `superpowers:writing-plans` 等技能 | 按命名 `YYYY-MM-DD-<project>.md` |
| `superpowers/specs/` | superpowers 生成的设计规格 | `superpowers:brainstorming` 等技能 | 按命名 `YYYY-MM-DD-<project>-design.md` |

## 当前文档清单

- `handoff/2026-09-05-loom-handoff.md` — 交接文档（P1 后已更新）：153 tests green，剩余缺口与 P2+ 计划
- `reports/2026-09-05-overview.md` — 项目全景进展：架构图、完成度、模块清单（P0 前快照）
- `reports/2026-09-05-next-steps.md` — 下步工作推荐：P0-P3 优先级与执行顺序（P0/P1 已完成）
- `reports/2026-09-05-p0-daemon-gate-complete.md` — P0-A/B 完成报告：daemon + 门禁实现明细与验证
- `superpowers/plans/2026-09-05-loom.md` — SDD 实施计划（28 任务）
- `superpowers/specs/2026-09-05-loom-design.md` — 设计规格：两层图系统架构

# AGENTS.md

> AgentConch 的指令文件 — 只当目录，不当超级 Prompt。
> 每一行对应一个历史教训。Agent 在此项目工作时，先读此文件。

## 项目定位

Agent Harness Engineering 技术实践平台。不是产品，是实验底座。

## 核心架构（详见 docs/technical-design.md）

- **9 大能力域**：信息边界 / 工具系统 / 上下文管理 / 记忆状态 / 执行编排 / 评估验证 / 可观测性 / 约束恢复 / 治理
- **三层扩展模型**：Plugin（域内新实现）→ Hook/中间件（横切逻辑）→ 自定义能力域（全新维度）
- **三件套**：Registry 注册中心 + Profile 实验配置 + Experiment 对比框架
- **依赖倒置**：核心层只定义接口，能力域反向依赖核心

## 关键约定

- 新技术点先放 `plugins/`，验证有效后再沉淀进 `conch/domains/`
- 核心包 `conch/core/` 极少改动，只加接口不加业务
- 能力域接口定义 WHAT 不定义 HOW
- Hook 只触发副作用，中间件只处理数据流，二者职责隔离
- MVP 先做 4 域最小闭环（Loop + Tool + AGENTS.md + Trace），按需补层

## 技术选型

- Python 3.11+ / asyncio
- Pydantic v2（Profile 校验）/ OpenTelemetry（可观测性）/ Docker（沙箱）

## 目录导航

```
conch/core/       → 核心抽象（稳定，极少改动）
conch/domains/    → 9 域默认实现
conch/runtime/    → 运行时适配（LLM/沙箱/存储）
profiles/         → 实验配置（YAML）
plugins/          → 新技术点实验区
docs/             → 技术方案 + 技术点详解
benchmarks/       → 评测任务集
```

## 技术点文档索引

详见 `docs/technical-points/` 目录，每个核心技术点有独立文档。

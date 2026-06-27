# AGENTS.md

> AgentConch 的指令文件 — 只当目录，不当超级 Prompt。
> 每一行对应一个历史教训。Agent 在此项目工作时，先读此文件。

## 项目定位

Agent Harness Engineering 技术实践平台。v2 定位：可运行的 harness 应用 + 可扩展的研究底座（双栖）。

## 核心架构（详见 docs/technical-design-v2.md）

- **10 大能力域**：信息边界 / 工具系统 / 上下文管理 / 记忆状态 / 执行编排 / 评估验证 / 可观测性 / 约束恢复 / 治理 / **护栏**（v2 新增）
- **五层架构**：前端层(Next.js) / API网关层(FastAPI) / Harness可扩展层(core) / 成熟框架底座层(adapters) / 运行时层
- **三件套叠加机制**：Registry 包装成熟框架组件为 Plugin / Profile 声明框架组合 / Hook 桥接到框架原生事件点
- **核心创新**：Hook 桥接层（core/hook_bridge.py）——框架事件→语义Hook总线，换引擎只需新写桥接Plugin
- **依赖倒置**：核心层只定义接口，adapters 反向依赖核心

## 关键约定

- 新技术点先放 `backend/plugins/`，验证有效后再沉淀进 `backend/conch/adapters/`
- 核心包 `backend/conch/core/` 极少改动，只加接口不加业务
- 能力域接口定义 WHAT 不定义 HOW，接口不泄漏框架概念
- Hook 只触发副作用，中间件只处理数据流，二者职责隔离
- 成熟框架优先，自研收敛到可扩展层

## 技术选型（v2）

- 后端：Python 3.10+ / FastAPI / LangGraph / MCP / litellm / NeMo Guardrails / Langfuse / Pydantic v2
- 前端：Next.js 14 / TypeScript / Tailwind / zustand
- 存储：PostgreSQL + Chroma + Redis（阶段二）；MVP 内存
- 沙箱：Docker

## 目录导航

```
backend/conch/core/       → 核心抽象（稳定，极少改动，框架无关）
backend/conch/adapters/   → 成熟框架适配层（包装为 Plugin）
backend/conch/api/        → FastAPI 路由（SSE/WS/REST）
backend/conch/runtime/    → 运行时（沙箱/存储）
backend/profiles/         → 实验配置（YAML）
backend/plugins/          → 新技术点实验区
frontend/                 → Next.js 前端
docs/                     → 技术方案 + 技术点详解
benchmarks/               → 评测任务集
```

## 技术点文档索引

详见 `docs/technical-points/` 目录，每个核心技术点有独立文档。

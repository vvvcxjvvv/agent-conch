# AgentConch v2 技术点文档

> 基于 `technical-design-v2.md` 与 `implementation-status-v2.md`，结合实际代码，覆盖 v2 核心组件的实现原理与加载使用方式。
>
> 组件划分参考 ETCLOVG 七层模型（HarnessEngineering 实现方案）。

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  前端层 (Next.js 14) — 三栏布局: 会话/对话+轨迹/实时指标    │
├─────────────────────────────────────────────────────────────┤
│  API 网关层 (FastAPI) — SSE 流式 + WebSocket + REST         │
├─────────────────────────────────────────────────────────────┤
│  Harness 可扩展层 (conch/core) — 框架无关                    │
│  ExtensionPoint · Registry · Profile · HookBus · Pipeline   │
│  CostGuard · HookBridge · GuardrailPipeline                 │
├─────────────────────────────────────────────────────────────┤
│  成熟框架底座层 (conch/adapters) — 包装为 Plugin            │
│  LangGraph · MCP · litellm · NeMo · Langfuse · Mem0         │
├─────────────────────────────────────────────────────────────┤
│  运行时层 (conch/runtime) — Docker 沙箱 · 存储              │
└─────────────────────────────────────────────────────────────┘
```

### 核心组件关系

```
Profile (YAML) ─→ Registry ─→ Plugin 实例 ─→ AgentRuntime
                       │              │
                  @register     build_runtime()
                       │              │
                  adapters/*    deps.py (API 层)
                       │
              ExtensionPoint (接口契约)
                       │
          ┌────────┬───┴───┬──────────┐
    Plugin  Plugin  Plugin  Plugin    Plugin
    (编排)  (工具)  (护栏)  (记忆)   (可观测)
       │
  HookBridge ─→ HookBus ─→ GuardrailPipeline ─→ CostGuard
```

### 三件套叠加机制

| 机制 | 说明 | 文档 |
|------|------|------|
| **Registry** | 装饰器注册 + 拓扑加载 + 版本共存，框架组件包装为 Plugin | [01] |
| **Profile** | YAML 声明式组合，extends 继承，切换配置即切换实验 | [03] |
| **Hook Bridge** | 框架事件 → 语义 Hook 总线，换引擎零改动复用 | [02] [04] |

## 文档索引

| # | 技术点 | 文件 | 对应 ETCLOVG |
|---|--------|------|-------------|
| 01 | 可扩展核心：ExtensionPoint + Registry | [01-extension-registry.md](01-extension-registry.md) | — |
| 02 | Hook 总线 + Middleware + Hook Bridge | [02-hook-middleware-bridge.md](02-hook-middleware-bridge.md) | — |
| 03 | Profile 引擎 + 实验框架 | [03-profile-experiment.md](03-profile-experiment.md) | — |
| 04 | 编排引擎：LangGraph ReAct + single_loop | [04-orchestration.md](04-orchestration.md) | L 层 |
| 05 | 工具系统：MCP Provider + builtin_shell | [05-tool-system.md](05-tool-system.md) | T 层 |
| 06 | 护栏体系：NeMo + GuardrailPipeline | [06-guardrail.md](06-guardrail.md) | E 层（护栏） |
| 07 | 上下文管理 + 记忆系统 | [07-context-memory.md](07-context-memory.md) | C 层 + E 层 |
| 08 | 成本守卫 + 可观测性 | [08-cost-observability.md](08-cost-observability.md) | O 层 |
| 09 | LLM 接入：litellm 统一多模型 | [09-llm-provider.md](09-llm-provider.md) | — |
| 10 | API 层 + 运行时 | [10-api-runtime.md](10-api-runtime.md) | — |

## 推荐阅读顺序

```
01 可扩展核心 → 02 Hook+中间件+桥接 → 03 Profile+实验
                     ↓
              04 编排引擎 → 05 工具系统 → 06 护栏
                     ↓
              07 上下文+记忆 → 08 成本+可观测 → 09 LLM接入 → 10 API运行时
```

01-03 是地基（核心抽象层），理解这三篇才能理解后续所有组件"为什么这样设计以及如何加载"。04-06 是核心能力域，07-10 是横切关注点与运行时。

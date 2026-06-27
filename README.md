# AgentConch

> Agent Harness Engineering 技术实践平台 — 成熟框架底座 + 可扩展层 + 用户前端。

**Agent = Model + Harness。** 模型是 CPU，Harness 是操作系统。当模型能力趋于稳定，任务执行的可靠性越来越取决于模型外层的那层工程。

AgentConch v2 用 **LangGraph / MCP / Mem0 / NeMo / Langfuse / DeepEval / litellm** 等成熟框架做底座，在其上**叠加**经过验证的可扩展性精髓——**Registry / Profile / Hook 三件套**。核心创新是 **Hook 桥接层**：把框架原生事件桥接到框架无关的语义 Hook 总线，换编排引擎只需新写一个桥接 Plugin，已有 Hook 零改动复用。

## v2 vs v1

| 维度 | v1（已废弃） | v2（当前） |
|---|---|---|
| 定位 | 纯研究/实验底座 | 可运行应用 + 可扩展底座（双栖） |
| LLM | Mock / Scripted 模拟 | 真实 LLM（litellm 多模型） |
| 编排 | 自建 Loop（唯一） | LangGraph（默认）+ 自建 Loop（轻量选项） |
| 前端 | 静态 HTML | Next.js 14 三栏布局 |
| 能力域 | 9 域 | 10 域（新增 guardrail） |
| 价值验证 | 骨架跑通 | Agent 真能干活 + 新技术点零侵入接入 |

## 快速开始

### 后端

```bash
cd backend
pip install -e ".[dev]"

# 配置 LLM API（本地/国内模型，litellm 统一接入）
export OPENAI_API_KEY="sk-..."  # 或自托管端点

# 启动 API 服务
uvicorn conch.api:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev  # http://localhost:3000
```

### 测试

```bash
cd backend
python -m pytest tests/ -v  # 8 项单元测试
```

## 架构

### 五层架构

```
┌─────────────────────────────────────────────────────────┐
│  前端层 (Next.js 14)                                    │
│  用户前台：对话 + 执行可视化 + 实时指标 + HITL           │
├─────────────────────────────────────────────────────────┤
│  API 网关层 (FastAPI)                                   │
│  SSE 流式 / WebSocket 双向(HITL) / REST 配置            │
├─────────────────────────────────────────────────────────┤
│  Harness 可扩展层 (conch/core — 框架无关)               │
│  Registry / Profile / Hook / Pipeline / CostGuard       │
│  HookBridge / GuardrailPipeline                         │
├─────────────────────────────────────────────────────────┤
│  成熟框架底座层 (conch/adapters — 包装为 Plugin)        │
│  LangGraph / MCP / Mem0 / NeMo / Langfuse / litellm     │
├─────────────────────────────────────────────────────────┤
│  运行时层 (conch/runtime)                               │
│  Docker 沙箱 / PostgreSQL / Chroma / Redis              │
└─────────────────────────────────────────────────────────┘
```

### 三件套叠加机制

| 机制 | 说明 |
|---|---|
| **Registry 包装框架为 Plugin** | 每个成熟框架组件实现域接口 + `@registry.register`，成为可替换插件 |
| **Profile 声明框架组合** | YAML 声明每个域用哪个框架 Plugin + 参数，切换 Profile = 切换框架组合 |
| **Hook 桥接层** | `core/hook_bridge.py` 把框架原生事件桥接到语义 Hook 总线，换引擎只需新写桥接类 |

### 10 大能力域

| 域 | 成熟框架底座 | 默认 Plugin |
|---|---|---|
| 信息边界 | AGENTS.md | `agents_md` |
| 工具系统 | **MCP SDK** | `mcp_provider` |
| 上下文管理 | 自研 compaction | `jit_compaction` |
| 记忆状态 | **Mem0**（阶段二） | `notes_file`（MVP） |
| 执行编排 | **LangGraph** | `langgraph_react` / `single_loop` |
| 评估验证 | **DeepEval**（阶段三） | — |
| 可观测性 | **Langfuse** | `langfuse_tracer` / `console_tracer` |
| 约束恢复 | 自研 | — |
| 治理 | 自研 allowlist | — |
| **护栏**（v2 新增） | **NeMo + LlamaGuard** | `nemo_guardrails` |

## 三层扩展模型

任何新技术点都有归宿，且核心代码永远不需要改动：

| 层级 | 适用场景 | 机制 |
|---|---|---|
| **L1 插件** | 已有域内新实现 | 实现域接口 + `@registry.register` |
| **L2 Hook / 中间件** | Loop 关键节点的横切逻辑 | 挂载到 Hook 总线 / 中间件链 |
| **L3 自定义能力域** | 全新技术维度 | 注册新域 + 定义接口 |

```python
# 新技术点接入示例：一个新护栏插件，核心 0 改动
@registry.register("guardrail", "perspective_api", "1.0")
class PerspectiveGuardrail(Plugin):
    domain = "guardrail"
    name = "perspective_api"
    def check_input(self, text, state):
        if self.client.score(text) > 0.8:
            return GuardrailResult(blocked=True, reason="toxicity")
        return GuardrailResult()
# Profile 中 guardrail.impl 改为 perspective_api 即生效
```

## 项目结构

```
agent-conch/
├── backend/
│   ├── conch/
│   │   ├── core/               # 可扩展层核心（框架无关）
│   │   │   ├── extension.py    # 10 域 ExtensionPoint 接口
│   │   │   ├── registry.py     # 注册中心（拓扑/版本/生命周期）
│   │   │   ├── hooks.py        # Hook 总线 + 14 挂载点
│   │   │   ├── middleware.py   # Pipeline 数据流
│   │   │   ├── profile.py      # Profile 引擎（extends + Pydantic）
│   │   │   ├── cost_guard.py   # CostGuard 分级降级
│   │   │   ├── hook_bridge.py  # 框架事件→Hook 桥接（核心创新）
│   │   │   ├── guardrail_pipeline.py  # 六层护栏管道
│   │   │   └── experiment.py   # 实验框架
│   │   ├── adapters/           # 成熟框架适配层（包装为 Plugin）
│   │   │   ├── llm/            # litellm_provider
│   │   │   ├── orchestration/  # langgraph_react / single_loop
│   │   │   ├── tool/           # mcp_provider / builtin_shell
│   │   │   ├── guardrail/      # nemo_guardrails
│   │   │   ├── observability/  # langfuse_tracer / console_tracer
│   │   │   ├── information/    # agents_md
│   │   │   ├── context/        # jit_compaction
│   │   │   └── memory/         # notes_file
│   │   ├── api/                # FastAPI 路由
│   │   │   ├── routes/         # chat(SSE) / session / profile / plugin
│   │   │   ├── deps.py         # 依赖注入 + build_runtime
│   │   │   └── sse.py          # SSE 流式工具
│   │   └── runtime/            # 沙箱 + 存储
│   ├── profiles/               # 实验配置（YAML）
│   ├── plugins/                # 新技术点实验区
│   ├── guardrail_configs/      # NeMo 护栏配置
│   ├── tests/                  # 单元测试
│   └── pyproject.toml
├── frontend/                   # Next.js 14 前端
│   ├── app/                    # 三栏布局
│   ├── components/             # chat / metrics 组件
│   └── lib/                    # store / sse-client / api
├── benchmarks/                 # 评测任务集
├── docs/                       # 技术方案 + 技术点文档
└── AGENTS.md                   # 项目指令文件
```

## 分阶段路线

| 阶段 | 目标 | 状态 |
|---|---|---|
| **一 MVP** | 用户对话 → Agent 用工具完成任务 → 流式展示 → 基础护栏 | ✅ 已完成 |
| **二 生产加固** | 六层护栏 + Mem0 记忆 + CostGuard + HITL | ⏳ 未开始 |
| **三 开发者后台** | DeepEval + Profile A/B + trace diff | ⏳ 未开始 |
| **四 多 Agent + 治理** | LangGraph Supervisor + RBAC + 审计 | ⏳ 未开始 |

## 核心文档

- [技术方案 v2.0](docs/technical-design-v2.md) — 当前主线架构设计
- [实现状态 v2](docs/implementation-status-v2.md) — MVP 完成情况与测试结果
- [技术方案 v0.3](docs/technical-design.md) — 历史版本（已废弃，保留参考）
- [技术点详解](docs/technical-points/) — 13 篇技术点深入文档

### 技术点文档索引

| # | 技术点 | 文档 |
|---|---|---|
| 01 | 扩展点契约 | [01-extension-point.md](docs/technical-points/01-extension-point.md) |
| 02 | 注册中心 | [02-registry.md](docs/technical-points/02-registry.md) |
| 03 | Hook 与中间件 | [03-hook-and-middleware.md](docs/technical-points/03-hook-and-middleware.md) |
| 04 | Profile 与实验框架 | [04-profile-and-experiment.md](docs/technical-points/04-profile-and-experiment.md) |
| 05 | Agent Loop 引擎 | [05-agent-loop.md](docs/technical-points/05-agent-loop.md) |
| 06 | 上下文管理 | [06-context-management.md](docs/technical-points/06-context-management.md) |
| 07 | 工具系统与 MCP | [07-tool-system-mcp.md](docs/technical-points/07-tool-system-mcp.md) |
| 08 | 记忆五分法 | [08-memory-five-types.md](docs/technical-points/08-memory-five-types.md) |
| 09 | 多 Agent 协作 | [09-multi-agent-orchestration.md](docs/technical-points/09-multi-agent-orchestration.md) |
| 10 | 可观测性与自观测 | [10-observability.md](docs/technical-points/10-observability.md) |
| 11 | 沙箱与安全治理 | [11-sandbox-security.md](docs/technical-points/11-sandbox-security.md) |
| 12 | 成本守卫与分级降级 | [12-cost-guard.md](docs/technical-points/12-cost-guard.md) |
| 13 | Skill 系统 | [13-skill-system.md](docs/technical-points/13-skill-system.md) |

## 设计哲学

- **成熟框架优先** — 能用 LangGraph/MCP/Mem0 解决的不重新发明，自研收敛到可扩展层
- **核心稳定，边界常新** — 接口定义 WHAT 不定义 HOW，接口不泄漏框架概念
- **可扩展性 > 功能完备性** — 宁可能力域接口稳定但实现少，也不要接口臃肿却难以扩展
- **先可用，再可调** — MVP 先让终端用户能用，后续再补开发者观测后台
- **反对过度工程** — MVP 用最小框架子集跑通闭环，按需补层

## 技术选型

### 后端
FastAPI / LangGraph / MCP SDK / litellm / NeMo Guardrails / LlamaGuard / Langfuse / DeepEval / Pydantic v2 / OpenTelemetry

### 前端
Next.js 14 (App Router) / TypeScript / Tailwind CSS / shadcn/ui / zustand / TanStack Query

### 存储
PostgreSQL / Chroma / Redis（阶段二）；MVP 内存

## License

MIT

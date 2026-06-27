# AgentConch 技术方案 v2.0

> **项目代号**：agent-conch
> **定位**：可运行的 harness 应用 + 可扩展的研究底座（双栖）
> **架构路线**：成熟框架底座 + agent-conch 式可扩展层
> **文档版本**：v2.0（推翻 v0.3 实现，继承可扩展性精髓）
> **最后更新**：2026-06-27

---

## 0. TL;DR

AgentConch v2.0 是一次"推翻重做"：抛弃 v1 从未接入真实 LLM 的 9 域骨架实现，改用 **LangGraph / MCP / Mem0 / NeMo / Langfuse / DeepEval / litellm** 等成熟框架做底座，在其上**叠加** v1 经过验证的可扩展性精髓——**Registry / Profile / Hook 三件套**。

核心创新是 **Hook 桥接层**：把框架原生事件（如 LangGraph callbacks）桥接到框架无关的语义 Hook 总线（`pre_model_call` / `pre_tool` / `on_cost_exceeded`…）。换编排引擎只需新写一个桥接 Plugin，所有已有的护栏、审计、成本守卫逻辑**零改动复用**。这保证了"用成熟框架快速落地"与"新技术点零侵入接入"两个目标同时成立。

v2.0 同时补齐了 v1 完全缺失的**用户友好前端**：Next.js 对话界面 + 任务执行可视化（流式输出、工具调用卡片、护栏干预提示、HITL 审批、实时成本指标），让 Agent 真正能为终端用户干活，而不只是研究骨架。

**一句话**：v2 把 v1 的"可扩展思想"嫁接到"成熟框架躯体"上，并长出了"用户前端"。核心稳定、边界常新、应用可用。

---

## 1. 项目定位与命名

### 1.1 双栖定位

v1 是纯研究/实验底座，9 域骨架从未接真实 LLM，没有前端。v2 升级为**双栖**：

| 维度 | v1 旧定位 | v2 新定位 |
|---|---|---|
| 性质 | 纯研究/实验底座 | **可运行的应用 + 可扩展的底座**双栖 |
| 用户 | 仅开发者 | 终端用户（MVP）+ 开发者（后续） |
| LLM | Mock / Scripted 模拟 | 真实 LLM（litellm 多模型） |
| 前端 | 静态 HTML | Next.js 完整前台 |
| 编排 | 自建 Loop（唯一） | LangGraph（默认）+ 自建 Loop（轻量选项） |
| 价值验证 | 骨架跑通 | Agent 真能干活 + 新技术点零侵入接入 |

### 1.2 与 v1 的关系

- **推翻**：9 域骨架实现（`conch/domains/`，从未接真实 LLM）、自建 Loop 作为唯一编排、ScriptedProvider 模拟、静态 HTML 前端、内存态 store
- **继承**：三层扩展模型（Plugin / Hook / 自定义域）、Registry 三件套（注册中心 + Profile + 实验）、Hook 三约束（职责隔离 + 优先级 + 中断白名单）、Pipeline 数据流、"WHAT 不 HOW" 接口哲学、CostGuard 分级降级、记忆五分法

### 1.3 命名

继续沿用 **agent-conch**。海螺寓意（外壳 = harness 保护 + 塑形，内部共振放大模型能力）仍然成立。版本号升至 **v2.0**，标志从"研究平台"到"可运行应用"的跃迁。

### 1.4 设计原则

1. **成熟框架优先，自研收敛到可扩展层**。能用 LangGraph/MCP/Mem0 解决的，不重新发明；只把"新技术点如何零侵入接入"这件事自研。
2. **可扩展性 > 功能完备性**。接口稳定但实现少，优于接口臃肿却难扩展。
3. **安全 day-one**。沙箱与权限校验是 MVP 底线，不是远期功能。
4. **配置即实验**。一组 Plugin + 参数 = 一个 Profile，切换配置即切换实验。
5. **先可用，再可调**。MVP 先让终端用户能用，后续再补开发者观测后台。
6. **反对过度工程**。MVP 用最小框架子集跑通闭环，按需补层。

---

## 2. 整体架构

### 2.1 五层架构

```
┌─────────────────────────────────────────────────────────────┐
│  前端层 (Next.js 14)                                         │
│  用户前台 MVP：对话 + 执行可视化 + 实时指标 + HITL            │
│  开发者后台(后续)：trace diff / Profile A-B / 实验看板       │
├─────────────────────────────────────────────────────────────┤
│  API 网关层 (FastAPI)                                        │
│  SSE 流式输出 / WebSocket 双向(HITL审批) / REST 配置管理     │
├─────────────────────────────────────────────────────────────┤
│  Harness 可扩展层 (conch/core — 继承 v1，框架无关)           │
│  Registry 注册中心 | Profile 实验配置 | Hook 总线            │
│  Pipeline 数据流 | Experiment 对比 | GuardrailPipeline       │
│  CostGuard 成本守卫 | HookBridge 框架事件桥接                │
│  (定义 WHAT 不定义 HOW，框架无关，零改动接入新技术点)         │
├─────────────────────────────────────────────────────────────┤
│  成熟框架底座层 (conch/adapters — 新增，包装为 Plugin)       │
│  LangGraph 编排 | MCP 工具 | Mem0 记忆 | NeMo/LlamaGuard 护栏│
│  Langfuse 可观测 | DeepEval 评测 | litellm 多模型            │
│  (每个框架组件 = 一个 Plugin，注册到 Registry)               │
├─────────────────────────────────────────────────────────────┤
│  运行时层 (conch/runtime)                                    │
│  Docker 沙箱 | PostgreSQL 状态/轨迹 | Chroma 向量 | Redis 缓存│
└─────────────────────────────────────────────────────────────┘
```

**关键**：可扩展层（`core`）在框架底座层（`adapters`）**之上**。`core` 定义接口契约（WHAT），`adapters` 把成熟框架包装成 Plugin 实现（HOW）并注册到 Registry。Profile 声明用哪套框架组合，Hook 通过桥接层挂到框架原生事件点。

### 2.2 三件套叠加机制（设计灵魂）

这是 v2 最关键的设计——回答"如何既用成熟框架、又保留零侵入可扩展性"。三种叠加机制：

#### 机制一：Registry 包装成熟框架组件为 Plugin

每个成熟框架组件被包装成一个 Plugin，实现对应域的 ExtensionPoint 接口，注册到 Registry。框架成为可替换的"实现"，而非"地基"：

```python
# adapters/orchestration/langgraph_react.py
@registry.register("orchestration", "langgraph_react", "1.0")
class LangGraphReActOrchestrator(Plugin):
    """LangGraph ReAct 编排 — 包装 langgraph.prebuilt.create_react_agent"""
    domain = "orchestration"
    name = "langgraph_react"
    metadata = {"capabilities": ["react", "tool_use"], "framework": "langgraph"}

    def __init__(self, model: str = "gpt-4o", recursion_limit: int = 25):
        from langchain_openai import ChatOpenAI
        self.llm = ChatOpenAI(model=model, streaming=True)
        self.recursion_limit = recursion_limit
        self._graph = None  # 延迟构建（需 tools）

    def build_graph(self, tools, system_prompt):
        self._graph = create_react_agent(self.llm, tools, prompt=system_prompt)

    async def run(self, task, agents, state):
        # 通过 callbacks 桥接到 conch Hook bus
        from conch.core.hook_bridge import LangGraphHookBridge
        config = {"recursion_limit": self.recursion_limit,
                  "callbacks": [LangGraphHookBridge(state.hook_bus, state)]}
        async for event in self._graph.astream_events(
            {"messages": [{"role": "user", "content": task}]},
            config=config, version="v2"):
            yield event  # 流式事件 → SSE 推前端
```

```python
# adapters/tool/mcp_provider.py
@registry.register("tool", "mcp_provider", "1.0")
class MCPToolProvider(Plugin):
    """MCP 工具提供者 — 连接 MCP Server，发现并执行工具"""
    domain = "tool"

    def __init__(self, servers: list[dict]):
        self.servers = servers  # [{"command": "...", "args": [...]}]

    async def on_load(self):
        from mcp import ClientSession, StdioServerParameters
        self._sessions = []
        for srv in self.servers:
            session = ClientSession(StdioServerParameters(**srv))
            await session.connect()
            self._sessions.append(session)

    def tools_for(self, task, state):
        return [self._mcp_to_tool(t) for s in self._sessions for t in s.tools]

    async def execute(self, tool, args, state):
        return await self._route(tool).call_tool(tool, args)
```

```python
# adapters/memory/mem0_provider.py
@registry.register("memory", "mem0", "1.0")
class Mem0MemoryProvider(Plugin):
    """Mem0 记忆 — 委托 store/recall 给 Mem0"""
    domain = "memory"

    def __init__(self, user_id: str = "auto", agent_id: str = "conch"):
        from mem0 import Memory
        self.mem = Memory()
        self.user_id, self.agent_id = user_id, agent_id

    def store(self, key, value, mem_type="episodic"):
        self.mem.add({"role": "user", "content": value},
                     user_id=self.user_id, agent_id=self.agent_id)

    def recall(self, query, mem_type="episodic", limit=5):
        return self.mem.search(query, user_id=self.user_id, limit=limit)
```

#### 机制二：Profile 声明框架组合

Profile（YAML）声明每个域用哪个框架 Plugin + 参数。**切换 Profile = 切换框架组合，零代码改动**。`extends` 支持增量实验：

```yaml
# profiles/user-chat-v1.yaml — MVP 用户对话 Profile
name: user-chat-v1
description: 终端用户对话 Profile，LangGraph+MCP+Mem0+NeMo 最小组合
model: gpt-4o
model_fallback: gpt-4o-mini
max_steps: 25
max_tokens: 100000
domains:
  information:    { impl: agents_md, params: { file: ./AGENTS.md } }
  orchestration:  { impl: langgraph_react, params: { recursion_limit: 25 } }
  tool:           { impl: mcp_provider, params: { servers: [
                     {command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "."]}
                   ]}}
  memory:         { impl: mem0, params: { user_id: "auto" } }
  guardrail:      { impl: nemo_guardrails, params: { config: ./guardrail_configs/chat } }
  observability:  { impl: langfuse_tracer, params: { project: "conch-prod" } }
  eval:           { impl: deepeval_runner, params: { metrics: [answer_relevancy, faithfulness] } }
  context:        { impl: jit_compaction, params: { threshold: 0.4 } }
  governance:     { impl: allowlist_perms, params: { tools: [read_file, write_file, list_files] } }
```

```yaml
# profiles/user-chat-v2-cheap.yaml — 仅换模型+护栏，继承其余
name: user-chat-v2-cheap
extends: user-chat-v1
model: gpt-4o-mini        # 换便宜模型
domains:
  guardrail: { impl: llamaguard_only, params: {} }  # 换轻量护栏
```

#### 机制三：Hook 桥接层（核心创新）

Hook 总线定义的是**框架无关的语义节点**（`pre_model_call` / `pre_tool` / `on_cost_exceeded`…），与具体编排引擎解耦。每个编排 Plugin 负责把框架原生事件桥接到 Hook bus。对 LangGraph，通过其 callbacks 机制桥接：

```python
# core/hook_bridge.py — 框架事件 → conch Hook bus 的桥接层
class LangGraphHookBridge:
    """将 LangGraph/LangChain 回调事件桥接到 conch Hook 语义节点。

    这样 conch 的 Hook（pre_model_call/post_tool/on_cost_exceeded 等）
    能在任何编排引擎上工作，无论底层是 LangGraph 还是自建 Loop。
    """

    def __init__(self, hook_bus: "HookBus", state_ref):
        self.hook_bus = hook_bus
        self.state = state_ref

    # ── LangChain Callback Handler 接口实现 ──
    async def on_llm_start(self, serialized, prompts, **kwargs):
        self.hook_bus.fire("pre_model_call", self.state)

    async def on_llm_end(self, response, **kwargs):
        action = self._parse_llm_result(response)
        self.hook_bus.fire("post_model_call", self.state, action)

    async def on_tool_start(self, serialized, input_str, **kwargs):
        self.hook_bus.fire("pre_tool", self.state,
                           tool=serialized.get("name"), args=input_str)

    async def on_tool_end(self, output, **kwargs):
        self.hook_bus.fire("post_tool", self.state, result=output)

    async def on_tool_error(self, error, **kwargs):
        self.hook_bus.fire("on_tool_error", self.state, error=error)
```

**桥接的价值**：换编排引擎（LangGraph → 自建 Loop → AutoGen），只需新写一个桥接 Plugin，所有已有 Hook（审计、护栏、成本守卫）**零改动复用**。这正是"成熟框架底座 + 零侵入可扩展层"叠加的根本保证。

### 2.3 一次 Agent Step 的数据流

```
用户输入
  │
  ▼
[API 层] 创建会话 → 加载 Profile → Registry 构建各域 Plugin 实例
  │
  ▼
[编排 Plugin: langgraph_react] 启动 LangGraph 图
  │
  ▼ (每一步)
┌─────────────────────────────────────────────────┐
│ 1. 上下文组装 (ContextManager Plugin)            │
│    Pipeline: JIT加载 → 元数据增强 → 工具结果清理  │
│              → 语义压缩 → 40%利用率守卫           │
│                                                   │
│ 2. 输入护栏 (Hook: pre_model_call)               │
│    → GuardrailPipeline.input: NeMo筛查→LlamaGuard │
│                                                   │
│ 3. LLM 推理 (litellm streaming)                  │
│    Hook桥接: LangGraph callback → pre/post_model  │
│    流式 token → SSE 实时推送前端                  │
│                                                   │
│ 4. 输出护栏 (Hook: post_model_call)              │
│    → GuardrailPipeline.output: NeMo→LlamaGuard    │
│                                                   │
│ 5. 工具调用? (Hook: pre_tool → 权限校验+工具护栏) │
│    是 → MCP Provider 执行 → (Hook: post_tool)     │
│         → 工具结果经 Pipeline token优化入上下文    │
│         → Mem0 记录情景记忆                       │
│    否 → 文本输出                                  │
│                                                   │
│ 6. 可观测 (Langfuse callback → trace+cost)        │
│ 7. CostGuard 检查 (Hook: on_cost_exceeded)        │
│ 8. 评测 (Evaluator: should_eval? → DeepEval)      │
└─────────────────────────────────────────────────┘
  │
  ▼ (循环直到完成/HITL审批/成本终止)
[API 层] SSE 流式输出 + WebSocket 事件 + 最终轨迹
```

---

## 3. 能力域映射

把参考方案的 ETCLOVG 七层 + v1 的 9 域，映射到 v2 的具体组件：

| ETCLOVG 七层 | v1 九域 | v2 Plugin | 成熟框架底座 | 可扩展点 |
|---|---|---|---|---|
| C 上下文工程 | 域3 上下文管理 | ContextManager | LangGraph state + 自研 compaction | 新压缩算法 = 新 Plugin |
| T 工具与执行 | 域2 工具系统 | ToolProvider | **MCP SDK** | 新 MCP server = 新工具源 |
| L 生命周期编排 | 域5 执行编排 | OrchestrationMode | **LangGraph** | 新编排模式 = 新 Plugin |
| E 状态与记忆 | 域4 记忆与状态 | MemoryProvider | **Mem0** | 新记忆后端 = 新 Plugin |
| E 架构约束与护栏 | 域8 约束恢复 | GuardrailProvider | **NeMo + LlamaGuard** | 新护栏模型 = 新中间件 |
| V 验证与反馈 | 域6 评估验证 | Evaluator | **DeepEval** | 新评测指标 = 新 Plugin |
| O 可观测性 | 域7 可观测性 | ObservabilityProvider | **Langfuse** + OpenTelemetry | 新 trace 后端 = 新 Plugin |
| G 治理与安全 | 域9 治理 | GovernanceProvider | 自研 allowlist + 审计 | 新权限模型 = 新 Plugin |
| — | 域1 信息边界 | InformationProvider | AGENTS.md + Skill 系统 | 新指令策略 = 新 Plugin |

### 六层纵深防御护栏落地映射

参考方案的核心——六层防御护栏，映射到 v2 的 Hook + Pipeline 机制，**无需新抽象**：

| 护栏层 | 实现机制 | 成熟框架 |
|---|---|---|
| 1. 输入筛查 | `pre_model_call` Hook → input Pipeline | NeMo Guardrails |
| 2. LLM 推理护栏 | 模型内置 safety + Provider 参数 | litellm safety params |
| 3. 工具护栏 | `pre_tool` Hook（可中断）→ 权限校验 + 参数 Schema | 自研 + NeMo |
| 4. 检索护栏 | 记忆 Pipeline 中间件（间接注入扫描） | 自研 relevance filter |
| 5. 输出筛查 | `post_model_call` Hook → output Pipeline | NeMo + LlamaGuard |
| 6. 监控审计 | `on_tool_error` / `post_tool` Hook → 审计日志 | Langfuse + 自研审计 |

**三重行为闸门**（参考方案）：

| 闸门 | 校验时机 | 实现 | 处理 |
|---|---|---|---|
| 规划闸门 | 推理后 | `post_model_call` Hook | 越界则拒绝执行 |
| 工具调用闸门 | 工具执行前 | `pre_tool` Hook（中断白名单） | 高危拦截 + 人工审批 |
| 输出闸门 | 输出前 | `post_model_call` Hook | 不合规则重新生成 |

---

## 4. 前端设计

### 4.1 用户前台 MVP

**技术栈**：Next.js 14 (App Router) + TypeScript + Tailwind CSS + shadcn/ui + zustand + TanStack Query + ai-sdk

**页面结构**（三栏布局）：

```
┌──────────┬───────────────────────────┬──────────┐
│ 左栏      │  中栏（主交互区）          │ 右栏      │
│          │                            │          │
│ 会话列表  │  ┌─ Tab: 对话 ─┬─ 轨迹 ─┐  │ 实时指标  │
│          │  │              │        │  │          │
│ Profile  │  │  流式输出     │ Step链 │  │ Token:   │
│ 选择器    │  │  (SSE 逐字)  │ 工具流 │  │ $0.023   │
│          │  │              │ 护栏   │  │ Steps: 5 │
│ 历史任务  │  │  工具调用卡片 │ 事件   │  │          │
│          │  │  (可展开参数/ │        │  │ 护栏事件  │
│          │  │   结果)       │        │  │ ▓▓▓░░    │
│          │  │              │        │  │          │
│          │  │  护栏干预提示  │        │  │ 模型:    │
│          │  │  ⚠ 已拦截     │        │  │ gpt-4o   │
│          │  │              │        │  │          │
│          │  ├──────────────┴────────┤  │ HITL待审 │
│          │  │  [输入框]      [发送]  │  │ □ bash?  │
│          │  └───────────────────────┘  │ [批准]   │
└──────────┴───────────────────────────┴──────────┘
```

**关键交互**：
- **流式输出**：SSE 逐 token 渲染，用户看到 Agent "正在思考"
- **工具调用卡片**：每次工具调用生成可折叠卡片，显示工具名 / 参数 / 结果 / 耗时
- **轨迹时间线**：Tab 切换查看，每步显示推理 → 工具 → 结果链路
- **护栏干预提示**：当护栏拦截/修改时，弹出醒目提示（"输入含敏感内容，已过滤"）
- **实时指标**：右栏 token / 成本 / 步数实时累加，护栏触发计数
- **HITL 审批**：危险工具调用时，WebSocket 推送审批请求，用户点击批准/拒绝

### 4.2 开发者后台（阶段三）

- **Trace 对比**：两个 Profile 的执行轨迹并排 diff，高亮差异步
- **Profile A/B**：选两个 Profile + 任务集，跑实验，展示成功率 / 成本 / 步数对比表 + 图
- **实验框架看板**：DeepEval 评测结果，指标趋势图
- **护栏配置**：可视化编辑护栏规则，热重载生效
- **插件管理**：查看已注册 Plugin，启用 / 禁用 / 版本切换

### 4.3 前后端通信

| 通道 | 用途 | 技术 |
|---|---|---|
| **SSE** | 流式输出（token 逐个推送） | FastAPI StreamingResponse + EventSource |
| **WebSocket** | 双向：HITL 审批 + 工具事件推送 | FastAPI WebSocket |
| **REST** | 配置管理（Profile / Plugin / 会话 CRUD） | FastAPI REST |

**事件类型设计**（SSE 消息）：
```
event: text_delta      data: {"content": "正在"}
event: tool_call       data: {"tool": "read_file", "args": {...}, "call_id": "..."}
event: tool_result     data: {"call_id": "...", "result": "...", "tokens": 120}
event: guardrail       data: {"layer": "input", "action": "blocked", "reason": "..."}
event: cost_update     data: {"tokens": 5230, "cost": 0.023, "step": 5}
event: hitl_request    data: {"tool": "run_bash", "args": {...}, "approve_url": "..."}
event: done            data: {"success": true, "total_cost": 0.05}
```

---

## 5. 可扩展性机制（核心章）

> 这一章回答最关键的问题：**新技术点出现时，如何零侵入接入？** 答案是三层扩展模型，叠加在成熟框架之上。

### 5.1 L1 插件：在已有域内新增实现

最常见的扩展方式。实现域接口 + `@registry.register`，零侵入。已在 2.2 节机制一详述包装成熟框架组件的模式。下面是接入**全新技术点**的示例：

**示例一：新护栏插件（接入 Perspective API 内容安全）**

```python
# plugins/guardrail/perspective_api.py
@registry.register("guardrail", "perspective_api", "1.0")
class PerspectiveGuardrail(Plugin):
    domain = "guardrail"; name = "perspective_api"
    metadata = {"capabilities": ["toxicity"]}

    def __init__(self, api_key: str):
        self.client = PerspectiveClient(api_key)

    def check_input(self, text) -> "GuardrailResult":
        score = self.client.score(text)
        if score > 0.8:
            return GuardrailResult(blocked=True, reason="toxicity")
        return GuardrailResult(blocked=False)
# 接入完成。Profile 中 guardrail.impl 改为 perspective_api 即生效，核心 0 改动。
```

**示例二：新记忆后端（接入 Qdrant 向量库）**

```python
# plugins/memory/qdrant_backend.py
@registry.register("memory", "qdrant", "1.0")
class QdrantMemory(Plugin):
    domain = "memory"; name = "qdrant"

    def __init__(self, url, collection="conch"):
        from qdrant_client import QdrantClient
        self.client = QdrantClient(url)

    def store(self, key, value, mem_type): ...
    def recall(self, query, mem_type, limit): ...
# Profile 中 memory.impl 改为 qdrant 即生效。
```

**示例三：新编排模式（接入 AutoGen 多 Agent）**

```python
# plugins/orchestration/autogen_supervisor.py
@registry.register("orchestration", "autogen_supervisor", "1.0")
class AutoGenSupervisor(Plugin):
    domain = "orchestration"; name = "autogen_supervisor"
    metadata = {"capabilities": ["multi_agent", "supervisor"]}

    async def run(self, task, agents, state):
        from autogen import GroupChat, AssistantAgent
        # 桥接 AutoGen 事件 → Hook bus（写一个 AutoGenHookBridge）
        ...
# Profile 中 orchestration.impl 改为 autogen_supervisor 即生效。
```

### 5.2 L2 Hook / 中间件：横切逻辑注入

当新技术点是 Loop 关键节点的横切逻辑（如每步后熵增检测、自定义审计），挂 Hook 或加中间件：

```python
@hook("post_step", priority=10)
def entropy_guard(state):
    """新技术点：每步后检测熵增，触发清理"""
    if detect_drift(state):
        state.trigger_cleanup()
```

**Hook 三大约束（v1 固化，v2 继承）**：

| 约束 | 规则 | 理由 |
|---|---|---|
| 职责隔离 | Hook 仅触发副作用（日志/告警/中断），禁止改主流程核心数据；中间件仅处理数据流变换，禁止中断 | 防止横切逻辑污染主流程 |
| 优先级 | `priority` 数值越小越先执行（默认 100），同节点串行 | 解决执行顺序不可控 |
| 中断白名单 | 仅 `on_tool_error` / `pre_step` / `pre_tool` / `on_cost_exceeded` / `on_error` 支持中断返回 | 防止非关键 Hook 意外终止任务 |

**中间件链**用于需要"链式处理"的数据流（上下文 / 工具结果 / 记忆）：

```python
context_pipeline = Pipeline([
    JitLoader(),           # 即时加载
    MetadataEnricher(),    # 元数据信号
    ToolResultClearer(),   # 清理深层工具结果
    SemanticCompactor(),   # 语义压缩
    UtilizationGuard(0.4), # 40% 阈值守卫
])
```

### 5.3 L3 自定义能力域：全新维度逃生口

当出现 9 域都装不下的全新维度（如"Agent 情绪系统"）：

```python
# 1. 定义新域接口
class EmotionProvider(ExtensionPoint, Protocol):
    domain = "emotion"
    def detect(self, state) -> dict: ...

# 2. 注册到 DOMAINS
from conch.core.extension import DOMAINS
DOMAINS.append("emotion")

# 3. 实现并注册 Plugin
@registry.register("emotion", "sentiment_v1", "1.0")
class SentimentEmotion(Plugin): ...

# 4. Profile 中配置
# emotion: { impl: sentiment_v1, params: {} }
```

### 5.4 扩展机制总结

```
新技术点出现
     │
     ▼
 能否归入已有 9 域？
     │是 → 写 Plugin，实现域接口 + @register  （L1，最常见）
     │否
     ▼
 是 Loop 关键节点的横切逻辑？
     │是 → 挂 Hook 或加中间件              （L2）
     │否
     ▼
 是全新技术维度？
     └→ 注册自定义能力域 + 定义接口          （L3，罕见但保底）
```

**结论：任何新技术点都有归宿，且核心代码永远不需要改动。** 叠加在成熟框架之上时，这个承诺依然成立——因为框架被包装成 Plugin，核心层始终框架无关。

---

## 6. 技术选型矩阵

### 6.1 后端

| 组件 | 选型 | 用途 | 理由 | 备选 |
|---|---|---|---|---|
| Web 框架 | **FastAPI** | API 网关 | 异步原生、SSE/WS 支持、自动文档 | Litestar |
| 编排框架 | **LangGraph** | Agent 图编排 | 状态图 + 流式 + checkpoint 成熟 | AutoGen / CrewAI |
| 工具协议 | **MCP SDK** | 工具发现与执行 | Anthropic 标准、生态丰富 | 自研工具协议 |
| 记忆框架 | **Mem0** | 分层记忆 | 自动记忆抽取 + 检索、五分法对齐 | Letta(MemGPT) |
| 护栏 | **NeMo Guardrails** | 输入输出护栏 | 声明式、可编程、成熟 | Guardrails AI |
| 护栏(模型) | **LlamaGuard** | 内容安全分类 | 轻量、开源、多类别 | Perspective API |
| 可观测 | **Langfuse** | trace/cost/评测 | 开源自托管、LLM 原生 | LangSmith(云) |
| 评测 | **DeepEval** | CI 评测流水线 | Pytest 集成、多指标 | Promptfoo |
| LLM 接入 | **litellm** | 多模型统一 | 100+ 模型统一接口 | 自抽象 Provider |
| 配置校验 | **Pydantic v2** | Profile 校验 | v1 已用 | — |
| 可观测协议 | **OpenTelemetry** | 标准化 trace | 业内标准 | — |

### 6.2 前端

| 组件 | 选型 | 理由 |
|---|---|---|
| 框架 | **Next.js 14 (App Router)** | SSR/SSG/RSC、生态成熟 |
| 语言 | **TypeScript** | 类型安全 |
| 样式 | **Tailwind CSS** | 原子化、快速 |
| 组件库 | **shadcn/ui** | 可定制、无运行时开销 |
| 状态管理 | **zustand** | 轻量、无 boilerplate |
| 数据获取 | **TanStack Query** | SSE/WS 友好、缓存 |
| 流式渲染 | **ai-sdk (Vercel)** | SSE 逐 token 渲染成熟方案 |

### 6.3 存储与沙箱

| 组件 | 用途 | 理由 |
|---|---|---|
| **PostgreSQL** | 会话 / 状态 / 轨迹 / 审计 | 关系型、可靠 |
| **Chroma** | 向量记忆（Mem0 后端） | 轻量、本地优先 |
| **Redis** | 短期记忆 / 会话缓存 / 限流 | 低延迟 |
| **Docker** | 工具执行隔离 | 跨平台、v1 已有加固基线 |

---

## 7. 项目结构

```
agent-conch/
├── backend/
│   ├── conch/
│   │   ├── core/                    # 可扩展层核心（继承 v1，框架无关）
│   │   │   ├── extension.py         # ExtensionPoint 契约（保留，新增 guardrail 域）
│   │   │   ├── registry.py          # 注册中心（直接复用）
│   │   │   ├── hooks.py             # Hook 总线（直接复用）
│   │   │   ├── middleware.py        # Pipeline 数据流（直接复用）
│   │   │   ├── profile.py           # Profile 引擎（改造复用，强化 Pydantic）
│   │   │   ├── experiment.py        # 实验框架（改造复用，接 DeepEval）
│   │   │   ├── hook_bridge.py       # 新增：框架事件→Hook 桥接层
│   │   │   ├── guardrail_pipeline.py# 新增：六层护栏管道（Pipeline+Hook）
│   │   │   └── cost_guard.py        # CostGuard（从 loop.py 拆出）
│   │   ├── adapters/                # 成熟框架适配层（新，包装为 Plugin）
│   │   │   ├── orchestration/
│   │   │   │   ├── langgraph_react.py      # LangGraph ReAct（默认）
│   │   │   │   ├── langgraph_supervisor.py # LangGraph Supervisor（阶段四）
│   │   │   │   └── single_loop.py          # 自建 Loop（轻量选项，从 v1 迁移）
│   │   │   ├── tool/
│   │   │   │   ├── mcp_provider.py         # MCP 工具（默认）
│   │   │   │   └── builtin_shell.py        # 内置工具（v1 迁移）
│   │   │   ├── memory/
│   │   │   │   ├── mem0_provider.py        # Mem0（默认）
│   │   │   │   └── notes_file.py           # 文件笔记（v1 迁移，降级用）
│   │   │   ├── guardrail/
│   │   │   │   ├── nemo_guardrails.py      # NeMo 护栏
│   │   │   │   └── llamaguard.py           # LlamaGuard
│   │   │   ├── observability/
│   │   │   │   ├── langfuse_tracer.py      # Langfuse（默认）
│   │   │   │   └── console_tracer.py       # 控制台（v1 迁移）
│   │   │   ├── eval/
│   │   │   │   └── deepeval_runner.py      # DeepEval
│   │   │   ├── context/
│   │   │   │   └── jit_compaction.py       # 上下文管理（v1 迁移）
│   │   │   └── llm/
│   │   │       └── litellm_provider.py     # litellm 多模型
│   │   ├── api/                     # FastAPI 路由（新）
│   │   │   ├── routes/
│   │   │   │   ├── chat.py          # SSE 流式对话
│   │   │   │   ├── session.py       # 会话管理
│   │   │   │   ├── profile.py       # Profile CRUD
│   │   │   │   ├── plugin.py        # 插件查询
│   │   │   │   └── experiment.py    # 实验触发
│   │   │   ├── sse.py               # SSE 流式工具
│   │   │   ├── websocket.py         # WebSocket HITL
│   │   │   └── deps.py              # 依赖注入
│   │   └── runtime/                 # 运行时（保留 + 扩展）
│   │       ├── sandbox/             # Docker 沙箱
│   │       └── store/               # PG/Chroma/Redis 适配
│   └── pyproject.toml
├── frontend/                        # Next.js（新）
│   ├── app/
│   │   ├── (chat)/page.tsx          # 用户对话主页
│   │   ├── (dev)/page.tsx           # 开发者后台（阶段三）
│   │   └── layout.tsx
│   ├── components/
│   │   ├── chat/                    # 对话流式渲染
│   │   ├── trace/                   # 轨迹可视化
│   │   ├── tool-card/               # 工具调用卡片
│   │   ├── metrics/                 # 实时指标
│   │   └── guardrail/               # 护栏提示
│   ├── lib/
│   │   ├── sse-client.ts
│   │   ├── ws-client.ts
│   │   └── api.ts
│   └── package.json
├── profiles/                        # 实验配置（YAML）
├── plugins/                         # 新技术点实验区
├── benchmarks/                      # 评测任务集
├── guardrail_configs/               # NeMo 护栏配置
└── docs/
```

**目录约定**：`plugins/` 是新技术点的首选落地点——先在这里实验，验证有效后再沉淀进 `adapters/`。

---

## 8. 分阶段实现路线图

遵循"先 MVP 用户前台可用，再生产加固，再开发者后台，最后多 Agent 治理"的渐进原则。每个阶段定义**量化退出标准**，不达标不进下一阶段。

### 阶段一：MVP — 用户前台最小可用（1-2 周）

**目标**：终端用户能对话 → Agent 用工具完成任务 → 流式展示 → 基础护栏。

**技术范围**（成熟框架最小子集）：
- LangGraph `create_react_agent`（最小编排，不搞复杂图）
- MCP filesystem server（文件读写工具）
- litellm 接入 OpenAI / Claude（真实 LLM）
- NeMo Guardrails 输入 / 输出基础筛查
- FastAPI SSE 流式 + Next.js 对话 UI
- Langfuse trace（基础轨迹）

**实现清单**：
- [ ] core: `hook_bridge.py`（LangGraph callback → Hook）、`guardrail_pipeline.py` 骨架、`cost_guard.py`
- [ ] adapters: `langgraph_react` / `mcp_provider` / `litellm_provider` / `nemo_guardrails` / `langfuse_tracer`
- [ ] api: SSE 流式对话端点 / 会话管理 / Profile 查询
- [ ] frontend: 对话页（流式输出 + 工具调用卡片 + 实时 token/cost）
- [ ] 1 个 demo Profile（`user-chat-v1`）+ 5 个预设任务

**退出标准（量化）**：
- 真实 LLM 完成 5 个预设任务（读文件 → 分析 → 写文件），成功率 ≥ 60%
- SSE 首 token 延迟 < 500ms（本地）
- 工具调用在 UI 可见（参数 + 结果），用户能看清 Agent 干了什么
- NeMo 护栏拦截 3 个明显有害输入（如"删除所有文件"），拦截率 100%
- **核心 0 改动**接入 1 个新插件（如换一种 trace 输出），验证扩展机制仍成立

### 阶段二：生产加固（2-4 周）

**目标**：六层护栏 + 记忆层 + 可观测 + 成本熔断 + HITL，形成生产级可靠闭环。

**技术范围**：
- 六层护栏完整（NeMo + LlamaGuard + 工具护栏 + 检索护栏 + 审计）
- Mem0 记忆层（短期 + 情景 + 语义）
- Langfuse 完整 trace（成本 / 延迟 / 链路）
- CostGuard 分级降级（L1 压缩 → L2 切模型 → L4 终止）
- HITL 审批（危险工具 WebSocket 审批）
- Context compaction + 40% 利用率守卫

**退出标准（量化）**：
- 护栏拦截预设有害测试集（20 条），拦截率 100%，误杀率 < 10%
- Mem0 跨会话记忆：第 2 次对话能引用第 1 次的信息
- CostGuard 在 token 超 80% 阈值时正确触发 L2 切模型，不失控
- HITL 审批：危险工具（`run_bash`）调用时弹出审批，拒绝则跳过
- Langfuse trace 含完整 step/tool/cost 链路，可导出

### 阶段三：开发者后台 + 实验框架（2-3 周）

**目标**：trace 对比 + Profile A/B + 评测流水线，赋能 harness 研究。

**技术范围**：
- DeepEval 评测集成（`answer_relevancy` / `faithfulness` / `task_success`）
- Profile A/B 实验框架（接 v1 的 `experiment.py`）
- 开发者后台前端（trace diff / A-B 对比表 / 指标看板）
- SWE-bench Lite 真实数据集接入

**退出标准（量化）**：
- 2 个 Profile A/B 对比，输出量化表（成功率 / 成本 / 步数 / 上下文利用率）
- DeepEval CI 流水线：PR 触发评测，指标回退则 fail
- trace 可视化：两个 Profile 轨迹并排 diff，高亮差异步
- SWE-bench Lite 跑通 ≥ 10 任务，有公开可比结果

### 阶段四：多 Agent + 治理（2-3 周）

**目标**：Supervisor 多 Agent + 权限模型 + 审计。

**技术范围**：
- LangGraph Supervisor 模式（主 Agent 拆分 → worker 并行 → 汇总）
- RBAC 权限模型（工具 / 文件 / 网络分级）
- 审计日志（不可篡改，全链路回溯）
- 并发控制（信号量）

**退出标准（量化）**：
- Supervisor 模式完成 1 个多文件重构任务，worker 并行执行
- RBAC：不同角色只能调用授权工具，越权调用 100% 拒绝
- 审计日志可回溯单次任务全链路（每步工具调用 + 结果 + 审批）

---

## 9. 关键设计权衡与风险

### 9.1 成熟框架 vs 自研的边界

| 必须**自研** | 直接**用框架** |
|---|---|
| Registry / Profile / Hook 可扩展层（核心价值） | LangGraph 编排（不重新发明图引擎） |
| GuardrailPipeline 六层编排（业务逻辑） | MCP 工具协议（用标准 SDK） |
| Hook 桥接层（语义统一） | Mem0 记忆抽取（用其算法） |
| Experiment 对比框架（实验逻辑） | litellm 多模型（用其适配） |
| CostGuard 降级策略（业务决策） | Langfuse trace（用其后端） |

**原则**：可扩展层（WHAT）自研，框架能力（HOW）用成熟组件。护栏的"六层在哪挂"自研，"单层怎么查"用 NeMo / LlamaGuard。

### 9.2 可扩展层过度抽象风险

**风险**：Plugin 接口过早固化，新技术点装不进。
**对冲**：三层逃生口（Plugin → Hook → 自定义域）。MVP 只定义 9 域最小接口，按需加域。定期消融实验移除不必要抽象（参考 Anthropic 洞察：模型变强后 harness 应定期简化）。

### 9.3 前后端流式通信工程难点

| 难点 | 方案 |
|---|---|
| SSE 断线重连 | 前端 EventSource 自动重连 + 后端 LangGraph checkpoint |
| 工具调用中插入流式文本 | 事件类型区分（`text_delta` / `tool_call` / `tool_result`） |
| HITL 审批阻塞流 | SSE 输出 + WebSocket 审批双通道，审批挂起当前 step |
| 长任务超时 | CostGuard L4 终止 + 前端超时提示 |

### 9.4 评测有效性（用 AI 测 AI）

**风险**：LLM-as-Judge 同源偏差（生成模型自评会系统性高估自己）。
**对冲**：DeepEval 多指标交叉 + 真实 benchmark（SWE-bench）+ 人工抽检 + **生成-评估解耦**（Evaluator 用不同模型，参考方案核心原则）。

### 9.5 主要风险清单

1. **接口设计过早固化** → 三层逃生口 + 消融实验定期重构
2. **过度工程化** → MVP 只做最小框架子集，按需补层
3. **框架升级破坏适配层** → adapters 隔离框架变动，core 不感知；版本锁定 + 适配层测试
4. **流式通信复杂度** → MVP 先做单向 SSE，HITL 用 WebSocket，分阶段引入

---

## 10. 与 v1 迁移策略

### 10.1 资产保留

| 资产 | 处理 | 理由 |
|---|---|---|
| 核心抽象思想（三层扩展 / 三件套 / Hook 三约束） | **保留** | 设计精髓，框架无关 |
| `conch/core/extension.py` | **保留 + 扩展** | 加 guardrail 域接口，接口设计优秀 |
| `conch/core/registry.py` | **保留** | 依赖拓扑 / 生命周期 / 发现 / 版本共存，无需改 |
| `conch/core/hooks.py` | **保留** | 14 挂载点 + 三约束，框架无关 |
| `conch/core/middleware.py` | **保留** | Pipeline 数据流，复用做护栏 |
| `conch/core/profile.py` | **保留 + 强化** | extends + 校验优秀，强化 Pydantic |
| `conch/core/experiment.py` | **保留 + 接 DeepEval** | A/B 对比框架，接 DeepEval 指标 |
| 技术点文档（`docs/technical-points/` 13 篇） | **保留** | 知识资产 |
| benchmark（swe-mini） | **保留** | 评测资产 |

### 10.2 推翻重写

| 资产 | 处理 | 理由 |
|---|---|---|
| 9 域骨架实现（`conch/domains/`） | **推翻 → `adapters/`** | 从未接真实 LLM，重写为框架适配器 |
| `conch/core/loop.py` 自建 AgentLoop | **降级为可选 Plugin** | LangGraph 为默认编排，自建 Loop 保留为轻量选项 |
| `conch/web/` 静态 HTML | **推翻** | 换 Next.js 完整前端 |
| ScriptedProvider 模拟 | **推翻** | 接真实 LLM（litellm） |
| `runtime/store/memory_store.py` | **推翻** | 换 PostgreSQL + Chroma + Redis |

### 10.3 conch/core/ 8 文件改造结论

| 文件 | 决策 | 改动量 |
|---|---|---|
| `extension.py` | 改造复用 | 新增 GuardrailProvider 接口 + DOMAINS 加 "guardrail" |
| `registry.py` | 直接复用 | 零改动 |
| `hooks.py` | 直接复用 | 零改动 |
| `middleware.py` | 直接复用 | 零改动 |
| `profile.py` | 改造复用 | 强化 Pydantic 校验（生产用 Pydantic） |
| `experiment.py` | 改造复用 | 接 DeepEval 指标，接真实 LLM 执行 |
| `loop.py` | 拆分改造 | CostGuard 拆到 `cost_guard.py`；AgentLoop 降级为 `single_loop` Plugin；编排主路径走 LangGraph |
| `__init__.py` | 更新导出 | 适配新模块 |

**结论**：8 个文件中 3 个直接复用、4 个改造复用、1 个拆分改造。**核心抽象层 80% 保留**，体现了 v1 设计的优秀——接口定义 WHAT 不定义 HOW，使得从"自建一切"到"成熟框架底座"的迁移只需替换实现层（`adapters`），核心层几乎不动。这正是可扩展性精髓的价值验证。

---

## 11. 核心原则总结

| 原则 | 含义 |
|---|---|
| **成熟框架优先** | 能用 LangGraph/MCP/Mem0 解决的不重新发明，自研收敛到可扩展层 |
| **确定性 > 概率性** | 护栏用代码规则而非软提示，确定性执行 |
| **分层防御** | 六层护栏层层拦截，不依赖单层 |
| **过程 > 结果** | 评测过程质量，pass@k 优于 pass@1 |
| **最小权限** | 工具、数据、Agent 间通信均遵循最小权限 |
| **持续 > 一次性** | 评测是 CI/CD 一部分，不是上线前一次性检查 |
| **可观测先于优化** | 先建立全链路 trace，才能定位瓶颈 |
| **人在回路** | 高危操作保留人工否决权 |
| **核心稳定、边界常新** | 接口定义 WHAT，实现（HOW）可随技术演进替换 |

---

## CHANGELOG

### v2.0 — 2026-06-27（推翻重做，成熟框架底座 + 可扩展层 + 用户前端）

**架构路线变更**
- 推翻 v0.3 的"自建一切"路线，改用成熟框架底座（LangGraph/MCP/Mem0/NeMo/Langfuse/DeepEval/litellm）
- 新增 `conch/adapters/` 适配层，把每个框架组件包装为 Plugin 注册到 Registry
- 新增 `core/hook_bridge.py` 桥接层，框架原生事件 → 框架无关的语义 Hook 总线
- 编排主路径从自建 Loop 切换到 LangGraph，自建 Loop 降级为轻量可选 Plugin

**前端补齐**
- 新增 Next.js 14 完整前端，三栏布局（会话列表 / 对话+轨迹 / 实时指标）
- SSE 流式输出 + WebSocket HITL 审批 + REST 配置管理

**能力域强化**
- 新增 guardrail 独立域，落地参考方案的六层纵深防御护栏
- 记忆层从文件笔记升级到 Mem0（五分法对齐）
- 评测层接入 DeepEval（CI 流水线）
- 可观测层接入 Langfuse（开源自托管）

**分阶段路线**
- MVP 先做用户前台最小可用（LangGraph + MCP + litellm + NeMo + FastAPI SSE + Next.js）
- 后续生产加固 → 开发者后台 → 多 Agent 治理，每阶段量化退出标准

**迁移策略**
- conch/core/ 8 文件 80% 保留（3 直接复用 + 4 改造复用 + 1 拆分改造）
- 9 域骨架实现推翻重写为 adapters
- 静态 HTML 前端推翻为 Next.js

### v0.3 — 2026-06-26（历史版本，保留参考）
- 见 `docs/technical-design.md`，自建 9 域 + 三层扩展 + 三件套，未接真实 LLM

---

_本方案为 v2.0 版本。AgentConch 从"研究骨架"升级为"可运行应用 + 可扩展底座"双栖——核心稳定、边界常新、应用可用。_

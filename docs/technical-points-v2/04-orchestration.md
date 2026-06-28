# 04 — 编排引擎：LangGraph ReAct + single_loop

> **代码位置**：`backend/conch/adapters/orchestration/langgraph_react.py`（140 行）、`single_loop.py`（160 行）
> **对应 ETCLOVG**：L 层（生命周期编排）

## 1. 两种编排模式

| 模式 | Plugin 名 | 框架 | 适用场景 |
|------|----------|------|---------|
| **LangGraph ReAct** | `langgraph_react` | langgraph.prebuilt | 默认编排，生产级 |
| **自建 Loop** | `single_loop` | 无框架依赖 | 轻量备选，教学/调试 |

两者都实现 `OrchestrationMode.run(task, agents, state) → AsyncIterator[dict]`，yield 统一 SSE 事件格式。Profile 中改 `orchestration.impl` 即可切换。

## 2. LangGraphReActOrchestrator（默认）

### 实现原理

```python
@registry.register("orchestration", "langgraph_react", "1.0")
class LangGraphReActOrchestrator(Plugin):
    def __init__(self, model, recursion_limit, api_base, api_key, temperature):
        self.model_name = model
        # api_key/api_base 优先级：构造参数 > 环境变量 OPENAI_API_KEY/BASE
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.api_base = api_base or os.environ.get("OPENAI_API_BASE")

    def build_graph(self, tools, system_prompt):
        """构建 LangGraph ReAct 图，在 run() 前由 deps.py 调用"""
        llm = self._build_llm()  # ChatOpenAI (streaming=True)
        self._graph = create_react_agent(llm, tools, prompt=system_prompt)

    async def run(self, task, agents, state):
        """流式执行，yield SSE 事件"""
        bridge = LangGraphHookBridge(state.hook_bus, state)
        config = {"recursion_limit": self.recursion_limit,
                  "callbacks": [bridge]}
        async for event in self._graph.astream_events(
            inputs, config=config, version="v2"):
            # on_chat_model_stream → yield text_delta
            # on_tool_start         → yield tool_call
            # on_tool_end           → yield tool_result
```

### 关键设计点

1. **延迟构建**：`_graph` 在 `build_graph()` 中构建，因为需要 tools 和 system_prompt（由 `ToolProvider` 和 `InformationProvider` 在运行时提供）。
2. **Hook 桥接**：通过 LangGraph callbacks 机制注入 `LangGraphHookBridge`，框架事件自动触发语义 Hook。
3. **API key 自动读取**：从环境变量 `OPENAI_API_KEY` 读取，Profile 中不传参即可工作（`.env` 配置）。
4. **模型适配**：litellm 的 `"provider/model"` 格式自动拆分为 langchain_openai 的 model 名（`openai/gpt-4o` → `gpt-4o`）。

## 3. SingleLoopOrchestration（轻量备选）

### 实现原理

```python
@registry.register("orchestration", "single_loop", "1.0")
class SingleLoopOrchestration(Plugin):
    async def run(self, task, agents, state):
        """手动步进循环，不依赖 LangGraph"""
        while not state.done and state.steps < self.max_steps:
            hook_bus.fire("pre_step", state)
            # 组装上下文
            # LLM 流式推理（litellm_provider.stream）
            # 工具执行 + 护栏检查
            # CostGuard 检查
            hook_bus.fire("post_step", state)
            yield ...  # SSE 事件
```

直接从 v1 的 `AgentLoop` 改造而来，保留了 Hook 触发顺序（pre_step → pre_model_call → post_model_call → pre_tool → post_tool → post_step），但底层 LLM 调用改为 `LiteLLMProvider.stream`。

## 4. 加载使用方式

```
API 层 deps.py: build_runtime(profile)
  ├─ registry.build("orchestration", "langgraph_react", ...)
  │    └─ 实例化 LangGraphReActOrchestrator
  │
  ├─ registry.build("tool", "mcp_provider", ...)
  ├─ registry.build("information", "agents_md", ...)
  │
  └─ chat.py (SSE 端点):
       rt = build_runtime(profile)
       tools = rt.tools.tools_for(task, rt.state)
       sys_prompt = rt.info_provider.assemble(task, rt.state)
       rt.orchestrator.build_graph(tools, sys_prompt)
       
       async for event in rt.orchestrator.run(task, [], rt.state):
           yield sse_event(event_type, event)  # → 前端
```

## 5. 事件流格式

编排 `run()` yield 的事件与 SSE 一一对应：

| 事件类型 | 触发 | 前端展示 |
|---------|------|---------|
| `text_delta` | LLM 流式 token | 逐字渲染 |
| `tool_call` | 工具开始执行 | 工具调用卡片 |
| `tool_result` | 工具执行完成 | 卡片显示结果 |
| `guardrail` | 护栏拦截 | 拦截提示横幅 |
| `done` | 任务完成 | 状态更新 |

## 6. 可扩展点

- 新编排模式 → 实现 `OrchestrationMode.run()` + `@register`
- 新 Hook Bridge → 如 `AutoGenHookBridge`（阶段四）
- 自定义 recursion_limit → Profile params 传入

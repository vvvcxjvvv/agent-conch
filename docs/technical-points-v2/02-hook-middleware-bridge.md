# 02 — Hook 总线 + Middleware 管道 + Hook Bridge 桥接

> **代码位置**：`backend/conch/core/hooks.py`（159 行）、`backend/conch/core/middleware.py`（59 行）、`backend/conch/core/hook_bridge.py`（110 行）
> **设计原则**：Hook 处理控制流（副作用/中断），Middleware 处理数据流（变换），Hook Bridge 框架事件→语义 Hook。

## 1. Hook 总线 — 控制流横切

### 14 个挂载点

| 挂载点 | 触发时机 | 可中断 |
|--------|---------|--------|
| `on_task_start` | 任务开始 | ❌ |
| `pre_step` | 每步开始 | ✅ |
| `post_step` | 每步结束 | ❌ |
| `pre_tool` | 工具执行前 | ✅ |
| `post_tool` | 工具执行后 | ❌ |
| `on_tool_error` | 工具执行出错 | ✅ |
| `pre_model_call` | LLM 推理前 | ❌ |
| `post_model_call` | LLM 推理后 | ❌ |
| `on_compaction` | 上下文压缩触发 | ❌ |
| `on_context_reset` | 上下文重置 | ❌ |
| `on_eval` | 评测触发 | ❌ |
| `on_cost_exceeded` | 成本超阈值 | ✅ |
| `on_task_end` | 任务结束 | ❌ |
| `on_error` | 异常发生 | ✅ |

### 三大约束

```python
# 1. 职责隔离：Hook 仅触发副作用，禁止修改主流程核心数据
# 2. 优先级：priority 数值越小越先执行（默认 100）
# 3. 中断白名单：仅 INTERRUPTIBLE_HOOKS 中的 5 个节点允许中断

INTERRUPTIBLE_HOOKS = {"on_tool_error", "pre_step", "pre_tool",
                        "on_cost_exceeded", "on_error"}
```

### Hook 注册与触发

```python
bus = HookBus()
bus.register("post_step", my_audit, priority=10, name="audit_log")
bus.fire("post_step", state)  # 按优先级顺序串行执行

# 装饰器注册
@hook("post_step", priority=10)
def audit_log(state):
    if state.total_cost > 100:
        return HookResult(action=HookAction.INTERRUPT, reason="cost too high")
```

`HookInterrupted` 异常被编排 Loop 捕获，优雅终止任务。

## 2. Middleware Pipeline — 数据流变换

```python
class Middleware(Generic[T]):
    def process(self, data: T) -> T: ...

class Pipeline(Generic[T]):
    def add(self, middleware: Middleware[T]) -> Pipeline[T]: ...
    def run(self, data: T) -> T: ...  # 按序应用所有中间件
```

Hook 处理"什么时候做"（控制流），Pipeline 处理"怎么做"（数据流）。例如上下文压缩："触发条件判断"是 Hook（`on_cost_exceeded`→检查阈值），"执行压缩清理"是 Pipeline（`JitLoader→SemanticCompactor→UtilizationGuard`）。

## 3. Hook Bridge — 框架事件桥接（核心创新）

v2 的核心创新。Hook 总线定义的是**框架无关的语义节点**（`pre_model_call` / `pre_tool` 等），每个编排 Plugin 通过 Bridge 把框架原生事件映射到这些语义节点。

```python
# core/hook_bridge.py
class LangGraphHookBridge:
    """LangGraph/LangChain 回调 → conch Hook 语义节点"""
    def __init__(self, hook_bus: HookBus, state: State): ...

    async def on_llm_start(self, ...):   → hook_bus.fire("pre_model_call", state)
    async def on_llm_end(self, ...):     → hook_bus.fire("post_model_call", state, action)
    async def on_tool_start(self, ...):  → hook_bus.fire("pre_tool", state, tool, args)
    async def on_tool_end(self, ...):    → hook_bus.fire("post_tool", state, result)
    async def on_tool_error(self, ...):  → hook_bus.fire("on_tool_error", state, error)
    async def on_chain_start(self, ...): → hook_bus.fire("pre_step", state)
    async def on_chain_end(self, ...):   → hook_bus.fire("post_step", state)
```

### 桥接的价值

换编排引擎（LangGraph → 自建 Loop → AutoGen），只需新写一个 Bridge 类（如 `AutoGenHookBridge`），所有已有的护栏 Hook、审计 Hook、成本守卫 Hook **零改动复用**。这是"成熟框架底座 + 零侵入可扩展层"叠加的根本保证。

```python
# 使用方式（编排 Plugin 内部）
bridge = LangGraphHookBridge(state.hook_bus, state)
config = {"callbacks": [bridge], "recursion_limit": 25}
async for event in graph.astream_events(inputs, config=config, version="v2"):
    ...
```

## 4. 加载流程

```
AgentRuntime 构建
  └─ build_runtime(profile)        ← api/deps.py
       ├─ HookBus()                 ← 全局 Hook 总线
       ├─ GuardrailPipeline(...)    ← 护栏管道（基于 Middleware.Pipeline）
       └─ State(hook_bus=hook_bus)  ← hook_bus 注入到 State
```

编排 Plugin 的 `run()` 方法接收 `state`（含 `hook_bus`），创建 `LangGraphHookBridge` 并挂到 LangGraph config。框架回调自动触发语义 Hook，无需编排逻辑显式调用 `hook_bus.fire()`。

## 5. 可扩展点

- 新横切关注点 → `@hook("post_step")` 或 `Pipeline.add(MyMiddleware())`
- 新编排引擎 → 写 `NewEngineHookBridge`，映射框架事件到语义 Hook
- 新护栏层 → `GuardrailMiddleware` 封装，加入 `GuardrailPipeline`

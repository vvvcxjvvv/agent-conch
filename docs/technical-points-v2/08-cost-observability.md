# 08 — 成本守卫 + 可观测性

> **代码位置**：`backend/conch/core/cost_guard.py`（105 行）、`backend/conch/adapters/observability/langfuse_tracer.py`（90 行）、`console_tracer.py`（120 行）
> **对应 ETCLOVG**：O 层（可观测性）+ 横切成本控制

## 1. CostGuard — Token Budget 分级降级

### 实现原理

```python
class CostGuard:
    def __init__(self, max_tokens: int | None):
        self.max_tokens = max_tokens

    def check(self, state: State) -> DegradeLevel:
        ratio = state.total_tokens / self.max_tokens
        if ratio >= 1.0:  return DegradeLevel.L4_TERMINATE
        if ratio >= 0.9:  return DegradeLevel.L3_DISABLE_TOOLS   # 延后
        if ratio >= 0.8:  return DegradeLevel.L2_SWITCH_MODEL
        if ratio >= 0.6:  return DegradeLevel.L1_COMPACT
        return DegradeLevel.NONE

    def apply(self, state, level):
        state.degrade_level = max(state.degrade_level, level)
        state.hook_bus.fire("on_cost_exceeded", state, level=level)
        if level == L4_TERMINATE:
            state.status = TaskStatus.DEGRADED  # 终止任务
```

### 四级降级策略

| 级别 | 阈值 | 动作 | 实现 |
|------|------|------|------|
| L1 Compact | 60% | 触发上下文压缩 | `ContextManager.compact()` |
| L2 Switch | 80% | 切换廉价模型 | `Profile.model → model_fallback` |
| L3 Disable | 90% | 禁用非核心工具 | 延后（MVP 走 L2） |
| L4 Terminate | 100% | 终止任务 | `State.status = DEGRADED` |

### State 状态机

```python
@dataclass
class State:
    task, status: TaskStatus, steps, actions, context,
    total_tokens, total_cost, result, error, degrade_level
    hook_bus: HookBus | None    # v2 新增，供 Hook Bridge 读取
    profile: Profile | None     # v2 新增
```

编排 Plugin 每步后调 `cost_guard.check(state)`，根据返回值执行降级。

## 2. 可观测性 — 双模式

### LangfuseTracer（可选）

```python
@registry.register("observability", "langfuse_tracer", "1.0")
class LangfuseTracer(Plugin):
    def on_load(self):
        handler = CallbackHandler(public_key=..., secret_key=..., host=...)
        self._callback_handler = handler  # 挂到 LangGraph config.callbacks

    def trace(self, state):  # 记录 step trace
    def metrics(self):       # 返回累计指标 {steps, tokens, cost}
```

当 Profile 中 `observability.impl = langfuse_tracer` 时启用，自动挂为 LangChain callback，全链路 trace 记录。

### ConsoleTracer（MVP 默认）

```python
@registry.register("observability", "console_tracer", "1.0")
class ConsoleTracer(Plugin):
    def trace(self, state):
        print(f"[Step {state.steps}] tokens={state.total_tokens} cost=${state.total_cost:.4f}")

    def metrics(self):
        return {"steps": self._steps, "tokens": self._tokens, "cost": self._cost}
```

Langfuse 未配置时兜底，控制台输出轨迹。

## 3. 加载使用方式

```python
# deps.py: build_runtime()
rt.cost_guard = CostGuard(max_tokens=profile.max_tokens)
rt.observability = registry.build("observability", impl, ...)

# 编排 Plugin 每步后
level = cost_guard.check(state)
if level != DegradeLevel.NONE:
    cost_guard.apply(state, level)

# 可观测 trace
rt.observability.trace(state)   # → Langfuse / Console
```

## 4. 实时指标传递（SSE → 前端）

```
编排 run() yield cost_update 事件
  └─ chat.py (SSE):
       yield sse_event("cost_update", {"tokens": ..., "cost": ..., "steps": ...})
            └─ 前端 MetricsPanel 实时更新 token/cost/步数
```

## 5. 可扩展点

- 新降级策略 → `CostGuard.check()` 加阈值分支
- 新可观测后端 → 实现 `ObservabilityProvider.trace/metrics` + `@register`
- 新指标 → `State` 加字段 + `trace()` 记录 + SSE 事件

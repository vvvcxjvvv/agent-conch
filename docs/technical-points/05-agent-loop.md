# 05 · Agent Loop 引擎

> 最小可靠的单 Agent 循环，多 Agent 在其上组合。内建 streaming 输出与 cost guard 分级降级。

## 循环结构

```
任务输入
    │
    ▼
┌─ on_task_start ─────────────────────────────────┐
│                                                  │
│  ┌─ pre_step ──────────────────────────────┐    │
│  │                                          │    │
│  │  组装上下文 (ContextManager.assemble)    │    │
│  │  pre_model_call → 推理(streaming) → post_model_call │
│  │                                          │    │
│  │  if 工具调用:                            │    │
│  │    pre_tool → 权限校验 → 执行 → post_tool │    │
│  │              └→ on_tool_error           │    │
│  │                                          │    │
│  │  记录轨迹 (Observability.trace)          │    │
│  │  成本守卫 (CostGuard.check → 降级)       │    │
│  │  评测 (Evaluator.should_eval → eval)    │    │
│  │  post_step                              │    │
│  └──────────────────────────────────────────┘    │
│           ↑ 循环直到 done 或 max_steps            │
└── on_task_end ──────────────────────────────────┘
```

## 核心组件

### State

Agent 执行状态，贯穿整个循环：

```python
@dataclass
class State:
    task: Any
    status: TaskStatus        # PENDING/RUNNING/DONE/DEGRADED/FAILED
    steps: int
    actions: list[dict]       # 每步动作记录
    context: Any              # 当前上下文
    total_tokens: int         # 累计 token
    total_cost: float         # 累计成本
    degrade_level: DegradeLevel
    result: Any
    error: Exception | None
```

### CostGuard

token budget 分级降级，与上下文管理联动：

| 降级级别 | 触发条件 | 动作 | MVP |
|---|---|---|---|
| L1 压缩 | 超 60% 阈值 | 触发 compaction | ✅ |
| L2 切模型 | 超 80% 阈值 | 切换到 model_fallback | ✅ |
| L3 禁工具 | 超 90% 阈值 | 禁用非核心工具 | 延后 |
| L4 终止 | 超 100% 预算 | 终止任务，返回中间结果 | ✅ |

```python
class CostGuard:
    def check(self, state: State) -> DegradeLevel:
        ratio = state.total_tokens / self.max_tokens
        if ratio >= 1.0: return L4_TERMINATE
        if ratio >= 0.8: return L2_SWITCH_MODEL
        if ratio >= 0.6: return L1_COMPACT
        return NONE
```

超阈值时优先触发 compaction 而非直接终止——cost guard 与域3上下文管理联动。

### Streaming

Provider 层统一提供 `stream()` 异步生成器，Loop 层边接收边检测工具调用：

```python
async for chunk in self.model.stream(context):
    self.obs.trace(state)        # 可逐步渲染输出
    if chunk.is_tool_call:
        break
```

流式输出对交互体验至关重要——用户能看到 Agent "正在思考"，而非等几十秒才出结果。

## 依赖注入

AgentLoop 通过 Profile + Registry 构建各域插件实例，核心层不依赖任何具体实现（依赖倒置）：

```python
class AgentLoop:
    def __init__(self, profile, registry, model, hook_bus):
        self.profile = profile
        self.registry = registry
        self.model = model
        self.hooks = hook_bus
        self.cost_guard = CostGuard(profile.max_tokens)

    def _ensure_plugins(self):
        # 按 Profile 配置延迟构建各域插件
        p = self.profile.domains
        self._ctx_mgr = self._build_or_none("context", p)
        self._tool_mgr = self._build_or_none("tool", p)
        ...
```

## Hook 集成

Loop 的每个关键节点都触发 Hook（见 03-hook-and-middleware.md），支持：
- `pre_tool` 安全审计中断
- `post_step` 熵增检测
- `on_cost_exceeded` 成本降级
- `on_error` 故障恢复

## 多 Agent 扩展

单 Agent Loop 是基础，多 Agent 协作在其上组合，实现 `OrchestrationMode` 接口（见 09-multi-agent-orchestration.md）。

## 相关文件

- `conch/core/loop.py`
- `docs/technical-points/03-hook-and-middleware.md`
- `docs/technical-points/12-cost-guard.md`

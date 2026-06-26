# 03 · Hook 总线与中间件链

> 可扩展性的逃生口——当新技术点既不属于已有 9 域、也无法用新插件表达时，通过 Hook 挂载到 Loop 任意节点。

## Hook vs 中间件：职责边界

| 机制 | 处理 | 能力 | 禁止 |
|---|---|---|---|
| **Hook** | 控制流 | 触发副作用（日志/告警/统计）、可中断流程 | 修改主流程核心数据 |
| **中间件 Pipeline** | 数据流 | 对数据做变换并传递 | 中断执行流程 |

两者不互斥——一个技术点可能同时用到两者：

> Context Reset 的"触发条件判断"是 Hook（控制流：决定是否重置），而"执行压缩清理"是 Pipeline（数据流：变换上下文数据）。

## Hook 挂载点

Agent Loop 的所有关键节点都支持 Hook：

```
on_task_start
  ├── pre_step
  │   ├── pre_model_call → [推理] → post_model_call
  │   ├── pre_tool → [工具执行] → post_tool / on_tool_error
  │   ├── on_compaction / on_context_reset
  │   ├── on_cost_exceeded
  │   ├── on_eval
  │   └── post_step
  └── on_task_end / on_error
```

## 三大约束（v0.3 固化）

### 1. 职责隔离

Hook **仅触发副作用**，禁止修改主流程核心数据。中间件**仅处理数据流**，禁止中断执行。

```python
@hook("post_step", priority=10)
def entropy_guard(state):
    """✅ 正确：只读 state，触发副作用"""
    if detect_drift(state):
        state.trigger_cleanup()  # 通过 state 方法，不直接改核心数据

@hook("post_step")
def bad_hook(state):
    """❌ 错误：直接修改核心数据"""
    state.actions = []  # 禁止！
```

### 2. 优先级

`priority` 数值越小越先执行（默认 100），同节点 Hook 按优先级顺序串行：

```python
@hook("pre_tool", priority=1)    # 先执行：安全审计
def security_audit(action, state): ...

@hook("pre_tool", priority=50)   # 后执行：性能监控
def perf_monitor(action, state): ...
```

### 3. 中断白名单

仅以下节点允许中断主流程，其余节点禁止终止：

```python
INTERRUPTIBLE_HOOKS = {
    "on_tool_error",    # 工具出错时可中断
    "pre_step",         # 步骤开始前可中断
    "pre_tool",         # 工具执行前可中断（如安全拦截）
    "on_cost_exceeded", # 成本超支时可中断
    "on_error",         # 错误发生时可中断
}
```

非白名单节点尝试中断会被忽略并记录告警。

## 中间件链

用于 context / tool / memory 等需要"链式处理"的域：

```python
context_pipeline = Pipeline([
    JitLoader(),           # 即时加载
    MetadataEnricher(),    # 元数据信号
    ToolResultClearer(),   # 清理深层工具结果
    SemanticCompactor(),   # 语义压缩
    UtilizationGuard(0.4), # 40% 阈值守卫
])

# 按顺序应用
context = context_pipeline.run(context)
```

每个中间件实现 `process(data) -> data`，数据流经整条链。

## 典型用例

| 场景 | 机制 | 挂载点 |
|---|---|---|
| 安全审计拦截危险工具 | Hook（可中断） | `pre_tool` |
| 每步后检测熵增触发清理 | Hook | `post_step` |
| 成本超支降级 | Hook（可中断） | `on_cost_exceeded` |
| 上下文压缩 | Pipeline | context 域 |
| 工具结果 token 优化 | Pipeline | tool 域 |
| 审计日志记录 | Hook | `post_tool` / `on_error` |

## 相关文件

- `conch/core/hooks.py`
- `conch/core/middleware.py`

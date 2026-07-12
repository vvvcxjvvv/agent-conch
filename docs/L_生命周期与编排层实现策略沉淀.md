# L 层 — 生命周期与编排层实现策略沉淀

> 层级：L (Lifecycle & Orchestration)  
> 阶段：P1 Workflow Agent

---

## 一、设计目标回顾

### 1.1 本层定位

L 层是 Agent-Conch 的控制中枢，负责 Agent 的执行循环、错误恢复、生命周期管理和多 Agent 编排。Agent Loop 是整个系统的核心：Observe-Think-Act 循环驱动 Agent 持续工作直到任务完成或达到限制。

### 1.2 P1 计划能力

- Agent Loop：Observe-Think-Act 循环 + forward_with_handling 错误降级
- Agent Runtime 可插拔：RuntimeRegistry + BuiltinConchRuntime
- Layer 基础框架：Layer 接口 + ExecutionLimitsLayer
- 并行工具执行

### 1.3 核心约束

- Agent Runtime 可插拔：不绑定单一执行循环
- Layer 插件体系：横切能力不写进 Agent Loop

---

## 二、核心实现方案

### 2.1 整体结构

```
engine/
├── conch_engine.py        # ConchEngine — 顶层编排器
├── agent_loop.py          # AgentLoop — Observe-Think-Act 循环
├── error_classifier.py    # ErrorClassifier — 错误分类与恢复策略
├── runtime/
│   ├── types.py           # AgentRuntime ABC + RuntimeRegistry + AgentResult
│   └── builtin.py         # BuiltinConchRuntime
└── layers/
    ├── base.py            # Layer ABC + LayerManager + GraphContext + NodeContext
    └── execution_limits.py # ExecutionLimitsLayer
```

### 2.2 核心类/接口

**AgentLoop**：核心执行循环
- `run(session_id, user_input) → AgentResult`：主入口
- 循环流程：
  1. 检查执行限制（max_turns / max_time）
  2. Layer.on_graph_start（首轮）
  3. forward_with_handling → LLM 调用
  4. 保存 assistant 消息
  5. 记录 LLM 调用轨迹
  6. 判断是否结束（无 tool_calls → break）
  7. Layer.on_node_run_start
  8. 并行执行工具调用（读并行 + 写串行）
  9. Layer.on_node_run_end
  10. 保存工具结果消息 + 记录轨迹
  11. 处理注入消息（VerificationLayer 等）
- `forward_with_handling(session_id) → LLMResponse | None`：错误降级
  - 最多 3 次重试
  - 策略：RETRY（指数退避）/ REQUERY / COMPACT / ABORT / CONTINUE
- `_call_model(session_id) → LLMResponse`：LLM 调用封装
  - 组装消息（system prompt + DB 历史消息）
  - 获取工具 schema
  - 调用 litellm.acompletion
  - 解析响应（content / tool_calls / usage）
- `_execute_tools_parallel(tool_calls) → list[ToolExecutionRecord]`：并行工具执行

**ConchEngine**：顶层编排器
- 初始化所有子系统（SessionDB / SandboxRegistry / ToolRegistry / LayerManager / TrajectoryStore）
- 注册 12 核心工具
- 生成 System Prompt（base + env + AGENTS.md）
- 创建 AgentLoop + BuiltinConchRuntime
- 提供 `run(user_input, session_id)` / `replay(session_id_or_file)` 接口

**AgentRuntime (ABC)**：Agent 执行器抽象
- `run(session_id, user_input) → AgentResult`
- `supported_tools() / supported_layers()`
- BuiltinConchRuntime：使用 AgentLoop 的标准循环

**Layer (ABC)**：生命周期钩子
- 5 个钩子：on_graph_start / on_node_run_start / on_node_run_end / on_event / on_graph_end
- LayerManager：按注册顺序执行，支持 should_abort 中断

**ErrorClassifier**：错误分类器
- 15 种 FailoverReason（API 超时/限流/认证/内容策略/连接 + 工具错误 + 上下文窗口 + 权限 + 格式 + 成本 + 未知）
- 5 种 RecoveryStrategy（RETRY / REQUERY / COMPACT / ABORT / CONTINUE）
- `classify(error) → ClassifiedError`：基于错误消息关键词匹配

### 2.3 Agent Loop 执行流程图

```
run(session_id, user_input)
  │
  ├── 创建/恢复 session
  ├── 添加 user 消息到 DB
  ├── Layer.on_graph_start
  │
  └── while turn_count < max_turns:
       ├── 检查时间限制
       ├── turn_count++, start_turn
       │
       ├── forward_with_handling(session_id)
       │    └── _call_model → litellm.acompletion
       │         ├── 成功 → return LLMResponse
       │         └── 失败 → ErrorClassifier.classify
       │              ├── RETRY → 退避重试
       │              ├── ABORT → return None
       │              └── CONTINUE → return error LLMResponse
       │
       ├── 保存 assistant 消息
       ├── 记录 LLM 轨迹
       ├── if no tool_calls → break
       │
       ├── Layer.on_node_run_start
       ├── 解析 tool_calls
       ├── _execute_tools_parallel (读并行 + 写串行)
       ├── Layer.on_node_run_end
       ├── 保存 tool 结果消息
       ├── 记录工具轨迹
       └── 处理 inject_messages
```

### 2.4 核心代码路径

- `src/agent_conch/engine/agent_loop.py` — AgentLoop + LLMResponse
- `src/agent_conch/engine/conch_engine.py` — ConchEngine
- `src/agent_conch/engine/error_classifier.py` — ErrorClassifier + FailoverReason + RecoveryStrategy
- `src/agent_conch/engine/runtime/types.py` — AgentRuntime + RuntimeRegistry + AgentResult
- `src/agent_conch/engine/runtime/builtin.py` — BuiltinConchRuntime
- `src/agent_conch/engine/layers/base.py` — Layer + LayerManager + GraphContext + NodeContext
- `src/agent_conch/engine/layers/execution_limits.py` — ExecutionLimitsLayer

---

## 三、设计落地对照

### ✅ 完全对齐设计

- Agent Loop Observe-Think-Act 循环
- forward_with_handling 错误降级（4 种恢复策略）
- AgentRuntime 可插拔 + RuntimeRegistry
- Layer 插件体系（5 钩子 + LayerManager）
- ExecutionLimitsLayer（max_turns + max_time）
- 并行工具执行（asyncio.gather + return_exceptions）

### ⚠️ 调整项

| 能力项 | 设计方案 | 实际实现 | 调整原因 |
| ------ | -------- | -------- | -------- |
| ErrorClassifier | 20+ 种错误 | 15 种 | P1 基础够用，P2 扩展 |
| auto-compact check | ContextEngine.maintain | 占位（无 Context Engine） | P2 交付物 |
| assemble context | ContextEngine.assemble | 直接从 DB 读取消息 | P2 交付物 |
| Prompt Caching | system_and_3 策略 | 未实现 | P2 交付物 |
| 多 Agent 编排 | Coordinator/Worker | 未实现 | P2/P4 交付物 |
| Pause/Resume | 状态序列化到 SQLite | CheckpointManager 占位 | P2 交付物 |

---

## 四、关键技术点与踩坑记录

### 4.1 forward_with_handling 异常吞没问题

**问题**：Agent Loop 循环中 `try/except` 块捕获了所有异常，导致 `break` 语句未执行。具体表现为：`trajectory.save_step()` 是同步方法，但被 `await` 调用导致 TypeError，TypeError 被循环的 except 块捕获，break 未执行，Agent 一直循环到 max_turns。

**根因**：`TrajectoryStore.save_step` 是同步方法（返回 int），但 Agent Loop 中用 `await self.trajectory.save_step(...)` 调用。`await int` 抛 TypeError，被 `except Exception` 捕获。

**解决方案**：
1. 将 `await self.trajectory.save_step(...)` 改为 `self.trajectory.save_step(...)`（同步调用）
2. 考虑未来将 save_step 改为 async（P2 用 aiosqlite 时）

**教训**：Agent Loop 的 except 块不应静默吞没异常。应该在 except 中记录详细错误信息，或在开发阶段打印 traceback。

### 4.2 LLM mock 测试中的 AsyncMock 问题

**问题**：使用 `patch.object(engine.agent_loop, "_call_model", side_effect=callable_object)` 时，如果 callable_object 的 `__call__` 是 async 方法但对象本身不是 async 函数，patch 不会创建 AsyncMock，导致 `await mock()` 返回 Mock 对象而非 coroutine。

**解决方案**：不使用 patch.object + side_effect，直接替换实例属性：`engine.agent_loop._call_model = mock_callable`。这样 `self._call_model(session_id)` 直接调用 callable 对象，正确返回 coroutine。

### 4.3 并行工具执行的读写分离

**设计**：并行执行只用于互不依赖的操作（读操作），写操作串行。

**实现**：通过 `tool.is_write_tool` 属性分离 tool_calls。读操作用 `asyncio.gather(return_exceptions=True)`，写操作逐个执行。结果按原始 tool_call_id 排序。

### 4.4 Layer 钩子的 abort 传播

**设计**：Layer.on_graph_start 可以设置 `ctx.should_abort = True` 中止执行。

**实现**：LayerManager.on_graph_start 遍历 Layer，每次检查 `ctx.should_abort`，为 True 则停止遍历并返回。Agent Loop 检查 `graph_ctx.should_abort` 决定是否继续。

---

## 五、验证与覆盖情况

### 5.1 测试覆盖

| 测试类 | 测试数 | 覆盖场景 |
| ------ | ------ | -------- |
| TestExecutionLimitsLayer | 3 | 未超限/max_turns/max_time |
| TestLayerManager | 3 | 添加移除/start_time/abort 传播 |
| TestErrorClassifier | 9 | timeout/rate_limit/auth/content_policy/context_window/permission/retry/non-retryable |
| 集成测试 | 5 | 完整循环/并行/沙箱/重试/回放 |

### 5.2 未覆盖场景

- 多 Agent 编排（Coordinator/Worker）
- Pause/Resume 状态恢复
- LLMQuotaLayer 配额熔断
- VerificationLayer 自动验证
- SuspendLayer 暂停事件捕获

---

## 六、演进与优化方向

### P2 演进
- ContextEngine 接入：AgentLoop._call_model 中的消息组装改为通过 ContextEngine.assemble
- Prompt Caching 接入：消息组装后添加 prompt_caching.apply
- auto-compact 接入：循环开头添加 context_engine.maintain
- ErrorClassifier 扩展到 20+ 种
- Subagent + 孤儿恢复
- Pause/Resume 完整实现

### P3 演进
- LLMQuotaLayer 配额熔断
- VerificationLayer 执行验证
- SuspendLayer + PauseStatePersistLayer
- OTel ObservabilityLayer

### P4 演进
- Coordinator 多 Agent 主从编排
- Cron 调度（3 分钟硬中断）
- PolicyLayer 策略引擎

### 长期演进
- 自定义 Runtime（研究/运维/远程执行）
- Agent Loop 可视化调试
- 执行流程图自动生成

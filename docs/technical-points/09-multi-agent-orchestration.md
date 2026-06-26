# 09 · 多 Agent 协作

> 单 Agent 是默认，多 Agent 在 Loop 之上组合。规模决定选择——小项目单 Agent 够用，大项目走向专业化分工。

## 三种标准模式

### OrchestratorWorker（主从）

主 Agent 拆分任务并分派，worker 执行后回报，主 Agent 汇总。

```
       ┌─ Worker 1 ─┐
Planner├─ Worker 2 ─┤→ Merger → 结果
       └─ Worker 3 ─┘
```

适用：任务可清晰拆分的场景（如多文件重构）。

### FanOutFanIn（并行）

同一任务扇出到多个 Agent 并行处理，结果聚合。

```
Task ─┬─ Agent 1 ─┐
      ├─ Agent 2 ─┤→ Aggregate → 结果
      └─ Agent 3 ─┘
```

适用：多视角评估、多方案生成后择优。

### GeneratorEvaluator（GAN 式）

Generator 生成 → Evaluator 评估 → 反馈循环，对抗自我评价偏差。

```
Generator ⇄ Evaluator
    │           │
    └─ 反馈 ←──┘
```

参考 Anthropic 三智能体架构。打分权重可故意提高难度维度，逼模型往上走。

## 接口预留

```python
class OrchestrationMode(ExtensionPoint, Protocol):
    async def run(self, task, agents, state) -> State: ...

    # 多 Agent 协作预留接口（L3 实现）
    async def task_split(self, task, state) -> list[SubTask]: ...
    """任务拆分"""
    async def state_sync(self, agents, state) -> None: ...
    """状态同步：避免信息孤岛"""
    async def conflict_resolve(self, results, state) -> Result: ...
    """冲突解决：多 Agent 结果冲突时的裁决"""
```

> 三个方法为 L3 多 Agent 阶段预留，单 Agent 模式可不实现。

## 并发控制

多 Agent 并行执行时，通过信号量限制并发数：

```python
class ConcurrencyGuard:
    def __init__(self, max_concurrent=4):
        self._sem = asyncio.Semaphore(max_concurrent)
```

> **资源池调度边界**：v0.2 评审提出"资源池+任务队列、按推理/执行/评估三类 Agent 划分独立池+优先级调度"。此项属 L3/L4 需求，**明确延后**——MVP 信号量已够用，规模化后再引入资源池模型。

## 状态机编排（第四种模式）

Stripe 式"确定性节点 + Agent 节点混合"状态机，作为 `StateMachine` 插件实现：

```
[lint 节点(确定性)] → [实现功能节点(Agent)] → [push 节点(确定性)] → [修CI节点(Agent)]
```

该确定的地方确定，该灵活的地方灵活。

## 与 LangGraph 的关系

AgentConch 自建 Loop 保证核心可控（Hook 总线覆盖完整），LangGraph 作为编排域的一个**可选插件**：

```
编排域插件：
  - single_loop       （默认）
  - orchestrator_worker
  - fan_out_fan_in
  - generator_evaluator
  - state_machine
  - langgraph_engine  （可选，封装 LangGraph 图引擎）
```

同一任务可对比 `single_loop` vs `langgraph_engine` vs `state_machine` 的效果差异——这正是实验框架的价值。

## 单 Agent vs 多 Agent 的选择

| 规模 | 推荐 | 参考 |
|---|---|---|
| 小项目 | 单 Agent | Hashimoto 坚持单 Agent |
| 大项目 | 多 Agent 专业化分工 | Carlini 用 16 个并行 Agent |

> Carlini 关键洞察："我是在为 Claude 写这个测试框架，不是为自己写"——Harness 的服务对象首先是 Agent。

## 相关文件

- `conch/core/extension.py` — OrchestrationMode 接口
- `conch/domains/orchestration/single_loop.py` — 默认实现
- `docs/technical-points/05-agent-loop.md` — Loop 引擎

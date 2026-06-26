# 10 · 可观测性与 Agent 自观测

> 评测与可观测性不应割裂，应被视为同一反馈回路的一部分。

## 四级核心指标集

对齐 LangSmith / 业内通用标准：

| 类别 | 指标 | MVP |
|---|---|---|
| **执行类** | step 总数、工具调用成功率、Context Reset 次数、平均单步延迟 | ✅ |
| **成本类** | 总 token 消耗、模型调用费用、单任务综合成本 | ✅ |
| **效果类** | 任务成功率、评测得分、人工抽检通过率、故障恢复率 | 阶段二 |
| **健康类** | 权限越权次数、沙箱异常次数、插件加载失败率 | 阶段三 |

> MVP 先实现执行类 + 成本类，效果类随域6评测体系补齐，健康类随域9治理补齐。

## Agent 自观测（OpenAI 实践）

> "可观测性给 Agent 看"——性能指标变成 Agent 可自测的。

AgentConch 将核心指标封装为**只读工具**，Agent 可调用查询自身运行数据：

```python
# Agent 可调用的自观测工具
def get_current_stats() -> dict:
    """查询当前任务运行数据"""
    return {
        "steps": state.steps,
        "tokens_used": state.total_tokens,
        "cost": state.total_cost,
        "budget_remaining": max(0, max_tokens - state.total_tokens),
        "context_utilization": context.utilization,
    }
```

结合 Hook 实现自动调优：token 超支自动触发压缩（CostGuard L1），上下文利用率超 40% 自动触发 compaction。

## 轨迹追踪

OpenTelemetry 标准化轨迹，完整 step/tool/token 链路：

```python
class ConsoleTracer(ObservabilityProvider):
    def trace(self, state):
        print(f"[step {state.steps}] "
              f"action={state.actions[-1].get('type')} "
              f"tokens={state.total_tokens} "
              f"cost=${state.total_cost:.4f}")

    def metrics(self):
        return {
            "total_steps": state.steps,
            "total_tokens": state.total_tokens,
            "total_cost": state.total_cost,
            "tool_success_rate": ...,
        }
```

## 评测与可观测共享轨迹

Anthropic / LangChain 共识：评测 ≠ 割裂。评测器和可观测性读取同一份轨迹数据，形成闭环：

```
轨迹存储（共享）
    ├── 可观测性：读取 → 指标 → 成本/效率分析
    └── 评测：读取 → 评估 → 反馈 → 纠偏
```

## DOM 快照与截图

浏览器场景的可视化轨迹（参考 OpenAI 接入 Chrome DevTools Protocol）：
- DOM 快照：Agent 可抓取页面结构
- 截图：可视化调试
- 链路追踪：跨 Agent / 跨工具调用链

> 这些在 Playwright Evaluator 集成后启用（阶段三）。

## 接口

```python
class ObservabilityProvider(ExtensionPoint, Protocol):
    def trace(self, state) -> None: ...      # 记录一个 step
    def metrics(self) -> dict: ...           # 返回累计指标
```

## 相关文件

- `conch/core/extension.py` — ObservabilityProvider 接口
- `conch/domains/observability/console_tracer.py` — 默认实现
- `docs/technical-points/12-cost-guard.md` — 成本守卫联动

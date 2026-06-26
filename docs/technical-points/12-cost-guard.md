# 12 · 成本守卫与分级降级

> token budget 控制，与上下文管理联动降级，防止成本失控。

## 分级降级策略

CostGuard 维护单任务累计 token 计数，超阈值时按级别降级：

```
token 消耗比例
0% ─────────── 60% ───── 80% ── 90% ── 100%
  │              │        │      │       │
  │     L1 压缩  │ L2切模型│ L3禁工具│ L4终止
  │              │        │      │       │
  正常运行    触发compaction 切廉价模型 禁非核心工具 终止返回中间结果
```

| 级别 | 触发条件 | 动作 | MVP |
|---|---|---|---|
| L1 压缩 | 超 60% 阈值 | 触发 compaction，清理冗余上下文 | ✅ |
| L2 切模型 | 超 80% 阈值 | 切换到 `model_fallback` 廉价模型 | ✅ |
| L3 禁工具 | 超 90% 阈值 | 禁用非核心工具，仅保留只读 | 延后 |
| L4 终止 | 超 100% 预算 | 终止任务，返回中间结果 | ✅ |

## 核心逻辑

```python
class CostGuard:
    def __init__(self, max_tokens: int | None = None):
        self.max_tokens = max_tokens

    def check(self, state: State) -> DegradeLevel:
        if self.max_tokens is None:
            return DegradeLevel.NONE

        ratio = state.total_tokens / self.max_tokens
        if ratio >= 1.0: return DegradeLevel.L4_TERMINATE
        if ratio >= 0.8: return DegradeLevel.L2_SWITCH_MODEL
        if ratio >= 0.6: return DegradeLevel.L1_COMPACT
        return DegradeLevel.NONE
```

## 与上下文管理联动

超阈值时**优先触发 compaction 而非直接终止**——cost guard 与域3上下文管理联动：

```python
def _handle_degrade(self, state, level):
    if level == L1_COMPACT and self._ctx_mgr:
        state.context = self._ctx_mgr.compact(state.context, strategy="summary")
        self.hooks.fire("on_compaction", state)

    elif level == L2_SWITCH_MODEL and self.profile.model_fallback:
        self.profile.model = self.profile.model_fallback

    elif level == L4_TERMINATE:
        state.status = TaskStatus.DEGRADED
```

## Hook 集成

`on_cost_exceeded` 是可中断节点（中断白名单），Hook 可在此做额外处理：

```python
@hook("on_cost_exceeded", priority=1)
def budget_alert(state, level):
    """超支告警"""
    notify(f"Task {state.task} cost guard triggered: {level.name}")
```

## Profile 配置

```yaml
max_tokens: 100000              # token budget
model: gpt-4o                   # 默认模型
model_fallback: gpt-4o-mini     # L2 降级切换的廉价模型
```

## 成本统计维度

| 维度 | 说明 | MVP |
|---|---|---|
| token 费用 | 输入/输出 token × 单价 | ✅ |
| 模型调用费 | 每次模型调用的费用 | ✅ |
| 沙箱资源时长 | Docker 运行时长 × 单价 | 可选 |
| 第三方 API 费 | 外部工具/API 调用费用 | 可选 |

> **预算分组延后**：按任务/项目/团队设置独立 token 预算、超支自动拦截，属 L4 企业多租户，延后。

## 降级记录

每级降级记录到轨迹，便于复盘：

```
[step 8] cost_guard L1_COMPACT triggered (tokens=62000/100000=62%)
[step 12] cost_guard L2_SWITCH_MODEL triggered (tokens=81000/100000=81%)
[step 15] cost_guard L4_TERMINATE triggered (tokens=100500/100000=100.5%)
```

## 相关文件

- `conch/core/loop.py` — CostGuard / DegradeLevel
- `docs/technical-points/05-agent-loop.md` — Loop 集成
- `docs/technical-points/06-context-management.md` — compaction 联动

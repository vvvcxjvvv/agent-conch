# 01 · 扩展点契约（ExtensionPoint）

> 核心设计哲学：**能力域接口定义 WHAT（做什么），不定义 HOW（怎么做）。**

## 核心概念

AgentConch 把 Harness 拆解为 9 大能力域，每个域 = 一个 `ExtensionPoint`（扩展点）。扩展点是一份**稳定的接口契约**——它定义了该域"能做什么"，但不限定"怎么做"。

```
ExtensionPoint（接口契约，稳定）
       ▲
       │ 实现
       │
  Plugin A / Plugin B / Plugin C（具体技术点，可变）
```

## 为什么这样设计

AI Agent 领域技术更新极快。如果接口绑定了实现方式，新技术出现时就得改接口，导致核心层频繁变动、向后兼容断裂。

ExtensionPoint 只定义"做什么"：
- 上下文管理域定义 `assemble / compact / should_compact` 三个方法
- 不限定压缩算法是摘要、语义聚类还是 token 裁剪

这样即使 2027 年出了全新的上下文压缩技术，也只需写一个新插件实现接口，核心层零改动。

## 9 大能力域接口

| 域 | 扩展点 | 核心方法 |
|---|---|---|
| 1 信息边界 | `InformationProvider` | `assemble(task, state)` |
| 2 工具系统 | `ToolProvider` | `tools_for(task, state)` / `execute(tool, args, state)` |
| 3 上下文管理 | `ContextManager` | `assemble` / `compact` / `should_compact` |
| 4 记忆状态 | `MemoryProvider` | `store(key, value, type)` / `recall(query, type)` |
| 5 执行编排 | `OrchestrationMode` | `run(task, agents, state)` + 三方法预留 |
| 6 评估验证 | `Evaluator` | `should_eval(state)` / `eval(state)` |
| 7 可观测性 | `ObservabilityProvider` | `trace(state)` / `metrics()` |
| 8 约束恢复 | `ConstraintProvider` | `validate(action, state)` / `recover(error, state)` |
| 9 治理 | `GovernanceProvider` | `check_permission(tool, args)` / `audit(action, detail)` |

## 依赖倒置原则

核心层（`conch/core/`）**仅定义接口契约，不依赖任何具体能力域实现**。9 大能力域作为实现层，反向依赖核心抽象层。

```
conch/core/extension.py    ← 只定义 Protocol，不 import domains
        ▲
        │ 反向依赖
conch/domains/*/*.py       ← import core，实现接口，@register 注册
```

这保证核心层不被业务逻辑耦合——改一个域的实现不会影响核心，加一个新城也不需要改核心。

## 实现方式

AgentConch 使用 Python 的 `Protocol`（结构化子类型）而非 `ABC`（名义子类型）：

```python
@runtime_checkable
class ExtensionPoint(Protocol):
    domain: str
    name: str
    version: str
    metadata: dict[str, Any]
```

好处：
- **鸭子类型**：插件不需要继承基类，只要实现了方法就满足接口
- **runtime_checkable**：运行时可检查 `isinstance(obj, ExtensionPoint)`
- **零耦合**：插件作者不需要 import 核心基类

## 相关文件

- `conch/core/extension.py` — 9 域接口定义
- `conch/core/registry.py` — 插件注册中心

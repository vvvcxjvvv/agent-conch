# 01 — 可扩展核心：ExtensionPoint + Registry

> **代码位置**：`backend/conch/core/extension.py`（248 行）、`backend/conch/core/registry.py`（182 行）
> **设计原则**：接口定义 WHAT 不定义 HOW，核心层不泄漏框架概念。

## 1. ExtensionPoint — 能力域接口契约

`ExtensionPoint` 是所有能力域的基类 Protocol，每个域定义自己的接口：

```python
# core/extension.py
@runtime_checkable
class ExtensionPoint(Protocol):
    domain: str       # 能力域标识
    name: str         # 实现名
    version: str      # 语义化版本
    metadata: dict    # 自描述元数据（capabilities / cost 等）
```

### 10 大能力域 Protocol

| 域 | Protocol | 核心方法 |
|----|----------|---------|
| 信息边界 | `InformationProvider` | `assemble(task, state)` |
| 工具系统 | `ToolProvider` | `tools_for(task, state)` / `execute(tool, args, state)` |
| 上下文 | `ContextManager` | `assemble(task, state)` / `compact(ctx)` / `should_compact(ctx)` |
| 记忆 | `MemoryProvider` | `store(key, value, mem_type)` / `recall(query, mem_type)` |
| 编排 | `OrchestrationMode` | `run(task, agents, state)` / `task_split` / `state_sync` |
| 评测 | `Evaluator` | `should_eval(state)` / `eval(state)` |
| 可观测 | `ObservabilityProvider` | `trace(state)` / `metrics()` |
| 约束恢复 | `ConstraintProvider` | `validate(action, state)` / `recover(error, state)` |
| 治理 | `GovernanceProvider` | `check_permission(tool, args)` / `audit(action, detail)` |
| **护栏** | `GuardrailProvider` | `check_input(text, state)` / `check_output` / `check_tool` |

v2 新增 `GuardrailProvider`（第 10 域）和 `GuardrailResult` dataclass（blocked / reason / sanitized / action）。

### Plugin 基类

```python
class Plugin:
    domain: str = ""; name: str = ""; version: str = "1.0"; metadata: dict = {}
    def on_load(self): ...    # 初始化资源
    def on_unload(self): ...  # 清理资源
    def on_reload(self): ...  # 热重载（unload + load）
```

适配器通过继承 `Plugin` 获得生命周期管理，同时实现对应域的 Protocol。

## 2. Registry — 注册中心

### 注册机制

```python
# 装饰器注册
@registry.register("orchestration", "langgraph_react", "1.0")
class LangGraphReActOrchestrator(Plugin):
    domain = "orchestration"
    name = "langgraph_react"
    ...
```

装饰器自动设置 `cls.domain / cls.name / cls.version`，存入 `_domains[domain][name][version]` 三级索引。

### 构建流程

```python
# Profile 加载后，API 层调用 registry.build 实例化
instance = registry.build("tool", "mcp_provider", "latest",
                          servers=[...])
```

内部流程：
1. `_resolve()` 解析版本（"latest" 取最高语义化版本）
2. `_load_with_deps()` 拓扑排序加载依赖（`depends_on` 字段，循环检测）
3. 实例化 → `on_load()` → 缓存 instance

### 运行时能力发现

```python
# 按域列出所有实现
registry.list("tool")  # → ['mcp_provider', 'builtin_shell']

# 按 capability 过滤
registry.query("orchestration", "multi_agent")  # → ['langgraph_supervisor']
```

## 3. 加载使用方式

### 全链路：Profile → Plugin 实例

```
YAML Profile
  └─ ProfileLoader.load("user-chat-v1")
       └─ _build_profile(raw)         ← profile.py
            └─ profile.validate_domains()  ← 校验域名为合法 DOMAINS
                 └─ api/deps.py: build_runtime(profile)
                      └─ registry.build(domain, impl, version, **params)
                           └─ _resolve → _load_with_deps → 实例化 → on_load()
                                └─ 组装到 AgentRuntime 容器
```

### 接入新技术点（核心 0 改动验证）

```python
# 1. 实现域接口
class MyGuardrail(Plugin):
    domain = "guardrail"; name = "my_guardrail"
    def check_input(self, text, state):
        return GuardrailResult(blocked="bad" in text)

# 2. 注册（import 即注册）
registry.register("guardrail", "my_guardrail", "1.0")(MyGuardrail)

# 3. Profile 中改一行
# guardrail: { impl: my_guardrail, params: {} }

# 核心 0 改动，所有已有 Hook/审计/成本守卫逻辑继续工作。
```

## 4. 可扩展点

- **L1**：新域内实现 → 继承 Plugin + 实现域 Protocol + `@register`
- **L2**：横切逻辑 → Hook 挂载或中间件链插入
- **L3**：全新能力维度 → `DOMAINS.append("新域")` + 定义新 Protocol

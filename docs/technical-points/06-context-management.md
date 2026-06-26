# 06 · 上下文管理

> 找到最小的高信噪比 token 集合，最大化实现期望结果的概率。

## 核心理念

上下文是**有限资源**，具有递减的边际收益。随着上下文窗口中 token 数量增加，模型准确回忆信息的能力会下降（"context rot"现象）。

AgentConch 上下文管理域（域3）负责：在合适时机给模型提供**正确且必要**的信息。

## 关键技术

### 即时上下文（Just-in-Time）

保留轻量引用（文件路径、查询 ID、网页链接），运行时动态拉取，而非预加载全部数据：

```python
class JitLoader(Middleware):
    def process(self, context):
        # 不预加载文件内容，只保留路径引用
        # Agent 需要时通过工具读取
        context.refs = extract_references(context)
        return context
```

参考 Anthropic / Claude Code：模型可以编写定向查询、存储结果，并利用 `head`/`tail` 分析大量数据，而无需将完整数据加载到上下文。

### 40% 利用率阈值

| 区间 | 表现 |
|---|---|
| **Smart Zone** (0~40%) | 推理聚焦、工具调用准确、代码质量高 |
| **Dumb Zone** (>40%) | 幻觉增多、兜圈子、格式混乱、代码变差 |

`should_compact()` 监控利用率，超 40% 触发压缩：

```python
class UtilizationGuard(Middleware):
    def __init__(self, threshold=0.4):
        self.threshold = threshold
    def process(self, context):
        if context.utilization > self.threshold:
            context.needs_compaction = True
        return context
```

### 上下文压缩（Compaction）

接近窗口上限时摘要蒸馏，高保真：

```python
def compact(self, context, strategy="summary"):
    # 保留关键信息：架构决策、未解决的 bug、实现细节
    # 丢弃冗余信息：冗余的工具输出、重复消息
    # 压缩后保留最近访问的文件
    ...
```

调优建议：先最大化召回率（确保捕获每条相关信息），再迭代提升精确率（消除多余内容）。

### 工具结果清理（Tool Result Clearing）

最简单、最安全的轻量压缩：深层历史中的工具结果移除——Agent 无需再看到原始结果。

### Context Resets

接近上下文饱和时，结构化交接后重启干净 Agent：

```
上下文接近饱和
    │
    ▼
结构化提取当前状态（已完成工作/待办/关键决策）
    │
    ▼
启动新干净 Agent
    │
    ▼
交接文档给它 → 新 Agent 从干净状态继续
```

> 类比程序遇到内存泄漏：重启进程，从检查点恢复状态。

## 中间件链

上下文处理按顺序应用多个技术：

```python
context_pipeline = Pipeline([
    JitLoader(),           # 即时加载
    MetadataEnricher(),    # 元数据信号（文件名/路径/时间戳）
    ToolResultClearer(),   # 清理深层工具结果
    SemanticCompactor(),   # 语义压缩
    UtilizationGuard(0.4), # 40% 阈值守卫
])
```

## 三种策略选择

| 策略 | 适用场景 |
|---|---|
| 压缩（Compaction） | 大量来回交互、要求对话流畅性 |
| 笔记（Note-taking） | 具有明确里程碑的迭代开发 |
| Context Reset | 上下文严重污染、需要彻底重启 |

## 接口

```python
class ContextManager(ExtensionPoint, Protocol):
    def assemble(self, task, state) -> "Context": ...
    def compact(self, context, strategy="summary") -> "Context": ...
    def should_compact(self, context) -> bool: ...
```

## 相关文件

- `conch/core/extension.py` — ContextManager 接口
- `conch/domains/context/jit_compaction.py` — 默认实现
- `docs/technical-points/03-hook-and-middleware.md` — Pipeline 机制

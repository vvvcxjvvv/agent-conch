# 02 · 注册中心（Registry）

> 装饰器注册，零配置发现，依赖声明拓扑加载，运行时发现，版本共存。

## 核心机制

Registry 是 AgentConch 的插件管理中枢。它属于核心层，不依赖任何具体实现——插件通过 `@registry.register` 装饰器**反向注册**到 Registry。

```python
@registry.register("context", "semantic_compaction", "1.0",
                   depends_on=["tool:result_cleaner"])
class SemanticCompaction:
    """新技术点：基于语义聚类的上下文压缩"""
    metadata = {"cost": "medium", "capabilities": ["compaction", "summarization"]}
    def compact(self, context, strategy): ...
```

一行装饰器，插件即接入系统。核心代码零改动。

## 四大能力

### 1. 依赖声明与拓扑加载

插件可声明 `depends_on`，Registry 负责拓扑排序加载，避免手动管理初始化顺序：

```python
@registry.register("context", "semantic_compaction", depends_on=["tool:result_cleaner"])
class SemanticCompaction: ...
```

`registry.build("context", "semantic_compaction")` 时，Registry 自动先加载 `tool:result_cleaner`，再加载自身。检测到循环依赖时抛出异常。

### 2. 生命周期钩子

插件可选择实现 `on_load` / `on_unload` / `on_reload`：

```python
class MyPlugin(Plugin):
    def on_load(self):
        self.db = connect_db()        # 加载时初始化
    def on_unload(self):
        self.db.close()                # 卸载时清理
    def on_reload(self):
        self.on_unload()
        self.on_load()                 # 热重载
```

`on_unload` 异常时自动回滚状态并记录告警，避免插件卸载异常导致核心崩溃。

### 3. 运行时发现

`query(domain, capability)` 按能力查找，而非硬编码插件名——支持动态编排：

```python
# 找出所有支持 "compaction" 能力的上下文管理插件
plugins = registry.query("context", capability="compaction")
# → ["semantic_compaction", "summary_compaction", "token_truncation"]
```

### 4. 版本共存

同一插件多版本可注册，Profile 指定版本，便于 A/B 对比新旧实现：

```yaml
# Profile A 用 v1.0
context: { impl: semantic_compaction, version: "1.0" }

# Profile B 用 v2.0（实验新版）
context: { impl: semantic_compaction, version: "2.0" }
```

`version: "latest"` 自动取最高语义化版本。

## 数据结构

```
Registry
  └── _domains: { domain: { name: { version: PluginEntry } } }
                                    │
                                    ├── cls: 类对象
                                    ├── instance: 单例实例
                                    ├── loaded: 是否已加载
                                    └── depends_on: 依赖列表
```

## 相关文件

- `conch/core/registry.py`
- `docs/technical-points/01-extension-point.md`（接口契约）
- `docs/technical-points/04-profile-and-experiment.md`（Profile 指定版本）

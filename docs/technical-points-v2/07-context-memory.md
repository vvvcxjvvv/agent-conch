# 07 — 上下文管理 + 记忆系统

> **代码位置**：`backend/conch/adapters/context/jit_compaction.py`（110 行）、`backend/conch/adapters/memory/notes_file.py`（110 行）
> **对应 ETCLOVG**：C 层（上下文工程）+ E 层（状态与记忆）

## 1. JitCompaction — JIT + 40% 阈值守卫

> 原则：上下文工程不是"塞更多信息"，而是"精准供给有效信息"。

### 实现原理

```python
@registry.register("context", "jit_compaction", "1.0")
class JitCompaction(Plugin):
    def __init__(self, threshold=0.4, max_context_tokens=100000):
        self.threshold = threshold         # 利用率阈值
        self.max_context_tokens = max_context_tokens

    def assemble(self, task, state):
        """JIT 原则：state.context 已存在则不重新加载"""
        if state.context is not None:
            return state.context
        return [{"role": "user", "content": str(task)}]

    def should_compact(self, context):
        """检查上下文利用率是否超阈值"""
        tokens = self._estimate_tokens(context)  # 4 字符 ≈ 1 token
        return (tokens / self.max_context_tokens) > self.threshold

    def compact(self, context, strategy="summary"):
        """保留首尾消息，中间合并为一条摘要"""
        head, tail = context[0], context[-1]
        middle = context[1:-1]
        summary = "[compacted N messages] " + middle_text[:500]
        return [head, summary, tail]
```

对齐参考方案的"Lost in the Middle"缓解策略：保留首尾（高召回区），中间压缩（低召回区）。

### 压缩策略

| 策略 | 实现 | 说明 |
|------|------|------|
| `summary` | 保留首尾 + 中间摘要截断 500 字符 | MVP 唯一实现 |
| `sliding_window` | 接口预留 | 阶段二 |
| `semantic_compression` | 接口预留 | 阶段二（需 LLM 辅助） |

## 2. NotesFileMemory — 基于文件的结构化记忆

> 对齐五分法：短期（short-term）+ 情景（episodic）。语义/长期/程序性延后到阶段二（Mem0）。

### 实现原理

```python
@registry.register("memory", "notes_file", "1.0")
class NotesFileMemory(Plugin):
    def __init__(self, path="NOTES.md"):
        self._short: dict = {}              # 短期：内存 dict
        self._episodic_cache: list = []     # 情景：文件持久化

    def on_load(self):
        """启动时从 NOTES.md 恢复 episodic 记忆"""
        if self.path.exists():
            self._episodic_cache = self.path.read_text().splitlines()

    def store(self, key, value, mem_type="short"):
        if mem_type == "short":
            self._short[key] = value       # 内存
        elif mem_type == "episodic":
            entry = f"- [{key}] {value}"
            self._episodic_cache.append(entry)
            self._flush()                   # 实时写回文件

    def recall(self, query, mem_type="short", limit=5):
        """简单子串匹配检索（从最新到最旧）"""
        results = []
        for entry in reversed(candidates):
            if query.lower() in entry.lower():
                results.append(entry)
            if len(results) >= limit: break
        return results
```

### 记忆生命周期

```
on_load() → 读文件恢复 episodic
    ↓
store() → 写短期（内存）/ 情景（内存 + 文件）
    ↓
recall() → 子串匹配检索（MVP 简化）
    ↓
on_unload() → 默认不清理（episodic 已在 store 时 flush）
```

阶段二接入 Mem0 后，`MemoryProvider` 接口不变，只需 `@register("memory", "mem0", "1.0")` 新实现。

## 3. 加载使用方式

```python
# deps.py: build_runtime()
if "context" in profile.domains:
    rt.context_mgr = registry.build("context", "jit_compaction", ...)
if "memory" in profile.domains:
    rt.memory = registry.build("memory", "notes_file", ...)
```

编排 Plugin 在每步开始时调 `context_mgr.assemble(task, state)` 组装上下文，CostGuard 触发 compaction 时调 `compact()`。记忆在工具调用后存储（`memory.store(key, result, "episodic")`），下次任务开始时检索。

## 4. 可扩展点

- 新压缩算法 → 实现 `ContextManager.compact()` + `@register("context", ...)`
- 新检索策略 → 改写 `recall()` 方法（向量检索 → Mem0）
- 新记忆后端 → 实现 `MemoryProvider.store/recall` + `@register("memory", ...)`
- 语义记忆 → 阶段二 `mem0` adapter

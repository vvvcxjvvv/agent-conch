# 07 — 上下文管理 + 记忆系统

> **代码位置**：`backend/conch/adapters/context/jit_compaction.py`、`backend/conch/adapters/memory/{mem0_provider,notes_file}.py`、`backend/conch/api/routes/chat.py`
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

## 2. NotesFileMemory — MVP 降级记忆

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

## 3. Mem0MemoryProvider — 阶段二记忆闭环

> 当前实现优先接真实 Mem0；若本地未安装或初始化失败，则自动回退到 JSONL 持久化。

### 实现原理

```python
@registry.register("memory", "mem0", "1.0")
class Mem0MemoryProvider(Plugin):
    def on_load(self):
        self._init_mem0()                 # 可用则接真实 Mem0
        self._load_fallback_records()     # 始终保留本地 JSONL 兜底

    def store(self, key, value, mem_type="episodic"):
        if self._mem0 is not None:
            self._mem0.add(...)
        self._records.append(record)
        self._flush_fallback_records()

    def recall(self, query, mem_type="episodic", limit=5):
        if self._mem0 is not None:
            result = self._mem0.search(...)
            if result:
                return normalize(result)
        return self._fallback_recall(query, mem_type, limit)   # 本地 relevance 排序
```

### 当前增强点

- `fallback_recall` 已支持相关度打分与排序
- `episodic` 查询会联带召回 `semantic / long_term / procedural`
- 召回结果会携带 `score`
- `chat.py` 会在注入系统提示前执行检索护栏

### 当前接线位置

```python
# chat.py
memory_context = rt.memory.recall(task, mem_type="episodic", limit=3)
memory_context = filter_recalled_memories(memory_context)   # 检索护栏
system_prompt = f"{system_prompt}\n\nRelevant memory:\n..."

# 对话成功结束后
rt.memory.store("user:...", {"role": "user", "content": user_message}, "episodic")
rt.memory.store("assistant:...", {"role": "assistant", "content": reply}, "episodic")
```

效果：

- 构图前按当前任务召回相关记忆
- 召回结果按相关度排序
- 敏感或低相关记忆在注入前被过滤
- 召回内容通过系统提示注入 LangGraph
- 当前回合成功结束后写入 user / assistant 记忆
- 新会话可复用旧偏好与事实信息

## 4. 加载使用方式

```python
# deps.py: build_runtime()
if "context" in profile.domains:
    rt.context_mgr = registry.build("context", "jit_compaction", ...)
if "memory" in profile.domains:
    rt.memory = registry.build("memory", "mem0", ...)
```

编排 Plugin 在每步开始时调 `context_mgr.assemble(task, state)` 组装上下文，CostGuard 触发 compaction 时调 `compact()`。记忆在工具调用后存储（`memory.store(key, result, "episodic")`），下次任务开始时检索。

## 5. 可扩展点

- 新压缩算法 → 实现 `ContextManager.compact()` + `@register("context", ...)`
- 新检索策略 → 改写 `recall()` 方法（向量检索 → Mem0）
- 新记忆后端 → 实现 `MemoryProvider.store/recall` + `@register("memory", ...)`
- 语义排序 / 长期记忆提升 → 在 `mem0_provider.py` 内继续增强，不改核心接口

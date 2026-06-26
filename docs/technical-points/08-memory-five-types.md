# 08 · 记忆五分法

> 对齐 CrewAI / Semantic Kernel 等主流框架的统一记忆分类体系。

## 为什么五分法

原三层设计（短期/会话/持久）过于粗糙，无法与主流框架对比。采用业内通用的五分法后，AgentConch 的记忆实验结果才能与 CrewAI、Semantic Kernel 横向对比。

## 五种记忆类型

| 类型 | 含义 | 存储 | 用途 | MVP |
|---|---|---|---|---|
| **短期 Short-term** | 当前 step 工作记忆 | 内存 | 单步推理上下文 | ✅ |
| **情景 Episodic** | 跨 step、Context Reset 后恢复 | 文件（NOTES.md / progress.json） | 会话级进度与中间产物 | ✅ |
| **语义 Semantic** | 跨会话的事实知识积累 | 向量库 | 长期知识检索 | 阶段三 |
| **长期 Long-term** | 持久化的历史经验 | KV / 向量库 | 跨会话技能沉淀 | 阶段三 |
| **程序性 Procedural** | 已学会的工具用法与操作模式 | 规则库 / 脚本缓存 | 避免重复学习相同操作 | 阶段三 |

## 与原三层设计的映射（向后兼容）

```
原"短期"  → Short-term（工作记忆）
原"会话"  → Episodic（情景记忆，跨 step 恢复）
原"持久"  → Semantic + Long-term（语义知识 + 长期积累）
新增      → Procedural（程序性记忆，如已学会的工具用法）
```

## 结构化笔记（Anthropic 实践）

Agent 定期将笔记写入上下文窗口之外的持久化记忆，后续重新拉入：

```python
class NotesFile(MemoryProvider):
    def store(self, key, value, mem_type="episodic"):
        if mem_type == "episodic":
            self.notes[key] = {
                "value": value,
                "step": current_step,
                "timestamp": now(),
            }
            self._flush()  # 写入 NOTES.md
```

参考 Anthropic Claude 玩 Pokémon 的案例：Agent 在数千步过程中维护精确记录——"过去 1234 步一直在 Route 1 训练，Pikachu 已获得 8 个等级"。Context Reset 后，Agent 读取自己的笔记继续。

## 记忆工具

基于文件的记忆系统，使 Agent 能够：
- 在上下文窗口之外存储和查阅信息
- 随时间积累知识库
- 跨会话维护项目状态
- 引用先前工作而无需将所有内容保留在上下文中

## 接口

```python
class MemoryProvider(ExtensionPoint, Protocol):
    def store(self, key: str, value: Any, mem_type: str = "short") -> None: ...
    def recall(self, query: str, mem_type: str = "short", limit: int = 5) -> list[Any]: ...
```

`mem_type` 取值：`short` / `episodic` / `semantic` / `long` / `procedural`

## 框架对比

| 框架 | 短期 | 情景 | 语义 | 长期 | 程序性 |
|---|---|---|---|---|---|
| **AgentConch** | ✅ | ✅ | ✅ | ✅ | ✅ |
| CrewAI | ✅ | ✅ | ✅ | ✅ | — |
| Semantic Kernel | ✅ | — | ✅ | ✅ | ✅ |

> AgentConch 是唯一全覆盖五种记忆类型的框架——这也是实践 harness engineering 的价值：把每种记忆类型作为独立技术点实验。

## 相关文件

- `conch/core/extension.py` — MemoryProvider 接口
- `conch/domains/memory/notes_file.py` — 默认实现

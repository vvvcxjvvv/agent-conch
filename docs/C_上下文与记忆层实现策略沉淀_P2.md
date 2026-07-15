# C 层 — 上下文与记忆层实现策略沉淀 (P2)

> 层级：C (Context & Memory)  
> 阶段：P2 Stateful Harness  
> 相比 P1 更新：从"基础 System Prompt"升级为完整 C 层（ContextEngine + 压缩 + Caching + Skill + Memory）

---

## 一、设计目标回顾

### 1.1 本层定位

C 层是 Agent-Conch 最核心的层，负责控制模型在有限上下文窗口内看到什么、记住什么、遗忘什么。P2 将 P1 的"直接从 DB 加载消息"升级为可插拔 Context Engine + 渐进式压缩 + Prompt Caching + Skill 按需注入 + 分层记忆。

### 1.2 P2 计划能力

- 可插拔 Context Engine (ContextEngine ABC + LegacyEngine)
- 渐进式上下文压缩 (三步管线)
- Prompt Caching (system_and_3)
- Skill 体系 (多层级加载 + Schema-based selective injection)
- 分层记忆 (Short/Session/Long/Meta + 自动提取)

### 1.3 核心约束

- 铁律：不允许变更过去上下文、不允许切换 toolset、不允许重建 system prompt
- 唯一例外：context compression
- Skill 不当工具，而是上下文资产管理
- 记忆提取带写权限限制 + 去重签名

---

## 二、核心实现方案

### 2.1 整体结构

```
context/
├── engine.py              # ContextEngine ABC + LegacyEngine + SimpleTokenCounter
├── compact/
│   └── pipeline.py        # ContextCompressor + ResultCleanup + ContentFolding + SummaryArchive
├── prompt_caching.py      # PromptCaching (system_and_3)
├── skills/
│   └── registry.py        # SkillLoader + SkillInjector + SkillFrontmatter
└── memory/
    └── manager.py         # MemoryManager + Short/Session/Long/Meta Memory
```

### 2.2 ContextEngine ABC

5 个抽象方法：
- `bootstrap(session_id)` → ContextState：初始化上下文状态
- `assemble(session_id, budget)` → AssembleResult：组装消息列表（含 system + history）
- `maintain(session_id)`：回合后维护（auto-compact 检查）
- `compact(session_id)` → AssembleResult：执行压缩
- `after_turn(session_id, turn_result)`：回合后处理（记忆提取）

LegacyEngine 实现了全部方法，行为与 P1 一致（直接从 DB 加载），作为所有自定义引擎的 fallback。

### 2.3 渐进式压缩三步管线

| 步骤 | 类名 | LLM 调用 | 策略 |
|------|------|---------|------|
| Step 1 | ResultCleanup | 零 | 清理旧工具结果（>200 chars），保留最近 10 条 |
| Step 2 | ContentFolding | 零 | 折叠超长内容（>2000 chars），head 900 + tail 500 |
| Step 3 | SummaryArchive | 1 次 | LLM 结构化摘要（Historical/In-Progress/Pending/Remaining） |

只有仍超预算时才进入下一步。Compact Attachment 提取 recent_files/discovered_tools/async_tasks。

### 2.4 Prompt Caching

system_and_3 策略：4 个 cache_control 断点
1. system prompt 末尾
2-4. 最后 3 条非 system 消息

`_can_carry_marker` 检查：内容 >= 100 chars 才值得占用断点。非 Anthropic 模型为 no-op。

### 2.5 Skill 体系

**加载层级**（优先级从低到高）：
1. Bundled skills (skills/bundled/)
2. User skills (~/.agent-conch/skills/)
3. Project skills (从 cwd 向上遍历到 git root)
4. Plugin skills

**Schema-based selective injection**：
- 根据 `inject_schema.when` 条件判断是否注入
- 根据 `inject_schema.fields` 选择性注入部分章节
- 前置条件检查（env_vars + commands）

### 2.6 分层记忆

| 层级 | 类名 | 存储 | 生命周期 |
|------|------|------|----------|
| 短期 | ShortTermMemory | 进程内存 | 单次会话 |
| 中期 | SessionMemory | 内存 cache | 跨轮次 |
| 长期 | LongTermMemory | SQLite + MEMORY.md | 跨会话 |
| 元记忆 | MetaMemory | SQLite FTS5 | 跨会话 |

自动提取：LLM 模式 + 规则模式（fallback），去重签名防止重复。

---

## 三、设计落地对照

### ✅ 完全对齐设计

- ContextEngine ABC 5 个抽象方法
- LegacyEngine 内置 fallback
- 三步管线成本逐步递增
- Prompt Caching system_and_3 + _can_carry_marker
- Skill 多层级加载 + frontmatter 解析
- Schema-based selective injection
- 四层记忆 + FTS5 元记忆
- 记忆去重签名

### ⚠️ 调整项

| 能力项 | 设计方案 | 实际实现 | 调整原因 |
|--------|---------|---------|---------|
| SummaryArchive LLM | 调用 auxiliary model | 可选 llm_caller（None 时跳过） | 未实现独立 auxiliary model 配置 |
| Token 计数 | tiktoken 精确计数 | SimpleTokenCounter (4 chars ≈ 1 token) | 简化实现，P3 可替换 |
| LongTermMemory 检索 | 向量检索 | LIKE 模糊匹配 | 向量检索需要额外依赖 |
| Skill Curator | 自改进闭环 | 未实现 | P4 交付物 |

---

## 四、关键技术点与踩坑记录

### 4.1 ContextEngine 接入 Agent Loop

**改造点**：`_call_model()` 从直接 `db.get_messages_as_dicts()` 改为 `context_engine.assemble()`。

**兼容性**：`context_engine=None` 时 fallback 到 P1 行为，P1 测试全部通过。

### 4.2 压缩管线的成本控制

**设计**：三步管线只有仍超预算时才进入下一步。ResultCleanup 和 ContentFolding 零 LLM 调用，SummaryArchive 才调用 LLM。

**实现**：每步后检查 `token_counter.estimate()` vs budget。

### 4.3 Skill 章节拆分

**实现**：按 `## 标题` 拆分 SKILL.md 正文为 sections dict。inject_schema.fields 指定章节名，只注入对应内容。

**踩坑**：标题匹配需 case-insensitive + space-to-underscore 转换。

### 4.4 FTS5 降级

**问题**：部分 SQLite 编译不包含 FTS5 扩展。

**解决**：try-except 降级为普通表 + LIKE 查询。

---

## 五、验证与覆盖情况

### 5.1 测试覆盖

| 测试类 | 测试数 | 覆盖场景 |
|--------|--------|---------|
| TestTokenCounter | 3 | 简单/空/tool_calls |
| TestLegacyEngine | 3 | bootstrap/assemble/maintain |
| TestResultCleanup | 3 | 短消息/旧工具结果/短内容不清理 |
| TestContentFolding | 3 | 短内容/长内容/头尾保留 |
| TestContextCompressor | 2 | 附件提取/管线 |
| TestPromptCaching | 5 | no-op/Anthropic/can_carry/disabled/savings |
| TestSkillLoader | 2 | frontmatter 解析/目录加载 |
| TestSkillInjector | 5 | task_type/tags/query/selective/no_match |
| TestMemoryManager | 4 | 长期记忆/去重/短期/规则提取 |
| **总计** | **32** | |

### 5.2 未覆盖场景

- ContextCompressor 完整三步管线集成（含 LLM 摘要）
- Skill 多层级优先级覆盖
- Memory LLM 提取模式
- FTS5 实际全文搜索
- ContextEngine maintain → compact 自动触发

---

## 六、演进与优化方向

### P3 演进
- 接入 SummaryArchive LLM caller（主模型或 auxiliary model）
- maintain() 中实现 auto-compact 自动触发
- SimpleTokenCounter → tiktoken 精确计数
- Context Engine 自定义实现（代码任务/研究任务不同策略）

### P4 演进
- Skill Curator 自改进闭环
- LongTermMemory 向量检索
- 记忆写入审批 (WriteApproval)
- Context Engine 策略可配置（YAML 驱动）

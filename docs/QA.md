## Q1: P1阶段渐进式工具发现机制（Progressive Tool Discovery）的设计思想是什么？为什么这么设计？优缺点在哪里？业内成熟的实现方案是怎样的？

---

### 一、设计思想

Agent-Conch 的渐进式工具发现机制核心思想是**工具懒加载**（Lazy Loading for Tools）：不把所有已注册工具的 JSON Schema 一次性塞入 LLM 的 system prompt / context window，而是分层暴露——核心工具始终可见，非核心工具按需搜索发现。

具体实现分为三层：

**1. 核心工具集（is_core=True）**

12 个高频工具（`bash`、`read_file`、`write_file`、`edit_file`、`grep`、`glob`、`web_search`、`web_fetch`、`skill`、`ask_user`、`task_manage`、`tool_search`）始终暴露给 LLM，不走搜索路径。它们的 schema 直接进入每次 API 请求的 `tools` 字段。

**2. 非核心工具集（is_core=False）**

Plugin 工具、MCP 工具、扩展工具等默认对 LLM 不可见——它们的 schema 不会出现在 API 请求中。LLM 只能通过调用 `tool_search(query="关键词")` 来发现它们。

**3. 自动阈值开关**

不是无脑启用搜索模式，而是先算一笔账：把所有非核心工具的 schema 序列化为 JSON，粗估 token 数（`chars / 4`），如果超过 context window 的 10%（可配置，`tool_search_threshold`），才启用搜索机制；否则全部直接暴露。

```
should_enable_search():
  estimated_tokens = sum(len(json.dumps(tool.to_schema())) for non_core_tools) // 4
  threshold_tokens = context_window * 0.10
  return estimated_tokens > threshold_tokens
```

搜索算法是加权关键词匹配：`name` 子串命中得 3 分，`description` 命中得 2 分，`tags` 命中得 1 分，按总分排序返回 top-N。

---

### 二、为什么这么设计

**问题根源：context window 是稀缺资源。**

一个工具的 JSON Schema 平均 200-500 token。当 Agent 通过 Plugin/MCP 机制接入几十甚至上百个工具时，光工具声明就会吃掉 10K-50K token，直接挤压用户代码、对话历史、文件内容的空间。在 32K 窗口的模型上，这足以导致可用 context 腰斩。

设计决策的逻辑链：

1. **为什么分核心/非核心而不是全部按需搜索？** 核心工具调用频率占 90%+，如果每次都要先 `tool_search("read file")` 再 `read_file`，等于给每次文件操作加一轮 LLM 往返——延迟和 token 成本双倍。高频工具必须零摩擦直达。

2. **为什么用百分比阈值而非固定 token 数？** 128K 模型的 10% 是 12,800 token，32K 模型的 10% 是 3,200 token。百分比自适应不同模型的上下文窗口大小——小窗口更早触发搜索，因为每个 token 更珍贵。固定值（如 2000 token）会在大窗口模型上过早启用搜索（不必要延迟），在小窗口模型上过晚启用（浪费 context）。

3. **为什么搜索算法用关键词匹配而非 embedding？** P1 阶段追求零外部依赖、零额外推理成本。关键词匹配是 O(n) 字符串扫描，无延迟、无需模型调用。Embedding 语义搜索需要额外 embedding 模型和向量索引，引入架构复杂度。P1 先解决"有没有"，P3+ 再解决"搜得准不准"。

4. **为什么 `tool_search` 本身是核心工具？** 如果它不是核心工具，LLM 就看不到它，也就无法触发搜索——这是一个 bootstrap 悖论。`tool_search` 必须始终可见，它是通往非核心工具的唯一入口。

---

### 三、优缺点

**优点**

- **Token 节省显著**：50 个非核心工具 × 平均 300 token = 15K token，启用搜索后每次请求只携带 `tool_search` 自身的 ~150 token，节省 99%。
- **零外部依赖**：关键词匹配 + 字符数估算，不需要 embedding 模型、向量数据库或额外 API 调用。
- **核心工具零延迟**：高频路径不受搜索机制影响，体验无损。
- **自适应阈值**：百分比机制自动适配不同 context window 大小的模型，无需手动调参。
- **与健康检查正交**：ToolRegistry 的瞬态故障抑制（连续失败 60s 内不暴露）和 check_fn TTL 缓存（30s）与搜索机制独立运作，被抑制的工具即使在搜索结果中也不会被暴露。

**缺点**

- **Token 估算粗糙**：`chars / 4` 是英文自然文本的经验值，JSON Schema 中结构性字符（`{`、`}`、`"`、`[`、`]`）密度高，tiktoken 实际编码可能偏差 15-30%。低估会导致阈值误判，高估会导致过早启用搜索。
- **搜索召回率有限**：纯子串匹配无法处理同义词和语义近似。搜 `database` 找不到 description 写 `SQL store` 的工具；搜 `数据库` 找不到 description 全英文的工具。这在工具数量较少时问题不大，但随工具规模增长会恶化。
- **额外 LLM 往返**：LLM 需要先调用 `tool_search`，拿到结果后再调用实际工具——至少多一轮 LLM 推理。如果 LLM 搜索关键词不精确，可能需要多次搜索才能找到目标工具。
- **阈值是硬切换**：超阈值一刀切全部隐藏、未超全部暴露，没有中间态。理想情况下应该按工具优先级/频率渐进隐藏，而非二元切换。
- **缺少搜索缓存**：同一轮对话中多次搜索相似关键词时，每次都全量遍历。如果工具列表上百，遍历开销不可忽略。
- **`should_enable_search()` 无缓存**：每次调用都遍历全部非核心工具 + `json.dumps` + 求和。工具列表不频繁变化时应缓存结果，仅在 `register`/`unregister` 时失效。

---

### 四、业内成熟实现方案

**1. OpenAI Function Calling 的原生限制**

OpenAI 的 function calling API 本身没有工具发现机制——所有 `tools` 参数里的函数 schema 全量发送。实践中开发者自行控制：只注册当前任务需要的工具，通过路由层（router）根据用户意图选择工具子集。这是最简单的"手动渐进发现"，但不自动化。

**2. LangChain / LangGraph 的 Tool Retriever 模式**

LangChain 提供了 `ToolRetriever` 抽象，思路与 Agent-Conch 高度一致：

- 所有工具注册到一个 vector store，每个工具的 name + description 被 embedding。
- Agent 启动时只加载少量核心工具。
- 当 Agent 需要更多工具时，调用一个特殊的 `search_tools` 元工具，retriever 做 embedding 相似度搜索返回 top-K 工具。
- LangGraph 进一步支持"动态工具绑定"：每个 graph node 可以在运行时决定向 LLM 暴露哪些工具。

与 Agent-Conch 的差异：LangChain 用 embedding 语义搜索（解决召回率问题），但引入了向量数据库依赖；Agent-Conch 用关键词匹配（零依赖但召回率受限）。

**3. Anthropic Claude MCP（Model Context Protocol）**

MCP 协议定义了 `tools/list` 方法，客户端可以按需查询 MCP server 暴露的工具列表。MCP server 可以返回工具的 `annotations`（如 `readOnlyHint`、`destructiveHint`），客户端根据这些元数据决定是否暴露给 LLM。MCP 本身不做"搜索"，但它的"按 server 分组 + 按需 list"已经是一种粗粒度的渐进发现。Claude 的实际实现是：MCP 工具的 schema 不会全量进 prompt，而是在 agent 需要时才动态注入。

**4. AutoGPT / SuperAGI 的动态工具加载**

AutoGPT 早期版本的做法是：把所有工具的 name + description 拼成一个列表放进 prompt，让 LLM 自己选一个工具名，然后系统动态加载该工具的完整 schema。这本质上也是一种"描述符先行，schema 后载"的渐进发现，但粒度更粗（全量描述符 vs 全量 schema），且依赖 LLM 的选择准确性。

**5. Agent-Conch 的定位**

综合来看，Agent-Conch 的渐进式工具发现机制在架构上与 LangChain ToolRetriever 模式同源，核心思想一致（懒加载 + 元工具搜索 + 核心集常驻）。区别在于：

| 维度 | Agent-Conch (P1) | LangChain | MCP |
|------|-------------------|-----------|-----|
| 搜索算法 | 关键词加权匹配 | Embedding 语义搜索 | 不搜索，按需 list |
| 外部依赖 | 无 | 向量数据库 | MCP server |
| 阈值机制 | context window 百分比自动开关 | 手动配置 | 无 |
| 核心集隔离 | is_core 硬分层 | 软配置 | 按 server 分组 |
| Token 估算 | chars/4 粗估 | tiktoken 精确 | N/A |

Agent-Conch P1 阶段的实现是一个"够用且零依赖"的基线版本。向 P3+ 演进的自然路径是：将关键词匹配替换为 embedding 语义搜索（解决召回率）、用 tiktoken 替换 chars/4（解决估算精度）、加入搜索结果缓存（解决重复查询）、将硬阈值切换改为按优先级渐进隐藏（解决一刀切问题）。

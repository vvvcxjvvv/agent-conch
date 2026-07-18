# Agent-Conch 技术选型与设计方案

> Agent-Conch 是一个全栈通用 AI Agent Harness 项目，以 ETCLOVG 七层模型为架构骨架，以 H=(E,T,C,S,L,V) 六组件形式化模型为语义约束，目标成熟度 P4（Governable Production Harness）。

---

## 一、设计哲学

### 1.1 核心论点

**Agent = Model + Harness**。Agent-Conch 的全部价值在 Harness 层：通过外部系统设计而非模型权重优化，让 AI 智能体在生产环境中实现稳定可控、可验证、可落地、可治理。

### 1.2 七大工程原则的落地承诺

| 原则     | 落地方案                                                     |
| -------- | ------------------------------------------------------------ |
| 约束解放 | RBAC + 配额熔断 + 敏感路径硬编码 + 沙箱隔离 + 安全审计       |
| 最小工具 | 核心工具 12 个 + Footprint Ladder 六级扩展阶梯 + ToolSearch 渐进发现 |
| 零信任   | Reviewer LLM 评审 + review_on_submit 自审 + VerificationLayer 执行验证 |
| 状态外置 | SQLite 优先，所有运行时状态外置到 DB，不依赖模型记忆         |
| 验证前置 | 每步写入操作后自动 lint/type check/test，质量门禁卡点        |
| 熵增管理 | 渐进式上下文压缩 + Curator Skill 自改进 + Trajectory 压缩    |
| 简单优先 | 核心保持窄腰，能力通过 Skill/Plugin/MCP 扩展；YAML 驱动配置  |

### 1.3 核心差异化

Agent-Conch 的核心差异化集中在可靠性、可验证性和可治理性：

1. **验证层（V 层）**：Agent-Conch 将 VerificationLayer 内置到 Agent 执行流程中
2. **并行工具执行**：Agent-Conch 原生支持 `asyncio.gather` 并行 tool_calls
3. **两级 Skill 注入**：默认目录注入（所有 skill 无门槛生效），LLM 通过 `skill` 工具按需加载正文。`inject_schema` 可选优化精准匹配。
4. **回归用例体系**：Agent-Conch 将失败案例自动沉淀为测试用例
5. **策略引擎**：Agent-Conch 统一管理合规规则、内容安全、敏感信息过滤

---

## 二、技术选型

### 2.1 语言与运行时

| 维度     | 选型                          | 理由                                                         |
| -------- | ----------------------------- | ------------------------------------------------------------ |
| 核心语言 | **Python 3.10+**              | asyncio 原生异步；Pydantic 类型安全；LLM/工具/数据处理生态成熟 |
| 前端     | **TypeScript + React + Vite** | Web Console / Inspector / Chat Workbench 统一前端，P3 阶段引入；桌面端可复用同一套 React 代码接 Electron |
| 包管理   | **uv**                        | 极快依赖解析，Rust 实现                                      |
| 配置格式 | **YAML + TOML**               | YAML 驱动 Agent 行为配置；TOML 用于项目级配置                |

### 2.2 核心依赖

| 依赖                     | 用途                                           |
| ------------------------ | ---------------------------------------------- |
| `litellm`                | 多模型统一调用（OpenAI/Anthropic/Google/本地） |
| `pydantic`               | 工具参数 Schema 校验、配置模型                 |
| `asyncio`                | 异步 Agent 循环 + 并行工具执行                 |
| `sqlite3` (stdlib)       | 状态存储 + FTS5 全文搜索                       |
| `opentelemetry-sdk`      | 结构化 Trace                                   |
| `tiktoken` / `anthropic` | 精确 Token 计数                                |
| `mcp`                    | MCP 协议客户端                                 |
| `httpx`                  | 异步 HTTP 客户端                               |
| `rich`                   | CLI 终端渲染                                   |
| `click`                  | CLI 框架                                       |

### 2.3 存储策略

**SQLite 优先**：

```
~/.agent-conch/
├── state.db                    # 全局状态（sessions, agents, traces, skills, memory, regression_cases）
├── agents/
│   └── <agent_id>/
│       └── agent.db            # Agent 级状态（subagents, tasks, checkpoints）
├── skills/                     # SKILL.md 文件（C 层存储/检索/注入）
├── memory/                     # MEMORY.md + USER.md（长期记忆索引）
└── trajectories/               # Trajectory JSONL（轨迹回放）
```

原则：所有运行时状态（sessions、cache、queues、registries、indexes、cursors、checkpoints）用 SQLite，不用 JSON/JSONL/sidecar 文件。文件系统仅用于 SKILL.md、MEMORY.md 等人类可读知识资产。

SQLite 的作用是承接 Agent 的长期运行状态：会话、轨迹、审批、索引、检查点都可以被查询和审计。这样设计的原因是状态不能依赖模型记忆，也不应该散落在多个临时文件里；默认使用 SQLite 可以在保持部署简单的同时，获得结构化查询和恢复能力。

### 2.4 沙箱策略

| 后端       | 场景                      |
| ---------- | ------------------------- |
| **Local**  | 开发/个人场景，默认信任   |
| **Docker** | 生产/隔离场景，容器级隔离 |
| **SSH**    | 远程执行场景（P2 阶段）   |

FS Bridge 抽象层：文件操作后端无关化，`stat/read/write/rename` 统一接口。

沙箱策略的作用是限制 Agent 的执行边界，并让同一套工具可以运行在本地、容器或远程机器上。这样设计是因为执行环境必须可隔离、可替换、可恢复；FS Bridge 让工具不用关心具体后端差异，后续增加快照、回滚和远程执行时不会影响工具层。

### 2.5 React 前端交互技术选型

Agent-Conch 前端定位为**轻量控制台 + 调试工作台**，不是完整低代码平台。第一阶段只承担三类职责：实时观察 Agent run、查看工具调用与验证结果、处理高风险操作审批。

前端的作用是补足 CLI 不擅长的观察和治理能力：运行回放、工具调用展开、审批处理、指标查看。这样设计是为了避免早期陷入复杂低代码平台建设，先让 Web Console 服务于调试和治理。

**推荐技术栈**：

| 类别        | 选型                                                  |
| ----------- | ----------------------------------------------------- |
| 构建        | Vite + React + TypeScript                             |
| 路由        | React Router                                          |
| 数据请求    | TanStack Query                                        |
| 本地状态    | Zustand 或 Nanostores                                 |
| 实时事件    | SSE 优先，WebSocket 后置                              |
| 样式        | Tailwind CSS + CSS Variables                          |
| 基础组件    | Radix UI / Base UI                                    |
| 图标        | lucide-react 或 Tabler Icons                          |
| 画布        | ReactFlow（仅用于执行流程图 / Verification Pipeline） |
| 代码与 Diff | Monaco Editor + Shiki                                 |
| 图表        | ECharts                                               |
| 测试        | Vitest + React Testing Library + Playwright           |

**核心交互范围**：

1. Chat Workbench：会话列表、对话流、工具调用块、运行状态。
2. Run Inspector：Trajectory / trace / exit_status / verification report 查看。
3. Approval Panel：危险命令、文件写入、Skill/Memory 写入的审批。
4. Tool & Skill Console：工具健康状态、MCP 连接、Skill 元数据与 Curator 状态。
5. Dashboard：成功率、失败原因、成本、Token、工具耗时等基础指标。

**阶段策略**：P3 做 Web Console，不引入 Electron；P4 再把同一套 React 应用包装为桌面端，补本地文件、系统通知和终端桥接能力。

---

## 三、架构设计

### 3.1 整体架构拓扑

```
用户入口 (CLI / Web API / Webhook / IM Gateway)
    │
    ▼
AgentConch (cli.py)                              ← 交互编排器
    │
    ├── ConchEngine (engine/conch_engine.py)      ← L层核心：Agent 引擎
    │    ├── AgentLoop (engine/agent_loop.py)       ← Observe-Think-Act 循环
    │    ├── RuntimeRegistry (engine/runtime/)      ← L层：Agent Runtime 可插拔
    │    │    └── BuiltinConchRuntime               ← 内置 Agent Runtime
    │    ├── LayerSystem (engine/layers/)           ← L层：Layer 插件体系
    │    │    ├── ExecutionLimitsLayer               ← 步骤/时间限制
    │    │    ├── ObservabilityLayer                  ← OTel Trace
    │    │    ├── LLMQuotaLayer                       ← 配额熔断
    │    │    ├── VerificationLayer                   ← V层：执行验证（自研核心差异）
    │    │    ├── SuspendLayer                        ← 暂停/恢复
    │    │    ├── PauseStatePersistLayer              ← 暂停状态持久化
    │    │    └── PolicyLayer                         ← G层：策略引擎
    │    └── ErrorClassifier (engine/error_classifier.py) ← L层：20+ 种错误分类
    │
    ├── ToolSystem (tools/)
    │    ├── ToolRegistry (tools/registry.py)       ← T层：工具注册 + check_fn TTL
    │    ├── ToolSearch (tools/tool_search.py)       ← T层：渐进式工具发现
    │    ├── ToolPolicy (tools/tool_policy.py)       ← T层：Allow/Deny 策略
    │    ├── FootprintLadder (tools/footprint.py)    ← T层：六级扩展阶梯
    │    ├── MCPClient (tools/mcp_client.py)         ← T层：MCP 协议
    │    └── 12 核心工具 (tools/core/)               ← bash/read/write/edit/glob/grep/search/web_fetch/web_search/skill/ask_user/task_manage
    │
    ├── ContextSystem (context/)
    │    ├── ContextEngine (context/engine.py)       ← C层：可插拔上下文引擎
    │    │    └── LegacyEngine                        ← 内置 fallback
│    ├── ContextCompressor (context/compact/)    ← C层：渐进式上下文压缩
│    │    ├── ResultCleanup                         ← 清理旧工具结果
│    │    ├── ContentFolding                        ← 折叠超长内容
│    │    └── SummaryArchive                        ← LLM 摘要归档
    │    ├── PromptCaching (context/prompt_caching.py) ← C层：system_and_3 策略
    │    ├── SkillRegistry (context/skills/)          ← C层：Skill 存储/检索/注入
    │    │    ├── SkillLoader                           ← 多层级加载
    │    │    ├── SkillInjector                         ← Schema-based selective injection
    │    │    └── Curator                               ← Skill 自改进闭环
    │    └── MemoryManager (context/memory/)          ← C层：分层记忆
    │         ├── ShortTermMemory                       ← 工作记忆
    │         ├── SessionMemory                         ← 会话记忆 (SQLite)
    │         ├── LongTermMemory                        ← 持久记忆 (MEMORY.md + 向量检索)
    │         └── MetaMemory                            ← 元记忆 (FTS5 跨会话搜索)
    │
    ├── StateStore (state/)
    │    ├── SessionDB (state/session_db.py)          ← S层：SQLite 会话存储
    │    ├── CheckpointManager (state/checkpoint.py)  ← S层：快照/恢复
    │    └── TrajectoryStore (state/trajectory.py)    ← S层：轨迹持久化 + 回放
    │
    ├── Sandbox (sandbox/)
    │    ├── SandboxRegistry (sandbox/registry.py)    ← E层：沙箱后端注册
    │    ├── LocalBackend (sandbox/local.py)           ← E层：本地执行
    │    ├── DockerBackend (sandbox/docker.py)         ← E层：Docker 隔离
    │    ├── FsBridge (sandbox/fs_bridge.py)           ← E层：文件系统桥接
    │    └── PathValidator (sandbox/path_validator.py) ← E层：路径安全
    │
    ├── Security (security/)
    │    ├── PermissionChecker (security/permissions.py) ← G层：权限决策
    │    ├── SensitivePaths (security/sensitive_paths.py) ← G层：敏感路径硬编码
    │    ├── SecurityAudit (security/audit.py)          ← G层：安全审计
    │    ├── CredentialPool (security/credentials.py)   ← G层：多 key 轮换
    │    ├── WriteApproval (security/write_approval.py) ← G层：写入审批
    │    └── PolicyEngine (security/policy_engine.py)   ← G层：策略引擎（自研）
    │
    ├── Verification (verification/)
    │    ├── VerificationLayer (verification/layer.py)  ← V层：执行流程内置验证（自研核心）
    │    ├── Reviewer (verification/reviewer.py)        ← V层：LLM 评审选择
    │    ├── SelfReview (verification/self_review.py)   ← V层：review_on_submit 自审
    │    ├── VerificationReport (verification/report.py) ← V层：验证报告
    │    └── RegressionSuite (verification/regression.py) ← V层：回归用例（自研）
    │
    ├── Observability (observability/)
    │    ├── OTelTracer (observability/otel.py)        ← O层：OpenTelemetry
    │    ├── TraceStore (observability/trace_store.py)  ← O层：Trace 持久化
    │    ├── ExitStatusClassifier (observability/exit_status.py) ← O层：exit_status 归因
    │    ├── InsightsEngine (observability/insights.py) ← O层：会话分析
    │    └── ReplayPlayer (observability/replay.py)     ← O层：轨迹回放
    │
    ├── MultiAgent (multiagent/)
    │    ├── Coordinator (multiagent/coordinator.py)   ← L层：主从编排
    │    ├── SubagentManager (multiagent/subagent.py)  ← L层：子 Agent + 孤儿恢复
    │    └── Delegation (multiagent/delegation.py)     ← L层：任务委托
    │
    └── Hooks (hooks/)
         └── HookExecutor (hooks/executor.py)          ← L层：生命周期钩子
```

### 3.2 ETCLOVG 七层设计详解

#### E 层 — 执行环境与沙箱

| 能力      | 实现方案                                                |
| --------- | ------------------------------------------------------- |
| 沙箱后端  | Local + Docker + SSH（P2），通过 SandboxRegistry 可插拔 |
| FS Bridge | 统一文件操作接口（stat/read/write/rename），后端无关    |
| 隔离级别  | Docker 容器级（默认）→ 网络白名单（P3）→ gVisor（P4）   |
| 资源配额  | CPU/内存/Token/时间/API 频次硬限制                      |
| 快照/回滚 | Docker commit 快照 + restore                            |
| 路径安全  | PathValidator 防路径遍历 + 敏感路径硬编码不可覆盖       |

**关键设计**：

```python
# sandbox/fs_bridge.py
class FsBridge(ABC):
    @abstractmethod
    async def stat(self, path: str) -> FileStat: ...
    @abstractmethod
    async def read(self, path: str, offset: int = 0, limit: int = -1) -> bytes: ...
    @abstractmethod
    async def write(self, path: str, data: bytes) -> None: ...
    @abstractmethod
    async def rename(self, old: str, new: str) -> None: ...

# sandbox/registry.py
class SandboxRegistry:
    def get_backend(self, session_id: str) -> SandboxBackend:
        # sandbox.mode: "non-main" (非主会话用沙箱) / "always" / "never"
        ...
```

#### T 层 — 工具接口层

工具层的作用是把外部能力变成模型可理解、可校验、可管控的接口。Agent-Conch 采用“少量核心工具 + 渐进发现 + 策略管控”的设计：核心工具保持稳定和高频，低频能力通过 ToolSearch 或 MCP 扩展。这样可以降低模型选择工具的复杂度，同时保留扩展能力。

| 能力       | 实现方案                                                     |
| ---------- | ------------------------------------------------------------ |
| 核心工具   | 12 个：bash、read_file、write_file、edit_file、glob、grep、web_search、web_fetch、skill、ask_user、task_manage、tool_search |
| 工具协议   | Function Calling（原生）+ MCP（生态扩展）                    |
| 工具发现   | ToolSearch 渐进发现（自动阈值：非核心工具 schema 超过 context window 10% 时启用） |
| 可用性管理 | check_fn 前置检查 + 30s TTL 缓存 + 60s 瞬态故障抑制          |
| 策略控制   | ToolPolicy（Allow/Deny + Sender Policy + Sandbox Policy）三层 |
| 扩展阶梯   | Footprint Ladder：扩展现有代码 → CLI + Skill → service-gated tool → plugin → MCP → 新核心工具（最后手段） |
| 并行执行   | 单次响应多 tool_use 时 `asyncio.gather(return_exceptions=True)` 并行（自研差异化） |
| 参数校验   | Pydantic input_model + JSON Schema 自动生成                  |
| 输出管理   | 工具输出截断 + offload 到临时文件（仅保留预览）              |

`ToolPolicy` 用于把读、写、执行、网络、部署等操作分级管控；`check_fn` 用于在工具暴露给模型前确认依赖是否可用，避免模型调用不可用工具。并行工具执行只用于互不依赖的操作，例如读取文件、搜索、查询状态；写操作和危险操作仍需串行或进入审批流程。

**核心工具清单**（遵循最小工具原则）：

```python
# tools/core/ — 12 个核心工具
class BashTool(BaseTool):          # Shell 命令执行
class ReadFileTool(BaseTool):      # 文件读取
class WriteFileTool(BaseTool):     # 文件写入
class EditFileTool(BaseTool):      # 文件编辑（str_replace）
class GlobTool(BaseTool):          # 文件模式匹配
class GrepTool(BaseTool):          # 内容搜索
class WebSearchTool(BaseTool):     # Web 搜索
class WebFetchTool(BaseTool):      # Web 页面抓取
class SkillTool(BaseTool):         # Skill 调用
class AskUserTool(BaseTool):       # 用户提问
class TaskManageTool(BaseTool):    # 后台任务管理
class ToolSearchTool(BaseTool):    # 工具搜索（延迟发现）
```

**Footprint Ladder**（控制核心工具膨胀）：

```
Level 1: 扩展现有工具代码        # 零成本，首选
Level 2: CLI 命令 + SKILL.md    # 知识注入，不增加工具数
Level 3: service-gated tool      # 条件加载工具（check_fn 控制）
Level 4: plugin tool             # 插件工具（隔离运行）
Level 5: MCP server tool         # 外部 MCP 工具
Level 6: 新核心工具              # 最后手段，需架构评审
```

#### C 层 — 上下文与记忆层

这是 Agent-Conch 最核心的层，负责控制模型在有限上下文窗口内看到什么、记住什么、遗忘什么。

##### 可插拔 Context Engine

Context Engine 的作用是统一管理上下文组装、压缩、记忆检索和回合后维护。这样设计是因为不同任务需要不同上下文策略：代码任务更关心文件与 diff，研究任务更关心来源与摘要，运维任务更关心日志和状态。将上下文能力做成可插拔引擎，可以替换策略而不改 Agent 执行循环。

```python
# context/engine.py
class ContextEngine(ABC):
    @abstractmethod
    async def bootstrap(self, session_id: str) -> ContextState: ...
    @abstractmethod
    async def assemble(self, session_id: str, budget: TokenBudget) -> AssembleResult: ...
    @abstractmethod
    async def maintain(self, session_id: str, messages: list[Message]) -> None: ...
    @abstractmethod
    async def compact(self, session_id: str, strategy: CompactStrategy) -> CompactResult: ...
    @abstractmethod
    async def after_turn(self, session_id: str, turn_result: TurnResult) -> None: ...

class LegacyEngine(ContextEngine):
    """内置 fallback 引擎，始终可用"""
    ...
```

##### 渐进式上下文压缩

渐进式上下文压缩的作用是在不丢关键状态的前提下控制 token 成本。它先使用确定性、低成本方式清理冗余；只有仍超预算时才调用 LLM 做摘要归档。这样设计可以避免每次压缩都依赖模型摘要，降低成本和不确定性。

```python
# context/compact/pipeline.py
class ContextCompressor:
    async def compact(self, messages: list[Message], budget: int) -> list[Message]:
        estimated = self.token_counter.estimate(messages)
        if estimated <= budget:
            return messages

        # Step 1: 清理旧工具结果（零 LLM 调用）
        messages = self.result_cleanup.compact(messages)
        if self.token_counter.estimate(messages) <= budget:
            return messages

        # Step 2: 折叠超长内容（零 LLM 调用）
        messages = self.content_folding.compact(messages)
        if self.token_counter.estimate(messages) <= budget:
            return messages

        # Step 3: 摘要归档（LLM 结构化摘要）
        messages = await self.summary_archive.compact(messages)
        return messages
```

**清理旧结果**（最廉价）：清除早期工具调用的大段输出，替换为 `[Old tool result content cleared]`，保留最近 5 条消息。

**折叠长内容**（中等成本）：对超长文本块做确定性截断（head 900 chars + tail 500 chars，中间标记 `collapsed N chars`），不调用 LLM。

**摘要归档**（最昂贵）：调用 auxiliary model 做结构化摘要，包含 Historical Task / In-Progress / Pending Asks / Remaining Work 四部分。添加 `REFERENCE ONLY` 前缀和 summary end marker，防止模型误读。

**Compact Attachment**：压缩时自动提取 recent files、discovered tools、async tasks 等结构化附件，避免关键状态丢失。

##### Prompt Caching

Prompt Caching 的作用是复用稳定上下文，减少长任务中重复发送 system prompt、工具说明和近期上下文的成本。缓存边界必须稳定，否则缓存命中率会下降，甚至导致相同任务每轮都重新付费。

```python
# context/prompt_caching.py
class PromptCaching:
    def apply(self, messages: list[Message]) -> list[Message]:
        """system_and_3 策略：4 个 cache_control 断点"""
        # 1. system prompt 末尾
        # 2-4. 最后 3 条非 system 消息
        # 统一 TTL（5m 或 1h）
        # _can_carry_marker 检查防止浪费断点
        ...
```

铁律：不允许变更过去上下文、不允许切换 toolset、不允许重建 system prompt。唯一例外是 context compression。

##### Skill 体系

Skill 的作用是按需注入领域知识和操作规程。Agent-Conch 不把 Skill 当成工具，而是把它作为上下文资产管理。

**两级注入机制**（P2 实现）：

1. **目录注入（默认）**：system prompt 中只注入 skill 的目录信息（name + description + tags + category），约 100-300 token/skill。LLM 根据目录自行判断是否需要加载完整内容。

2. **按需加载**：LLM 通过 `skill` 工具（`action="load", skill_name="xxx"`）按需获取完整 SKILL.md 正文。这避免了全文注入导致的 token 浪费。

3. **选择性注入（可选优化）**：当 task_type / tags / query 明确且 skill 配置了 `inject_schema` 时，可通过 `compact=False` 模式直接全文注入匹配的 skill 到 system prompt，跳过工具调用步骤。

**存储格式**：SKILL.md + YAML frontmatter（agentskills.io 兼容标准）

```yaml
---
name: code-review                    # 必填
description: Code review skill       # 必填
version: 1.0.0
platforms: [macos, linux]
prerequisites:
  env_vars: [GITHUB_TOKEN]
  commands: [git, rg]
inject_schema:                       # 可选：精准注入优化
  when: "task_type == 'code_review'"
  fields: [guidelines, checklist]    # 只注入指定章节
metadata:
  tags: [review, quality]            # 标签（用于 LLM 匹配和目录展示）
  category: engineering              # 领域分类
---
```

**加载层级**（优先级从低到高）：
1. Bundled skills（`skills/bundled/`）
2. User skills（`~/.agent-conch/skills/`）
3. Project skills（从 cwd 向上遍历到 git root）
4. Plugin skills

**与 Anthropic / OpenAI 的对齐**：默认行为与 Claude Code 一致——放进去就用，不做任何匹配过滤。`inject_schema` 是可选的 token 优化机制，不是加载前提。

**Curator 自改进闭环**：
- 空闲时触发（非 cron），距上次运行超过 `interval_hours`（默认 7 天）
- auxiliary model 评审 agent 创建的 skills → pin / archive / consolidate / patch
- 严格不变量：只触碰 agent 创建的 skills；永不删除只归档；pinned 豁免
- 运行前做 tar.gz 快照备份

##### 分层记忆

| 层级   | 实现                                          | 存储              | 生命周期 |
| ------ | --------------------------------------------- | ----------------- | -------- |
| 短期   | 工作记忆（当前对话 + tool carryover）         | 进程内存          | 单次会话 |
| 中期   | 会话记忆（ContextEngine + ContextCompressor） | SQLite + 内存     | 跨轮次   |
| 长期   | 持久记忆（MEMORY.md + 向量检索）              | 文件系统 + SQLite | 跨会话   |
| 元记忆 | 跨会话搜索（FTS5 + LLM 摘要）                 | SQLite FTS5       | 跨会话   |

**记忆自动提取**：每轮结束后异步触发 LLM 提取可持久化知识，带写权限限制 + 去重签名。

#### L 层 — 生命周期与编排层

##### Agent Loop

```python
# engine/agent_loop.py
class AgentLoop:
    async def run(self, session_id: str, user_input: str) -> AgentResult:
        while self.turn_count < self.max_turns:
            # 1. auto-compact check（C 层渐进式上下文压缩）
            await self.context_engine.maintain(session_id, self.messages)

            # 2. Layer: on_graph_start（ExecutionLimits / LLMQuota / Policy）
            await self.layers.on_graph_start(context)

            # 3. assemble context（C 层可插拔引擎）
            assembled = await self.context_engine.assemble(session_id, self.budget)

            # 4. apply prompt caching
            messages = self.prompt_caching.apply(assembled.messages)

            # 5. stream model response
            response = await self.model.query(messages, tools=self.tool_defs)

            # 6. if no tool_use → break
            if not response.tool_calls:
                break

            # 7. execute tool calls (parallel)
            results = await asyncio.gather(*[
                self._execute_tool_call(tc) for tc in response.tool_calls
            ], return_exceptions=True)

            # 8. Layer: on_node_run_end（VerificationLayer 验证）
            await self.layers.on_node_run_end(context, results)

            # 9. append tool results
            self.messages.extend(results)

            # 10. record trajectory
            await self.trajectory_store.save(session_id, turn)

            self.turn_count += 1

        return AgentResult(status="completed", trajectory=...)
```

##### Agent Runtime 可插拔

Agent Runtime 的作用是允许不同类型的 Agent 执行器接入统一控制面。这样设计是因为通用 Harness 不应绑定单一 Agent 循环：编码、研究、工作流、远程执行可以使用不同 runtime，但共享工具、状态、验证和治理能力。

```python
# engine/runtime/types.py
class AgentRuntime(ABC):
    @abstractmethod
    async def run(self, session_id: str, input: str) -> AgentResult: ...
    @abstractmethod
    def supported_tools(self) -> list[str]: ...
    @abstractmethod
    def supported_layers(self) -> list[type[Layer]]: ...

class RuntimeRegistry:
    def register(self, name: str, runtime: type[AgentRuntime]): ...
    def select(self, config: RuntimeConfig) -> AgentRuntime: ...
```

##### Layer 插件体系

Layer 的作用是承载配额、可观测、暂停恢复、验证、策略等横切能力。这样设计可以避免把所有逻辑写进 Agent Loop，使执行循环保持清晰；不同部署场景也可以按需启用不同 Layer。

```python
# engine/layers/base.py
class Layer(ABC):
    async def on_graph_start(self, ctx: GraphContext) -> None: ...
    async def on_node_run_start(self, ctx: NodeContext) -> None: ...
    async def on_node_run_end(self, ctx: NodeContext, result: Any) -> None: ...
    async def on_event(self, event: Event) -> None: ...
    async def on_graph_end(self, ctx: GraphContext) -> None: ...
```

| Layer                  | 职责                         | ETCLOVG 映射 |
| ---------------------- | ---------------------------- | ------------ |
| ExecutionLimitsLayer   | max_steps / max_time 限制    | L            |
| ObservabilityLayer     | OTel span 创建               | O            |
| LLMQuotaLayer          | 配额检查 + 扣减 + 超限 abort | G            |
| VerificationLayer      | 工具调用后自动验证           | V            |
| SuspendLayer           | 捕获 Pause 事件              | L            |
| PauseStatePersistLayer | 暂停状态序列化到 SQLite      | L            |
| PolicyLayer            | 策略引擎规则执行             | G            |

##### ErrorClassifier

```python
# engine/error_classifier.py
class FailoverReason(Enum):
    API_TIMEOUT = "api_timeout"
    API_RATE_LIMIT = "api_rate_limit"
    API_CONTENT_POLICY = "api_content_policy"    # 不重试
    API_AUTH_ERROR = "api_auth_error"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_BLOCKED = "tool_blocked"
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
    PERMISSION_DENIED = "permission_denied"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    FORMAT_ERROR = "format_error"
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"
    SSL_CERT_VERIFICATION = "ssl_cert_verification"  # 不重试
    # ... 20+ 种

class ErrorClassifier:
    def classify(self, error: Exception) -> ClassifiedError:
        """返回错误类型 + 恢复策略（retry/requery/compact/abort）"""
        ...
```

##### 多 Agent 编排

| 模式                | 实现                                                         |
| ------------------- | ------------------------------------------------------------ |
| Coordinator/Worker  | 主 Agent 仅持有 spawn/send_message/stop 工具，Worker 上下文隔离 |
| Subagent + 孤儿恢复 | SQLite 持久化注册表，父 Agent 崩溃后恢复子 Agent             |
| Delegation          | 子 Agent 委托执行，DELEGATE_BLOCKED_TOOLS 禁止列表           |

##### Pause/Resume

完整状态序列化到 SQLite：`GraphRuntimeState` + `generate_entity` → 序列化 → 恢复时反序列化重建。支持长时间暂停后恢复（等待人工审批）。

#### O 层 — 可观测性层

可观测性层的作用是回答三个问题：Agent 做了什么、为什么失败、成本花在哪里。Trajectory 保存可回放证据，Trace 保存结构化运行路径，Insights 汇总长期指标。这样设计可以让调试、评审、回归用例生成都建立在事实记录上。

| 能力             | 实现方案                                                     |
| ---------------- | ------------------------------------------------------------ |
| 全链路 Trace     | OTel 原生 span，每轮思考/工具调用入参返回/状态变化/耗时/Token |
| Trace 持久化     | OTel → SQLite（结构化存储，支持查询）                        |
| exit_status 归因 | 每次退出明确分类（submitted/cost_limit/context_window/timeout/format/error/forfeit/environment/api） |
| 轨迹回放         | Trajectory JSONL 每步保存 + `conch replay <trajectory_file>` 回放 |
| 跨会话搜索       | SQLite FTS5 全文搜索历史对话                                 |
| Insights 报告    | 会话成功率、平均轮次、失败原因分布、成本消耗                 |
| 可视化           | Web Inspector（P3 阶段）                                     |

#### V 层 — 验证与评估层（自研核心差异化）

这是 Agent-Conch 最大的差异化层，用于把“模型声称完成”转化为“有证据地完成”。

##### VerificationLayer（执行流程内置验证）

VerificationLayer 的作用是在工具调用后自动执行语法检查、类型检查、测试和格式校验，并把失败结果反馈给 Agent 修复。这样设计是因为不能依赖模型自称完成；验证层把“完成”变成有证据的完成，是 Agent 可自主运行的关键。

```python
# verification/layer.py
class VerificationLayer(Layer):
    async def on_node_run_end(self, ctx: NodeContext, result: Any) -> None:
        """工具调用后自动验证"""
        for tool_call in result.tool_calls:
            if tool_call.name in WRITE_TOOLS:  # write_file, edit_file, bash
                verification = await self.verify(tool_call, ctx.session_id)
                if not verification.passed:
                    # 注入错误信息让模型修复
                    ctx.inject_message(verification.error_message)
                    # 质量门禁：失败则阻止进入下一步
                    ctx.block_progress(reason=verification.reason)
```

验证类型：

| 类型      | 触发条件                | 执行方式                                             |
| --------- | ----------------------- | ---------------------------------------------------- |
| 语法检查  | write_file/edit_file 后 | `python -m py_compile` / `tsc --noEmit` / `gofmt -l` |
| Lint 检查 | 代码文件修改后          | `ruff check` / `eslint` / `golangci-lint`            |
| 类型检查  | 代码文件修改后          | `mypy` / `tsc --noEmit`                              |
| 单元测试  | 测试文件修改后          | `pytest` / `go test`                                 |
| 格式校验  | 任何工具输出            | JSON Schema / 正则 / 字段完整性                      |
| 语义校验  | 关键节点                | LLM-as-Judge 评估输出合理性                          |

##### Reviewer 评审选择

Reviewer 的作用是在关键结果提交前进行独立评审，尤其适合多次尝试、复杂修改或高风险输出。这样设计可以发现遗漏、错误假设和不完整修复，降低单次模型输出不稳定带来的风险。

```python
# verification/reviewer.py
class Reviewer:
    async def review_and_select(self, attempts: list[AgentResult]) -> AgentResult:
        """多次尝试 + LLM 评审选择最佳"""
        # Phase 1: Preselector 筛选（格式校验 + 基本完整性）
        candidates = self.preselector.filter(attempts)
        # Phase 2: Chooser 选择（LLM 评审）
        best = await self.chooser.select(candidates)
        return best
```

##### review_on_submit 自审

提交前自动触发自审：Agent 用独立 LLM 调用评审自己的输出，检查是否满足 success criteria。

##### 验证报告分离

明确区分「Agent 自述（不可信）」与「服务级验证（可信）」：

```python
@dataclass
class VerificationReport:
    agent_claim: str           # Agent 自述完成（不可信）
    service_verification: dict # 服务级验证结果（可信）
    exit_status: ExitStatus    # 精确退出状态
    evidence: list[str]        # 验证证据（测试输出、lint 结果等）
```

##### 回归用例体系（自研）

回归用例体系的作用是把失败案例沉淀为可重复执行的测试用例。这样设计可以让系统从失败中积累约束，避免同类问题反复出现。

```python
# verification/regression.py
class RegressionSuite:
    async def capture_failure(self, session_id: str, failure: FailureCase):
        """失败案例自动沉淀为测试用例"""
        case = RegressionCase(
            input=failure.input,
            expected=failure.expected,
            actual=failure.actual,
            error_type=failure.error_type,
            captured_at=datetime.now(),
        )
        await self.db.save(case)

    async def run_regression(self) -> RegressionResult:
        """运行回归测试集，防止重复踩坑"""
        cases = await self.db.load_all()
        results = await asyncio.gather(*[self._run_case(c) for c in cases])
        return RegressionResult(passed=sum(r.passed for r in results), total=len(results))
```

#### G 层 — 治理与安全层

治理与安全层的作用是把权限、审批、成本、合规和审计从提示词约束变成系统约束。这样设计是因为生产环境中不同用户、环境、操作风险不同，必须通过显式策略来决定哪些操作可自动执行，哪些必须审批，哪些必须禁止。

| 能力            | 实现方案                                                     |
| --------------- | ------------------------------------------------------------ |
| 权限模型        | RBAC 40+ 权限点 + 操作 5 级分级（read/write/exec/network/deploy） |
| 敏感路径        | 硬编码不可覆盖（`/etc`, `~/.ssh`, `/.env` 等）+ 用户规则叠加 |
| 写入审批        | WriteApproval：memory/skill 写入可配置需用户审批             |
| 成本熔断        | LLMQuotaLayer：单任务 Token/时间/资源预算上限，超支自动终止  |
| 安全审计        | SecurityAudit：channel/config/exec/sandbox/gateway/plugins/filesystem 多维度 |
| Credential Pool | 多 API key 轮换 + Secret Sources（Bitwarden/1Password 集成） |
| 策略引擎        | PolicyEngine：统一管理合规规则、内容安全、敏感信息过滤       |
| 审计追踪        | 完整操作日志 + 可追溯决策链路（SQLite 持久化）               |

**策略引擎**（自研差异化）：

```python
# security/policy_engine.py
class PolicyEngine:
    def __init__(self, rules: list[PolicyRule]):
        self.rules = rules

    def evaluate(self, action: Action, context: ActionContext) -> PolicyDecision:
        """评估操作是否允许"""
        for rule in self.rules:
            decision = rule.evaluate(action, context)
            if decision == PolicyDecision.DENY:
                return decision
            if decision == PolicyDecision.REQUIRE_APPROVAL:
                # 触发 HITL 审批
                return decision
        return PolicyDecision.ALLOW
```

策略规则示例（YAML 配置）：

```yaml
policies:
  - name: no_prod_deploy
    rule: "action.type == 'deploy' and env == 'prod'"
    decision: REQUIRE_APPROVAL
  - name: no_sensitive_file_write
    rule: "action.type == 'write' and path matches_sensitive_pattern"
    decision: DENY
  - name: max_daily_cost
    rule: "session.daily_cost > 100"
    decision: DENY
```

---

## 四、H=(E,T,C,S,L,V) 六组件映射

| 符号  | 组件                 | Agent-Conch 模块                                             | 完整度               |
| ----- | -------------------- | ------------------------------------------------------------ | -------------------- |
| **E** | Execution Loop       | `engine/agent_loop.py` + `sandbox/`                          | 完整                 |
| **T** | Tool Registry        | `tools/registry.py` + `tools/tool_search.py` + `tools/tool_policy.py` | 完整                 |
| **C** | Context Manager      | `context/engine.py` + `context/compact/` + `context/skills/` + `context/memory/` | 完整                 |
| **S** | State Store          | `state/session_db.py` + `state/checkpoint.py` + `state/trajectory.py` | 完整                 |
| **L** | Lifecycle Hooks      | `engine/layers/` + `hooks/` + `multiagent/`                  | 完整                 |
| **V** | Evaluation Interface | `verification/` + `observability/exit_status.py`             | **完整（自研强化）** |

---

## 五、成熟度目标

| 阶段 | 级别                          | 核心特征                                                     | 交付周期 |
| ---- | ----------------------------- | ------------------------------------------------------------ | -------- |
| P1   | Workflow Agent                | 固定流程 + 工具调用 + 基础日志 + 简单检查                    | 2-3 周   |
| P2   | Stateful Harness              | 任务状态 + 上下文组装 + 记忆分层 + retry/timeout/checkpoint  | 3-4 周   |
| P3   | Auditable Harness             | 完整 trace + 失败归因 + 确定性验证 + 验证报告                | 3-4 周   |
| P4   | Governable Production Harness | 权限审批 + 人工接管 + 可观测可评估可回放 + 回归集 + 策略治理 | 4-6 周   |

**学术梯度目标**：H3（有证据的完成）— 确定性检查 + bug 复现 + 失败归因 + 验证协议 + 验证报告。

---

## 六、分阶段落地路线

### P1 阶段：Workflow Agent（2-3 周）

**交付物**：

| 模块                   | 实现内容                                                     |
| ---------------------- | ------------------------------------------------------------ |
| Agent Loop             | Observe-Think-Act 循环 + forward_with_handling 错误降级      |
| Agent Runtime 可插拔   | RuntimeRegistry + BuiltinConchRuntime                        |
| 12 核心工具            | bash/read/write/edit/glob/grep/web_search/web_fetch/skill/ask_user/task_manage/tool_search |
| ToolPolicy             | Allow/Deny + Sandbox Policy                                  |
| ToolSearch             | 渐进发现 + 自动阈值                                          |
| check_fn               | 前置检查 + TTL 缓存 + 瞬态故障抑制                           |
| SQLite 状态存储        | SessionDB 基础表                                             |
| Local 沙箱 + FS Bridge | 本地执行 + 文件操作抽象                                      |
| 基础 System Prompt     | base + env + AGENTS.md 发现                                  |
| Layer 基础框架         | Layer 接口 + ExecutionLimitsLayer                            |

**验证标准**：能完成「读取文件 → 修改 → 运行测试 → 回答」循环；SQLite 持久化；沙箱隔离生效

### P2 阶段：Stateful Harness（3-4 周）

**交付物**：

| 模块                  | 实现内容                                                     |
| --------------------- | ------------------------------------------------------------ |
| 可插拔 Context Engine | ContextEngine 接口 + LegacyEngine                            |
| 渐进式上下文压缩      | 清理旧结果 → 折叠长内容 → 摘要归档                           |
| Prompt Caching        | system_and_3 策略 + 确定性排序                               |
| Skill 体系            | 多层级加载 + 目录注入（默认）+ 按需加载（skill 工具）+ compact/full 双模式 |
| ErrorClassifier       | 20+ 种错误分类 + 恢复策略                                    |
| Docker 沙箱           | Docker 后端 + hard_reset + FS Bridge 适配                    |
| Subagent + 孤儿恢复   | SQLite 持久化注册表 + 父崩溃恢复                             |
| 敏感路径硬编码        | SENSITIVE_PATH_PATTERNS + 用户规则叠加                       |
| Trajectory 持久化     | 每步保存 + exit_status 分类                                  |
| 持久记忆              | MEMORY.md + 自动提取 + 去重签名                              |
| 并行工具执行          | asyncio.gather 并行 tool_calls                               |
| Pause/Resume          | 完整状态序列化到 SQLite                                      |

**验证标准**：长对话不崩溃；Skill 按需加载；子 Agent 隔离执行；轨迹可查；敏感路径被保护；并行工具生效

### P3 阶段：Auditable Harness（3-4 周）

**交付物**：

| 模块                    | 实现内容                                              |
| ----------------------- | ----------------------------------------------------- |
| GraphEngine Layer 体系  | LLMQuotaLayer + SuspendLayer + PauseStatePersistLayer |
| OTel ObservabilityLayer | OTel 原生 span + 节点类型 parser                      |
| VerificationLayer       | 工具调用后自动 lint/type check/test + 质量门禁        |
| Reviewer 评审           | 多次尝试 + LLM 评审选择最佳                           |
| review_on_submit 自审   | 提交前自动自审                                        |
| 验证报告分离            | Agent 自述 vs 服务级验证                              |
| FTS5 跨会话搜索         | session_search 工具                                   |
| Security Audit          | 多维度安全审计 + Dangerous Config Detection           |
| Trajectory 回放         | `conch replay <file>` 结构化回放                      |
| Insights 报告           | 会话成功率 + 失败原因分布 + 成本统计                  |
| Webhook / API Server    | HTTP API 入口                                         |
| React Web Console       | 会话观察、工具调用展示、运行回放、审批面板            |

**验证标准**：OTel span 可查；多次尝试选择最佳；工具调用后自动验证；历史可搜索；安全审计通过；轨迹可回放；Web Console 能观察 run 并完成审批

### P4 阶段：Governable Production Harness（4-6 周）

**交付物**：

| 模块                 | 实现内容                                 |
| -------------------- | ---------------------------------------- |
| RBAC                 | 40+ 权限点 + 操作 5 级分级               |
| 策略引擎             | PolicyEngine 统一合规规则管理            |
| 回归用例体系         | 失败案例自动沉淀 + 回归测试              |
| Curator 自改进       | Skill 自动归档/改进/consolidation        |
| WriteApproval        | memory/skill 写入审批 + pending store    |
| Credential Pool      | 多 API key 轮换 + Bitwarden/1Password    |
| Cron 调度            | 定时任务 + 3 分钟硬中断                  |
| Coordinator 多 Agent | 主从编排 + 决策表 + 上下文隔离           |
| 成本熔断             | 单任务 Token/时间/资源预算               |
| 快照/回滚            | Docker commit 快照 + restore             |
| Web Dashboard        | 治理、指标、回放、回归用例的基础管理界面 |
| Electron Desktop     | P4 复用 Web Console，补本地文件/终端桥接 |

**验证标准**：角色权限控制；成本预算可熔断；Skill 自动归档/改进；定时任务执行；回归测试通过率作为质量门禁；轨迹可回放；多 Agent 协作；前端能完成基础治理和指标查看

---

## 七、分层设计汇总

```
E 层：Local/Docker/SSH 沙箱 + FS Bridge + 快照/回滚
T 层：12 核心工具 + ToolSearch + ToolPolicy + 并行工具执行
C 层：可插拔 Context Engine + 渐进式上下文压缩 + Prompt Caching + Skill/Memory
L 层：Agent Loop + Agent Runtime 可插拔 + Layer 插件体系 + 多 Agent 编排
O 层：OpenTelemetry Trace + Trajectory 回放 + exit_status 归因 + Insights
V 层：VerificationLayer + Reviewer + review_on_submit + 回归用例体系
G 层：RBAC + 配额熔断 + 敏感路径保护 + WriteApproval + SecurityAudit + PolicyEngine
S 层：SQLite 优先 + Checkpoint + TrajectoryStore + FTS5 搜索
```

---

## 八、自研差异化清单

| 差异化模块                             | 说明                                                 |
| -------------------------------------- | ---------------------------------------------------- |
| VerificationLayer                      | 工具调用后自动 lint/type check/test + 质量门禁       |
| 并行工具执行                           | asyncio.gather 并行执行多个 tool_call                |
| 两级 Skill 注入             | 目录注入（默认）+ 按需加载（skill 工具）+ inject_schema 可选精准匹配 |
| 回归用例体系                           | 失败案例自动沉淀为测试用例 + 回归测试                |
| 策略引擎                               | PolicyEngine 统一合规规则管理（YAML 配置）           |
| 快照/回滚                              | Docker commit 快照 + restore                         |
| 渐进式压缩 + 可插拔引擎融合            | 渐进式上下文压缩与可插拔 Context Engine 组合         |

---

## 九、目录结构

```
agent-conch/
├── pyproject.toml
├── conch.yaml                       # 默认 Agent 配置
├── apps/
│   ├── web/                         # React Web Console（Vite + React + TypeScript）
│   │   ├── src/
│   │   │   ├── app/                 # chat/runs/tools/skills/dashboard/settings
│   │   │   ├── components/          # ui/chat/trace/diff
│   │   │   ├── hooks/
│   │   │   ├── lib/                 # api-client/event-stream
│   │   │   ├── store/
│   │   │   └── types/
│   │   └── package.json
│   └── desktop/                     # P4：Electron wrapper，复用 apps/web
├── src/
│   └── agent_conch/
│       ├── __init__.py
│       ├── cli.py                   # CLI 入口
│       ├── engine/                  # L 层：引擎与编排
│       │   ├── conch_engine.py
│       │   ├── agent_loop.py
│       │   ├── error_classifier.py
│       │   ├── runtime/             # Agent Runtime 可插拔
│       │   └── layers/              # Layer 插件体系
│       ├── tools/                   # T 层：工具系统
│       │   ├── registry.py
│       │   ├── tool_search.py
│       │   ├── tool_policy.py
│       │   ├── footprint.py
│       │   ├── mcp_client.py
│       │   └── core/                # 12 核心工具
│       ├── context/                 # C 层：上下文与记忆
│       │   ├── engine.py            # 可插拔 Context Engine
│       │   ├── compact/             # 渐进式上下文压缩
│       │   ├── prompt_caching.py
│       │   ├── skills/              # Skill 体系 + Curator
│       │   └── memory/              # 分层记忆
│       ├── state/                   # S 层：状态存储
│       │   ├── session_db.py
│       │   ├── checkpoint.py
│       │   └── trajectory.py
│       ├── sandbox/                 # E 层：沙箱
│       │   ├── registry.py
│       │   ├── local.py
│       │   ├── docker.py
│       │   ├── fs_bridge.py
│       │   └── path_validator.py
│       ├── security/                # G 层：治理与安全
│       │   ├── permissions.py
│       │   ├── sensitive_paths.py
│       │   ├── audit.py
│       │   ├── credentials.py
│       │   ├── write_approval.py
│       │   └── policy_engine.py
│       ├── verification/            # V 层：验证与评估
│       │   ├── layer.py
│       │   ├── reviewer.py
│       │   ├── self_review.py
│       │   ├── report.py
│       │   └── regression.py
│       ├── observability/           # O 层：可观测性
│       │   ├── otel.py
│       │   ├── trace_store.py
│       │   ├── exit_status.py
│       │   ├── insights.py
│       │   └── replay.py
│       ├── multiagent/              # L 层：多 Agent
│       │   ├── coordinator.py
│       │   ├── subagent.py
│       │   └── delegation.py
│       ├── hooks/                   # L 层：生命周期钩子
│       │   └── executor.py
│       └── prompts/                 # Prompt 模板
│           ├── system_prompt.py
│           └── agents_md.py         # AGENTS.md 发现
├── skills/                          # Bundled skills
├── tests/
└── docs/
```

---

## 十、关键设计决策记录

| 决策           | 选择                      | 理由                                                         | 否定项                                        |
| -------------- | ------------------------- | ------------------------------------------------------------ | --------------------------------------------- |
| 语言           | Python                    | LLM 工程、工具编排、异步执行和数据处理生态成熟               | TypeScript（ML 生态弱）                       |
| 存储           | SQLite 优先               | 结构化查询 + FTS5 全文搜索 + 并发 + 审计；零外部依赖         | PostgreSQL（部署重）、纯文件系统（查询弱）    |
| 压缩           | 渐进式上下文压缩          | 先清理旧结果，再折叠长内容，最后才调用 LLM 摘要；成本逐步递增 | 单一 LLM 摘要（成本高）、滑动窗口（丢信息）   |
| 工具数量       | 12 核心 + 渐进发现        | 最小工具原则，少而精远胜多而杂                               | 40+ 全量注入（决策分支多、出错率高）          |
| Context Engine | 可插拔                    | 上下文策略可扩展，支持第三方引擎                             | 固定管线（不可扩展）                          |
| 验证层         | 内置到 Agent 执行流程中   | 将验证从事后补充变成每轮执行的质量门禁                       | 仅离线批处理验证（交互式执行流程无覆盖）      |
| 配置           | YAML 驱动                 | 声明式配置可审计、可复现、易于团队共享                       | 纯代码配置（不可审计）                        |
| Prompt Caching | system_and_3 + 确定性排序 | 75% 成本节省 + 缓存稳定性                                    | 无 caching（成本高）                          |
| Skill 注入     | 目录注入（默认）+ 按需加载 | 不设门槛，放进去就用；LLM 自行判断加载；支持 compact/full 双模 | 全文注入（浪费 token）或无 skill 体系（结构缺失） |
| 前端           | Vite + React + TypeScript | 先做轻量 Web Console，覆盖 run 观察、审批、回放和基础指标；P4 再复用到 Electron | P3 直接做完整低代码平台或桌面端（复杂度过高） |
| 实时通道       | SSE 优先，WebSocket 后置  | Agent run 是服务端事件流，SSE 简单稳定；双向协作再引入 WebSocket | 一开始全量 WebSocket（复杂度高）              |
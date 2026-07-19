# Agent-Conch 项目全景认知文档

> 面向：新人研发、接手迭代人员  
> 目标：快速吃透架构全貌、运行机制、设计思想与开发规范，快速落地二次开发  
> 基准：当前主分支代码（95 源文件 / 13511 行 Python，209 passed / 1 skipped）

---

## 一、项目核心概览（极速认知）

### 1.1 定位

Agent-Conch 是一个**全栈通用 AI Agent Harness**。核心论点：

> **Agent = Model + Harness**

全部价值在 Harness 层：通过外部系统设计（而非模型权重优化），把 LLM 能力组织成可运行、可审计、可恢复、可治理的 Agent 系统。模型可以出错，Harness 必须保证可观测、可恢复、可治理。

### 1.2 ETCLOVG 七层架构核心思想

自下而上的七层模型，每层都是可插拔的 `Layer`，由 `ConchEngine` 在 Agent Loop 中统一编排：

| 层级 | 名称 | 一句话职责 |
| --- | --- | --- |
| **E** | 执行环境 | 命令执行与文件操作的隔离底座（Local/Docker/SSH） |
| **T** | 工具接口 | 外部能力统一接口（13 核心工具 + MCP） |
| **C** | 上下文记忆 | 模型看到什么、记住什么、遗忘什么 |
| **S** | 状态存储 | 状态外置底座（SQLite） |
| **L** | 生命周期编排 | Agent 执行循环与横切能力 |
| **O** | 可观测性 | 做了什么、为什么失败、成本花在哪 |
| **V** | 验证评估 | 把"声称完成"变成"有证据完成" |
| **G** | 治理安全 | 权限审批成本合规从提示词变成系统约束 |

### 1.3 H=(E,T,C,S,L,V) 六组件模型

形式化语义约束，把 Agent 抽象为六个组件：

| 符号 | 组件 | 对应模块 | 完整度 |
| --- | --- | --- | --- |
| E | Execution Loop | `engine/agent_loop.py` + `sandbox/` | 完整 |
| T | Tool Registry | `tools/` | 完整 |
| C | Context Manager | `context/` | 完整 |
| S | State Store | `state/` | 完整 |
| L | Lifecycle Hooks | `engine/layers/` + `hooks/` + `multiagent/` | 完整 |
| V | Evaluation Interface | `verification/` + `observability/exit_status.py` | 完整（自研强化） |

### 1.4 设计哲学

不追求模型能力堆叠，而追求**工程确定性**。把模型当"能力源"，Harness 负责编排、约束、验证与审计。

### 1.5 核心工程原则

| 原则 | 落地承诺 |
| --- | --- |
| 约束解放 | RBAC + 预算熔断 + 敏感路径硬编码 + 沙箱隔离 + 安全审计 |
| 最小工具 | 13 核心工具 + 六级扩展阶梯 + 渐进发现 |
| 零信任 | LLM 评审 + 提交自审 + 运行时验证层 |
| 状态外置 | SQLite 优先，运行时状态全进 DB，不依赖模型记忆 |
| 验证前置 | 每步写操作后自动 lint/type/test，质量门禁卡点 |
| 熵增管理 | 渐进式上下文压缩 + Skill 自改进 + 轨迹压缩 |
| 简单优先 | 核心窄腰，能力通过 Skill/Plugin/MCP 扩展；YAML 驱动 |

### 1.6 0-1 落地成熟度

| 阶段 | 级别 | 核心特征 | 状态 |
| --- | --- | --- | --- |
| P1 | Workflow Agent | 循环 + 工具 + 状态 + Local 沙箱 | 已完成 |
| P2 | Stateful Harness | 压缩 + 记忆 + Skill + Docker + 子 Agent | 已完成 |
| P3 | Auditable Harness | Trace + 验证 + 报告 + 搜索 + Web Console | 已完成 |
| P4 | Governable Production Harness | 权限审批 + 回归 + 调度 + 多 Agent + Web/Electron | 已完成 |

### 1.7 核心解决问题

- **可靠性**：错误分类恢复（retry/requery/compact/abort）+ 断点恢复 + 轨迹回放
- **可验证性**：运行时验证层 + 失败沉淀回归 + 多候选 LLM 评审 + 报告分离
- **可治理性**：RBAC 52 权限点 + 声明式策略引擎 + 一次性写审批 + 四维预算熔断
- **成本可控**：渐进式压缩 + Prompt Caching + 长输出制品化 + 预算熔断

### 1.8 核心差异化优势

- 运行时验证层（写后自动 lint/type/test + 失败沉淀回归）
- 渐进式上下文压缩三步管线（成本递增，能用规则不调 LLM）
- 并行工具执行读写分离（读并行 / 写串行）
- 两级 Skill 注入（目录注入 + 按需加载 + inject_schema 精准匹配）
- 声明式策略引擎（受控子集 + RBAC 先行 + 风险阈值审批）
- 三后端沙箱 + 快照回滚 + gVisor + 网络白名单
- 四层记忆 + FTS5 元记忆

### 1.9 能力边界（诚实声明）

- 单机与轻量多实例为主，不面向跨地域分布式部署
- 真实 Docker/gVisor、Vault 凭证、SSH 远端冒烟依赖外部环境
- Coordinator 为进程内 asyncio，非分布式队列
- Electron 签名/公证/自动更新属于发布工程，未产出
- Token 计数用近似估算（4 chars ≈ 1 token），未接入 tiktoken

---

## 二、整体架构全景

### 2.1 ASCII 整体架构拓扑图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户入口层                                │
│        CLI  │  FastAPI + SSE  │  React Web  │  Electron Desktop  │
└────────────┬────────────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────────────┐
│                    引擎编排层（L 层核心）                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ConchEngine（顶层编排器，组装所有子系统）                │   │
│  │  └─ AgentLoop（Observe → Think → Act 循环）              │   │
│  │     + forward_with_handling（错误降级）                   │   │
│  │     + ErrorClassifier（31 种错误分类）                    │   │
│  │     + BuiltinConchRuntime（可插拔 Runtime）               │   │
│  └────────┬───────────────────────────────────────────────┬───┘   │
│           │                                                │       │
│  ┌────────▼─────────┐                           ┌──────────▼────┐ │
│  │  Layer 插件链    │                           │  多 Agent 编排 │ │
│  │  LayerManager    │                           │  Coordinator  │ │
│  │  按注册顺序执行   │                           │  + SubagentMgr│ │
│  │  8 个 Layer:     │                           │  + CronScheduler│
│  │  ExecutionLimits │                           │  决策表+信号量 │ │
│  │  Observability   │                           │  默认并发 4   │ │
│  │  LLMQuota        │                           └───────────────┘ │
│  │  Verification    │                                             │
│  │  Suspend         │                                             │
│  │  PauseStatePersist                                             │
│  │  CostBudget      │                                             │
│  │  HookExecutor    │                                             │
│  └────────┬─────────┘                                             │
└───────────┼──────────────────────────────────────────────────────┘
            │
┌───────────▼──────────────────────────────────────────────────────┐
│                       能力供给层                                  │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │ 工具接口 │  │  上下文记忆  │  │  验证评估   │  │  可观测  │ │
│  │ T 层     │  │  C 层        │  │  V 层       │  │  O 层    │ │
│  │ToolRegistry│ │ContextEngine │  │VerificationLayer│ │OTelTracer│ │
│  │13核心工具 │  │+压缩三步管线 │  │+Reviewer   │  │+TraceStore│ │
│  │+MCP+Search│  │+Caching+Skill│  │+SelfReview │  │+DecisionTrace│
│  │+Policy    │  │+四层记忆     │  │+回归用例   │  │+Insights │ │
│  └────┬─────┘  └──────┬───────┘  └─────┬───────┘  └────┬─────┘ │
└───────┼───────────────┼────────────────┼────────────────┼───────┘
        │               │                │                │
┌───────▼───────────────▼────────────────▼────────────────▼───────┐
│                       治理与安全层（G 层）                        │
│  RBAC(52权限/5级/6角色) · PolicyEngine · WriteApprovalStore      │
│  CredentialPool(env/bw/op) · ContentSafetyGuard · SecurityAudit  │
│  BudgetManager(四维) · 拦截工具调用链路                            │
└───────────────────────────────┬──────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────┐
│                       执行环境层（E 层）                          │
│  SandboxRegistry → LocalBackend / DockerBackend(gVisor) / SSHBackend│
│  + FsBridge(7方法) + PathValidator(双重检查) + NetworkPolicy     │
│  + SnapshotManager(异步 commit/restore/delete)                   │
└───────────────────────────────┬──────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────┐
│                       状态存储层（S 层）                          │
│  SessionDB(SQLite): sessions/messages/turns/trajectories/         │
│    traces/decision_traces/verification_reports/approvals/         │
│    run_budgets/regression_cases/curator_proposals/cron_schedules/ │
│    coordinator_runs/snapshots/events                              │
│  + TrajectoryStore + CheckpointManager + FTS5(降级LIKE)          │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 分层讲解

**E 层（执行环境）** — Agent 的执行底座。`SandboxBackend` 抽象命令执行，`FsBridge` 抽象文件操作，两者解耦。`PathValidator` 做路径安全双重检查。`NetworkPolicy` 在 HTTP(S) 层做主机通配符与 CIDR 决策。`SnapshotManager` 异步适配 Docker 快照。被 T 层调用。

**T 层（工具接口）** — 外部能力统一接口。`BaseTool` 基类 + Pydantic `input_model` 校验 + JSON Schema 自动生成。`ToolRegistry` 统一注册、执行、健康管理。`ToolPolicy` 三层策略。`ToolSearch` 渐进发现。`MCPClient` 动态工具。`ToolOutputManager` 长输出制品化。调用 E，被 L 编排。

**C 层（上下文记忆）** — 最核心的层。`ContextEngine` ABC 五钩子，`LegacyEngine` fallback。`ContextCompressor` 三步渐进压缩。`PromptCaching` system_and_3。`SkillLoader`/`SkillInjector` 两级注入。`MemoryManager` 四层记忆。被 L 调用，读写 S。

**S 层（状态存储）** — 状态外置底座。`SessionDB` 管理全部 SQLite 表。`TrajectoryStore` 双源轨迹。`CheckpointManager` 断点恢复。被所有层读写。

**L 层（生命周期编排）** — `AgentLoop` 执行循环 + `LayerManager` 插件链 + `HookExecutor` 生命周期钩子 + `Coordinator`/`SubagentManager` 多 Agent + `CronScheduler` 定时调度。编排 T/C/V/O/G。

**O 层（可观测性）** — `ObservabilityLayer` 转 OTel span，`OTelTracer` 双写 OTel SDK 与 `TraceStore`。`DecisionTraceStore` 记录 observe/decide/act/verify/conclude/govern 六阶段决策摘要。`InsightsEngine` 聚合统计。`EventBus` SQLite 事件流支持多实例轮询。

**V 层（验证评估）** — `VerificationLayer` 写后自动验证 + 质量门禁。`Reviewer` LLM 多候选选优 + 启发式 fallback。`SelfReview` 确定性自审。`RegressionStore`/`RegressionRunner` 失败沉淀与门禁。

**G 层（治理安全）** — `RBAC` 52 权限点 + 五级操作 + 六角色。`PolicyEngine` 受控声明式 DSL。`WriteApprovalStore` 一次性审批。`CredentialPool` 多源轮换。`ContentSafetyGuard` 脱敏与阻断。`BudgetManager` 四维预算。拦截 T/L 链路。

### 2.3 整体数据流

```
任务输入
  → ConchEngine.run() 创建/恢复会话，绑定身份·角色·预算
  → RBAC 鉴权（RUN_CREATE 权限）
  → 设置会话身份（principal/role/sender）
  → MCP 工具懒加载刷新
  → BuiltinConchRuntime.run() → AgentLoop.run()
  → Layer 链 on_graph_start：执行限制 → 可观测 span → 配额 → 策略
  → 循环（每轮）：
      → ContextEngine.maintain()（auto-compact 检查）
      → forward_with_handling() → _call_model()
          → ContextEngine.assemble() 组装消息
          → PromptCaching.apply() 插入 cache_control 断点
          → ToolRegistry.get_available_schemas() 获取工具 schema
          → litellm.acompletion() 调用 LLM
          → CredentialPool 凭证轮换
      → 无工具调用 → 跳出循环
      → 有工具调用 → Layer.on_node_run_start
      → 工具调度：校验→Policy→RBAC/PolicyEngine→Approval→Budget→执行
      → 读写分离并行（读 asyncio.gather / 写串行）
      → Layer.on_node_run_end → VerificationLayer 写后验证
      → 结果脱敏 → OutputManager 制品化 → 轨迹/Trace
      → ContextEngine.after_turn()（记忆提取）
  → Layer 链 on_graph_end
  → SelfReview 自审（若 review_on_submit）
  → ContentSafetyGuard.redact() 最终回答脱敏
  → exit_status 归因 + 预算摘要
  → 返回 AgentResult
```

### 2.4 请求全链路流转（工具调用细节）

```
LLM 返回 tool_calls
  │
  ▼
AgentLoop._execute_tools_parallel()
  ├─ 按 is_write_tool 分离读/写
  ├─ 读操作 → asyncio.gather(ToolRegistry.execute_tool_call, return_exceptions=True)
  └─ 写操作 → 逐个串行 execute_tool_call
  │
  ▼
ToolRegistry.execute_tool_call(call, session_id)
  ├─ 1. 查找工具（未找到 → error record）
  ├─ 2. validate_input（Pydantic 校验，先过滤多余字段再实例化）
  ├─ 3. ToolPolicy.evaluate（Allow/Deny + 规则 + 默认 ALLOW）
  ├─ 4. PolicyEngine.evaluate（RBAC 先行 → 规则匹配 → 风险阈值审批）
  │     ├─ DENY → blocked record
  │     └─ REQUIRE_APPROVAL → WriteApprovalStore.authorize_or_request
  │         └─ 未授权 → approval_required record → AgentLoop 暂停
  ├─ 5. BudgetManager.consume_tool（超限 → blocked record）
  ├─ 6. tool.execute(**validated)
  ├─ 7. record_success/record_failure（健康记账，连续失败 ≥2 → 60s 抑制）
  ├─ 8. ContentSafetyGuard.sanitize_result（脱敏）
  └─ 9. ToolOutputManager.process（超 20000 chars → 0600 制品 + 4000 预览）
```

---

## 三、项目目录与代码结构解析

### 3.1 顶层目录

```
agent-conch/
├── conch.yaml                    # 默认配置（驱动全部行为）
├── pyproject.toml                # 项目元数据 + 依赖 + 工具配置
├── src/agent_conch/              # 后端核心（95 源文件，13511 行）
├── apps/
│   ├── web/                      # React + TypeScript 工作台
│   │   └── src/{App.tsx, api.ts, types.ts}
│   └── desktop/                  # Electron（main.cjs + preload.cjs）
├── tests/                        # 13 测试文件，2936 行，209 passed
├── docs/                         # 各层实现策略沉淀 + 阶段总结
└── plan/                         # 设计文档（agent-conch-design.md）
```

### 3.2 核心入口文件标注

| 入口类型 | 文件 | 核心类/函数 | 说明 |
| --- | --- | --- | --- |
| **CLI 入口** | `src/agent_conch/cli.py` | `main()`（click group） | 6 子命令：run/replay/tools/health/serve/config |
| **引擎入口** | `src/agent_conch/engine/conch_engine.py` | `ConchEngine` | 顶层编排器，组装所有子系统 |
| **循环入口** | `src/agent_conch/engine/agent_loop.py` | `AgentLoop.run()` | Observe-Think-Act 主循环 |
| **工具注册入口** | `src/agent_conch/engine/conch_engine.py` | `ConchEngine._register_core_tools()` | 注册 13 核心工具 |
| **工具执行入口** | `src/agent_conch/tools/registry.py` | `ToolRegistry.execute_tool_call()` | 工具调度总入口 |
| **上下文入口** | `src/agent_conch/context/engine.py` | `LegacyEngine.assemble()` | 上下文组装 |
| **压缩入口** | `src/agent_conch/context/compact/pipeline.py` | `ContextCompressor.compact()` | 渐进压缩 |
| **验证入口** | `src/agent_conch/verification/layer.py` | `VerificationLayer.on_node_run_end()` | 写后验证 |
| **状态存储入口** | `src/agent_conch/state/session_db.py` | `SessionDB` | SQLite 全量状态 |
| **安全策略入口** | `src/agent_conch/security/policy_engine.py` | `PolicyEngine.evaluate()` | 策略决策 |
| **API 入口** | `src/agent_conch/api/server.py` | `create_app(engine)` | FastAPI 应用工厂 |
| **配置入口** | `src/agent_conch/config.py` | `ConchConfig.load()` | YAML 配置加载 |

### 3.3 模块逐一解析

#### `src/agent_conch/engine/` — L 层核心

| 文件 | 核心类/函数 | 职责 |
| --- | --- | --- |
| `conch_engine.py` | `ConchEngine` | 顶层编排器，`__init__` 组装全部子系统，`run()` 是用户调用入口 |
| `agent_loop.py` | `AgentLoop`、`LLMResponse` | 主循环，`run()` 执行循环，`forward_with_handling()` 错误降级，`_call_model()` 调 LLM，`_execute_tools_parallel()` 并行工具 |
| `error_classifier.py` | `ErrorClassifier`、`FailoverReason`、`RecoveryStrategy` | 31 种错误分类 → 4 种恢复策略 |
| `runtime/types.py` | `AgentRuntime`（ABC）、`RuntimeRegistry`、`AgentResult`、`RuntimeConfig` | 可插拔 Runtime 抽象 |
| `runtime/builtin.py` | `BuiltinConchRuntime` | 内置 Runtime，封装 AgentLoop |
| `layers/base.py` | `Layer`（ABC）、`LayerManager`、`GraphContext`、`NodeContext`、`Event` | Layer 插件框架，5 钩子 + should_abort 中止 |
| `layers/execution_limits.py` | `ExecutionLimitsLayer` | max_turns / max_time 限制 |
| `layers/llm_quota.py` | `LLMQuotaLayer` | Token 配额熔断 |
| `layers/suspend.py` | `SuspendLayer`、`PauseStatePersistLayer` | 暂停捕获 + 状态持久化 |

#### `src/agent_conch/tools/` — T 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `base.py` | `BaseTool`（ABC）、`ToolResult`、`ToolCall`、`ToolExecutionRecord` | 工具基类，Pydantic input_model 校验，`to_schema()` 生成 JSON Schema，`validate_input()` 先过滤再校验 |
| `registry.py` | `ToolRegistry`、`ToolHealthState` | 注册/执行/健康管理，`execute_tool_call()` 是工具调度总入口，check_fn 30s TTL + 连续失败 ≥2 次 60s 抑制 |
| `tool_policy.py` | `ToolPolicy`、`PolicyRule`、`PolicyContext`、`ToolAction` | Allow/Deny + 规则 + 默认 ALLOW 三层策略 |
| `tool_search.py` | `ToolSearch` | 渐进发现，非核心 schema 超 context window 10% 启用 |
| `footprint.py` | `FootprintLadder` | 六级扩展阶梯评估 |
| `mcp_client.py` | `MCPClient`、`MCPServerSpec` | MCP 协议客户端，stdio 生命周期 + 动态发现/注册 |
| `output_manager.py` | `ToolOutputManager` | 超阈值（20000 chars）截断落 0600 制品，返回 4000 预览 |
| `core/` | 13 个工具类 | bash/read_file/write_file/edit_file/glob/grep/web_search/web_fetch/skill/ask_user/task_manage/tool_search/session_search |

#### `src/agent_conch/context/` — C 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `engine.py` | `ContextEngine`（ABC）、`LegacyEngine`、`TokenBudget`、`AssembleResult`、`SimpleTokenCounter` | 五钩子抽象 + fallback 实现，`assemble()` 组装消息，`maintain()` auto-compact 检查 |
| `compact/pipeline.py` | `ContextCompressor`、`ResultCleanup`、`ContentFolding`、`SummaryArchive`、`CompactResult` | 三步渐进压缩管线 |
| `prompt_caching.py` | `PromptCaching` | system_and_3 四断点，MIN_CACHEABLE_CHARS=100，非 Anthropic no-op |
| `skills/registry.py` | `SkillLoader`、`SkillInjector`、`Skill` | 四级加载 + frontmatter + inject_schema 选择性注入 |
| `skills/curator.py` | `SkillCurator`、`CuratorProposal` | archive/improve/consolidation 提案，经 WriteApproval 应用 |
| `memory/manager.py` | `MemoryManager`、`ShortTermMemory`、`SessionMemory`、`LongTermMemory`、`MetaMemory` | 四层记忆 + extract_and_persist 自动提取 |

#### `src/agent_conch/sandbox/` — E 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `local.py` | `SandboxBackend`（ABC）、`LocalBackend`、`CommandResult` | 本地执行后端，asyncio.create_subprocess_shell + 超时 kill |
| `docker.py` | `DockerBackend`、`DockerFsBridge`、`DockerConfig` | Docker 隔离，异步 commit/restore/delete，透传 --runtime runsc |
| `ssh.py` | `SSHBackend`、`SSHFsBridge`、`SSHConfig` | OpenSSH argv 执行 + 严格 host key + 远端 FsBridge |
| `fs_bridge.py` | `FsBridge`（ABC）、`LocalFsBridge`、`FileStat` | 文件操作抽象，7 方法 |
| `path_validator.py` | `PathValidator` | 原始字符串模式匹配 + resolved 精确比较双重检查 |
| `network_policy.py` | `NetworkPolicy` | HTTP(S) 主机通配符 + CIDR 白名单 |
| `registry.py` | `SandboxRegistry`、`SandboxMode` | 后端注册与选择（non-main/always/never） |
| `snapshots.py` | `SnapshotManager` | 异步快照管理，持久化外部引用 |

#### `src/agent_conch/state/` — S 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `session_db.py` | `SessionDB`、`Session`、`Message`、`Turn` | SQLite 全量状态，sessions/messages/turns/trajectories 四基础表 + 治理表 |
| `trajectory.py` | `TrajectoryStore`、`TrajectoryStep` | 双源轨迹（SQLite + JSONL），`replay()` 支持 DB/文件 |
| `checkpoint.py` | `CheckpointManager`、`Checkpoint` | 断点保存/恢复，pause/resume |

#### `src/agent_conch/verification/` — V 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `layer.py` | `VerificationLayer` | 写后自动 lint/type/test，首个失败即停，注入修复消息，block_progress 质量门禁 |
| `report.py` | `VerificationReport`、`VerificationCheck`、`VerificationStore` | agent_claim vs checks 分离持久化 |
| `regression.py` | `RegressionCase`、`RegressionStore`、`RegressionRunner` | SHA256 指纹去重沉淀 + 批量执行 + gate_passed/pass_rate 门禁 |
| `reviewer.py` | `Reviewer` | LLM JSON 评审 + 启发式 fallback |
| `self_review.py` | `SelfReview`、`SelfReviewResult` | 确定性规则自审，避免 mock 误触外部 LLM |

#### `src/agent_conch/security/` — G 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `permissions.py` | `Permission`（52 枚举）、`ActionLevel`（5 级）、`RBAC`、`AuthorizationResult` | 权限模型 + 6 内置角色（viewer/operator/developer/maintainer/admin/worker） |
| `policy_engine.py` | `PolicyEngine`、`PolicyRequest`、`PolicyEffect`、`PolicyResult` | 受控声明式 DSL，RBAC 先行 → 规则匹配 → 风险阈值审批 |
| `content_safety.py` | `ContentSafetyGuard` | 按字段语义扫描内联密钥，redact + sanitize_result |
| `credentials.py` | `CredentialPool`、`CredentialRef`、`CredentialLease` | env/bitwarden/1password 三 resolver，priority/uses/last-used 轮换 + 失败冷却 |
| `audit.py` | `SecurityAudit`、`AuditFinding` | 多维度危险配置扫描 |
| `sensitive_paths.py` | `SensitivePathChecker` | 独立敏感路径模块，Unix/Windows 双平台 |

#### `src/agent_conch/observability/` — O 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `otel.py` | `OTelTracer`、`ObservabilityLayer`、`NodeTypeParser` | graph/node/event 转 OTel span，双写 TraceStore |
| `trace_store.py` | `TraceStore`、`SpanRecord` | SQLite Trace 持久化 |
| `decision_trace.py` | `DecisionTraceStep`、`DecisionTraceStore` | observe/decide/act/verify/conclude/govern 六阶段决策摘要 |
| `exit_status.py` | `ExitStatus`（9 枚举）、`classify_exit_status` | 退出归因 |
| `insights.py` | `InsightsEngine` | 成功率/失败分布/Token/工具耗时聚合 |
| `events.py` | `EventBus` | SQLite 事件流，支持多实例轮询 |

#### `src/agent_conch/governance/` — L/G 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `budget.py` | `BudgetLimits`、`BudgetManager`、`CostBudgetLayer` | 四维预算（Token/时间/工具次数/资源），实时记账 + BUDGET_EXCEEDED |
| `scheduler.py` | `CronScheduler`、`Schedule`、`ScheduleRun` | UTC 五字段 + asyncio.wait_for 180s 硬中断 |

#### `src/agent_conch/multiagent/` — L 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `coordinator.py` | `Coordinator`、`DecisionTable`、`CoordinatorTask`、`CoordinatorRun` | 决策表驱动顺序/并行 worker + Semaphore（默认 4）+ 独立 session |
| `subagent.py` | `SubagentManager`、`SubagentRecord` | 子 Agent 注册表 + find_orphans/adopt_orphan 孤儿恢复 |

#### `src/agent_conch/hooks/` — L 层

| 文件 | 核心类 | 职责 |
| --- | --- | --- |
| `executor.py` | `HookSpec`、`HookExecution`、`HookExecutor`、`HookExecutorLayer` | 可配置事件命令 + fail_closed + SQLite 审计 |

#### `src/agent_conch/api/` — API 层

| 文件 | 核心类/函数 | 职责 |
| --- | --- | --- |
| `server.py` | `create_app(engine)` | FastAPI 应用工厂，40+ 路由 |
| `approvals.py` | `WriteApprovalStore`、`Approval`、`ApprovalStore` | 请求哈希防篡改 + pending 复用 + 批准后一次性消费 |

#### `src/agent_conch/prompts/` — Prompt 模板

| 文件 | 核心函数 | 职责 |
| --- | --- | --- |
| `system_prompt.py` | `build_system_prompt()` | base + env + mode 组装 |
| `agents_md.py` | `discover_agents_md()` | 从 cwd 向上遍历发现 AGENTS.md |

### 3.4 "改动该改在哪里"速查

| 改动需求 | 改动位置 |
| --- | --- |
| 新增工具 | `tools/core/` 新建文件继承 `BaseTool` + `conch_engine._register_core_tools()` 注册 |
| 新增 Layer | `engine/layers/` 或对应层目录新建类继承 `Layer` + `conch_engine._setup_layers()` 注册 |
| 修改上下文策略 | `context/engine.py` 的 `LegacyEngine` 或新建 `ContextEngine` 子类 |
| 修改压缩规则 | `context/compact/pipeline.py` 的 `ResultCleanup`/`ContentFolding`/`SummaryArchive` |
| 修改验证命令 | `conch.yaml` 的 `verification.commands` |
| 修改权限规则 | `conch.yaml` 的 `governance.policy_rules` |
| 修改预算 | `conch.yaml` 的 `budget.*` |
| 新增 API 路由 | `api/server.py` 的 `create_app()` 内 |
| 新增沙箱后端 | `sandbox/` 新建类继承 `SandboxBackend` + `FsBridge` + `conch_engine.__init__` 注册 |

---

## 四、核心运行流程

### 4.1 Agent 运行主循环流程

```
用户调用 ConchEngine.run(user_input, session_id, role)
  │
  ▼
RBAC 鉴权（RUN_CREATE 权限）──拒绝──► 返回 blocked
  │
  ▼
ToolRegistry.set_session_identity() 设置身份
  │
  ▼
MCP 工具懒加载（首次调用 refresh_mcp_tools）
  │
  ▼
BuiltinConchRuntime.run() → AgentLoop.run(session_id, user_input)
  │
  ▼
ContextEngine.bootstrap() 初始化上下文状态
  │
  ▼
SessionDB.add_message("user", user_input)
  │
  ▼
LayerManager.on_graph_start(graph_ctx)
  ├─ ExecutionLimitsLayer 记录开始时间
  ├─ ObservabilityLayer 创建 graph span
  ├─ LLMQuotaLayer 检查配额
  ├─ CostBudgetLayer 初始化预算
  └─ HookExecutorLayer 执行 on_graph_start hook
  │
  ▼
┌──────────── 循环（turn_count < max_turns）────────────┐
│                                                       │
│  检查时间限制（elapsed >= max_time → 返回 max_turns）  │
│  turn_count++                                         │
│  SessionDB.start_turn()                               │
│  ContextEngine.maintain()（auto-compact 检查）         │
│                                                       │
│  forward_with_handling(session_id):                   │
│    └─ _call_model():                                  │
│         ├─ ContextEngine.assemble() 组装消息           │
│         ├─ PromptCaching.apply() 插入断点              │
│         ├─ ToolRegistry.get_available_schemas()        │
│         ├─ CredentialPool.acquire() 获取凭证           │
│         ├─ litellm.acompletion() 调用 LLM              │
│         └─ 失败 → ErrorClassifier → 恢复策略            │
│              ├─ RETRY → 指数退避重试（最多 3 次）      │
│              ├─ REQUERY → 重新提问                     │
│              ├─ COMPACT → 压缩上下文后重试             │
│              └─ ABORT → 返回 None                      │
│                                                       │
│  保存 assistant 消息 + 记录 LLM 轨迹                   │
│  记录 DecisionTrace（observe/decide/conclude）         │
│                                                       │
│  无 tool_calls → last_response = content → break      │
│                                                       │
│  有 tool_calls:                                       │
│    ├─ LayerManager.on_node_run_start()                │
│    ├─ 解析 ToolCall.from_llm()                        │
│    ├─ 并行/串行执行（见 4.2）                          │
│    ├─ LayerManager.on_node_run_end()                  │
│    │    └─ VerificationLayer 写后验证（见 4.5）        │
│    ├─ 保存 tool 结果消息 + 记录工具轨迹                 │
│    ├─ 处理 inject_messages（验证失败注入修复消息）      │
│    ├─ 检查 approval_required → 暂停返回                │
│    └─ SessionDB.finish_turn()                         │
│                                                       │
│  except → ErrorClassifier.classify()                  │
│    └─ ABORT → 返回 error                              │
│    └─ 其他 → 继续下一轮                                │
│                                                       │
└───────────────────────────────────────────────────────┘
  │
  ▼
LayerManager.on_graph_end()
ContextEngine.after_turn()（记忆提取）
MetaMemory.index_session()
SelfReview.run()（若 review_on_submit）
ContentSafetyGuard.redact()（最终回答脱敏）
classify_exit_status()（9 种退出归因）
SessionDB.update_session_status()
返回 AgentResult
```

### 4.2 工具调用流程

见 2.4 节"请求全链路流转（工具调用细节）"。

关键代码路径：`AgentLoop._execute_tools_parallel()` → `ToolRegistry.execute_tool_call()` → `tool.execute()`。

### 4.3 上下文压缩流程

```
ContextEngine.maintain(session_id)  ← 每轮循环开头调用
  │
  ▼
组装完整消息 → SimpleTokenCounter.estimate()
  │
  ├─ token_count <= budget.available_for_context → 不压缩，清除缓存
  │
  ▼
超预算 → _compact_messages()
  │
  ▼
ContextCompressor.compact(messages, budget)
  │
  ▼
Step 1: ResultCleanup（零 LLM）
  ├─ 清理 >200 chars 的旧工具结果
  ├─ 保留最近 10 条（KEEP_RECENT=10）
  ├─ 替换为占位标记
  └─ 仍超预算？──是──► Step 2
                └─ 否──► 完成
  │
  ▼
Step 2: ContentFolding（零 LLM）
  ├─ 对 >2000 chars 内容折叠（THRESHOLD=2000）
  ├─ head 900 + tail 500（HEAD_CHARS/TAIL_CHARS）
  ├─ 中间标记 collapsed N chars
  └─ 仍超预算？──是──► Step 3
                └─ 否──► 完成
  │
  ▼
Step 3: SummaryArchive（一次 LLM）
  ├─ 结构化摘要：Historical / In-Progress / Pending / Remaining
  ├─ 添加 REFERENCE ONLY 前缀
  ├─ Compact Attachment 提取（recent_files/discovered_tools/async_tasks）
  └─ 缓存 compacted_messages 到 state.metadata
  │
  ▼
更新 ContextState：compact_count++、last_compact_turn、recent_files 等
```

### 4.4 状态持久化流程

```
每个操作 → SessionDB（同步 sqlite3，check_same_thread=False）

会话生命周期：
  create_session → add_message(user) → start_turn →
  add_message(assistant) → add_message(tool)* → finish_turn →
  ... 循环 ... → update_session_status(completed)

轨迹双源：
  运行时 → TrajectoryStore.save_step() → SQLite trajectories 表
  导出   → TrajectoryStore.export_jsonl() → ~/.agent-conch/trajectories/{id}.jsonl
  回放   → TrajectoryStore.replay() → 支持 DB 或 JSONL 文件

断点恢复：
  pause → CheckpointManager.pause() → 序列化状态到 checkpoints 表
  resume → CheckpointManager.resume() → 反序列化重建
```

### 4.5 执行验证流程

```
VerificationLayer.on_node_run_end(ctx, results)
  │
  ├─ 检查是否有成功的写操作（write_file/edit_file）
  │    └─ 否 → 跳过
  │
  ▼
是 → 按 conch.yaml verification.commands 串行执行
  ├─ command_result = await runner(command, cwd, timeout)
  ├─ VerificationCheck 记录（name/command/passed/exit_code/output[-4000:]/duration_ms）
  ├─ 首个失败即 break
  │
  ▼
VerificationReport.create(session_id, turn_index, agent_claim, checks)
  ├─ agent_claim = ctx.response.content（Agent 自述，不可信）
  ├─ checks = 服务级验证结果（可信）
  ├─ VerificationStore.save() 持久化
  │
  ├─ 通过 → ctx.metadata["verification_passed"] = True
  │
  ▼
失败
  ├─ RegressionStore.capture(report)（SHA256 指纹去重沉淀）
  ├─ ctx.inject_message(修复消息)（注入下一轮让模型修复）
  └─ ctx.block_progress("Verification quality gate failed")
```

### 4.6 安全校验流程

```
工具执行前（ToolRegistry.execute_tool_call 内）：
  │
  ├─ ToolPolicy.evaluate(ctx) → ALLOW/DENY/REQUIRE_APPROVAL
  │
  ├─ PolicyEngine.evaluate(PolicyRequest):
  │    ├─ RBAC.authorize(role, permission) → 拒绝则 blocked
  │    ├─ 规则匹配（roles/senders/tools/actions/level/argument_contains）
  │    └─ PolicyEffect: ALLOW / DENY / REQUIRE_APPROVAL
  │
  ├─ WriteApprovalStore.authorize_or_request():
  │    ├─ 生成请求哈希（防篡改）
  │    ├─ pending 状态可复用
  │    ├─ 未授权 → 返回 approval_required → AgentLoop 暂停
  │    └─ 批准后 consume() 一次性消费 → resume_approval() 恢复原始请求
  │
  ├─ BudgetManager.consume_tool(): 超限 → blocked
  │
  ▼
工具执行后：
  ├─ ContentSafetyGuard.sanitize_result(): 脱敏工具结果
  └─ ContentSafetyGuard.redact(): 最终回答脱敏
```

---

## 五、核心能力与关键策略详解

### 5.1 沙箱隔离机制

**核心类**：`SandboxBackend`（ABC）、`LocalBackend`、`DockerBackend`、`SSHBackend`、`FsBridge`（ABC）、`PathValidator`、`NetworkPolicy`、`SandboxRegistry`、`SnapshotManager`

**实现原理**：

- `SandboxBackend` 抽象命令执行（`execute()` + `is_available()`），`FsBridge` 抽象文件操作（7 方法：stat/read/write/rename/delete/list_dir/makedirs），两者解耦让工具层不关心后端差异
- `SandboxRegistry` 按 `sandbox.mode`（non-main/always/never）选择后端：主会话默认 Local，子会话用配置的隔离后端
- `PathValidator` 双重检查：原始字符串模式匹配（跨平台兼容）+ resolved 路径精确比较，敏感路径硬编码不可覆盖（`/etc`、`~/.ssh`、`/.env`、`~/.config`、`~/.aws`、`~/.gnupg`、`/proc`、`/sys`、`/dev` 等）
- `DockerBackend` 透传 `--runtime runsc` 接入 gVisor，异步 commit/restore/delete 实现快照
- `SSHBackend` 走 OpenSSH argv + 严格 host key 校验
- `NetworkPolicy` 在 HTTP(S) 层做主机通配符与 CIDR 决策，接入 web_search/web_fetch 工具

**触发时机**：工具层所有文件操作和命令执行都经 FsBridge/SandboxBackend，不直接调 os/subprocess。

**约束规则**：敏感路径硬编码不可被用户规则覆盖；Windows resolve 不稳定用双重检查规避。

### 5.2 工具注册与渐进发现

**核心类**：`ToolRegistry`、`BaseTool`、`ToolSearch`、`ToolHealthState`

**实现原理**：

- `BaseTool` 子类定义 `name`/`description`/`input_model`（Pydantic）/`is_write_tool`/`is_dangerous`/`is_core`/`tags`
- `to_schema()` 自动生成 JSON Schema（移除 title 减少 token）
- `validate_input()` 先过滤 input_model 不接受的字段再实例化，防止 LLM 传入冗余参数
- `ToolRegistry.check_tool_available()` 带 30s TTL 缓存（check_ttl），连续失败 ≥2 次进入 60s 瞬态抑制（transient_suppress）
- `get_available_schemas()` 过滤被抑制工具 + check_fn 不可用工具（核心工具不强制 check）
- `ToolSearch` 按非核心工具 schema token 占比阈值（默认 10%，`auto_threshold=0.10`）决定是否启用渐进发现

**触发时机**：`AgentLoop._call_model()` 每轮调用 `get_available_schemas(include_core_only=True)` 获取工具列表给 LLM。

### 5.3 并行工具执行

**核心函数**：`AgentLoop._execute_tools_parallel()`

**实现原理**：

```python
# 伪代码
write_calls, read_calls = 分离(tool_calls, key=tool.is_write_tool)

# 读操作并行
read_results = asyncio.gather(
    *[execute_tool_call(tc) for tc in read_calls],
    return_exceptions=True  # 异常不中断其他读
)

# 写操作串行
for tc in write_calls:
    record = await execute_tool_call(tc)

# 按原始 tool_call_id 排序合并
results.sort(key=lambda r: order_map[r.tool_call_id])
```

**约束规则**：只对互不依赖的读操作并行；写操作和危险操作串行避免竞争。当 `parallel_tools=True` 且 `len(tool_calls) > 1` 时启用，否则全串行。

### 5.4 可插拔上下文引擎

**核心类**：`ContextEngine`（ABC）、`LegacyEngine`、`TokenBudget`、`AssembleResult`

**五个钩子**：

1. `bootstrap(session_id)` → 初始化 `ContextState`
2. `assemble(session_id, budget)` → 组装消息列表（system + history + 压缩上下文）
3. `maintain(session_id)` → auto-compact 检查
4. `compact(session_id)` → 立即压缩（供错误恢复调用）
5. `after_turn(session_id, turn_result)` → 记忆提取

**铁律**：不允许变更过去上下文、不切换 toolset、不重建 system prompt，唯一例外是压缩。

**接入点**：`AgentLoop.__init__` 接收 `context_engine` 参数，`_call_model()` 调 `assemble()`，循环开头调 `maintain()`，`forward_with_handling` 的 COMPACT 策略调 `compact()`。

### 5.5 多级上下文压缩

见 4.3 节。三步管线成本递增：零 LLM → 零 LLM → 一次 LLM。`CompactResult` 记录 `steps_applied` 和 `attachments`。

### 5.6 Prompt 缓存策略

**核心类**：`PromptCaching`

**实现原理**：`system_and_3` 策略，4 个 cache_control 断点：

1. system prompt 末尾
2-4. 最后 3 条非 system 消息

`MIN_CACHEABLE_CHARS = 100`：内容 ≥100 chars 才占断点，防止浪费。非 Anthropic 模型为 no-op。

**触发时机**：`AgentLoop._call_model()` 中 `assemble()` 后调 `prompt_caching.apply(messages)`。

### 5.7 Skill 两级注入与自迭代

**核心类**：`SkillLoader`、`SkillInjector`、`Skill`、`SkillCurator`

**两级注入**：

1. **目录注入（默认）**：`SkillLoader.load_all()` 四级加载（bundled → user → project → plugin），`SkillInjector.inject()` 只把 name+description+tags 注入 system prompt
2. **按需加载**：LLM 通过 `skill` 工具 `action="load"` 获取完整正文
3. **可选优化**：`inject_schema.when` 条件匹配时，`fields` 指定章节直接全文注入

**自迭代**：`SkillCurator.analyze()` 识别 archive/improve/consolidation 候选，仅处理 agent-created 且未 pinned 的 Skill，生成 `CuratorProposal`，经 `WriteApproval` 应用。

### 5.8 分层记忆体系

**核心类**：`MemoryManager`、`ShortTermMemory`、`SessionMemory`、`LongTermMemory`、`MetaMemory`

| 层级 | 存储 | 生命周期 |
| --- | --- | --- |
| ShortTermMemory | 进程内存 | 单次会话 |
| SessionMemory | 内存 cache | 跨轮次 |
| LongTermMemory | SQLite + MEMORY.md | 跨会话，LIKE 模糊检索 |
| MetaMemory | SQLite FTS5（缺失降级 LIKE） | 跨会话全文搜索 |

**自动提取**：`MemoryManager.extract_and_persist()` 在 `ContextEngine.after_turn()` 中调用，LLM 模式 + 规则 fallback，SHA256 去重签名防重复。`LongTermMemory.persist_to_file()` 写 MEMORY.md。

### 5.9 运行时验证机制

见 4.5 节。`VerificationLayer.WRITE_TOOLS = {"write_file", "edit_file"}`，只在成功写操作后触发。

### 5.10 LLM 评审与自审

**核心类**：`Reviewer`、`SelfReview`

- `Reviewer`：接收候选集，LLM JSON 评审选优，异常时确定性启发式 fallback
- `SelfReview`：`ConchEngine.run()` 完成态返回前执行（`review_on_submit` 配置），确定性规则检查，失败改写 status 为 error，避免额外 LLM 调用导致已完成任务不稳定

### 5.11 回归用例沉淀

**核心类**：`RegressionStore`、`RegressionRunner`、`RegressionCase`

- `RegressionStore.capture(report)`：验证失败时用 SHA256 指纹去重沉淀
- `RegressionRunner`：批量执行，输出 `gate_passed`（pass_rate >= minimum_pass_rate）

### 5.12 分层权限与策略引擎

**核心类**：`RBAC`、`Permission`（52 枚举）、`ActionLevel`（5 级：READ/WRITE/EXECUTE/ADMIN/CRITICAL）、`PolicyEngine`、`WriteApprovalStore`、`BudgetManager`、`ContentSafetyGuard`

**决策顺序**：RBAC 先行 → YAML 规则匹配 → 风险阈值审批 → 写审批（哈希防篡改 + 一次性消费）→ 预算检查（四维实时记账）

**6 内置角色**：viewer / operator / developer / maintainer / admin / worker

**规则 DSL**：受控声明式子集（roles/senders/tools/actions/level/argument_contains），未引入 OPA/CEL。

### 5.13 可观测追踪

**核心类**：`OTelTracer`、`ObservabilityLayer`、`TraceStore`、`DecisionTraceStore`、`EventBus`、`InsightsEngine`

- `ObservabilityLayer` 把 graph/node/event 钩子转 OTel span，`OTelTracer` 双写 OTel SDK 与 `TraceStore`（全局 provider 只能设一次，复用已有）
- `DecisionTraceStore` 记录 observe/decide/act/verify/conclude/govern 六阶段，只记可观察证据，不采集模型思维链
- `EventBus` SQLite 事件流支持多 API 实例轮询
- `exit_status` 9 种归因：success/max_turns/timeout/quota_exceeded/budget_exceeded/verification_failed/security_blocked/error/aborted

### 5.14 断点恢复

**核心类**：`CheckpointManager`、`SuspendLayer`、`PauseStatePersistLayer`

- `pause()` → `CheckpointManager.pause()` 序列化状态到 checkpoints 表
- `resume()` → `CheckpointManager.resume()` 反序列化重建
- `resume_approval()` → 批准后执行持久化的原始工具请求，批准记录只能消费一次
- `CronScheduler` 用 `asyncio.wait_for` 180s 硬中断

### 5.15 子 Agent 编排机制

**核心类**：`Coordinator`、`DecisionTable`、`SubagentManager`

- `Coordinator.execute()`：决策表驱动顺序/并行 worker，`asyncio.Semaphore(max_workers=4)` 限并发，worker 独立 session 上下文隔离，结果持久化
- `SubagentManager`：子 Agent 注册表，`find_orphans()`/`adopt_orphan()` 孤儿恢复，`DELEGATE_BLOCKED_TOOLS` 禁止列表
- `CronScheduler`：UTC 五字段解析 + next-run + 持久化任务/结果

---

## 六、核心设计决策与取舍

| 决策 | 选择 | 理由 | 否定项 |
| --- | --- | --- | --- |
| 语言 | Python 3.10+ | LLM 工程/工具编排/异步/数据处理生态成熟 | TypeScript（ML 生态弱） |
| 存储 | SQLite 优先 | 结构化查询+FTS5+审计+零外部依赖 | PostgreSQL（部署重）、纯文件（查询弱） |
| SQLite 访问 | 同步 sqlite3 + `check_same_thread=False` | stdlib 同步 API，操作 <1ms 不阻塞；后续可切 aiosqlite | 直接异步（stdlib 不支持） |
| 压缩 | 渐进式三步 | 成本逐步递增，能用规则不调 LLM | 单一 LLM 摘要（成本高）、滑动窗口（丢信息） |
| Token 计数 | SimpleTokenCounter（4 chars ≈ 1 token） | 零依赖，近似够用 | tiktoken（精确但依赖重，后续可替换） |
| 工具数量 | 13 核心 + 渐进发现 | 最小工具原则 | 40+ 全量注入（决策分支多） |
| Context Engine | 可插拔 ABC | 上下文策略可扩展 | 固定管线（不可扩展） |
| 验证层 | 内置执行流程 on_node_run_end | 每轮质量门禁 | 仅离线批处理 |
| 配置 | YAML 驱动 | 声明式可审计 | 纯代码配置 |
| Prompt Caching | system_and_3 + MIN_CACHEABLE_CHARS=100 | 75% 成本节省 + 稳定性 | 无 caching |
| Skill 注入 | 目录注入 + 按需加载 | 不设门槛，放进去就用 | 全文注入（浪费 token） |
| 前端 | Vite+React+TS，P4 复用 Electron | 轻量 Console 优先 | 直接做低代码平台 |
| 实时通道 | SSE 优先 | 服务端事件流，简单稳定 | 全量 WebSocket |
| 规则引擎 | 受控声明式子集 | 减少依赖与动态执行风险 | OPA/CEL |
| 事件共享 | SQLite polling | 同库多实例，零外部依赖 | 外部 broker |
| 凭证 | CLI resolver 接入 bw/op | 复用本机登录态，明文不落库 | 内嵌 SDK |
| 前端三栏 | 深海青蓝三栏工作台 | 观察为主，治理为辅 | 卡片堆叠 |

---

## 七、业内对标核心差异

### 7.1 六维度横向对比

| 维度 | Agent-Conch | OpenHarness 类 | Dify | SWE-agent | Hermes 类 | OpenClaw 类 |
| --- | --- | --- | --- | --- | --- | --- |
| **架构分层** | ETCLOVG 七层 + H 六组件 + Layer 可插拔 | 2-3 层 | 工作流节点 | 循环+工具单层 | 编排+Worker | 沙箱单层 |
| **工具体系** | 13 核心 + 渐进发现 + MCP + 读写分离并行 | 固定工具集 | 节点即工具 | 固定 ACI | Worker 持有 | 无工具层 |
| **上下文管理** | 可插拔引擎 + 三步压缩 + Caching + 四层记忆 | 无或截断 | 无 | 简单截断 | Worker 各自 | 无 |
| **验证能力** | 运行时验证 + 回归沉淀 + LLM 评审 + 报告分离 | 无 | 无 | 启发式 | 无 | 无 |
| **可观测性** | OTel + DecisionTrace + 双源轨迹 + exit_status + Insights | 基础日志 | 流程日志 | 轨迹记录 | Worker 状态 | 沙箱日志 |
| **安全治理** | RBAC 52权限 + 策略引擎 + 写审批 + 四维预算 + 凭证池 | 无或简单 | RBAC | 无 | 无 | 沙箱隔离 |

### 7.2 独有优势

- 运行时验证层 + 失败沉淀回归（业内多数无）
- 渐进式压缩三步管线（业内多为简单截断或单一 LLM 摘要）
- 并行工具执行读写分离（多数 Agent 串行）
- 两级 Skill 注入 + inject_schema 精准匹配
- 声明式策略引擎 + RBAC 先行 + 一次性写审批
- 三后端沙箱 + gVisor + 网络白名单 + 快照回滚
- 四层记忆 + FTS5 元记忆

### 7.3 当前短板

- 无向量检索（长期记忆用 LIKE，元记忆用 FTS5）
- 无分布式编排（Coordinator 为进程内 asyncio）
- 无外部消息总线（SQLite polling，无 Redis/NATS）
- 无远端 OTel exporter（仅写 SQLite）
- 无浏览器 E2E 框架（Web Console 仅构建+API 测试）
- 无产品级签名/公证（Electron 仅源码+可分发目录）

---

## 八、项目核心卡点、注意事项与开发规范

### 8.1 开发改造禁忌

- **禁止绕过 ToolRegistry 直接执行系统命令**：所有新工具必须经 `ToolRegistry.execute_tool_call()` 的 RBAC → PolicyEngine → Approval → Budget 链路
- **禁止 Agent Loop 内 except 静默吞异常**：曾因 `await` 同步 `save_step` 触发 TypeError 被吞，导致循环跑满 max_turns
- **禁止变更过去上下文**：C 层铁律，唯一例外是压缩
- **禁止重建 system prompt**：会破坏 Prompt Caching 稳定性
- **禁止跨工作目录修改不相关文件**：保持改动范围最小

### 8.2 核心约束

- `TrajectoryStore.save_step()` 是同步方法，Agent Loop 中直接调用不加 `await`
- `check_fn` 结果带 30s TTL，连续失败 ≥2 次进入 60s 抑制
- `VerificationLayer` 只在 `write_file`/`edit_file` 成功后触发，首个失败即停
- `WriteApproval` 批准后只能消费一次
- `CronScheduler` 硬超时上限 180 秒
- `Coordinator` 默认并发上限 4

### 8.3 关键容错机制

- `forward_with_handling`：retry（指数退避）/ requery / compact / abort 四种恢复策略，最多 3 次重试
- FTS5 缺失时降级为 LIKE
- PromptCaching 非 Anthropic 模型为 no-op
- rich 不可用时 CLI 退化为简单 print
- `check_fn` 不可用工具被过滤不暴露给 LLM

### 8.4 常见报错与原因

| 报错 | 原因 | 解决 |
| --- | --- | --- |
| `Max time exceeded` | 超过 `agent_loop.max_time` | 调大配置或优化任务 |
| `Tool blocked by policy` | ToolPolicy 或 PolicyEngine 拒绝 | 检查 `governance.policy_rules` |
| `Approval required` | 高风险操作需审批 | 调用 `/approvals/{id}/decision` 批准 |
| `Tool blocked by budget` | 预算超限 | 调大 `budget.*` 或检查 Token 消耗 |
| `Verification quality gate failed` | 写后验证失败 | 检查 `verification.commands` 输出 |
| `BUDGET_EXCEEDED` | 四维预算超限 | 检查 `budget.max_*` |
| `Context window exceeded` | 上下文超限 | 检查 auto_compact 是否启用 |
| `Tool suppressed due to transient failures` | 连续失败 ≥2 次 | 检查工具依赖或等待 60s |

### 8.5 性能瓶颈

- 同步 SQLite + 异步事件循环（高并发写入竞争）
- Token 计数用近似估算（压缩阈值偏差）
- 单 SQLite 写者（高频写入竞争）
- FTS5 降级 LIKE（搜索性能下降）

### 8.6 权限与安全红线

- 敏感路径硬编码不可覆盖
- 凭证明文不落库（env/bitwarden/1password CLI resolver）
- ContentSafetyGuard 按字段语义扫描内联密钥
- 工具结果与最终回答统一脱敏
- 高风险操作必须经 WriteApproval

### 8.7 上下文使用规范

- 不重建 system prompt（破坏 Caching）
- 压缩经 `ContextCompressor` 三步管线，不自定义截断
- `auto_compact=True` 时 `maintain()` 自动检查
- Skill 经 `SkillInjector` 注入，不手动拼接到 system prompt

### 8.8 工具扩展规范

1. 继承 `BaseTool`，定义 `name`/`description`/`input_model`/`is_write_tool`/`is_dangerous`/`is_core`/`tags`
2. 实现 `async def execute(**kwargs) -> ToolResult`
3. 可选设置 `check_fn` 做可用性前置检查
4. 在 `ConchEngine._register_core_tools()` 注册
5. `governance_action` 属性可声明操作类型（read/write/exec/network）

### 8.9 Skill 编写规范

- SKILL.md + YAML frontmatter（name/description/version/tags/category 必填）
- `inject_schema` 可选（when 条件 + fields 章节）
- 按章节 `## 标题` 拆分正文
- 四级加载：bundled → user → project → plugin

### 8.10 验证层接入规范

- `verification.commands` 在 `conch.yaml` 配置（如 `ruff check`/`mypy`/`pytest`）
- 只在 `write_file`/`edit_file` 成功后触发
- 首个失败即停 + 注入修复消息 + `block_progress`
- 失败自动经 SHA256 去重沉淀为回归用例

---

## 九、快速上手工作流

### 9.1 跑通项目

```bash
# 1. 克隆 + 安装
git clone https://github.com/vvvcxjvvv/agent-conch.git
cd agent-conch
pip install -e ".[dev]"

# 2. 配置模型（编辑 conch.yaml）
#    model.name: "deepseek/deepseek-chat"
#    model.api_key_env: "DEEPSEEK_API_KEY"
export DEEPSEEK_API_KEY="<your-key>"

# 3. 运行首个任务
conch run "读取 README.md 并总结"

# 4. 启动 API + Web 工作台
conch serve                          # 终端一
cd apps/web && npm install && npm run dev  # 终端二，打开 http://127.0.0.1:5173

# 5. 验证测试
pytest tests/
ruff check src tests
mypy src
```

### 9.2 新增工具（标准步骤）

1. 在 `src/agent_conch/tools/core/` 新建文件，如 `my_tool.py`
2. 继承 `BaseTool`，定义属性和 `input_model`：

```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "做某事"
    input_model = MyToolInput  # Pydantic BaseModel
    is_write_tool = False
    is_core = True
    tags = ["custom"]

    async def execute(self, **kwargs) -> ToolResult:
        # 实现
        return ToolResult.success("result")
```

3. 在 `ConchEngine._register_core_tools()` 注册：`self.tool_registry.register(MyTool(...))`
4. 在 `tests/test_tools.py` 补充测试
5. `pytest tests/test_tools.py` 验证

### 9.3 新增策略 Layer（标准步骤）

1. 在对应层目录新建文件，如 `src/agent_conch/engine/layers/my_layer.py`
2. 继承 `Layer`，实现所需钩子：

```python
class MyLayer(Layer):
    name = "my_layer"

    async def on_graph_start(self, ctx: GraphContext) -> None:
        # 逻辑
        if 某条件:
            ctx.should_abort = True
            ctx.abort_reason = "原因"
```

3. 在 `ConchEngine._setup_layers()` 注册：

```python
elif layer_name == "my_layer":
    self.layer_manager.add(MyLayer())
```

4. 在 `conch.yaml` 的 `layers.enabled` 添加 `"my_layer"`
5. 补充测试

### 9.4 修改上下文规则（标准步骤）

- **修改压缩阈值**：`context/compact/pipeline.py` 的 `ResultCleanup.KEEP_RECENT`/`ContentFolding.THRESHOLD`/`HEAD_CHARS`/`TAIL_CHARS`
- **修改 Token 预算**：`context/engine.py` 的 `TokenBudget`
- **新增 ContextEngine**：继承 `ContextEngine` ABC 实现五钩子，在 `ConchEngine.__init__` 替换 `LegacyEngine`

### 9.5 扩展验证能力（标准步骤）

- **新增验证命令**：`conch.yaml` 的 `verification.commands` 追加
- **修改触发条件**：`VerificationLayer.WRITE_TOOLS` 集合
- **调整回归门禁**：`conch.yaml` 的 `regression.minimum_pass_rate`
- **新增验证类型**：继承 `Layer` 实现 `on_node_run_end`，或扩展 `VerificationLayer`

### 9.6 新增 API 路由（标准步骤）

1. 在 `api/server.py` 的 `create_app()` 内添加路由
2. 用 `require(role, permission)` 做权限校查
3. 调用 `engine` 的对应方法
4. 补充 `tests/test_p4.py` 或新建测试文件

### 9.7 调试技巧

- `conch tools`：查看已注册工具与健康状态
- `conch health`：查看工具健康详情
- `conch config`：查看当前生效配置
- `conch replay <session_id>`：回放轨迹
- `curl http://127.0.0.1:8765/governance/overview`：治理总览
- `curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/runs/{id}/decisions`：决策轨迹
- `curl -N http://127.0.0.1:8765/events/{session_id}`：SSE 实时事件


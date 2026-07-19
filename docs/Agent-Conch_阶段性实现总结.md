# Agent-Conch 阶段性实现总结

> 基准设计：`plan/agent-conch-design.md`（ETCLOVG 七层模型 + H=(E,T,C,S,L,V) 六组件形式化）  
> 阶段范围：P1 Workflow Agent → P2 Stateful Harness → P3 Auditable Harness → P4 Governable Production Harness  
> 验收日期：2026-07-19  
> 当前代码：95 个源文件 / 13511 行 Python，13 个测试文件 / 2936 行，`pytest` 209 passed、1 skipped

---

## 一、整体架构与设计哲学

**核心论点：Agent = Model + Harness。** 全部价值在 Harness 层：通过外部系统设计而非模型权重优化，让 Agent 在生产环境中稳定可控、可验证、可落地、可治理。

七大工程原则的落地承诺：

| 原则 | 落地方案 |
| --- | --- |
| 约束解放 | RBAC + 配额熔断 + 敏感路径硬编码 + 沙箱隔离 + 安全审计 |
| 最小工具 | 12 核心工具 + FootprintLadder 六级扩展阶梯 + ToolSearch 渐进发现 |
| 零信任 | Reviewer LLM 评审 + review_on_submit 自审 + VerificationLayer 执行验证 |
| 状态外置 | SQLite 优先，所有运行时状态外置到 DB，不依赖模型记忆 |
| 验证前置 | 每步写操作后自动 lint/type check/test，质量门禁卡点 |
| 熵增管理 | 渐进式上下文压缩 + Curator Skill 自改进 + Trajectory 压缩 |
| 简单优先 | 核心保持窄腰，能力通过 Skill/Plugin/MCP 扩展；YAML 驱动配置 |

ETCLOVG 七层模型，每层都是可插拔的 `Layer`，由 `ConchEngine` 在 Observe-Think-Act 循环中编排：

```
G 治理与安全  RBAC · PolicyEngine · Approval · Budget · ContentSafety · CredentialPool
V 验证与评估  VerificationLayer · Reviewer · SelfReview · Regression
O 可观测性    OTel · Trace · Trajectory · exit_status · Insights · SSE
L 生命周期    AgentLoop · Layer · Hook · Coordinator · Cron · Subagent
C 上下文记忆  ContextEngine · Compact · PromptCaching · Skill · Memory
T 工具接口    Core Tools · MCP · Registry · ToolPolicy · OutputManager
E 执行环境    Local · Docker · SSH · gVisor · FsBridge · PathValidator
S 状态存储    SQLite · Checkpoint · FTS5 · Audit · EventStream
```

H=(E,T,C,S,L,V) 六组件映射：

| 符号 | 组件 | Agent-Conch 模块 | 完整度 |
| --- | --- | --- | --- |
| E | Execution Loop | `engine/agent_loop.py` + `sandbox/` | 完整 |
| T | Tool Registry | `tools/registry.py` + `tools/tool_search.py` + `tools/tool_policy.py` | 完整 |
| C | Context Manager | `context/engine.py` + `context/compact/` + `context/skills/` + `context/memory/` | 完整 |
| S | State Store | `state/session_db.py` + `state/checkpoint.py` + `state/trajectory.py` | 完整 |
| L | Lifecycle Hooks | `engine/layers/` + `hooks/` + `multiagent/` | 完整 |
| V | Evaluation Interface | `verification/` + `observability/exit_status.py` | 完整（自研强化） |

---

## 二、各阶段交付与完成度

### P1 Workflow Agent（基础骨架）

**目标**：Observe-Think-Act 执行循环 + 12 核心工具 + SQLite 状态持久化 + Local 沙箱隔离。

| 交付物 | 实现内容 | 核心代码 |
| --- | --- | --- |
| Agent Loop | Observe-Think-Act 循环 + `forward_with_handling` 错误降级 | `engine/agent_loop.py` |
| Agent Runtime | `RuntimeRegistry` + `BuiltinConchRuntime` | `engine/runtime/types.py`、`builtin.py` |
| 12 核心工具 | bash/read_file/write_file/edit_file/glob/grep/web_search/web_fetch/skill/ask_user/task_manage/tool_search | `tools/core/*.py` |
| ToolPolicy | Allow/Deny + Sandbox Policy + 自定义规则引擎 | `tools/tool_policy.py` |
| ToolSearch | 渐进发现 + 自动阈值（context window 10%） | `tools/tool_search.py` |
| check_fn | 前置检查 + 30s TTL 缓存 + 60s 瞬态故障抑制 | `tools/registry.py` |
| SQLite 状态存储 | sessions/messages/turns/trajectories 四表 + 跨连接持久化 | `state/session_db.py` |
| Local 沙箱 + FsBridge | `LocalBackend` + `LocalFsBridge` + `PathValidator` + `SandboxRegistry` | `sandbox/local.py`、`fs_bridge.py`、`path_validator.py` |
| 基础 System Prompt | base + env + AGENTS.md 发现 | `prompts/system_prompt.py`、`agents_md.py` |
| Layer 基础框架 | Layer ABC（5 钩子）+ `LayerManager` + `ExecutionLimitsLayer` | `engine/layers/base.py`、`execution_limits.py` |

**关键设计偏差与修复**：

1. C 层未实现可插拔 Context Engine，直接从 DB 加载消息 → P2 修复
2. `ErrorClassifier` 仅 15 种（设计要求 20+）→ P2 扩展到 25 种
3. `SandboxRegistry` NON_MAIN 模式退化为 Local（Docker 为 P2 交付）→ P2 修复
4. `TrajectoryStore.save_step` 为同步方法（SQLite stdlib 同步 API）→ P2 可选 aiosqlite
5. Windows 路径 resolve 不稳定 → 双重检查（原始字符串模式匹配 + resolved 精确比较）

**踩坑教训**：Agent Loop 的 `except` 块曾静默吞异常，导致 `await` 同步 `save_step` 触发的 TypeError 被捕获，`break` 未执行，循环跑满 max_turns。教训是循环内 except 不静默吞异常。

**验证标准达成**：读取文件 → 修改 → 运行测试 → 回答循环闭环；SQLite 持久化；沙箱隔离生效。

### P2 Stateful Harness（能用）

**目标**：从"能跑"升级到"能用"——长对话不崩溃、成本可控、领域知识按需注入、错误精准恢复、暂停/恢复、子 Agent 委托。重心在 C 层。

| 交付物 | 实现内容 | 核心代码 |
| --- | --- | --- |
| 可插拔 Context Engine | `ContextEngine` ABC（5 钩子）+ `LegacyEngine` fallback | `context/engine.py` |
| 渐进式上下文压缩 | 三步管线：`ResultCleanup`（零 LLM）→ `ContentFolding`（零 LLM）→ `SummaryArchive`（一次 LLM） | `context/compact/pipeline.py` |
| Prompt Caching | `system_and_3` 策略 + 4 断点 + `_can_carry_marker`（≥100 chars） | `context/prompt_caching.py` |
| Skill 体系 | 四级加载（bundled → user → project → plugin）+ frontmatter + `inject_schema.when`/`fields` 选择性注入 | `context/skills/registry.py` |
| 分层记忆 | Short/Session/Long/Meta 四层 + LLM/规则双模式提取 + 去重签名 + FTS5（缺失降级 LIKE） | `context/memory/manager.py` |
| ErrorClassifier | 25 种错误 + 不重试集（SSL/BAD_REQUEST/NOT_FOUND 等） | `engine/error_classifier.py` |
| Docker 沙箱 | `DockerBackend` + `DockerFsBridge` + `hard_reset` + snapshot + shell_quote 防注入 | `sandbox/docker.py` |
| 敏感路径硬编码 | 独立模块 `SensitivePathChecker` + Unix/Windows 双平台 + 文件名模式 | `security/sensitive_paths.py` |
| Checkpoint/Pause/Resume | checkpoints 表 + 完整状态序列化/恢复 | `state/checkpoint.py` |
| Subagent + 孤儿恢复 | subagents 表 + spawn/complete/fail + `find_orphans`/`adopt_orphan` + `DELEGATE_BLOCKED_TOOLS` | `multiagent/subagent.py` |
| Agent Loop 改造 | 接入 `ContextEngine.bootstrap/maintain/assemble/after_turn` + `prompt_caching.apply` | `engine/agent_loop.py` |

**关键设计偏差与修复**：

1. `SummaryArchive` LLM 调用为可选 `llm_caller`（None 时跳过），未实现独立 auxiliary model 配置
2. Token 计数用 `SimpleTokenCounter`（4 chars ≈ 1 token），未用 tiktoken 精确计数
3. `LongTermMemory` 检索用 LIKE 模糊匹配，未实现向量检索
4. Skill Curator 未实现（P4 交付）
5. FTS5 在部分 SQLite 编译缺失时降级为普通表 + LIKE

**验证标准达成**：长对话不崩溃；Skill 按需加载；子 Agent 隔离执行；轨迹可查；敏感路径被保护；并行工具生效。

### P3 Auditable Harness（有证据的完成）

**目标**：达到 H3"有证据的完成"——完整 trace、失败归因、确定性验证、验证协议与验证报告。

| 交付物 | 实现内容 | 核心代码 |
| --- | --- | --- |
| GraphEngine Layer 体系 | `LLMQuotaLayer` + `SuspendLayer` + `PauseStatePersistLayer` | `engine/layers/llm_quota.py`、`suspend.py` |
| OTel ObservabilityLayer | 原生 span + `NodeTypeParser` + `TraceStore` 双写 + `DecisionTraceStore` | `observability/otel.py`、`trace_store.py`、`decision_trace.py` |
| VerificationLayer | 写后 lint/type/test 串行 + 首个失败即注入修复消息 + 质量门禁 | `verification/layer.py` |
| Reviewer 评审 | 多候选 + LLM JSON 评审 + 启发式 fallback | `verification/reviewer.py` |
| review_on_submit 自审 | 完成态返回前确定性自审，失败改写为 error | `verification/self_review.py` |
| 验证报告分离 | `agent_claim`（不可信）与 `checks`（可信）分字段持久化 | `verification/report.py` |
| FTS5 跨会话搜索 | `session_search` 工具 + 完成会话幂等索引 | `tools/core/session_search.py` |
| Security Audit | 内联密钥/沙箱禁用/根目录暴露/Docker host 网络/公开 API/空门禁/无效配额/远程 HTTP 端点 | `security/audit.py` |
| Trajectory 回放 | SQLite/JSONL 双源 + CLI/API 展示 | `state/trajectory.py` |
| Insights 报告 | 会话成功率/失败分布/Token/工具耗时/工具失败聚合 | `observability/insights.py` |
| Webhook / API Server | FastAPI + SSE + run/决策轨迹/执行轨迹/Trace/验证/搜索/审计/Insights/评审/审批 | `api/server.py` |
| React Web Console | 深海青蓝三栏工作台 + SSE 时间线 + 决策轨迹页签 + Markdown/源文本切换 | `apps/web/src/App.tsx` |

**关键设计偏差与修复**：

1. OTel 未配置远端 exporter（属于部署配置），SQLite Trace API 保证无 collector 时仍可查
2. `SelfReview` 默认确定性规则避免额外 LLM 调用导致已完成任务不稳定；`Reviewer` 仍支持 LLM
3. 审批面板为 P3 交互 pending store，完整 `WriteApproval` 在 P4；不提前改变 P4 权限语义
4. MCP 不在 P3 设计交付表，按设计表验收（P4 缺口闭环增量补齐）
5. OTel 全局 provider 只能安全设置一次，初始化时复用已有 `TracerProvider`

**验证标准达成**：OTel span 可查；多次尝试选择最佳；工具调用后自动验证；历史可搜索；安全审计通过；轨迹可回放；Console 能观察 run 并完成审批。

### P4 Governable Production Harness（可治理）

**目标**：权限审批、人工接管、回归集、策略治理、成本熔断、多 Agent 编排。

| 交付物 | 实现内容 | 核心代码 |
| --- | --- | --- |
| RBAC | `Permission` 40+ 权限点 + READ/WRITE/EXECUTE/ADMIN/CRITICAL 五级 + viewer/operator/developer/maintainer/admin/worker 内置角色 | `security/permissions.py` |
| PolicyEngine | RBAC 先行 → YAML 规则匹配 → 风险阈值审批；工具执行和 API 双入口前置拦截；受控声明式 DSL（未引入 OPA/CEL） | `security/policy_engine.py`、`tools/registry.py` |
| 回归用例体系 | Verification 失败自动去重沉淀 + 启停 + 批量运行 + 最低通过率门禁 | `verification/regression.py` |
| Curator 自改进 | 仅处理 agent-created 且未 pinned Skill；archive/improve/consolidation 提案经 `WriteApproval` 应用 | `context/skills/curator.py` |
| WriteApproval | 受保护路径写入暂停 + 请求哈希防篡改 + pending 复用 + 批准后一次性消费恢复原始请求 | `api/approvals.py`、`engine/conch_engine.py` |
| Credential Pool | priority/uses/last-used 轮换 + 失败冷却 + env/Bitwarden/1Password CLI resolver + 明文不落库 | `security/credentials.py` |
| Cron 调度 | UTC 五字段解析 + next-run + 持久化任务/结果 + `asyncio.wait_for` 180s 硬中断 | `governance/scheduler.py` |
| Coordinator 多 Agent | 决策表驱动顺序/并行 worker + `Semaphore` 限并发 + worker 独立 session 上下文隔离 + 结果持久化 | `multiagent/coordinator.py` |
| 成本熔断 | `BudgetManager` 四维预算（Token/时间/工具次数/资源）实时记账 + 超限 `BUDGET_EXCEEDED` | `governance/budget.py`、`observability/exit_status.py` |
| 快照/回滚 | `SnapshotManager` 持久化外部引用 + 异步适配 Docker commit/restore/delete | `sandbox/snapshots.py`、`sandbox/docker.py` |
| Web Dashboard | 治理总览/回归/调度/Coordinator/凭证/快照视图 | `apps/web/src/App.tsx`、`api.ts` |
| Electron Desktop | context isolation + sandbox + 关闭 Node integration + 文件选择/通知 IPC + 终端经后端治理 API | `apps/desktop/main.cjs`、`preload.cjs` |

**关键设计偏差与修复**：

1. Coordinator 为进程内 asyncio + Semaphore，不是分布式队列；任务/结果模型不变，后续可替换 runner
2. PolicyEngine 规则 DSL 为受控声明式子集（roles/senders/tools/actions/level/argument_contains），未引入 OPA/CEL 以减少动态执行风险
3. Skill Improve 为确定性模板生成可审计替换内容并强制审批，避免未经验证模型内容覆盖 Skill
4. Credential vault 通过官方 CLI resolver 接入，不内嵌 SDK，复用本机登录态且避免 secret 落库
5. 事件共享用 SQLite polling 替代进程内队列，支持同库多实例，无外部 broker 跨主机能力
6. Electron 完成源码/依赖锁/语法检查/可分发目录打包，签名/公证/自动更新属于发布工程

**设计缺口闭环增量（2026-07-19）**：

| 缺口 | 实现 | 证据 |
| --- | --- | --- |
| SSH 沙箱 | OpenSSH argv 执行 + 严格 host key + 超时 + 远端 FsBridge + allowed roots | `sandbox/ssh.py`、`test_design_closure.py` |
| gVisor | Docker `runtime` 配置透传 `--runtime runsc` | `sandbox/docker.py` |
| 网络白名单 | HTTP(S) 主机通配符/CIDR 决策并接入 Web 工具 | `sandbox/network_policy.py` |
| MCP | stdio 生命周期 + 动态发现/注册/刷新/调用/清理 | `tools/mcp_client.py` |
| 内容安全 | 敏感内容外发阻断 + 工具结果与最终回答统一脱敏 | `security/content_safety.py` |
| 长输出管理 | 阈值截断 + 0600 私有制品落盘 + 预览引用 | `tools/output_manager.py` |
| 生命周期 Hook | 可配置事件命令 + fail-closed + SQLite 审计 | `hooks/executor.py` |
| Web 管理面 | 会话/消息 + Tool/MCP/Skill/Hook 资源控制台 | `apps/web/src/App.tsx` |

**验证标准达成**：角色权限控制；成本预算可熔断；Skill 自动归档/改进；定时任务执行；回归通过率质量门禁；轨迹可回放；多 Agent 协作；前端治理与指标；Desktop 桥接。

---

## 三、当前架构分层完成度

| 层级 | P1 | P2 | P3 | P4 | 最终状态 |
| --- | --- | --- | --- | --- | --- |
| **E 执行环境** | Local + FsBridge + PathValidator | Docker + hard_reset + snapshot | Local 执行确定性门禁 | SnapshotManager + SSH + gVisor + 网络白名单 | 三后端 + 快照回滚 + 网络隔离 |
| **T 工具接口** | 12 工具 + Registry + Policy + Search + check_fn | 并行执行接入 | session_search + 写后事件 | PolicyEngine/WriteApproval/Budget 前置拦截 + MCP + OutputManager | 治理前置 + MCP + 长输出制品化 |
| **C 上下文记忆** | 基础 System Prompt | ContextEngine + 压缩 + Caching + Skill + Memory | 跨会话索引 | Curator 自改进 | 可插拔引擎 + 渐进压缩 + 四层记忆 |
| **L 生命周期** | AgentLoop + Runtime + Layer 框架 | Checkpoint + Subagent | Quota/Suspend/PausePersist Layer | Cron + Coordinator | 统一 Layer 编排 + 多 Agent + 调度 |
| **O 可观测性** | Trajectory 记录 | exit_status 分类 | OTel + Trace + DecisionTrace + Insights + SSE | 成本与治理事件 + 跨实例轮询 | 双源轨迹 + 决策可解释 + Insights |
| **V 验证评估** | 未启动 | 未启动 | VerificationLayer + Reviewer + SelfReview + 报告分离 | 失败沉淀 + 回归门禁 | 有证据完成 + 回归资产 |
| **G 治理安全** | 未启动 | 敏感路径硬编码 | Quota + SecurityAudit | RBAC + PolicyEngine + Approval + Credential + Budget + ContentSafety | 全链路治理 |
| **S 状态存储** | 四表基础 | checkpoints + subagents | Trace/验证/审批表 | 审批/预算/回归/Curator/Cron/Coordinator/快照/事件流表 | SQLite 全量状态外置 |

---

## 四、验证结果汇总

### 4.1 测试

| 测试文件 | 覆盖范围 |
| --- | --- |
| `test_sandbox.py` | PathValidator、FsBridge、LocalBackend、DockerBackend、SSHBackend、网络策略 |
| `test_state.py` | SessionDB、TrajectoryStore、CheckpointManager |
| `test_tools.py` | 12 核心工具单元测试 |
| `test_tool_system.py` | ToolRegistry、ToolPolicy、ToolSearch、FootprintLadder、OutputManager |
| `test_engine.py` | AgentLoop、Layer、ErrorClassifier、Runtime |
| `test_context.py` | ContextEngine、压缩管线、PromptCaching、Skill、Memory |
| `test_integration.py` | 完整工作流、并行工具、沙箱隔离、错误恢复、轨迹回放 |
| `test_p2.py` | ContextEngine、压缩、Caching、Skill、Memory、Docker、Checkpoint、Subagent |
| `test_p3.py` | OTel、VerificationLayer、Reviewer、SelfReview、SecurityAudit、FTS5、Insights、API |
| `test_p4.py` | RBAC、PolicyEngine、Regression、Curator、WriteApproval、Credential、Cron、Coordinator、Budget、Snapshot |
| `test_design_closure.py` | SSH、gVisor、网络白名单、MCP、内容安全、长输出、Hook |

**当前结果**：`pytest tests/` **209 passed、1 skipped、0 failed**（11.38s）。`ruff check src tests` 0 问题；`mypy src` strict 0 问题。

### 4.2 前端与桌面

- Web：Vitest + TypeScript/Vite 生产构建 + Playwright Chromium E2E 全部通过；`npm audit` 0 vulnerability
- Desktop：main/preload 语法检查 + `electron-builder --dir` 可分发目录打包通过；`npm audit` 0 vulnerability

### 4.3 条件跳过与环境验收项

以下依赖外部环境，不以模拟测试替代：

- 真实 Docker daemon 的 commit/restore E2E（1 项条件跳过）
- 真实 Bitwarden/1Password 账户的凭证池 CI
- 真实模型 Token 成本与生产流量成功率
- SSH 远端验收目标
- Electron 代码签名/公证/自动更新

---

## 五、关键设计决策记录

| 决策 | 选择 | 理由 | 否定项 |
| --- | --- | --- | --- |
| 语言 | Python | LLM 工程、工具编排、异步执行和数据处理生态成熟 | TypeScript（ML 生态弱） |
| 存储 | SQLite 优先 | 结构化查询 + FTS5 + 并发 + 审计 + 零外部依赖 | PostgreSQL（部署重）、纯文件系统（查询弱） |
| 压缩 | 渐进式 | 先清理旧结果，再折叠长内容，最后才 LLM 摘要；成本逐步递增 | 单一 LLM 摘要（成本高）、滑动窗口（丢信息） |
| 工具数量 | 12 核心 + 渐进发现 | 最小工具原则，少而精 | 40+ 全量注入（决策分支多、出错率高） |
| Context Engine | 可插拔 | 上下文策略可扩展 | 固定管线（不可扩展） |
| 验证层 | 内置到执行流程 | 将验证从事后补充变成每轮质量门禁 | 仅离线批处理验证 |
| 配置 | YAML 驱动 | 声明式可审计、可复现 | 纯代码配置（不可审计） |
| Prompt Caching | system_and_3 | 75% 成本节省 + 缓存稳定性 | 无 caching（成本高） |
| Skill 注入 | 目录注入 + 按需加载 | 不设门槛，放进去就用；inject_schema 可选优化 | 全文注入（浪费 token） |
| 前端 | Vite + React + TypeScript | 先做轻量 Web Console，P4 复用到 Electron | 直接做完整低代码平台或桌面端 |
| 实时通道 | SSE 优先 | Agent run 是服务端事件流，SSE 简单稳定 | 一开始全量 WebSocket |
| 规则引擎 | 受控声明式子集 | 减少依赖和动态执行风险 | OPA/CEL（动态执行风险） |
| 事件共享 | SQLite polling | 支持同库多实例，零外部依赖 | 外部 broker（部署复杂） |

---

## 六、自研差异化清单

| 模块 | 说明 |
| --- | --- |
| VerificationLayer | 工具调用后自动 lint/type check/test + 质量门禁 |
| 并行工具执行 | `asyncio.gather` 并行多个 tool_call，按 `is_write_tool` 读写分离 |
| 两级 Skill 注入 | 目录注入（默认）+ 按需加载 + `inject_schema` 可选精准匹配 |
| 回归用例体系 | 失败案例自动去重沉淀为测试用例 + 通过率门禁 |
| 策略引擎 | `PolicyEngine` 统一合规规则管理（受控声明式 YAML） |
| 快照/回滚 | Docker commit 快照 + restore |
| 渐进式压缩 + 可插拔引擎融合 | 渐进式上下文压缩与可插拔 Context Engine 组合 |

---

## 七、遗留问题与后续方向

| 优先级 | 问题 | 临时规避 | 建议 |
| --- | --- | --- | --- |
| 中 | 无真实 Docker daemon 的 commit/restore E2E 证据 | 异步接口测试 + API 409 明确失败 | 发布环境验收 |
| 中 | Bitwarden/1Password 依赖已登录 CLI，未做真实账户 CI | env resolver 或注入测试 resolver | Secret-enabled CI |
| 中 | Coordinator/Cron 为单机进程，无法跨节点抢占 | 单实例 scheduler；SQLite 持久化恢复 | 分布式部署阶段 |
| 中 | 无 OTLP exporter，跨服务 Trace 不外发 | SQLite Trace API 查询 | P4 部署化 |
| 低 | 五字段 Cron 固定 UTC，无时区/DST 规则 | 在 task 中显式换算 UTC | 调度增强 |
| 低 | FTS5 缺失时搜索退化为 LIKE | 小数据量使用降级路径 | 打包阶段固定 SQLite 能力 |
| 低 | Web Console 无浏览器端 E2E 框架 | 构建 + API/SSE 自动测试 | 回归体系 |
| 低 | Electron 无签名/公证/自动更新 | 源码启动或内部构建 | 产品发布阶段 |

后续首要前置：在具备 Docker daemon、`bw`/`op` 登录态、真实模型 key 的受控环境运行外部依赖验收。扩展方向：为 EventBus/Coordinator/Scheduler 增加 Redis/NATS/队列 adapter，保持 SQLite 作为本地默认实现。安全要求：所有新工具继续通过 `ToolRegistry` 的 RBAC → PolicyEngine → WriteApproval → Budget 顺序，禁止绕过治理 API 直接执行系统命令。

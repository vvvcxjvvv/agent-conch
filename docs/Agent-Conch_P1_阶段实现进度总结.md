# Agent-Conch P1 阶段实现进度总结

> 阶段：P1 Workflow Agent  
> 目标成熟度：P1（固定流程 + 工具调用 + 基础日志 + 简单检查）  
> 基准文档：`agent-conch-design.md` 第六章 P1 阶段交付物

---

## 一、阶段总览

### 1.1 阶段定位与核心目标

P1 阶段定位为 **Workflow Agent**，核心目标是搭建 Agent-Conch 的最小可运行骨架：Observe-Think-Act 执行循环 + 12 核心工具 + SQLite 状态持久化 + Local 沙箱隔离。此阶段不追求上下文压缩、验证层、策略引擎等高级能力，而是确保"读取文件 → 修改 → 运行测试 → 回答"这一基础循环能稳定闭环。

### 1.2 周期

- 计划周期：2-3 周
- 实际完成：1 个开发会话

### 1.3 整体完成度

**95%** — P1 阶段所有设计交付物均已实现并通过测试验证，额外完成了 ErrorClassifier 基础版、TrajectoryStore、CLI 入口等设计文档中标注为 P2 的部分能力。

### 1.4 核心交付物完成情况总表

| 模块 | 设计要求 | 实现状态 | 完成度 |
| ---- | -------- | -------- | ------ |
| Agent Loop | Observe-Think-Act + forward_with_handling | ✅ 已完成 | 100% |
| Agent Runtime | RuntimeRegistry + BuiltinConchRuntime | ✅ 已完成 | 100% |
| 12 核心工具 | bash/read/write/edit/glob/grep/web_search/web_fetch/skill/ask_user/task_manage/tool_search | ✅ 已完成 | 100% |
| ToolPolicy | Allow/Deny + Sandbox Policy | ✅ 已完成 | 100% |
| ToolSearch | 渐进发现 + 自动阈值 | ✅ 已完成 | 100% |
| check_fn | 前置检查 + TTL 缓存 + 瞬态故障抑制 | ✅ 已完成 | 100% |
| SQLite 状态存储 | SessionDB 基础表 | ✅ 已完成 | 100% |
| Local 沙箱 + FS Bridge | 本地执行 + 文件操作抽象 | ✅ 已完成 | 100% |
| 基础 System Prompt | base + env + AGENTS.md 发现 | ✅ 已完成 | 100% |
| Layer 基础框架 | Layer 接口 + ExecutionLimitsLayer | ✅ 已完成 | 100% |

---

## 二、交付物逐项核对

| 模块 | 设计要求 | 实现状态 | 完成度说明 | 关联代码路径 |
| ---- | -------- | -------- | ---------- | ------------ |
| Agent Loop | Observe-Think-Act 循环 + forward_with_handling 错误降级 | ✅ 已完成 | 循环逻辑完整：auto-compact check(P1占位) → Layer.on_graph_start → assemble context → stream model → parallel tool execution → Layer.on_node_run_end → trajectory record。forward_with_handling 实现 retry/requery/compact/abort 四种恢复策略 | `src/agent_conch/engine/agent_loop.py` |
| Agent Runtime 可插拔 | RuntimeRegistry + BuiltinConchRuntime | ✅ 已完成 | AgentRuntime ABC + RuntimeRegistry register/select + BuiltinConchRuntime 使用 AgentLoop | `src/agent_conch/engine/runtime/types.py`, `builtin.py` |
| 12 核心工具 | bash/read_file/write_file/edit_file/glob/grep/web_search/web_fetch/skill/ask_user/task_manage/tool_search | ✅ 已完成 | 12 个工具全部实现，每个继承 BaseTool，使用 Pydantic input_model，通过 FsBridge/SandboxBackend 访问资源 | `src/agent_conch/tools/core/*.py` |
| ToolPolicy | Allow/Deny + Sandbox Policy 三层 | ✅ 已完成 | Allow/Deny 显式列表 + Sender Policy (subagent 限制) + Sandbox Policy (never 模式禁 exec) + 自定义规则引擎 | `src/agent_conch/tools/tool_policy.py` |
| ToolSearch | 渐进发现 + 自动阈值 | ✅ 已完成 | 核心工具始终暴露，非核心工具按关键词搜索，自动阈值基于 context window 10% | `src/agent_conch/tools/tool_search.py` |
| check_fn | 前置检查 + TTL 缓存(30s) + 瞬态故障抑制(60s) | ✅ 已完成 | ToolHealthState 管理 check_fn 缓存 + 连续失败计数 + suppress_until 抑制时间 | `src/agent_conch/tools/registry.py` |
| SQLite 状态存储 | SessionDB 基础表 | ✅ 已完成 | sessions/messages/turns/trajectories 四张表 + CRUD + 跨连接持久化验证 | `src/agent_conch/state/session_db.py` |
| Local 沙箱 + FS Bridge | 本地执行 + 文件操作抽象 | ✅ 已完成 | FsBridge ABC(stat/read/write/rename/delete/list_dir/makedirs) + LocalFsBridge + LocalBackend(execute) + PathValidator + SandboxRegistry | `src/agent_conch/sandbox/*.py` |
| 基础 System Prompt | base + env + AGENTS.md 发现 | ✅ 已完成 | BASE_SYSTEM_PROMPT 定义 Agent 身份/原则/工具说明 + env info 注入 + AGENTS.md 从 cwd 向上遍历发现 | `src/agent_conch/prompts/system_prompt.py`, `agents_md.py` |
| Layer 基础框架 | Layer 接口 + ExecutionLimitsLayer | ✅ 已完成 | Layer ABC(5个钩子) + LayerManager(顺序执行) + ExecutionLimitsLayer(max_turns/max_time) | `src/agent_conch/engine/layers/base.py`, `execution_limits.py` |

---

## 三、架构分层完成度总览

| 层级 | 层级名称 | 本阶段计划能力 | 实际覆盖情况 | 核心差异 |
| ---- | -------- | -------------- | ------------ | -------- |
| E | 执行环境与沙箱 | Local 沙箱 + FS Bridge + PathValidator | ✅ 完整覆盖 | 无偏差 |
| T | 工具接口层 | 12 核心工具 + ToolRegistry + ToolPolicy + ToolSearch + check_fn | ✅ 完整覆盖 | 额外实现了 FootprintLadder |
| C | 上下文与记忆层 | 基础 System Prompt（无 Context Engine / Prompt Caching / auto-compact） | ⚠️ 部分覆盖 | System Prompt + AGENTS.md 已实现；Context Engine / 压缩 / Caching 留待 P2 |
| L | 生命周期与编排 | Agent Loop + Runtime + Layer 框架 + ExecutionLimitsLayer | ✅ 完整覆盖 | 额外实现了 ErrorClassifier 基础版(15种) |
| O | 可观测性层 | 基础 Trajectory 记录 | ⚠️ 部分覆盖 | TrajectoryStore + JSONL 导出 + 回放已实现；OTel/Insights 留待 P3 |
| V | 验证与评估层 | 未计划 | ❌ 未启动 | P3 阶段实现 |
| G | 治理与安全层 | 未计划 | ❌ 未启动 | P2/P4 阶段实现 |
| S | 状态存储 | SQLite SessionDB 基础表 | ✅ 完整覆盖 | 额外实现了 TrajectoryStore + CheckpointManager 占位 |

---

## 四、关键设计偏差说明

### 偏差 1：C 层未实现可插拔 Context Engine

- **偏差点描述**：P1 直接从 SessionDB 加载消息列表作为上下文，未实现 ContextEngine ABC 和 LegacyEngine
- **原始设计方案**：设计文档 3.2 C 层要求可插拔 Context Engine，P2 阶段完整实现
- **实际实现方案**：AgentLoop._call_model() 直接调用 self.db.get_messages_as_dicts() 组装消息，加 system prompt 前缀
- **偏差原因**：P1 阶段优先保证基础循环闭环，Context Engine 属于 P2 交付物，提前实现会增加复杂度
- **影响范围**：无上下文压缩/记忆分层/Prompt Caching 能力，长对话可能超出 context window
- **后续修复计划**：P2 阶段实现 ContextEngine ABC + LegacyEngine + 渐进式压缩

### 偏差 2：ErrorClassifier 仅实现 15 种错误分类

- **偏差点描述**：设计文档要求 20+ 种错误分类，实际实现 15 种
- **原始设计方案**：20+ 种 FailoverReason，含 SSL_CERT_VERIFICATION 等不重试类型
- **实际实现方案**：15 种基础错误（API 超时/限流/认证/内容策略/连接 + 工具错误 + 上下文窗口 + 权限 + 格式 + 成本 + 未知）
- **偏差原因**：P1 阶段的核心循环不需要全部错误类型，基础分类已足够覆盖常见场景
- **影响范围**：部分边缘错误（SSL 证书、沙箱不可用等）会被归类为 UNKNOWN
- **后续修复计划**：P2 阶段扩展到 20+ 种

### 偏差 3：SandboxRegistry NON_MAIN/ALWAYS 模式退化为 Local

- **偏差点描述**：设计文档要求 NON_MAIN 模式下子会话使用沙箱后端，P1 全部退化为 LocalBackend
- **原始设计方案**：NON_MAIN 模式：主会话 local，子会话 docker；ALWAYS 模式：始终 docker
- **实际实现方案**：所有模式都返回 LocalBackend（Docker 后端在 P2 实现）
- **偏差原因**：P1 不包含 Docker 沙箱后端（设计文档将 Docker 列为 P2 交付物）
- **影响范围**：子 Agent 执行无容器隔离（但 PathValidator 仍提供路径级安全）
- **后续修复计划**：P2 阶段实现 DockerBackend

### 偏差 4：TrajectoryStore.save_step 为同步方法

- **偏差点描述**：设计文档中轨迹保存是异步流程的一部分，但 save_step 实现为同步方法
- **原始设计方案**：Agent Loop 中 `await self.trajectory.save_step(...)` 异步保存
- **实际实现方案**：save_step 是同步方法（内部调用同步的 SQLite 操作），Agent Loop 中直接调用不加 await
- **偏差原因**：SQLite stdlib 是同步 API，P1 阶段为简化实现直接同步调用。SQLite 单写者模型下性能可接受
- **影响范围**：大量轨迹写入可能短暂阻塞事件循环（P1 阶段不构成问题）
- **后续修复计划**：P2 可切换到 aiosqlite 或用 asyncio.to_thread 包装

---

## 五、验证结果汇总

### 5.1 设计文档验证标准达成情况

| 验证标准 | 达成情况 | 说明 |
| -------- | -------- | ---- |
| 能完成「读取文件 → 修改 → 运行测试 → 回答」循环 | ✅ 达成 | `test_read_modify_test_answer_cycle` 集成测试验证完整循环 |
| SQLite 持久化 | ✅ 达成 | `test_persistence_across_connections` 验证跨连接持久化 |
| 沙箱隔离生效 | ✅ 达成 | `test_sandbox_isolation` 验证敏感路径被 PathValidator 拦截 |

### 5.2 测试通过率

| 测试类别 | 测试文件 | 测试数 | 通过 | 失败 |
| -------- | -------- | ------ | ---- | ---- |
| 沙箱 (E层) | test_sandbox.py | 20 | 20 | 0 |
| 状态存储 (S层) | test_state.py | 16 | 16 | 0 |
| 核心工具 (T层) | test_tools.py | 17 | 17 | 0 |
| 工具系统 (T层) | test_tool_system.py | 20 | 20 | 0 |
| 引擎 (L层) | test_engine.py | 20 | 20 | 0 |
| 集成测试 | test_integration.py | 5 | 5 | 0 |
| **总计** | **6 个文件** | **98** | **98** | **0** |

### 5.3 关键指标

| 指标 | 数值 |
| ---- | ---- |
| 源代码文件 | 53 个 (.py) |
| 源代码行数 | 4,641 行 |
| 测试代码行数 | 1,353 行 |
| 测试覆盖率（文件级） | 6/6 模块全覆盖 |
| 测试通过率 | 100% (98/98) |
| 核心工具数 | 12 个 |
| SQLite 表数 | 4 张 (sessions/messages/turns/trajectories) |

### 5.4 集成测试验证场景

1. **完整工作流**：read_file → edit_file → bash(pytest) → 文本回答 ✅
2. **并行工具执行**：同时 read_file 两个文件 ✅
3. **沙箱隔离**：read_file("/etc/passwd") 被 PathValidator 拦截 ✅
4. **错误恢复**：LLM 超时 → retry → 成功 ✅
5. **轨迹回放**：DB 回放 + JSONL 导出 + 文件回放 ✅

---

## 六、遗留问题与技术债

### 高优先级

| # | 问题描述 | 影响范围 | 临时规避 | 建议修复阶段 |
| - | -------- | -------- | -------- | ------------ |
| 1 | C 层无上下文压缩，长对话会超出 context window | 长任务（>50轮）会失败 | 限制 max_turns | P2 |
| 2 | 无 Prompt Caching，每轮重复发送 system prompt + 工具 schema | Token 成本高 | 无 | P2 |
| 3 | SandboxRegistry NON_MAIN 模式退化为 Local | 子 Agent 无容器隔离 | PathValidator 提供路径级保护 | P2 |

### 中优先级

| # | 问题描述 | 影响范围 | 临时规避 | 建议修复阶段 |
| - | -------- | -------- | -------- | ------------ |
| 4 | ErrorClassifier 仅 15 种错误类型 | 边缘错误归类为 UNKNOWN | CONTINUE 策略兜底 | P2 |
| 5 | TrajectoryStore.save_step 同步调用 | 大量轨迹写入阻塞事件循环 | P1 阶段不构成问题 | P2 |
| 6 | SkillTool 为简化版，未实现 Schema-based selective injection | Skill 全文加载 | 无 | P2 |
| 7 | AskUserTool 默认回调使用 input()，不适合 Web 场景 | 仅 CLI 可用 | Web 模式需设置回调 | P3 |

### 低优先级

| # | 问题描述 | 影响范围 | 临时规避 | 建议修复阶段 |
| - | -------- | -------- | -------- | ------------ |
| 8 | WebSearchTool 使用 DuckDuckGo HTML 解析，依赖页面结构 | 搜索结果可能不稳定 | 无 | P3 |
| 9 | CheckpointManager 仅为占位 | 无 Pause/Resume 能力 | 无 | P2 |
| 10 | 无 MCP 客户端实现 | 不能接入 MCP 工具 | 无 | P2 |
| 11 | Windows 路径兼容性（resolve 行为差异）已修复但需持续关注 | 跨平台路径安全 | 已通过原始字符串模式匹配修复 | 持续维护 |

---

## 七、下一阶段前置建议

### 7.1 本阶段沉淀的可复用能力

1. **BaseTool + ToolRegistry 框架**：P2 新增工具只需继承 BaseTool 并注册，无需修改 Agent Loop
2. **Layer 插件体系**：P2/P3 新增 Layer（LLMQuotaLayer/VerificationLayer 等）只需继承 Layer 并添加到 LayerManager
3. **FsBridge 抽象**：P2 实现 DockerBackend 时只需实现 FsBridge 接口，工具层无需修改
4. **SessionDB schema**：P2 新增表（checkpoints/subagents 等）只需追加 DDL，不影响现有表
5. **ConchConfig YAML 加载**：P2 新增配置项只需在 dataclass 中添加字段

### 7.2 下一阶段（P2）的依赖条件与风险

**依赖条件**：
- P1 的 AgentLoop / ToolRegistry / SessionDB / FsBridge 框架必须稳定
- P1 的测试套件作为 P2 回归基线

**风险**：
- P2 引入 Context Engine 后，AgentLoop 的上下文组装逻辑需要重构（从直接 DB 读取改为通过 ContextEngine.assemble）
- P2 引入 Docker 沙箱后，需要确保 FsBridge 接口在 Docker 后端下行为一致
- P2 引入 Subagent 后，ToolPolicy 的 sender 策略需要实际生效（P1 仅框架，未接入子 Agent）

### 7.3 架构与技术栈调整建议

1. **Context Engine 接入点**：AgentLoop._call_model() 中的 `self.db.get_messages_as_dicts(session_id)` 替换为 `await self.context_engine.assemble(session_id, budget)`
2. **Prompt Caching 接入点**：AgentLoop._call_model() 中组装消息后添加 `messages = self.prompt_caching.apply(messages)`
3. **auto-compact 接入点**：AgentLoop.run() 循环开头添加 `await self.context_engine.maintain(session_id, self.messages)`
4. **aiosqlite 迁移**：如果 P2 的异步场景需要非阻塞 DB 操作，可将 SessionDB 底层从 sqlite3 切换到 aiosqlite（接口不变）
5. **Docker 后端**：实现 DockerBackend(SandboxBackend) + DockerFsBridge(FsBridge)，注册到 SandboxRegistry

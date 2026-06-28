# AgentConch v2 实现状态

> **版本**：v2.0 — 阶段一 MVP
> **最后更新**：2026-06-28
> **技术方案**：`docs/technical-design-v2.md`
> **功能与验证手册**：`docs/demo-validation-v2.md`

---

## 总体状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| 阶段一 MVP | ✅ **已完成** | core 改造 + adapters + FastAPI + Next.js 前端 + 测试通过 |
| 阶段二 生产加固 | ✅ **已完成** | 默认 LangGraph 主路径已接入工具护栏 / CostGuard / 治理审计 / HITL 原地恢复 / Mem0 记忆增强 / LlamaGuard / 检索护栏 / Langfuse trace |
| 阶段三 开发者后台 | ⏳ 未开始 | DeepEval + Profile A/B + trace diff |
| 阶段四 多 Agent + 治理 | ⏳ 未开始 | LangGraph Supervisor + RBAC + 审计 |

---

## 阶段一 MVP 完成清单

### Step 0: 清理 v1 + 骨架迁移 ✅

- [x] 删除 `conch/domains/`（9 域 18 文件）
- [x] 删除 `conch/web/`（静态 HTML 前端）
- [x] 删除 `conch/runtime/model/scripted.py`、`conch/runtime/store/memory_store.py`
- [x] 删除 `tests/`（旧测试）
- [x] 迁移 `conch/core/` 8 文件 → `backend/conch/core/`
- [x] 迁移 `conch/runtime/sandbox/` → `backend/conch/runtime/sandbox/`
- [x] 迁移 5 个可复用文件 → `backend/conch/adapters/`（jit_compaction / notes_file / builtin_shell / single_loop / console_tracer）
- [x] 新建目录骨架：`backend/conch/{api,adapters,core,runtime}` + `frontend/` + `backend/{profiles,plugins,guardrail_configs}`

### Step 1: core 改造（可扩展层）✅

- [x] `extension.py`：新增 `GuardrailProvider` Protocol + `GuardrailResult` dataclass；`DOMAINS` 加 `"guardrail"`（第 10 域）
- [x] `cost_guard.py`：从 `loop.py` 拆出 `TaskStatus` / `DegradeLevel` / `State` / `CostGuard`；`State` 加 `hook_bus` / `profile` 字段
- [x] `hook_bridge.py`：新建 `LangGraphHookBridge`，回调事件 → 语义 Hook 映射（on_llm_start→pre_model_call 等）
- [x] `guardrail_pipeline.py`：新建 `GuardrailPipeline` + `GuardrailMiddleware`，input/output 两路管道
- [x] `__init__.py`：更新导出（移除 AgentLoop，新增 guardrail/hook_bridge/guardrail_pipeline）
- [x] `loop.py`：删除（AgentLoop 降级到 `adapters/orchestration/single_loop.py`）
- [x] `registry.py` / `hooks.py` / `middleware.py` / `profile.py` / `experiment.py`：直接复用，零改动

### Step 2: adapters 实现（成熟框架底座层）✅

**新建 6 个 adapter**：
- [x] `adapters/llm/litellm_provider.py` — `LiteLLMProvider`：litellm.acompletion 统一接入，流式 + tool_calls 解析
- [x] `adapters/orchestration/langgraph_react.py` — `LangGraphReActOrchestrator`：包装 create_react_agent，astream_events + Hook 桥接
- [x] `adapters/tool/mcp_provider.py` — `MCPToolProvider`：连接 MCP server，工具发现 + 执行，转 LangChain Tool
- [x] `adapters/guardrail/nemo_guardrails.py` — `NemoGuardrail`：实现 GuardrailProvider 三方法，NeMo + 关键词兜底
- [x] `adapters/observability/langfuse_tracer.py` — `LangfuseTracer`：trace/cost/指标，Langfuse callback
- [x] `adapters/information/agents_md.py` — `AgentsMdProvider`：读取 AGENTS.md 作系统提示

**迁移改造 5 个文件**：
- [x] `adapters/orchestration/single_loop.py` — 重写为自包含编排，用 LiteLLMProvider 替代 v1 model 接口
- [x] `adapters/tool/builtin_shell.py` — 迁移（import 路径已正确）
- [x] `adapters/observability/console_tracer.py` — 迁移（MVP 默认可观测）
- [x] `adapters/context/jit_compaction.py` — 迁移
- [x] `adapters/memory/notes_file.py` — 迁移（MVP 记忆降级实现）

### Step 3: API 层（FastAPI）✅

- [x] `api/deps.py` — 依赖注入：`build_runtime(profile)` 按 Profile 构建 Plugin + State + guardrail_pipeline
- [x] `api/sse.py` — SSE 事件格式化 + 事件类型常量
- [x] `api/routes/chat.py` — `POST /api/chat/sessions/{id}/stream` SSE 流式对话
- [x] `api/routes/session.py` — 会话 CRUD
- [x] `api/routes/profile.py` — Profile 列表/详情
- [x] `api/routes/plugin.py` — 插件查询
- [x] `api/__init__.py` — FastAPI app + CORS + 路由挂载 + 健康检查

### Step 4: Frontend（Next.js 三栏）✅

- [x] `app/layout.tsx` + `app/page.tsx` — 三栏布局根
- [x] `components/chat/Sidebar.tsx` — 左栏：会话列表 + Profile 选择器
- [x] `components/chat/Conversation.tsx` — 中栏容器
- [x] `components/chat/MessageList.tsx` — 流式渲染 + 工具卡片 + 护栏提示
- [x] `components/chat/ToolCard.tsx` — 可折叠工具调用卡片（参数/结果/耗时）
- [x] `components/chat/GuardrailBanner.tsx` — 护栏拦截提示
- [x] `components/chat/InputBox.tsx` — 输入框（Enter 发送）
- [x] `components/metrics/MetricsPanel.tsx` — 右栏：token/cost/步数/护栏/模型
- [x] `lib/store.ts` — zustand 状态管理
- [x] `lib/sse-client.ts` — SSE 流式解析 + 事件分发
- [x] `lib/api.ts` — REST API 封装

### Step 5: 联调与验证 ✅

- [x] `backend/profiles/user-chat-v1.yaml` — MVP demo Profile
- [x] `backend/guardrail_configs/chat/` — NeMo 配置（config.yml + rails.co）
- [x] `benchmarks/mvp-tasks.md` — 5 个预设任务
- [x] `backend/tests/test_core.py` — 21 项单元测试全部通过

### Step 6: 依赖配置与文档 ✅

- [x] `backend/pyproject.toml` — 后端依赖（FastAPI/LangGraph/MCP/litellm/NeMo/Langfuse/Pydantic）
- [x] `frontend/package.json` — 前端依赖（Next.js 14/TS/Tailwind/zustand）
- [x] `AGENTS.md` — 更新为 v2 架构（10 域 + adapters + 成熟框架底座）
- [x] `docs/implementation-status-v2.md` — 本文档

---

## 阶段二 完成项

- [x] `State.runtime_events`：新增运行时事件队列，承接护栏与成本事件
- [x] `api/deps.py`：默认运行时 Hook 装配完成
- [x] `pre_tool`：工具护栏中断默认 LangGraph 主路径
- [x] `post_model_call`：usage 计账 + CostGuard 分级检查
- [x] `on_cost_exceeded`：成本事件回传 + L4 终止
- [x] `post_step`：observability trace 挂接完成
- [x] `governance`：`allowlist_perms` 最小权限 + JSONL 审计日志
- [x] `pre_tool`：治理校验优先于工具护栏，拒绝时回传 `governance` 层拦截事件
- [x] `core/hook_bridge.py`：工具参数标准化，Hook 可拿到结构化 args
- [x] `api/routes/chat.py`：SSE 追加 `guardrail` / `cost_update` / `hitl_request` 事件透传
- [x] `api/routes/websocket.py`：会话级 HITL WebSocket，支持 `approve` / `deny`
- [x] 前端待审批面板 + WebSocket 客户端：批准后原地恢复同一任务
- [x] `memory`：`mem0` adapter 接入，未安装 Mem0 时回退本地 JSONL 持久化
- [x] `api/routes/chat.py`：构图前按当前任务召回记忆并注入系统提示；回合成功结束后持久化 user/assistant 内容
- [x] `guardrail`：新增 `llamaguard_only` 二级分类器 + `stacked_guardrails` 组合 provider
- [x] `pre_model_call`：默认运行时输入护栏已接线，可在模型调用前中断危险输入
- [x] `post_model_call`：输出分类命中时回传 `output` 层 guardrail 事件
- [x] `chat`：检索护栏完成，召回记忆会按相关度排序并过滤低相关/敏感内容
- [x] `audit`：guardrail 事件统一写入治理审计与 observability event
- [x] `api/routes/chat.py` + 前端 SSE：审批后支持任务内原地恢复，不重复提交用户消息
- [x] `memory`：`mem0` fallback recall 增加语义排序与 long_term / procedural 支持
- [x] `observability`：新增 `stacked_tracer`，组合 `console_tracer + langfuse_tracer`

---

## 测试验证结果

### core 单元测试（25/25 通过）

| 测试 | 验证内容 |
|---|---|
| `test_domains_includes_guardrail` | DOMAINS 含 guardrail（第 10 域） |
| `test_guardrail_result_dataclass` | GuardrailResult 字段正确 |
| `test_state_has_hook_bus_field` | State 有 hook_bus / profile 字段 |
| `test_cost_guard_levels` | CostGuard 分级降级（60%→L1, 80%→L2, 100%→L4） |
| `test_guardrail_pipeline_blocks` | GuardrailPipeline 拦截 blocked 输入 |
| `test_hook_bridge_exists` | LangGraphHookBridge 回调方法完整 |
| `test_profile_loader_resolves_profile_relative_paths` | Profile 相对路径归一化正确 |
| `test_registry_registers_adapters` | 16 个 adapter 全部注册成功 |
| `test_zero_code_extension` | 核心 0 改动接入新插件验证 |
| `test_state_runtime_events_queue` | 运行时事件队列可缓存/清空 |
| `test_runtime_hooks_block_tool_and_emit_guardrail_event` | `pre_tool` 默认 Hook 会拦截危险工具并产出护栏事件 |
| `test_runtime_hooks_block_tool_by_governance_and_write_audit` | `pre_tool` 默认 Hook 会执行最小权限校验并写审计日志 |
| `test_approval_manager_consumes_one_time_grant` | 审批通过后只放行一次相同 tool+args |
| `test_runtime_hooks_emit_hitl_request_for_approval_tool` | 需要审批的工具会发出 `hitl_request` 并中断 |
| `test_runtime_hooks_record_usage_and_emit_cost_update` | `post_model_call` 默认 Hook 会累计 usage 并产生成本事件 |
| `test_mem0_memory_provider_fallback_store_and_recall` | `mem0` adapter 未安装真实 Mem0 时会回退到 JSONL 持久化并可重新召回 |
| `test_build_memory_context_appends_recalled_memory` | 对话系统提示会追加召回出的 Relevant memory 上下文 |
| `test_runtime_hooks_store_pending_resume_on_hitl_request` | 需要审批时会缓存可恢复任务上下文 |
| `test_mem0_memory_provider_ranks_semantic_matches` | fallback recall 会按语义相关度排序 |
| `test_build_memory_context_filters_sensitive_memory` | 检索护栏会过滤敏感记忆内容 |
| `test_stacked_tracer_fanout_metrics_and_events` | 组合 tracer 会扇出 trace 与 event 记录 |
| `test_llamaguard_only_blocks_by_category` | LlamaGuard 二级分类器会按风险类别拦截输入 |
| `test_stacked_guardrails_chain_input_checks` | 组合护栏会按顺序执行 NeMo → LlamaGuard |
| `test_runtime_hooks_block_input_and_emit_guardrail_event` | `pre_model_call` 默认 Hook 会拦截危险输入并回传 input guardrail 事件 |
| `test_runtime_hooks_emit_output_guardrail_event` | `post_model_call` 输出分类命中时会回传 output guardrail 事件 |

### adapters 注册验证

```
llm:           ['litellm']
orchestration: ['langgraph_react', 'single_loop']
tool:          ['mcp_provider', 'builtin_shell']
guardrail:     ['nemo_guardrails', 'llamaguard_only', 'stacked_guardrails']
observability: ['langfuse_tracer', 'console_tracer', 'stacked_tracer']
information:   ['agents_md']
context:       ['jit_compaction']
memory:        ['mem0', 'notes_file']
governance:    ['allowlist_perms']
```

---

## 退出标准达成情况

| 退出标准 | 状态 | 说明 |
|---|---|---|
| 真实 LLM 完成 5 预设任务，成功率 ≥ 60% | ⏳ 待联调 | 架构就绪，需安装依赖 + 配置 LLM API 后端到端验证 |
| SSE 首 token 延迟 < 500ms | ⏳ 待联调 | LangGraph astream_events 原生流式，架构支持 |
| 工具调用在 UI 可见 | ✅ | ToolCard 组件已实现，SSE 事件类型区分 |
| NeMo 护栏拦截 3 个有害输入 | ✅ | 关键词兜底已实现，NeMo 配置就绪 |
| 核心 0 改动接入 1 个新插件 | ✅ | `test_zero_code_extension` 验证通过 |

---

## MVP 简化策略（已实施）

| 组件 | MVP 实现 | 阶段二补全 |
|---|---|---|
| 记忆 | `mem0` adapter + 本地 JSONL fallback + 语义排序 | 真实 Mem0 向量后端增强 |
| Store | 内存 dict | PostgreSQL + Chroma + Redis |
| 可观测 | `stacked_tracer`（console + langfuse） | 外部部署后的全链路联调 |
| 评测 | 不做 | DeepEval CI 流水线 |
| 护栏 | NeMo + LlamaGuard + 检索护栏 + 审计 | 更细粒度分类/策略中心 |
| HITL | WebSocket 审批 + 前端待审批面板 + 原地恢复 | 后续可补任务级状态机恢复 |
| LLM | litellm 统一接入（本地/国内模型） | 多模型 + fallback |

---

## 关键文件清单

### 核心层（backend/conch/core/，9 文件）
- `extension.py` — 10 域 ExtensionPoint 契约（含 GuardrailProvider）
- `registry.py` — 注册中心（直接复用）
- `hooks.py` — Hook 总线 14 挂载点（直接复用）
- `middleware.py` — Pipeline 数据流（直接复用）
- `profile.py` — Profile 引擎（直接复用）
- `experiment.py` — 实验框架（直接复用）
- `cost_guard.py` — CostGuard + State（从 loop.py 拆出）
- `hook_bridge.py` — LangGraph 事件→Hook 桥接（新建）
- `guardrail_pipeline.py` — 六层护栏管道（新建）

### 适配层（backend/conch/adapters/，16 文件）
- `llm/litellm_provider.py` / `orchestration/{langgraph_react,single_loop}.py`
- `tool/{mcp_provider,builtin_shell}.py` / `guardrail/{nemo_guardrails,llamaguard,stacked_guardrails}.py`
- `governance/allowlist.py`
- `observability/{langfuse_tracer,console_tracer,stacked_tracer}.py` / `information/agents_md.py`
- `context/jit_compaction.py` / `memory/{mem0_provider,notes_file}.py`

### API 层（backend/conch/api/，9 文件）
- `__init__.py` / `deps.py` / `sse.py` / `hitl.py` / `routes/{chat,session,profile,plugin,websocket}.py`

### 前端（frontend/）
- `app/{layout,page}.tsx` / `components/{chat/*,metrics/*}` / `lib/{store,sse-client,ws-client,api}.ts`

### 配置
- `backend/profiles/user-chat-v1.yaml` / `backend/guardrail_configs/chat/{config.yml,rails.co}`
- `backend/pyproject.toml` / `frontend/package.json` / `AGENTS.md`

---

## 下一步（阶段三）

1. 安装依赖 + 配置 LLM API / Langfuse，跑通真实端到端 demo
2. 接入 DeepEval CI 流水线
3. 启动 Profile A/B 与 trace diff
4. 继续推进阶段三开发者后台

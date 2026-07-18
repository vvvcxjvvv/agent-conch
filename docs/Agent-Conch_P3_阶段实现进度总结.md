# Agent-Conch P3 阶段实现进度总结

> 阶段：P3 Auditable Harness  
> 基准：`plan/agent-conch-design.md` 第六章 P3 交付物  
> 前置：[P2 阶段总结](Agent-Conch_P2_阶段实现进度总结.md)  
> 验收日期：2026-07-18

## 一、阶段总览

P3 的目标是达到 H3“有证据的完成”：完整 trace、失败归因、确定性验证、验证协议与验证报告。设计计划周期为 3–4 周；仓库没有记录开发起始日期，实际周期不作推断。本次增量实现不覆盖 P1/P2 内容。

**整体完成度：100%（代码与自动化闭环）**。12 项交付物均有运行时接线和自动化证据；真实模型供应商调用与 Docker daemon 依赖外部环境，不计为本地自动化失败。

| 交付物 | 状态 | 证据 |
| --- | --- | --- |
| GraphEngine Layer 体系 | 已完成 | `engine/layers/llm_quota.py`、`engine/layers/suspend.py` |
| OTel ObservabilityLayer | 已完成 | `observability/otel.py`、`trace_store.py`、`decision_trace.py` |
| VerificationLayer | 已完成 | `verification/layer.py`、`report.py` |
| Reviewer 评审 | 已完成 | `verification/reviewer.py`、`POST /review` |
| review_on_submit 自审 | 已完成 | `verification/self_review.py`、`ConchEngine.run()` |
| 验证报告分离 | 已完成 | `VerificationReport.agent_claim/checks` |
| FTS5 跨会话搜索 | 已完成 | `tools/core/session_search.py` |
| Security Audit | 已完成 | `security/audit.py` |
| Trajectory 回放 | 已完成 | `state/trajectory.py`、`conch replay`、API |
| Insights 报告 | 已完成 | `observability/insights.py` |
| Webhook / API Server | 已完成 | `api/server.py`、`conch serve` |
| React Web Console | 已完成 | `apps/web/`，深海青蓝三栏工作台，含“决策轨迹”页签与 Markdown/源文本切换，生产构建通过 |

## 二、交付物逐项核对

| 模块 | 设计要求 | 实现状态 | 完成度说明 | 关联代码路径 |
| --- | --- | --- | --- | --- |
| GraphEngine Layer | Quota/Suspend/PausePersist | 已完成 | LayerManager 按 YAML 装配；配额事件可中止 Graph；暂停写 Checkpoint | `src/agent_conch/engine/layers/` |
| OTel | 原生 span + 节点 parser | 已完成 | graph/node/event span；NodeTypeParser 归类 model/tool/action；Decision Trace 提供可审计决策摘要 | `src/agent_conch/observability/` |
| Verification | 写后 lint/type/test + 门禁 | 已完成 | write/edit 成功后串行执行配置命令；首个失败即注入修复消息 | `src/agent_conch/verification/layer.py` |
| Reviewer | 多次尝试 + LLM 选优 | 已完成 | 接收候选集，LLM JSON 评审；异常时确定性启发式降级 | `src/agent_conch/verification/reviewer.py` |
| 自审 | 提交前自动自审 | 已完成 | 完成态返回前执行确定性自审，失败改写为 error | `src/agent_conch/verification/self_review.py` |
| 报告分离 | Agent 自述 vs 服务验证 | 已完成 | agent_claim 与 checks/passed 分字段持久化 | `src/agent_conch/verification/report.py` |
| 历史搜索 | session_search + FTS5 | 已完成 | 每个完成会话幂等索引；FTS5 不可用降级 LIKE | `src/agent_conch/context/memory/manager.py` |
| 安全审计 | 多维审计 + 危险配置 | 已完成 | 密钥、沙箱、根目录、公开 API、空门禁、无效配额、不安全模型端点 | `src/agent_conch/security/audit.py` |
| 回放 | 文件结构化回放 | 已完成 | SQLite/JSONL 双来源；CLI 与 API 展示 | `src/agent_conch/state/trajectory.py` |
| Insights | 成功率/失败分布/成本 | 已完成 | session 状态、Token、工具耗时、工具失败聚合 | `src/agent_conch/observability/insights.py` |
| API | HTTP 入口 | 已完成 | run/webhook、决策轨迹、执行轨迹、Trace、验证、搜索、审计、Insights、评审、审批、SSE | `src/agent_conch/api/server.py` |
| Web Console | 观察/工具/回放/审批 | 已完成 | 三栏工作台布局；SSE 时间线、决策轨迹、执行轨迹/Trace/验证页签、Markdown/源文本回答、审批、安全和指标 | `apps/web/src/App.tsx` |

## 三、架构分层完成度总览

| 层级 | 层级名称 | 本阶段计划能力 | 实际覆盖情况 | 核心差异 |
| --- | --- | --- | --- | --- |
| E | 执行环境与沙箱 | 验证命令执行基础 | LocalBackend 执行确定性门禁 | Docker 真实守护进程测试仍条件跳过 |
| T | 工具接口层 | session_search、写后事件 | 新增非核心搜索工具；写工具结果触发 V 层 | MCP 不属于当前 P3 设计表，未新增 |
| C | 上下文与记忆 | 跨会话索引 | 完成会话幂等写入 MetaMemory | FTS5 缺失时降级 LIKE |
| L | 生命周期与编排 | 三类 Layer、事件接线 | 配额、暂停恢复、事件总线均接入 AgentLoop | Suspend 为进程内信号，状态由 Checkpoint 持久化 |
| O | 可观测层 | OTel、归因、Insights | OTel/SQLite 双写、节点归类、Decision Trace、统计 API | Decision Trace 是可解释性增强；未配置远端 OTel exporter |
| V | 验证与评估层 | 门禁、评审、自审、报告 | 运行链路完整 | 自审默认确定性，避免额外模型调用导致结果不稳定 |
| G | 治理与安全层 | 配额、安全审计 | 多维规则扫描与 quota abort | RBAC/PolicyEngine 按设计留在 P4 |
| S | 状态存储层 | Trace/验证/审批持久化 | SQLite 新增 Trace/Decision Trace/验证/审批表，Trajectory 沿用 | SSE 订阅队列为进程内状态 |

## 四、关键设计偏差说明

1. **OTel 未配置远端 exporter**：原设计要求 OTel 原生 span；实际使用 SDK span 并同步保存 SQLite。原因是 exporter 目标属于部署配置。影响仅为默认不外发；P4 可按环境接入 OTLP exporter。
2. **自审采用确定性默认实现**：原设计未规定必须使用 LLM；实际 Reviewer 使用 LLM，review_on_submit 使用确定性规则。原因是避免已完成任务因第二次外部调用失败。影响是自审语义深度有限；可在配置化后启用 LLM 自审。
3. **审批面板为 P3 交互 pending store**：完整 WriteApproval 在设计中属于 P4。本阶段只实现控制台审批闭环 API，不拦截 memory/skill 写入，避免提前改变 P4 权限语义。
4. **新增 FastAPI/SSE/Vite 依赖**：设计只规定 HTTP API 和 React Console，未规定实现库；选型用于最小可维护闭环。
5. **MCP 未在 P3 新增**：旧 README 曾将 MCP 写入 P3 路线，但唯一基准设计的 P3 交付表不含 MCP；本阶段按设计表验收。

## 五、验证结果汇总

| 验证标准 | 结果 | 自动化证据 |
| --- | --- | --- |
| OTel span 可查 | 通过 | graph/node span 持久化专项测试 |
| 多次尝试选择最佳 | 通过 | Reviewer 候选选择与 fallback 测试 |
| 工具调用后自动验证 | 通过 | 成功/失败写工具门禁测试 |
| 历史可搜索 | 通过 | FTS5 session_search 工具测试 |
| 安全审计通过 | 通过 | 默认配置扫描；危险配置规则测试 |
| 轨迹可回放 | 通过 | 既有 trajectory/integration 回归 |
| Console 观察与审批 | 通过 | TypeScript/Vite 生产构建；SSE 与 HTTP 审批测试 |
| 决策过程可解释 | 通过 | observe/decide/act/verify/conclude/govern 摘要持久化、API 与集成测试 |

- Python：`ruff check src tests` 通过；`mypy src` strict 通过；`pytest tests/` 为 **181 passed、1 skipped、0 failed**。
- P3 专项：`tests/test_p3.py` 为 **15 passed**。
- Web：`npm run build` 通过，产物 JS 355.94 kB、gzip 109.10 kB；CSS 15.38 kB、gzip 4.01 kB；npm audit 0 vulnerability。
- 跳过项：真实 Docker daemon 集成测试 1 项，本机 daemon 不可用；Local/Docker 单元行为未失败。
- 不纳入伪造指标：真实模型 Token 成本、线上成功率和生产流量耗时尚无样本，Insights 在运行数据产生后计算。

## 六、遗留问题与技术债

| 优先级 | 问题与影响 | 临时规避 | 建议阶段 |
| --- | --- | --- | --- |
| 中 | 默认无 OTLP exporter，跨服务 Trace 不外发 | SQLite Trace API 查询 | P4 部署化 |
| 中 | SSE EventBus 为单进程内存队列，多实例不共享 | 单实例运行 API | P4 引入消息总线 |
| 中 | P3 审批只覆盖 UI/API，不是权限策略拦截 | 不把它作为 WriteApproval | P4 |
| 低 | FTS5 缺失时搜索退化为 LIKE | 小数据量使用降级路径 | 打包阶段固定 SQLite 能力 |
| 低 | Web Console 无浏览器端 E2E 框架 | 构建 + API/SSE 自动测试 | P4 回归体系 |

## 七、下一阶段前置建议

- 可复用：统一生命周期 Event、TraceStore、VerificationReport、SecurityAudit、ApprovalStore、API/SSE、React 控制台骨架。
- P4 前置：让 PolicyEngine 统一调用 SecurityAudit 与审批；将 quota 扩展为 Token/时间/资源预算；把 SSE 总线替换为可横向扩展的事件后端；基于失败报告生成回归用例。
- 风险：RBAC 与 WriteApproval 必须在工具执行前拦截，不能只停留在 UI；Coordinator 必须继承现有 Trace/Verification 上下文，避免子 Agent 成为审计盲区。

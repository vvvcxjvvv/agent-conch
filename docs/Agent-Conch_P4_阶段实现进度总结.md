# Agent-Conch P4 阶段实现进度总结

> 阶段：P4 Governable Production Harness  
> 基准：`plan/agent-conch-design.md` 第六章 P4 交付物  
> 前置：[P3 阶段总结](Agent-Conch_P3_阶段实现进度总结.md)  
> 验收日期：2026-07-18

## 一、阶段总览

P4 的设计目标是形成权限审批、人工接管、回归集、策略治理、成本熔断和多 Agent 编排组成的可治理生产 Harness。设计计划周期为 4–6 周；仓库未记录阶段起始日期，实际周期不作推断。本文件仅记录 P4 增量，不覆盖 P1–P3 历史结论。

**整体完成度：100%（代码与自动化闭环）**。12 项设计交付物均已进入运行时或前端入口并具备专项测试。真实 Docker daemon、Bitwarden/1Password 账户和生产模型流量依赖外部环境，作为环境验收项单列，不伪造通过数据。

| 交付物 | 状态 | 核心证据 |
| --- | --- | --- |
| RBAC | 已完成 | `security/permissions.py`，50+ 权限点、5 级操作、内置角色 |
| 策略引擎 | 已完成 | `security/policy_engine.py`，RBAC/规则/风险阈值统一决策 |
| 回归用例体系 | 已完成 | `verification/regression.py`，失败沉淀、去重、执行与通过率门禁 |
| Curator 自改进 | 已完成 | `context/skills/curator.py`，归档/改进/consolidation 提案与审批应用 |
| WriteApproval | 已完成 | `api/approvals.py`，精确请求指纹、pending 复用、批准后一次性消费 |
| Credential Pool | 已完成 | `security/credentials.py`，轮换/冷却、env/Bitwarden/1Password resolver |
| Cron 调度 | 已完成 | `governance/scheduler.py`，持久化五字段 Cron、180 秒硬中断 |
| Coordinator 多 Agent | 已完成 | `multiagent/coordinator.py`，决策表、串并行、上下文隔离、并发上限 |
| 成本熔断 | 已完成 | `governance/budget.py`，Token/时间/工具调用/资源单位综合预算 |
| 快照/回滚 | 已完成 | `sandbox/snapshots.py` + `sandbox/docker.py`，异步 commit/restore/delete |
| Web Dashboard | 已完成 | `apps/web/`，治理、回归、调度、Coordinator、凭证和快照视图 |
| Electron Desktop | 已完成 | `apps/desktop/`，复用 Web、目录/文件选择、通知、安全终端 IPC |

## 二、交付物逐项核对

| 模块 | 设计要求 | 实现状态 | 完成度说明 | 关联代码路径 |
| --- | --- | --- | --- | --- |
| RBAC | 40+ 权限点 + 操作 5 级分级 | 已完成 | `Permission` 超过 40 项；READ/WRITE/EXECUTE/ADMIN/CRITICAL；viewer/operator/developer/maintainer/admin/worker | `src/agent_conch/security/permissions.py` |
| PolicyEngine | 统一合规规则管理 | 已完成 | RBAC 先行，YAML 规则匹配，风险阈值审批；工具执行和 API 双入口前置拦截 | `src/agent_conch/security/policy_engine.py`、`tools/registry.py` |
| 回归用例 | 失败案例自动沉淀 + 回归测试 | 已完成 | Verification 失败自动去重沉淀；启停、批量运行、最低通过率门禁与 API | `src/agent_conch/verification/regression.py` |
| Curator | Skill 自动归档/改进/consolidation | 已完成 | 仅处理 agent-created 且未 pinned Skill；变更以提案产生并经 WriteApproval 应用 | `src/agent_conch/context/skills/curator.py` |
| WriteApproval | memory/skill 写入审批 + pending store | 已完成 | 受保护路径写入暂停；请求哈希防篡改；批准只消费一次；批准后恢复原始工具请求 | `src/agent_conch/api/approvals.py`、`engine/conch_engine.py` |
| Credential Pool | 多 API key 轮换 + Bitwarden/1Password | 已完成 | 按 priority/uses/last-used 轮换；失败冷却；CLI resolver 无 shell；元数据脱敏、明文不落库 | `src/agent_conch/security/credentials.py` |
| Cron | 定时任务 + 3 分钟硬中断 | 已完成 | UTC 五字段解析、next-run、持久化任务/结果、`asyncio.wait_for`，超时上限 180 秒 | `src/agent_conch/governance/scheduler.py` |
| Coordinator | 主从编排 + 决策表 + 上下文隔离 | 已完成 | 顺序/并行策略、worker 角色决策、独立 session、Semaphore 并发约束、结果持久化 | `src/agent_conch/multiagent/coordinator.py` |
| 成本熔断 | 单任务 Token/时间/资源预算 | 已完成 | 四维预算；LLM 与工具路径实时记账；超限拒绝并产生 `BUDGET_EXCEEDED` | `src/agent_conch/governance/budget.py`、`observability/exit_status.py` |
| 快照/回滚 | Docker commit 快照 + restore | 已完成 | SnapshotManager 持久化外部引用并异步适配 Docker commit/restore/delete | `src/agent_conch/sandbox/snapshots.py`、`sandbox/docker.py` |
| Web Dashboard | 治理、指标、回放、回归基础管理 | 已完成 | 深海青蓝三栏工作台增加治理总览、动作入口和现有轨迹/指标/审批视图 | `apps/web/src/App.tsx`、`api.ts` |
| Electron Desktop | 复用 Web + 本地文件/终端桥接 | 已完成 | context isolation、sandbox、关闭 Node integration；文件选择/通知 IPC；终端经后端治理 API | `apps/desktop/main.cjs`、`preload.cjs` |

## 三、架构分层完成度总览

| 层级 | 层级名称 | 本阶段计划能力 | 实际覆盖情况 | 核心差异 |
| --- | --- | --- | --- | --- |
| E | 执行环境与沙箱 | Docker 快照/回滚、Desktop 本地桥接 | SnapshotManager + Docker 异步接口；Electron 文件选择与终端桥接 | 真实 Docker daemon 验证条件跳过 |
| T | 工具接口层 | 策略与预算执行前拦截 | ToolRegistry 统一接入 PolicyEngine、WriteApproval、BudgetManager 和身份上下文 | bash 仍由既有 ToolPolicy 归类为写操作 |
| C | 上下文与记忆 | Skill Curator | 自动识别归档/改进/合并候选，审批后修改文件 | 改进内容为确定性模板，不额外调用 LLM |
| L | 生命周期与编排 | Cron、Coordinator、多 Agent | 持久化调度、3 分钟中断、决策表、隔离 worker session | Coordinator 为单进程 asyncio，不是分布式队列 |
| O | 可观测层 | 成本与治理事件、跨实例事件 | SQLite event stream 支持多 API 实例轮询；预算/审批/Coordinator 均可查询 | 未引入外部消息总线 |
| V | 验证与评估层 | 失败沉淀、回归门禁 | VerificationLayer 自动 capture，RegressionRunner 输出 gate_passed/pass_rate | 无浏览器 E2E 框架 |
| G | 治理与安全层 | RBAC、PolicyEngine、审批、凭证、熔断 | 所有能力进入 Engine/API/ToolRegistry 主链路 | 规则 DSL 为受控声明式子集，不是 OPA/CEL |
| S | 状态存储层 | 治理对象持久化 | SQLite 新增审批、预算、回归、Curator、Cron、Coordinator、快照、事件流表 | 单 SQLite 适合单机/轻量多实例，不面向跨地域 |

## 四、关键设计偏差说明

1. **Coordinator 为进程内编排**：原设计只规定主从编排、决策表和上下文隔离；实际使用 asyncio + Semaphore 与 SQLite。原因是先闭合单机生产 Harness。影响是不能跨主机调度；分布式 worker 可在后续替换 runner，不影响任务/结果模型。
2. **PolicyEngine 使用受控规则模型**：未引入 OPA/CEL。原因是 P4 规则只需 roles/senders/tools/actions/level/argument_contains，减少依赖和动态执行风险。复杂布尔表达式需后续扩展。
3. **Skill Improve 为确定性模板**：设计要求自动改进，未要求 LLM。实际生成可审计替换内容并强制审批，避免未经验证的模型内容直接覆盖 Skill。后续可把 LLM 作为提案生成器，审批约束不变。
4. **Credential vault 通过官方 CLI resolver 接入**：不内嵌 Bitwarden/1Password SDK。原因是复用本机登录态且避免 secret 落库。运行环境必须安装并解锁 `bw`/`op`。
5. **事件共享使用 SQLite polling**：替代 P3 进程内队列，已支持同库多实例，但没有外部 broker 的跨主机能力。后续生产集群可增加 Redis/NATS adapter。
6. **Electron 尚未产出签名安装包**：P4 交付要求 Desktop wrapper 与桥接，实际完成源码、依赖锁和语法检查；代码签名、公证、自动更新属于发布工程，不在交付表中。

## 五、验证结果汇总

| 验证标准 | 结果 | 自动化/实现证据 |
| --- | --- | --- |
| 角色权限控制 | 通过 | 未知/低权限拒绝、admin 权限与 API RBAC 测试 |
| 成本预算可熔断 | 通过 | Token/工具/资源计数及独立 exit status 测试 |
| Skill 自动归档/改进 | 通过 | Curator archive 与审批保护测试；三类 action 实现 |
| 定时任务执行 | 通过 | Cron 解析、到期执行、next-run 与结果持久化测试 |
| 回归通过率质量门禁 | 通过 | 失败去重 capture、批量执行、100% gate 测试 |
| 轨迹可回放 | 通过 | 全量既有回归；Desktop terminal 额外写入 trajectory |
| 多 Agent 协作 | 通过 | 并行 worker、结果顺序、隔离 metadata/session 测试 |
| 前端治理与指标 | 通过 | TypeScript/Vite 生产构建；治理 API 和动作接线 |
| Desktop 桥接 | 通过 | Electron main/preload 语法检查；后端终端 RBAC/预算/审计闭环测试 |

- Python：`ruff check src tests` **0 问题**；`mypy src` strict **0 问题**；`pytest tests/` **209 passed、1 skipped、0 failed**。
- P4 专项：`tests/test_p4.py` **19 passed**。
- Web：Vitest、TypeScript/Vite 构建、Playwright Chromium E2E 全部通过；`npm audit` 0 vulnerability。
- Desktop：main/preload 语法检查和 `electron-builder --dir` 可分发目录打包通过；`npm audit` 0 vulnerability。
- 条件跳过：真实 Docker daemon 集成测试 1 项；异步快照管理器以兼容异步后端的专项测试覆盖。
- 未产生的指标：真实 vault、真实模型 Token 成本、生产流量成功率、桌面签名包不具备本地自动化样本。

## 六、遗留问题与技术债

| 优先级 | 问题与影响 | 临时规避 | 建议阶段 |
| --- | --- | --- | --- |
| 中 | 无真实 Docker daemon 的 commit/restore E2E 证据 | 异步接口测试 + API 409 明确失败 | 发布环境验收 |
| 中 | Bitwarden/1Password 依赖已登录 CLI，未做真实账户 CI | env resolver 或注入测试 resolver | Secret-enabled CI |
| 中 | Coordinator/Cron 为单机进程执行，无法跨节点抢占 | 单实例 scheduler；SQLite 持久化恢复 | 分布式部署阶段 |
| 低 | 五字段 Cron 固定 UTC，无时区/DST 规则 | 在 task 中显式换算 UTC | 调度增强 |
| 低 | Electron 无签名、公证、自动更新 | 源码启动或内部构建 | 产品发布阶段 |

## 七、下一阶段前置建议

- P4 已完成设计路线中的最终阶段；后续应转入发布化，而不是继续扩展 Harness 核心面。
- 首要前置：在具备 Docker daemon、`bw`/`op` 登录态、真实模型 key 的受控环境运行外部依赖验收。
- 发布门禁：Electron 签名、公证、自动更新和多平台冒烟。
- 扩展方向：为 EventBus/Coordinator/Scheduler 增加 Redis/NATS/队列 adapter；保持 SQLite 作为本地默认实现。
- 安全要求：所有新工具继续通过 ToolRegistry 的 RBAC → PolicyEngine → WriteApproval → Budget 顺序，禁止绕过治理 API 直接执行系统命令。

## 八、设计缺口闭环增量（2026-07-19）

本节为增量记录，不替换前述 P4 交付结论。

| 缺口 | 本次实现 | 状态 | 证据 |
| --- | --- | --- | --- |
| SSH 沙箱 | OpenSSH argv 执行、严格 host key、超时、远端 FsBridge 与 allowed roots | 已完成 | `sandbox/ssh.py`、`test_design_closure.py` |
| gVisor | Docker `runtime` 配置并透传 `--runtime runsc` | 已完成（真实运行待环境） | `sandbox/docker.py`、Docker argv 测试 |
| 网络白名单 | HTTP(S) 主机通配符/CIDR 决策并接入 Web 工具 | 已完成 | `sandbox/network_policy.py` |
| MCP | stdio 生命周期、动态发现/注册/刷新/调用/清理 | 已完成 | `tools/mcp_client.py`、管理 API |
| 内容安全 | 敏感内容外发阻断、工具结果与最终回答统一脱敏 | 已完成 | `security/content_safety.py` |
| 长输出管理 | 阈值截断、0600 私有制品落盘、预览引用 | 已完成 | `tools/output_manager.py` |
| 生命周期 Hook | 可配置事件命令、fail-closed、SQLite 审计 | 已完成 | `hooks/executor.py` |
| Web 管理面 | 会话/消息、Tool/MCP/Skill/Hook 资源控制台 | 已完成 | `apps/web/src/App.tsx`、Vitest、Playwright |
| Electron 发布 | 可分发目录构建 | 已完成；签名/公证待证书环境 | `apps/desktop/package.json`、`npm run pack` |

外部验收边界：当前机器没有 Docker、`runsc`、`bw`、`op`，且未配置 SSH 目标与 Developer ID，因此对应真实环境冒烟和签名/公证不宣称通过；实现、模拟验证和无外部依赖门禁均已通过。

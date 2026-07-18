# Agent-Conch 参考项目与设计来源

> 本文档只记录 Agent-Conch 设计方案背后的参考项目、优秀实践和可借鉴模块。主设计文档 `agent-conch-design.md` 不再包含参考项目对比内容。

---

## 一、参考项目定位

| 项目         | 定位                     | 主要参考价值                                                 |
| ------------ | ------------------------ | ------------------------------------------------------------ |
| OpenHarness  | 全栈通用 Agent Harness   | 渐进式上下文压缩、Skill 体系、权限检查、Autopilot 验证报告   |
| Dify         | LLM 应用开发平台         | GraphEngine Layer、Pause/Resume、OTel Observability、RBAC、配额熔断 |
| SWE-agent    | 软件工程垂直 Harness     | ACI 工具接口、Reviewer、review_on_submit、Trajectory 回放、exit_status 分类 |
| Hermes Agent | 全栈个人 AI Agent        | Prompt Caching、ContextCompressor、Curator、ToolSearch、check_fn TTL、FTS5 搜索 |
| OpenClaw     | 全栈个人 AI 助手 Harness | Agent Runtime 抽象、Context Engine、SQLite 优先、FS Bridge、Subagent 孤儿恢复、安全审计 |

---

## 二、分层设计来源

| 层级                 | Agent-Conch 设计                                             | 参考来源                                                     |
| -------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| E 层：执行环境       | Local/Docker/SSH 沙箱、FS Bridge、快照/回滚                  | OpenClaw FS Bridge、SWE-agent hard_reset                     |
| T 层：工具接口       | 12 核心工具、ToolSearch、ToolPolicy、check_fn TTL、并行工具执行 | SWE-agent ACI、Hermes ToolSearch/check_fn、OpenClaw Tool Policy |
| C 层：上下文与记忆   | 可插拔 Context Engine、渐进式上下文压缩、Prompt Caching、Skill/Memory | OpenHarness compact、Hermes ContextCompressor/Curator、OpenClaw Context Engine |
| L 层：生命周期与编排 | Agent Loop、Agent Runtime 可插拔、Layer 插件体系、多 Agent 编排 | OpenClaw runtime/subagent、Dify Layer、Hermes ErrorClassifier、SWE-agent forward_with_handling |
| O 层：可观测性       | OTel Trace、Trajectory 回放、exit_status、Insights           | Dify OTel、SWE-agent trajectory、Hermes FTS5/Insights        |
| V 层：验证与评估     | VerificationLayer、Reviewer、review_on_submit、回归用例体系  | SWE-agent Reviewer/review_on_submit、OpenHarness autopilot 报告 |
| G 层：治理与安全     | RBAC、配额、敏感路径、WriteApproval、SecurityAudit、PolicyEngine | Dify RBAC/Quota、OpenHarness SensitivePaths、Hermes WriteApproval/CredentialPool、OpenClaw Audit |
| S 层：状态存储       | SQLite 优先、Checkpoint、TrajectoryStore、FTS5               | OpenClaw SQLite 优先、Hermes FTS5、SWE-agent trajectory      |

---

## 三、模块级参考映射

| Agent-Conch 模块             | 推荐参考                                                    |
| ---------------------------- | ----------------------------------------------------------- |
| `engine/agent_loop.py`       | SWE-agent `DefaultAgent.step()` / `forward_with_handling()` |
| `engine/runtime/`            | OpenClaw `src/agents/harness/` 的运行时抽象思想             |
| `engine/layers/`             | Dify GraphEngine Layer                                      |
| `tools/registry.py`          | Hermes `tools/registry.py`                                  |
| `tools/tool_search.py`       | Hermes ToolSearch + OpenClaw Tool Search                    |
| `tools/tool_policy.py`       | OpenClaw Tool Policy                                        |
| `context/engine.py`          | OpenClaw Context Engine                                     |
| `context/compact/`           | OpenHarness compact + Hermes ContextCompressor              |
| `context/prompt_caching.py`  | Hermes `agent/prompt_caching.py`                            |
| `context/skills/`            | OpenHarness SkillRegistry + Hermes skills/Curator           |
| `state/trajectory.py`        | SWE-agent `.traj` + replay                                  |
| `sandbox/fs_bridge.py`       | OpenClaw FS Bridge                                          |
| `security/permissions.py`    | OpenHarness PermissionChecker                               |
| `security/audit.py`          | OpenClaw Security Audit                                     |
| `security/write_approval.py` | Hermes WriteApproval                                        |
| `verification/reviewer.py`   | SWE-agent Reviewer                                          |
| `verification/report.py`     | OpenHarness Autopilot verification report                   |
| `observability/otel.py`      | Dify ObservabilityLayer                                     |
| `multiagent/subagent.py`     | OpenClaw Subagent orphan recovery                           |

---

## 四、自研优先项

这些能力参考项目中普遍薄弱或缺失，应作为 Agent-Conch 的核心差异化：

| 能力                                   | 自研目标                                                     |
| -------------------------------------- | ------------------------------------------------------------ |
| VerificationLayer                      | 工具调用后自动运行 lint/type check/test，并将失败结果反馈给 Agent 修复 |
| 并行工具执行                           | 单轮多个 tool_call 使用 `asyncio.gather` 并行执行            |
| Schema-based selective skill injection | 基于 Skill frontmatter 精准注入相关章节，避免全文注入        |
| 回归用例体系                           | 将失败案例沉淀为可重复执行的测试用例                         |
| PolicyEngine                           | 用 YAML/DSL 统一管理合规、审批、敏感操作和成本策略           |
| 快照/回滚                              | Docker commit 快照 + restore，支持失败后回滚执行环境         |
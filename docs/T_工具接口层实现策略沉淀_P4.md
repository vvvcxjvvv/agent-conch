# T 工具接口层实现策略沉淀（P4 增量）

## 一、设计目标回顾

T 层是所有工具执行的唯一入口。P4 要求把角色、策略、审批与预算真正放在执行前，而非只在 UI 展示，并保持既有 12 核心工具、ToolPolicy、ToolSearch 和并行执行兼容。

## 二、核心实现方案

ToolRegistry 为 session 绑定 `(principal, role, sender)`，执行顺序为：参数验证 → ToolPolicy → PolicyEngine/RBAC → WriteApproval → BudgetManager → tool.execute → 健康状态。审批记录保存精确参数哈希；批准后 ConchEngine 用原参数恢复一次。

- `src/agent_conch/tools/registry.py`
- `src/agent_conch/tools/tool_policy.py`
- `src/agent_conch/security/policy_engine.py`
- `src/agent_conch/api/approvals.py`

## 三、设计落地对照

- ✅ 工具执行前统一治理，API 与 Agent Loop 共享同一 Registry。
- ✅ memory/skill 文件写入自动转为 approval_required。
- ✅ 工具调用消耗工具次数和风险级资源单位。
- ⚠️ 既有 ToolPolicy 与新 PolicyEngine 并存；前者保留工具/sandbox 兼容规则，后者承担 P4 合规决策。

## 四、关键技术点与踩坑记录

审批不能只保存 operation 名称，否则批准时参数可被替换。实现对 session、operation、规范化 payload 做 SHA-256 指纹，pending 去重，approved 记录原子消费一次。session identity 在 finally 中清除，避免并发会话身份串扰。

## 五、验证与覆盖情况

覆盖 RBAC 拒绝、Policy approval、精确批准后执行、重复重放重新审批、预算超限阻断和 Desktop 统一工具入口。Ruff/mypy strict 与全量回归通过。

## 六、演进与优化方向

把 action 推断从工具属性扩展为工具声明的显式风险描述；增加按参数动态风险评分和 ToolRegistry 并发身份上下文隔离的压力测试。

## 七、设计缺口闭环增量（2026-07-19）

- 新增 MCPClient 与 MCPToolAdapter：stdio 连接初始化、工具发现、动态 Registry 注册、调用、错误状态和关闭清理均已闭环。
- 新增 ToolOutputManager：超过阈值的结果保存为权限 `0600` 的制品，只向模型返回受控预览和制品引用。
- ToolRegistry 在执行后按“内容脱敏 → 输出 offload”处理，MCP 工具继续复用现有 RBAC、PolicyEngine、审批和预算链。
- Web 资源控制台提供 Tool health/schema 与 MCP 状态/刷新入口；对应 Python 测试、Vitest 和 Playwright E2E 通过。

# G 治理与安全层实现策略沉淀（P4 增量）

## 一、设计目标回顾

G 层是 P4 核心：40+ 权限点、5 级操作、PolicyEngine、WriteApproval、Credential Pool 和单任务成本熔断必须在真实执行链生效。

## 二、核心实现方案

RBAC 将权限集合绑定内置角色；PolicyEngine 依次执行 RBAC、声明式规则和风险阈值。WriteApproval 对原始请求做指纹、复用 pending、记录决策人并只消费一次。BudgetManager 管理 Token/秒数/工具次数/资源单位。CredentialPool 只保存引用，按使用次数轮换，失败后冷却，支持 env、`bw` 与 `op` resolver。

- `src/agent_conch/security/permissions.py`
- `src/agent_conch/security/policy_engine.py`
- `src/agent_conch/api/approvals.py`
- `src/agent_conch/governance/budget.py`
- `src/agent_conch/security/credentials.py`

## 三、设计落地对照

- ✅ 权限点数量与 5 级操作满足设计。
- ✅ memory/skill 写入审批、pending store、精确恢复满足设计。
- ✅ 多 key 轮换与 Bitwarden/1Password CLI resolver 完成，secret 不落库。
- ✅ 四维成本预算在 LLM 和工具调用路径熔断。
- ⚠️ 规则语言为固定字段匹配，不支持任意表达式。

## 四、关键技术点与踩坑记录

授权顺序固定为 RBAC 优先，避免 allow 规则绕过角色权限。批准不等于永久授权，消费后同一请求再次执行会生成新 pending。vault 调用使用 argv、禁止 shell、10 秒超时；API 仅返回脱敏引用和使用状态。

## 五、验证与覆盖情况

覆盖权限数量、未知角色拒绝、规则审批、批准一次性消费、预算熔断、key 轮换/冷却、元数据脱敏和两个 vault resolver。真实 vault 账户、CLI 登录态和生产 key 未在本地 CI 使用。

## 六、演进与优化方向

增加自定义角色持久化、规则版本/审计、审批过期和双人复核；vault resolver 增加缓存 TTL 与健康检查；生产环境接入集中策略和密钥服务 adapter。

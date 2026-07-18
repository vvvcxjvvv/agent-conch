# G 治理与安全层实现策略沉淀（P3 增量）

## 一、设计目标回顾

G 层 P3 范围是配额熔断、Security Audit 和 Dangerous Config Detection；RBAC、PolicyEngine、完整 WriteApproval 属于 P4。

## 二、核心实现方案

LLMQuotaLayer 累计每次 llm_usage 的 total token 并中止超额 graph。SecurityAudit 递归检查内联密钥，并检查沙箱禁用、根目录暴露、Docker host 网络、公开 API、空验证门禁、无效配额和远程 HTTP 模型端点。路径：`engine/layers/llm_quota.py`、`security/audit.py`、`api/server.py`。

## 三、设计落地对照

- ✅ Token 配额熔断进入 AgentLoop。
- ✅ 多维危险配置扫描并通过 API 输出结构化 finding。
- ⚠️ ApprovalStore 只服务 P3 控制台交互，不宣称实现 P4 WriteApproval。

## 四、关键技术点与踩坑记录

密钥扫描依据字段语义，不扫描任意字符串，减少误报；远程 HTTP 与 localhost HTTP 区分；默认配置必须零 finding，危险样例必须稳定复现。

## 五、验证与覆盖情况

专项测试覆盖内联密钥、sandbox=never 和 quota abort；默认配置人工/接口扫描无危险项。未覆盖 RBAC 绕过、供应链依赖扫描和容器镜像 CVE。

## 六、演进与优化方向

P4 由 PolicyEngine 统一执行审计、RBAC、WriteApproval 和资源预算；加入规则版本、豁免审计、供应链扫描和凭证池。

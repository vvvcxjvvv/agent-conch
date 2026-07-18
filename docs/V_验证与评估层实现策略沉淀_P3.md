# V 验证与评估层实现策略沉淀（P3 增量）

## 一、设计目标回顾

V 层实现确定性检查、Reviewer、多次尝试选优、review_on_submit 和“Agent 自述/服务验证”分离，目标是从声称完成升级为有证据完成。

## 二、核心实现方案

成功的 write/edit 结果触发 `VerificationLayer`，按 YAML 串行执行 lint/type/test；报告持久化 `agent_claim` 和 checks。失败时阻塞进度并注入修复消息。Reviewer 对候选进行 LLM JSON 评审并有启发式 fallback；SelfReview 在返回前执行。路径：`verification/`、`engine/agent_loop.py`、`engine/conch_engine.py`。

## 三、设计落地对照

- ✅ 工具调用后自动验证和质量门禁。
- ✅ Agent 自述与服务级验证独立字段、独立证据。
- ✅ Reviewer 支持多候选选择。
- ⚠️ 默认 SelfReview 为确定性规则，不发起额外 LLM；Reviewer 仍支持 LLM。

## 四、关键技术点与踩坑记录

门禁只在成功写操作后触发，避免只读任务反复跑全套测试；首个失败即停止并保留末尾 4000 字输出。最初自审绑定辅助 LLM，使 mock 集成测试意外访问外部服务，改为确定性默认后恢复隔离性。

## 五、验证与覆盖情况

覆盖成功门禁、失败门禁、注入消息、报告字段、Reviewer fallback、自审通过；全量 181 项通过。未覆盖超大仓库门禁并行化、 flaky test 重试和验证命令可信来源签名。

## 六、演进与优化方向

P4 将失败案例自动沉淀为回归集；按语言自动选择验证协议；增加 flaky 分类、覆盖率阈值、制品签名和可选 LLM 自审。

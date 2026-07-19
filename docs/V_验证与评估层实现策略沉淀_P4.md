# V 验证与评估层实现策略沉淀（P4 增量）

## 一、设计目标回顾

V 层 P4 目标是把一次性 Verification 失败转成可复用回归用例，并以通过率作为持续质量门禁。

## 二、核心实现方案

VerificationLayer 在报告失败时调用 RegressionStore.capture；用 command/cwd/失败摘要指纹去重。RegressionRunner 串行执行 enabled cases，记录每次结果，计算 pass_rate，并与 minimum_pass_rate 比较生成 gate_passed。

- `src/agent_conch/verification/layer.py`
- `src/agent_conch/verification/regression.py`
- `src/agent_conch/verification/report.py`

## 三、设计落地对照

- ✅ 失败案例自动沉淀、去重、启停和重跑。
- ✅ 通过率直接输出质量门禁结果。
- ✅ Web/API 可查看用例并触发回归。
- ⚠️ 当前 runner 执行命令型用例，尚无浏览器视觉/E2E case 类型。

## 四、关键技术点与踩坑记录

若按完整 stdout 建指纹，时间戳和路径会制造重复 case；实现只取稳定字段和规范化失败摘要。门禁默认 1.0，避免“部分通过”被误判为可发布；阈值可由 YAML 调整。

## 五、验证与覆盖情况

验证失败报告两次 capture 只产生一个 case；模拟命令成功后 pass_rate=1.0 且 gate_passed=true。P4 专项和全量 200 个 Python 测试通过；浏览器 E2E 未覆盖。

## 六、演进与优化方向

增加 case 标签、依赖环境、并行执行、flaky 隔离和历史趋势；将 Web/Electron E2E、真实 Docker 快照、vault 冒烟纳入多类型回归门禁。

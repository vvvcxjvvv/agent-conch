# O 可观测层实现策略沉淀（P3 增量）

## 一、设计目标回顾

O 层目标是提供 OTel 原生 span、节点类型解析、Decision Trace、Trajectory 回放、exit_status 归因和 Insights，使执行证据可查询并可解释。

## 二、核心实现方案

`ObservabilityLayer` 将 graph/node/event 钩子转为 span；`OTelTracer` 同时写 OTel SDK 与 `TraceStore`；`DecisionTraceStore` 持久化观察、决策、执行、验证、结论和治理摘要；`NodeTypeParser` 归类 model/tool/action；Insights 从 sessions 与 trajectories 聚合。路径：`observability/otel.py`、`decision_trace.py`、`trace_store.py`、`exit_status.py`、`insights.py`、`state/trajectory.py`。

## 三、设计落地对照

- ✅ 原生 OTel span、节点 parser、SQLite 查询、回放和统计完成。
- ✅ Decision Trace 只记录可观察证据，不采集模型原始思维链。
- ✅ API/SSE 暴露 decisions，Web Console 提供“决策轨迹”页签。
- ⚠️ 未默认绑定 OTLP exporter；这是部署参数，不影响本地审计证据。

## 四、关键技术点与踩坑记录

OTel 全局 provider 只能安全设置一次，初始化时复用已有 TracerProvider；SQLite 记录使用独立 span_id/trace_id，保证无 collector 时仍可查。事件 span 只记录标量属性，避免 OTel 类型错误。

## 五、验证与覆盖情况

专项测试验证 graph/node span、Decision Trace 存储/API 和稳定顺序；集成测试验证 observe/decide/act/conclude 全链路。未验证远端 collector、跨进程 trace propagation 和生产采样策略。

## 六、演进与优化方向

P4 配置 OTLP exporter、采样和保留策略；统一 exit_status 写入 session 与 trace；建立失败归因维度和回归集关联。

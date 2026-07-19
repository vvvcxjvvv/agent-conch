# O 可观测层实现策略沉淀（P4 增量）

## 一、设计目标回顾

O 层 P4 需要让治理、成本、回归和多 Agent 行为可查询、可回放，并修复 P3 EventBus 仅单进程可见的限制。

## 二、核心实现方案

EventBus 在绑定 SessionDB 时把事件写入 SQLite event stream，订阅者按序号轮询，因此共享同一数据库的多个 API 实例可收到事件；无 DB 时保留原内存兼容模式。Budget、Approval、Regression、Coordinator、Snapshot 均提供 overview/list API，Desktop terminal 写入 TrajectoryStep。

- `src/agent_conch/observability/events.py`
- `src/agent_conch/observability/exit_status.py`
- `src/agent_conch/engine/conch_engine.py`
- `src/agent_conch/api/server.py`

## 三、设计落地对照

- ✅ 治理对象进入 Web Dashboard 和 HTTP 查询面。
- ✅ `BUDGET_EXCEEDED` 独立失败归因。
- ✅ 跨 EventBus 实例共享事件。
- ⚠️ SQLite polling 不是跨主机消息总线；OTLP exporter 仍由部署环境配置。

## 四、关键技术点与踩坑记录

仅保留内存 queue 会导致多 uvicorn worker 看不到事件。SQLite 方案复用 S 层，避免新增 broker；订阅使用增量 cursor 和短轮询，心跳仍由 SSE 层控制。事件 payload 保持 JSON，禁止放 credential secret。

## 五、验证与覆盖情况

专项测试创建两个 EventBus 实例，验证一端 publish、另一端 subscribe；全量 Trace、Decision、Trajectory、Insights 回归通过。未做高吞吐 polling 压测。

## 六、演进与优化方向

增加事件保留/清理、索引指标和长连接压力测试；集群部署提供 Redis Streams/NATS adapter，并保持事件 schema 与 SSE API 不变。

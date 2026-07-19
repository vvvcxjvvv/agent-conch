# L 生命周期与编排层实现策略沉淀（P4 增量）

## 一、设计目标回顾

L 层 P4 目标是 Cron 定时生命周期与 Coordinator 多 Agent 主从编排，要求 3 分钟硬中断、决策表、上下文隔离、受控并发和可恢复状态。

## 二、核心实现方案

CronScheduler 解析 UTC 五字段表达式，持久化 schedule、next_run 与每次结果，以 `asyncio.wait_for` 强制不超过 180 秒。Coordinator 用 DecisionTable 选择 worker role/strategy，SubagentManager 创建独立 session，Semaphore 控制并发，按输入顺序汇总结果。

- `src/agent_conch/governance/scheduler.py`
- `src/agent_conch/multiagent/coordinator.py`
- `src/agent_conch/multiagent/subagent.py`
- `src/agent_conch/engine/conch_engine.py`

## 三、设计落地对照

- ✅ 定时任务、硬中断、结果持久化。
- ✅ 主从编排、决策表、串并行策略、上下文隔离。
- ✅ scheduler/worker 以独立 principal/role 进入治理链。
- ⚠️ 单进程 asyncio 实现，不提供跨节点抢占。

## 四、关键技术点与踩坑记录

结果顺序不能依赖并行完成顺序，Coordinator 为每个 worker 保留输入索引后统一汇总。worker metadata 明示 `context_isolated`，禁止复用父会话消息。Cron 创建时校验语法和 timeout 上限，避免持久化不可执行任务。

## 五、验证与覆盖情况

覆盖 Cron next-run、非法表达式、到期执行和持久化；Coordinator 覆盖两个并行 worker、隔离 metadata、独立 session 与稳定结果顺序。未执行多进程故障转移测试。

## 六、演进与优化方向

增加时区/DST、misfire policy、幂等锁与分布式 lease；Coordinator 可替换 runner 为队列 worker，并增加取消传播、部分失败策略与动态决策表。

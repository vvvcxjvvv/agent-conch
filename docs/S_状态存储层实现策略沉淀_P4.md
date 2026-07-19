# S 状态存储层实现策略沉淀（P4 增量）

## 一、设计目标回顾

S 层为 P4 治理对象提供可恢复、可审计的单机默认存储，要求审批、预算、回归、Curator、调度、Coordinator、快照和事件不因进程重启丢失。

## 二、核心实现方案

各 P4 manager 在共享 SessionDB 连接上幂等创建专用表与索引：approvals、run_budgets、regression cases/runs、curator proposals、schedules/runs、coordinator runs、sandbox snapshots、event stream。既有审批表通过 PRAGMA 检查后增量 migration，避免覆盖 P3 数据。

- `src/agent_conch/state/session_db.py`
- `src/agent_conch/api/approvals.py`
- `src/agent_conch/governance/`
- `src/agent_conch/verification/regression.py`
- `src/agent_conch/sandbox/snapshots.py`

## 三、设计落地对照

- ✅ SQLite 优先原则保持不变。
- ✅ P3 approvals 表向前兼容迁移，不删除历史列/记录。
- ✅ 请求指纹、状态索引和 session 索引支持幂等查询。
- ⚠️ schema migration 仍由组件启动时执行，没有独立版本工具。

## 四、关键技术点与踩坑记录

索引若在旧表补列前创建会因列不存在失败，因此先创建/迁移列，再创建新索引。事件流使用单调 row id 作为订阅 cursor。所有 secret 只在 CredentialLease 内存存在，数据库只保存脱敏元数据所需引用配置之外的运行状态。

## 五、验证与覆盖情况

覆盖旧审批语义兼容、pending 去重、预算累计、回归去重、Cron/Coordinator/快照持久化以及两个 EventBus 实例共享 SQLite。未做大规模数据库锁竞争和长期清理压力测试。

## 六、演进与优化方向

引入显式 schema version/migration、WAL/忙等待参数、归档与保留策略；集群场景把高频事件和调度 lease 外置，SQLite 继续承担本地开发与单机部署默认实现。

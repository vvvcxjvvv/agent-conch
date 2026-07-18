# S 状态存储层实现策略沉淀（P3 增量）

## 一、设计目标回顾

S 层为 P3 审计闭环持久化 Trace、Decision Trace、Verification、Checkpoint、Trajectory、FTS5 索引和审批 pending 状态，坚持 SQLite 优先与可查询证据。

## 二、核心实现方案

各 store 复用同一 SessionDB connection 并自建表/index：`trace_spans`、`decision_traces`、`verification_reports`、`approvals`、`session_search`。Decision Trace 按自增 id 稳定回放；Trajectory 保持 SQLite+JSONL 双写出路径；Checkpoint 保存 pause 快照。路径：`observability/decision_trace.py`、`trace_store.py`、`verification/report.py`、`api/approvals.py`、`state/checkpoint.py`、`state/trajectory.py`。

## 三、设计落地对照

- ✅ P3 核心审计证据均可按 session 查询。
- ✅ VerificationReport 保存原始检查输出和 Agent claim。
- ⚠️ 通用 SSE 消息不落库；权威历史由 Trace/Decision Trace/Trajectory/Verification 表保存。

## 四、关键技术点与踩坑记录

每个 store 使用 `CREATE TABLE/INDEX IF NOT EXISTS` 支持旧库平滑升级；JSON 字段保留扩展性；FTS5 采用 delete+insert 幂等更新。当前连接为单进程 SQLite，未承诺多写节点一致性。

## 五、验证与覆盖情况

覆盖 span、decision trace、verification、approval、checkpoint、FTS 索引的写入读取；SessionDB/Trajectory 既有测试全部回归通过。未进行高并发锁竞争、迁移回滚和大库清理压测。

## 六、演进与优化方向

P4 引入 schema migration 版本、保留/归档策略、WAL 与备份恢复测试；多实例部署时把实时事件迁移到消息总线。

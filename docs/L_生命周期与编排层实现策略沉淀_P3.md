# L 生命周期与编排层实现策略沉淀（P3 增量）

## 一、设计目标回顾

L 层在 P3 承载 GraphEngine 横切能力：LLMQuotaLayer、SuspendLayer、PauseStatePersistLayer，并把 run/LLM/tool/verification 事件贯通。

## 二、核心实现方案

`ConchEngine` 按 YAML 装配 Layer；AgentLoop 在 graph start/end、node start/end、LLM usage 上触发钩子，并向 EventBus 发布状态。Quota 超限设置 GraphContext abort；pause/resume 同时更新 SuspendLayer 与 Checkpoint。路径：`engine/layers/`、`engine/agent_loop.py`、`engine/conch_engine.py`。

## 三、设计落地对照

- ✅ 三类 P3 Layer 均进入运行链路。
- ✅ 配额中止会关闭 graph span、更新 session 并发布结束事件。
- ⚠️ SuspendLayer 的快速判定集合位于进程内；持久状态由 PauseStatePersistLayer 保存，重启后的自动重建尚未实现。

## 四、关键技术点与踩坑记录

LayerManager 原先在依赖初始化前装配，P3 调整到 Checkpoint/Memory/Trace/Verification 初始化后，避免构造期空依赖。自审使用确定性默认值，避免集成测试被第二次 LLM 调用破坏。

## 五、验证与覆盖情况

覆盖 quota abort、pause/resume checkpoint、EventBus 事件；5 个集成测试和引擎回归全部通过。未覆盖进程崩溃后自动恢复正在运行的协程。

## 六、演进与优化方向

P4 将 Layer 事件持久化、支持分布式恢复；Coordinator 子 Agent 必须传播 trace_id、quota 和 verification 上下文。

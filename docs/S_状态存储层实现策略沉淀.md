# S 层 — 状态存储层实现策略沉淀

> 层级：S (State Store)  
> 阶段：P1 Workflow Agent

---

## 一、设计目标回顾

### 1.1 本层定位

S 层是 Agent-Conch 的状态持久化底座。设计文档的核心原则是"状态外置"：所有运行时状态（sessions、cache、queues、registries、indexes、cursors、checkpoints）用 SQLite，不依赖模型记忆，不用 JSON/JSONL/sidecar 文件。文件系统仅用于 SKILL.md、MEMORY.md 等人类可读知识资产。

### 1.2 P1 计划能力

- SQLite 状态存储（SessionDB 基础表）
- Trajectory 持久化（轨迹保存 + 回放）
- CheckpointManager 占位（P2 完整实现）

### 1.3 核心约束

- SQLite 优先：零外部依赖，结构化查询，FTS5 全文搜索
- 不用 JSON/JSONL 做运行时状态（JSONL 仅用于轨迹导出/审计）
- 支持跨连接持久化（进程重启后状态可恢复）

---

## 二、核心实现方案

### 2.1 整体结构

```
state/
├── session_db.py     # SessionDB — SQLite 会话存储
├── trajectory.py     # TrajectoryStore — 轨迹持久化与回放
└── checkpoint.py     # CheckpointManager — 快照/恢复 (P1 占位)
```

### 2.2 SQLite Schema

```sql
-- 会话表
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    cwd         TEXT NOT NULL DEFAULT '',
    model_name  TEXT NOT NULL DEFAULT '',
    metadata    TEXT NOT NULL DEFAULT '{}'  -- JSON
);

-- 消息表
CREATE TABLE messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL,        -- system|user|assistant|tool
    content       TEXT NOT NULL DEFAULT '',
    tool_calls    TEXT,                 -- JSON array or NULL
    tool_call_id  TEXT,                 -- tool response 关联 id
    turn_index    INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- 轮次表
CREATE TABLE turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    turn_index  INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);

-- 轨迹表
CREATE TABLE trajectories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    turn_id     INTEGER,
    step_data   TEXT NOT NULL,    -- JSON
    created_at  REAL NOT NULL
);
```

索引：`idx_messages_session`, `idx_messages_turn`, `idx_turns_session`, `idx_traj_session`

### 2.3 核心类/接口

**SessionDB**：SQLite 会话存储
- 连接管理：`check_same_thread=False` 允许跨线程（配合 asyncio.to_thread）
- Session CRUD：create_session / get_session / update_session_status
- Message CRUD：add_message / get_messages / get_messages_as_dicts（LLM API 格式）
- Turn 生命周期：start_turn / finish_turn
- Trajectory 存储：save_trajectory_step / get_trajectory
- 统计：count_messages / count_turns

**TrajectoryStore**：轨迹持久化与回放
- save_step(TrajectoryStep) → int：保存单步轨迹到 SQLite
- get_steps(session_id) → list[TrajectoryStep]：从 SQLite 加载
- export_jsonl(session_id) → Path：导出为 JSONL 文件（审计/回放）
- replay(session_id_or_file) → list[TrajectoryStep]：支持 DB 或 JSONL 文件回放
- format_replay(steps) → str：格式化为可读文本

**CheckpointManager**：快照/恢复（P1 占位）
- save_checkpoint / load_checkpoint / restore — 全部 raise NotImplementedError

**TrajectoryStep**：单步轨迹数据类
- session_id, turn_index, step_type（llm_call/tool_call/tool_result/user_input）
- tool_name, tool_input, tool_output, tool_status
- duration_ms, token_usage, timestamp, metadata

### 2.4 存储目录结构

```
~/.agent-conch/
├── state.db                    # 全局 SQLite（sessions/messages/turns/trajectories）
└── trajectories/
    └── {session_id}.jsonl      # 轨迹 JSONL 导出文件
```

### 2.5 核心代码路径

- `src/agent_conch/state/session_db.py` — SessionDB + Session + Message + Turn
- `src/agent_conch/state/trajectory.py` — TrajectoryStore + TrajectoryStep
- `src/agent_conch/state/checkpoint.py` — CheckpointManager + Checkpoint (P1 占位)

---

## 三、设计落地对照

### ✅ 完全对齐设计

- SQLite 优先，零外部依赖
- sessions/messages/turns/trajectories 四张基础表
- 结构化查询（索引 + SQL 查询）
- 跨连接持久化（验证通过）
- Trajectory JSONL 导出（审计/回放）
- 轨迹回放（DB + JSONL 双源）
- 文件系统仅用于 JSONL 导出（运行时状态全在 SQLite）

### ⚠️ 调整项

| 能力项 | 设计方案 | 实际实现 | 调整原因 |
| ------ | -------- | -------- | -------- |
| 异步 DB 操作 | asyncio 原生异步 | 同步 sqlite3 + check_same_thread=False | sqlite3 stdlib 是同步 API；P1 阶段 SQLite 操作快，不阻塞 |
| FTS5 全文搜索 | 跨会话搜索历史对话 | 未实现 | P3 阶段交付物（session_search 工具） |
| Checkpoint | 完整状态序列化 | NotImplementedError 占位 | P2 交付物 |
| Agent 级状态 | agents/<id>/agent.db | 全局 state.db 统一管理 | P1 无多 Agent，P2 拆分 |

---

## 四、关键技术点与踩坑记录

### 4.1 同步 SQLite + 异步事件循环

**问题**：Agent Loop 是异步的（asyncio），但 sqlite3 stdlib 是同步 API。直接在事件循环中调用 SQLite 操作会阻塞。

**P1 解决方案**：
- `check_same_thread=False` 允许跨线程访问
- SQLite 操作通常很快（<1ms），P1 阶段直接同步调用，不阻塞事件循环
- TrajectoryStore.save_step 是同步方法，Agent Loop 中直接调用（不加 await）

**P2 演进**：如果异步场景需要非阻塞 DB，可切换到 aiosqlite（接口不变）或用 asyncio.to_thread 包装。

### 4.2 跨连接持久化验证

**关键测试**：`test_persistence_across_connections`
- 创建 SessionDB 实例 → 写入 session + message → close
- 重新打开 SessionDB → 读取 session + message → 验证数据一致

这验证了 SQLite 文件的持久化能力：进程重启后状态可恢复。

### 4.3 tool_calls JSON 序列化

**设计**：assistant 消息的 tool_calls 存为 JSON 字符串（`TEXT` 列），而非单独表。

**原因**：tool_calls 是 assistant 消息的附属信息，不需要独立查询。JSON 序列化简单且足够。

**实现**：`add_message(tool_calls=...)` 时 `json.dumps(tool_calls)`；`get_messages()` 时 `json.loads(row["tool_calls"])`。

### 4.4 轨迹存储双源设计

**设计**：轨迹同时存储在 SQLite（可查询）和 JSONL（可审计/回放）。

**原因**：
- SQLite：运行时查询（如 "查找所有失败的工具调用"）
- JSONL：审计导出（脱离 DB 独立回放）、人工检查、版本控制

**实现**：运行时轨迹写入 SQLite trajectories 表；会话结束时可选调用 `export_jsonl()` 导出。`replay()` 方法支持两种数据源。

---

## 五、验证与覆盖情况

### 5.1 测试覆盖

| 测试类 | 测试数 | 覆盖场景 |
| ------ | ------ | -------- |
| TestSessionDB | 10 | 创建/获取/不存在/状态更新/消息CRUD/tool_calls/dicts/turn生命周期/轨迹存储/计数/跨连接持久化 |
| TestTrajectoryStore | 4 | 保存加载/JSONL导出/DB回放/JSONL回放 |

### 5.2 集成测试验证

- 轨迹回放：集成测试 `test_trajectory_replay` 验证 DB 回放 + JSONL 导出 + 文件回放
- 持久化：集成测试中所有 Agent run 的消息和轨迹均持久化到 SQLite

### 5.3 未覆盖场景

- FTS5 全文搜索（P3）
- Checkpoint 保存/恢复（P2）
- Agent 级独立 DB（P2）
- 大量数据下的查询性能（P3 压测）
- 并发写入冲突处理（P2/P3）

---

## 六、演进与优化方向

### P2 演进
- CheckpointManager 完整实现（Pause/Resume 状态序列化）
- FTS5 全文搜索表（跨会话搜索历史对话）
- Agent 级独立 DB（`agents/<agent_id>/agent.db`）
- 可选迁移到 aiosqlite
- Subagent 注册表持久化

### P3 演进
- Trace 持久化（OTel → SQLite）
- Insights 报告数据聚合
- 大数据量查询优化（分页/索引优化）

### P4 演进
- 审计追踪完整决策链路
- 回归用例存储（regression_cases 表）
- 数据迁移与版本管理

### 长期演进
- 可选切换到 PostgreSQL（多用户/高并发场景）
- 数据加密（at-rest encryption）
- 数据生命周期管理（自动清理/归档）
- 分布式状态存储（多节点 Agent）

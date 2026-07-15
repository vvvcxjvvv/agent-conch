# L/S/E/G 层 — P2 实现策略沉淀

> 本文档覆盖 P2 阶段中 L 层（生命周期）、S 层（状态存储）、E 层（执行环境）、G 层（治理安全）的更新。  
> C 层单独文档：[C_上下文与记忆层实现策略沉淀_P2.md](C_上下文与记忆层实现策略沉淀_P2.md)

---

## L 层 — 生命周期与编排 (P2 更新)

### 相比 P1 的更新点

| 能力 | P1 | P2 |
|------|-----|-----|
| ErrorClassifier | 15 种 | 25 种 + 不重试集 |
| Subagent | ❌ | ✅ SQLite 注册表 + 孤儿恢复 |
| Agent Loop | 直接 DB 加载 | 接入 ContextEngine + PromptCaching |

### ErrorClassifier 扩展 (15 → 25 种)

新增 10 种：
- API: API_SERVER_ERROR(5xx) / API_BAD_REQUEST(400) / API_NOT_FOUND(404) / API_OVERLOADED(529)
- 安全: SSL_CERT_VERIFICATION(不重试)
- 工具: TOOL_VALIDATION_ERROR
- 上下文: MAX_TOKENS_EXCEEDED / CONTEXT_TOO_SHORT
- 格式: JSON_DECODE_ERROR
- 基础设施: DATABASE_ERROR / SANDBOX_TIMEOUT

新增 `_NEVER_RETRY_REASONS` 集合，显式声明不可重试的错误。

**踩坑**：`max_tokens` 和 `context window` 都可能包含 "too long"，需先检查 max_tokens。

### Subagent + 孤儿恢复

- **SQLite 注册表**：subagents 表 (subagent_id/parent_id/session_id/task/status/result)
- **生命周期**：PENDING → RUNNING → COMPLETED/FAILED/CANCELLED
- **孤儿恢复**：find_orphans（父 Agent 不存在或已完成）→ recover_orphans（标记 ORPHANED）→ adopt_orphan（新父认领）
- **安全限制**：DELEGATE_BLOCKED_TOOLS 禁止子 Agent 使用 task_manage

### Agent Loop 改造

- `__init__` 新增 `context_engine` + `prompt_caching` 参数
- `run()` 开头调用 `context_engine.bootstrap()`
- 每轮开头调用 `context_engine.maintain()` (auto-compact 检查)
- `_call_model()` 使用 `context_engine.assemble()` + `prompt_caching.apply()`
- 每轮结束调用 `context_engine.after_turn()` (记忆提取)
- `context_engine=None` 时 fallback 到 P1 行为

---

## S 层 — 状态存储 (P2 更新)

### 相比 P1 的更新点

| 能力 | P1 | P2 |
|------|-----|-----|
| Checkpoint | 占位 (NotImplementedError) | ✅ 完整实现 |
| Pause/Resume | ❌ | ✅ 完整序列化 + 恢复 |
| FTS5 元记忆 | ❌ | ✅ MetaMemory (含降级) |

### Checkpoint/Pause/Resume 完整实现

- **checkpoints 表**：session_id/turn_index/status/messages_snapshot/agent_state/context_state
- **save_checkpoint**：序列化 messages + agent_state + context_state 到 SQLite
- **restore**：清空当前消息 → 从快照重建 → 更新 session 状态
- **pause**：save_checkpoint(status="paused") + update_session_status("paused")
- **resume**：load_checkpoint → restore → update_session_status("active")

---

## E 层 — 执行环境 (P2 更新)

### 相比 P1 的更新点

| 能力 | P1 | P2 |
|------|-----|-----|
| 沙箱后端 | Local only | + Docker |
| hard_reset | ❌ | ✅ 销毁重建 |
| 快照/回滚 | ❌ | ✅ docker commit + restore |

### Docker 沙箱后端

- **DockerBackend**：容器级隔离执行（docker exec）
- **DockerConfig**：image/memory_limit/cpu_limit/network/volumes
- **hard_reset**：销毁当前容器 → 从镜像创建新容器
- **snapshot/restore**：docker commit → 从快照镜像创建新容器
- **DockerFsBridge**：通过 docker exec cat/mv/rm 操作容器内文件
- **shell_quote**：防命令注入

**注意**：代码完整但未在 Windows 实跑（需 Docker Desktop）。`is_available()` 检查 Docker 可用性。

---

## G 层 — 治理与安全 (P2 更新)

### 相比 P1 的更新点

| 能力 | P1 | P2 |
|------|-----|-----|
| 敏感路径 | 内嵌 PathValidator | ✅ 独立模块 + 跨平台 + 文件名模式 |

### 敏感路径硬编码独立模块

- **SENSITIVE_PATHS_UNIX**：/etc, /root, ~/.ssh, ~/.aws, ~/.config, ~/.gnupg 等 25+ 路径
- **SENSITIVE_PATHS_WINDOWS**：C:\Windows\System32, C:\Program Files, C:\ProgramData 等 20+ 路径
- **SENSITIVE_FILE_PATTERNS**：.env, id_rsa, .pem, .key, credentials, .npmrc 等 25+ 文件名
- **SensitivePathChecker**：硬编码不可覆盖 + 用户规则叠加 + merge_with_validator
- **is_sensitive_path()**：路径前缀匹配 + 文件名模式匹配

---

## 验证与覆盖

### P2 新增测试

| 测试文件 | 测试数 | 覆盖层 |
|---------|--------|--------|
| test_context.py | 32 | C 层 |
| test_p2.py | 32 | L/S/E/G 层 |
| **总计** | **64** | |

### P2 测试明细

- ErrorClassifier: 12 个 (SSL/5xx/529/404/400/validation/max_tokens/json/db/sandbox_timeout/总数/不重试集)
- SensitivePaths: 7 个 (Unix/SSH/env/正常/用户路径/硬编码/合并)
- Checkpoint: 5 个 (save_load/list/restore/pause_resume/delete)
- Subagent: 9 个 (spawn/start_complete/fail/cancel/list/orphans/recover/adopt/blocked_tools)

### 全量测试结果

**162 passed, 0 failed** (98 P1 + 64 P2)

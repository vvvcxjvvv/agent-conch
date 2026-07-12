# E 层 — 执行环境与沙箱层实现策略沉淀

> 层级：E (Execution Environment & Sandbox)  
> 阶段：P1 Workflow Agent

---

## 一、设计目标回顾

### 1.1 本层在整体架构中的定位

E 层是 Agent-Conch 的执行底座，负责为 Agent 提供安全、可控的命令执行和文件操作环境。所有工具层的文件操作和命令执行都通过 E 层的抽象接口完成，而非直接调用 os/pathlib/subprocess。

### 1.2 P1 计划达成的核心能力

- Local 沙箱后端（开发/个人场景，默认信任）
- FS Bridge 文件操作抽象（stat/read/write/rename，后端无关）
- PathValidator 路径安全（防路径遍历 + 敏感路径硬编码）
- SandboxRegistry 可插拔后端注册

### 1.3 核心约束与工程原则

- 约束解放：沙箱隔离 + 敏感路径硬编码
- FS Bridge 让工具层不关心后端差异

---

## 二、核心实现方案

### 2.1 整体结构

```
sandbox/
├── path_validator.py    # PathValidator — 路径安全验证
├── fs_bridge.py         # FsBridge ABC + LocalFsBridge — 文件操作抽象
├── local.py             # LocalBackend — 命令执行后端
└── registry.py          # SandboxRegistry — 后端注册与选择
```

### 2.2 核心类/接口

**PathValidator**：路径安全验证器
- 硬编码敏感路径（`/etc`, `~/.ssh`, `/.env`, `~/.config`, `~/.aws`, `~/.gnupg`, `/proc`, `/sys`, `/dev`, `C:\Windows\System32` 等）
- 用户自定义敏感路径叠加
- `allowed_roots` 白名单限制
- 写操作额外检查（不允许写到敏感路径的父目录）
- 双重检查机制：原始字符串模式匹配 + resolved 路径精确比较

**FsBridge (ABC)**：文件系统桥接抽象
- 7 个抽象方法：stat / read / write / rename / delete / list_dir / makedirs
- 所有操作经过 PathValidator 安全校验

**LocalFsBridge**：本地文件系统实现
- 基于 pathlib，所有操作先经 PathValidator.validate_or_raise

**LocalBackend (SandboxBackend)**：本地命令执行后端
- `execute(command, cwd, timeout, env)` → CommandResult
- 使用 asyncio.create_subprocess_shell 异步执行
- 支持超时控制（TimeoutError → kill 进程）

**SandboxRegistry**：沙箱后端注册表
- 三种模式：NON_MAIN（子会话用沙箱）/ ALWAYS（始终沙箱）/ NEVER（无沙箱）
- `get_backend(session_id, is_main)` 根据模式选择后端
- P1 阶段所有模式退化为 LocalBackend

### 2.3 关键业务流程

```
工具层调用 → FsBridge.read/write → PathValidator.validate → 
  ├── allowed → 执行文件操作
  └── blocked → 返回 PermissionError

工具层执行命令 → LocalBackend.execute → 
  PathValidator.validate_or_raise(cwd) → asyncio.create_subprocess_shell → 
  asyncio.wait_for(timeout) → CommandResult
```

### 2.4 核心代码文件路径索引

- `src/agent_conch/sandbox/path_validator.py` — PathValidator + SENSITIVE_PATH_PATTERNS
- `src/agent_conch/sandbox/fs_bridge.py` — FsBridge ABC + LocalFsBridge + FileStat
- `src/agent_conch/sandbox/local.py` — SandboxBackend ABC + LocalBackend + CommandResult
- `src/agent_conch/sandbox/registry.py` — SandboxRegistry + SandboxMode

---

## 三、设计落地对照

### ✅ 完全对齐设计的能力项

- FsBridge 统一接口（stat/read/write/rename）：设计 4 个方法，实际实现 7 个（增加 delete/list_dir/makedirs）
- LocalBackend 本地执行：完全对齐
- PathValidator 防路径遍历 + 敏感路径硬编码：完全对齐
- SandboxRegistry 可插拔：完全对齐
- 资源配额（timeout）：完全对齐

### ⚠️ 调整/简化/增强的能力项

| 能力项 | 设计方案 | 实际实现 | 调整原因 |
| ------ | -------- | -------- | -------- |
| SandboxRegistry NON_MAIN 模式 | 子会话用 Docker | 退化为 Local | Docker 后端是 P2 交付物 |
| 敏感路径检查 | resolved 路径精确比较 | 增加原始字符串模式匹配 | Windows 上 resolve 行为不同，需双重检查 |
| 快照/回滚 | Docker commit | 未实现 | 依赖 Docker 后端，P2/P4 |

---

## 四、关键技术点与踩坑记录

### 4.1 Windows 路径 resolve 兼容性

**问题**：在 Windows 上，`Path("/etc").resolve()` 返回 `C:\etc`，但 `Path("/etc/passwd").resolve()` 也返回 `C:\etc\passwd`。`relative_to` 比较应该能匹配，但实际测试中敏感路径检查失败。

**根因**：Windows 路径 resolve 行为不稳定，且 `relative_to` 区分大小写。当路径不存在时（如 `C:\etc`），resolve 不会规范化大小写。

**解决方案**：双重检查机制
1. 原始字符串模式匹配（`normalized_path.startswith(pattern)`）— 跨平台兼容
2. resolved 路径精确比较（`relative_to`）— 作为补充

### 4.2 asyncio.create_subprocess_shell 在 Windows 上的行为

**问题**：`pwd` 命令在 Windows Git Bash 下返回 Unix 风格路径（`/c/Users/...`），与 Python 的 `str(Path(...))` 格式不一致。

**解决方案**：测试中使用目录名匹配而非完整路径匹配。实际使用中，工具返回的 stdout 直接传给 LLM，路径格式差异不影响 LLM 理解。

### 4.3 并发安全

**设计决策**：SQLite 使用 `check_same_thread=False`，允许跨线程访问（配合 asyncio.to_thread）。SQLite 的单写者模型保证了并发安全。

---

## 五、验证与覆盖情况

### 5.1 验证范围

| 测试类 | 测试数 | 覆盖场景 |
| ------ | ------ | -------- |
| TestPathValidator | 8 | 正常路径、敏感路径、SSH 路径、env 文件、allowed_roots、写父目录、用户自定义、raise |
| TestLocalFsBridge | 7 | read/write/stat/nonexistent/rename/list_dir/delete |
| TestLocalBackend | 6 | echo/exit_code/cwd/timeout/stderr/pytest |

### 5.2 未覆盖的边界场景

- Docker 后端（P2 实现）
- SSH 远程后端（P2 实现）
- 快照/回滚（P4 实现）
- 网络白名单（P3 实现）
- gVisor 隔离（P4 实现）

---

## 六、演进与优化方向

### P2 演进
- 实现 DockerBackend + DockerFsBridge
- SandboxRegistry NON_MAIN 模式真正切换到 Docker
- 实现 Docker commit 快照/回滚

### P3 演进
- 网络白名单（容器级网络隔离）
- gVisor 级别隔离（P4）

### 长期演进
- SSH 远程后端（跨机器执行）
- 云端沙箱（AWS Lambda / Cloud Run）
- 快照链管理（多检查点回溯）

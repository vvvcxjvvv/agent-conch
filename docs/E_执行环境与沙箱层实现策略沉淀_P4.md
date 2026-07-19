# E 执行环境与沙箱层实现策略沉淀（P4 增量）

## 一、设计目标回顾

E 层负责受控执行、文件桥接和可恢复环境。P4 目标是 Docker commit 快照/restore，并为 Electron Desktop 提供本地文件与终端桥接；执行不得绕过敏感路径、RBAC 和策略治理。

## 二、核心实现方案

`SnapshotManager → SandboxRegistry → DockerBackend snapshot/restore/remove`。快照外部引用和状态存入 SQLite；Manager 同时兼容同步测试后端与异步 Docker 后端。Electron 仅暴露文件/目录选择、通知和终端 IPC，终端请求发送 `POST /desktop/terminal`，再由 ToolRegistry 执行。

- `src/agent_conch/sandbox/snapshots.py`
- `src/agent_conch/sandbox/docker.py`
- `src/agent_conch/api/server.py`
- `apps/desktop/main.cjs`、`preload.cjs`

## 三、设计落地对照

- ✅ Docker commit、restore、delete 的状态闭环已接线。
- ✅ Electron 复用 Web Console，关闭 Node integration，启用 context isolation 与 sandbox。
- ✅ 终端命令继承路径验证、PolicyEngine、预算和轨迹审计。
- ⚠️ 安装包签名/公证不属于 P4 交付表，未实现。

## 四、关键技术点与踩坑记录

最初 SnapshotManager 同步调用异步 Docker 接口，假后端测试未暴露问题。验收时改为 awaitable 检测并统一异步 API，同时把专项测试后端改成 async，避免再次出现“协程字符串被持久化”。Electron 不直接执行 shell，防止形成第二条无治理执行链。

## 五、验证与覆盖情况

快照 create/restore/delete、异步后端适配、Desktop 低权限拒绝、命令执行、预算计数与 trajectory 写入均有 P4 测试。真实 Docker daemon 用例因本机无 daemon 条件跳过；Electron main/preload 语法检查通过。

## 六、演进与优化方向

增加真实 Docker 快照 CI、快照保留/配额策略、Electron 打包签名和多平台冒烟；远期可增加 gVisor backend，但保持 SandboxBackend 契约不变。

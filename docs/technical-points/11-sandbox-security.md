# 11 · 沙箱与安全治理

> 安全 day-one。Agent 能执行 bash 的第一天，就必须有权限分级与审计。

## 沙箱加固基线（MVP）

Docker 默认配置，进入 MVP：

| 加固项 | 配置 | 说明 |
|---|---|---|
| CPU 限制 | `--cpus=2` | 防止死循环吃满 CPU |
| 内存限制 | `--memory=512m` | 防止内存泄漏拖垮宿主 |
| 网络限制 | `--network=none`（默认） | 默认禁网，按需开放 |
| 禁用特权 | `--privileged=false` | 禁止容器提权 |
| 只读挂载 | `--read-only` + tmpfs | 系统目录只读，工作区 tmpfs |

可选强隔离：
- **Firecracker**（Linux）：microVM，更强隔离
- **WSL2**（Windows）：基于 Hyper-V 的隔离

```python
class DockerSandbox:
    def __init__(self, image="python:3.12-slim", cpus=2, memory="512m",
                 network="none", privileged=False, read_only=True):
        self.config = {
            "image": image,
            "cpus": cpus,
            "memory": memory,
            "network": network,
            "privileged": privileged,
            "read_only": read_only,
        }

    async def run_command(self, cmd: str, timeout: int = 30) -> dict:
        """在沙箱内执行命令，返回 stdout/stderr/exit_code"""
        ...
```

> 没有 Docker 环境时降级为本地执行（带告警），MVP 优先保证可跑。

## 权限模型（MVP: allowlist）

MVP 使用 allowlist 权限模型，简单有效：

```python
class AllowlistPerms(GovernanceProvider):
    def __init__(self, tools: list[str]):
        self.allowed = set(tools)

    def check_permission(self, tool: str, args: dict) -> bool:
        return tool in self.allowed
```

```yaml
# Profile 配置
governance:
  impl: allowlist_perms
  params:
    tools: [read_file, write_file, run_bash, list_files]
```

> **RBAC 延后**：admin/executor/reader 角色模型 + 工具级/文件级/网络级权限粒度 + 主体继承/临时授权，属 L4 企业级，延后。

## 审计日志

所有工具调用、文件操作、权限变更全链路落盘：

```python
class AllowlistPerms:
    def audit(self, action: str, detail: dict):
        log_entry = {
            "timestamp": now(),
            "action": action,       # "tool_call" / "file_write" / "perm_change"
            "detail": detail,       # 工具名、参数、结果、是否允许
            "trace_id": current_trace_id,
        }
        self._append_audit_log(log_entry)
```

> **哈希防篡改延后**：MVP 记录明文日志即可，哈希校验防篡改等有合规场景时再加（L4）。

## 权限校验流程

```
Agent 决策调用工具
    │
    ▼
pre_tool Hook（安全审计可中断）
    │
    ▼
Governance.check_permission(tool, args)
    │
    ├── 允许 → 执行工具
    │
    └── 拒绝 → 返回 PermissionDenied + 审计日志
```

## 约束与恢复（域8）

### 自定义 Linter + 修复指令

报错自带修复方法（OpenAI P0 实践）：

```python
class Linter(ConstraintProvider):
    def validate(self, action, state):
        if action["type"] == "tool_call" and action["tool"] == "write_file":
            content = action["args"].get("content", "")
            issues = self._check(content)
            if issues:
                return {
                    "valid": False,
                    "fix_hint": f"Found issues: {issues}. Suggested fix: ...",
                }
        return {"valid": True}
```

### 重试/回滚/降级

失败时提供恢复路径：
- **重试**：工具调用失败自动重试（最多 N 次）
- **回滚**：文件操作失败回滚到操作前状态
- **降级**：cost guard 触发时降级（见 12-cost-guard.md）

## 相关文件

- `conch/runtime/sandbox/docker_sandbox.py`
- `conch/domains/governance/allowlist.py`
- `conch/domains/constraint/linter.py`

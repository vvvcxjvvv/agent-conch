# 07 · 工具系统与 MCP

> 工具接口应为 Agent 而设计，而非直接沿用给人用的 API。

## 核心原则（Anthropic）

1. **最小可行工具集**：工具自包含、容错、用途明确，避免功能重叠
2. **Token 高效**：工具返回的信息应 token 高效
3. **输入参数设计**：参数应具有描述性、无歧义
4. **避免工具膨胀**：最常见的失败模式是工具集过于臃肿

> 如果人类工程师都无法确定某个场景该用哪个工具，AI agent 更做不到。

## 统一工具描述

```python
@dataclass
class Tool:
    name: str                    # 工具名，如 "read_file"
    description: str             # 给 Agent 看的描述
    params_schema: dict          # JSON Schema 参数描述
    permissions: list[str]       # 所需权限，如 ["file:read"]
```

## MCP 原生对齐（v0.3）

工具域核心接口**对齐 MCP（Model Context Protocol）协议规范**：

- 外部 MCP Server 可直连，无需额外适配
- AgentConch 工具自动转换为 MCP Tool 格式
- 未来支持插件导出为 MCP Server，复用到其他生态

```python
# MCP Server 直连示例
mcp_tools = mcp_adapter.import_server("http://localhost:3000")
# mcp_tools 已是标准 Tool 列表，直接注册到 Registry
```

## 工具执行流程

```
Agent 决策调用工具
    │
    ▼
pre_tool Hook（安全审计可中断）
    │
    ▼
Governance 权限校验（check_permission）
    │  └→ 拒绝 → 返回 PermissionDenied
    ▼
ToolProvider.execute(tool, args, state)
    │
    ▼
post_tool Hook（审计日志）
    │
    ▼
工具结果经中间件链 token 优化
    │
    ▼
结果入上下文
```

## 工具结果处理

### 即时上下文

工具返回大量数据时，不全部放入上下文，而是保留引用，Agent 按需读取。

### 工具结果清理

深层历史中的工具结果移除——一旦工具在消息历史深处被调用过，Agent 无需再看到原始结果。

## 内置工具（MVP）

| 工具 | 功能 | 权限 |
|---|---|---|
| `read_file` | 读取文件内容 | `file:read` |
| `write_file` | 写入文件 | `file:write` |
| `run_bash` | 执行 shell 命令（沙箱内） | `shell:exec` |
| `list_files` | 列出目录内容 | `file:read` |

## 接口

```python
class ToolProvider(ExtensionPoint, Protocol):
    def tools_for(self, task, state) -> list[Tool]: ...
    async def execute(self, tool: str, args: dict, state) -> ToolResult: ...
```

## 相关文件

- `conch/core/extension.py` — ToolProvider 接口
- `conch/domains/tool/builtin_shell.py` — 默认实现
- `docs/technical-points/11-sandbox-security.md` — 沙箱与权限

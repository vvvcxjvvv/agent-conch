# 05 — 工具系统：MCP Provider + builtin_shell

> **代码位置**：`backend/conch/adapters/tool/mcp_provider.py`（120 行）、`builtin_shell.py`（195 行）
> **对应 ETCLOVG**：T 层（工具与执行）

## 1. MCPToolProvider（默认工具源）

连接 Anthropic Model Context Protocol (MCP) server，发现工具 → 执行 → 结果格式化。

### 实现原理

```python
@registry.register("tool", "mcp_provider", "1.0")
class MCPToolProvider(Plugin):
    def __init__(self, servers: list[dict] | None = None):
        self.servers = servers or []      # MCP server 配置列表
        self._sessions: list = []          # 活跃 MCP session
        self._tools: list[dict] = []       # 缓存工具定义

    async def on_load(self):
        """连接所有 MCP server，发现工具"""
        for srv_cfg in self.servers:
            params = StdioServerParameters(**srv_cfg)
            session = ClientSession(params)
            await session.connect()
            tools = await session.list_tools()
            for tool in tools.tools:
                self._tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                    "session": session,     # 绑定 session 引用
                })
```

### 工具格式转换：MCP Tool → LangChain Tool

```python
def _mcp_to_langchain_tool(self, mcp_tool):
    """动态构建 LangChain StructuredTool"""
    return StructuredTool.from_function(
        coroutine=make_func(name, session),
        name=mcp_tool["name"],
        description=mcp_tool["description"],
    )
```

转换后的 `StructuredTool` 可直接传给 `create_react_agent(tools=...)`。

### Profile 配置

```yaml
domains:
  tool:
    impl: mcp_provider
    params:
      servers:
        - command: "npx"
          args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
```

支持多个 MCP server，聚合所有工具。`on_unload()` 断开所有 session。

## 2. BuiltinShellProvider（轻量内置工具）

v1 迁移，提供四个内置工具，不依赖 MCP SDK。

```python
@registry.register("tool", "builtin_shell", "1.0")
class BuiltinShellProvider(Plugin):
    # 四个工具:
    def read_file(path)    # 读取文件
    def write_file(path, content)  # 写入文件
    def run_bash(command)  # 执行 shell（可选 Docker 沙箱）
    def list_files(path)   # 列出目录
```

`run_bash` 通过 `DockerSandbox` 隔离执行（`docker_sandbox.py`），无 Docker 时降级本地执行。

## 3. 工具调用全链路

```
用户输入
  └─ LangGraphReActOrchestrator.run()
       └─ graph.astream_events(v2)
            └─ on_tool_start:
                 ├─ LangGraphHookBridge → hook_bus.fire("pre_tool", ...)
                 │    └─ 护栏检查: GuardrailPipeline.check_tool(tool, args)
                 │         └─ blocked → HookInterrupted → 工具跳过
                 ├─ ToolProvider.execute(tool, args, state)
                 │    └─ MCP session.call_tool(tool, args)
                 │         └─ 返回 ToolResult
                 └─ on_tool_end:
                      ├─ LangGraphHookBridge → hook_bus.fire("post_tool", ...)
                      └─ SSE > tool_result → 前端
```

## 4. 加载使用方式

```python
# API 层 deps.py: build_runtime()
if "tool" in profile.domains:
    rt.tools = registry.build("tool", cfg.impl, cfg.version, **cfg.params)

# chat.py (SSE 端点):
tools = rt.tools.tools_for(task, rt.state)  # → LangChain Tool 列表
rt.orchestrator.build_graph(tools, sys_prompt)  # 注入编排图
```

## 5. 可扩展点

- 新工具源 → 实现 `ToolProvider.tools_for/execute` + `@register("tool", ...)`
- 新 MCP server → Profile 中 servers 列表追加一项，零代码改动
- 工具沙箱 → `BuiltinShellProvider` 扩展 `run_bash` 的 Docker 配置
- 工具权限 → `GovernanceProvider.check_permission` 与 Hook `pre_tool` 联动

"""MCP 工具提供者 — 连接 MCP Server，发现并执行工具。

默认连接 @modelcontextprotocol/server-filesystem（文件读写）。
可配置多个 MCP server，聚合所有工具。

工具格式转换: MCP tool → LangChain Tool（供 LangGraph create_react_agent 使用）
"""

from __future__ import annotations

import logging
from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry

logger = logging.getLogger(__name__)


@registry.register("tool", "mcp_provider", "1.0")
class MCPToolProvider(Plugin):
    """MCP 工具提供者。

    Args:
        servers: MCP server 配置列表，每项格式:
            {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]}
    """

    domain = "tool"
    name = "mcp_provider"
    version = "1.0"
    metadata = {
        "capabilities": ["file_io", "mcp"],
        "description": "MCP 工具提供者（连接 MCP Server）",
    }

    def __init__(self, servers: list[dict] | None = None):
        self.servers = servers or []
        self._sessions: list[Any] = []
        self._tools: list[dict] = []  # 缓存 MCP tool 定义

    async def on_load(self) -> None:
        """连接所有 MCP server，发现工具。"""
        if not self.servers:
            logger.warning("MCPToolProvider: no servers configured")
            return

        try:
            from mcp import ClientSession, StdioServerParameters
        except ImportError:
            logger.error("mcp package not installed. Run: pip install mcp")
            return

        for srv_cfg in self.servers:
            try:
                params = StdioServerParameters(**srv_cfg)
                # MCP SDK 的连接是 contextmanager，MVP 简化为持久 session
                session = ClientSession(params)
                await session.connect()
                self._sessions.append(session)
                tools_result = await session.list_tools()
                for tool in tools_result.tools:
                    self._tools.append({
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema or {},
                        "session": session,
                    })
                logger.info("MCP server connected: %s (%d tools)",
                            srv_cfg.get("command"), len(tools_result.tools))
            except Exception:
                logger.exception("Failed to connect MCP server: %s", srv_cfg)

    async def on_unload(self) -> None:
        """断开所有 MCP session。"""
        for session in self._sessions:
            try:
                await session.close()
            except Exception:
                pass
        self._sessions.clear()
        self._tools.clear()

    def tools_for(self, task: Any, state: Any) -> list[Any]:
        """返回当前可用的 LangChain Tool 列表。"""
        return [self._mcp_to_langchain_tool(t) for t in self._tools]

    async def execute(self, tool: str, args: dict, state: Any) -> Any:
        """执行指定 MCP 工具。"""
        for t in self._tools:
            if t["name"] == tool:
                session = t["session"]
                result = await session.call_tool(tool, args)
                return result
        raise KeyError(f"Tool '{tool}' not found in MCP tools")

    def _mcp_to_langchain_tool(self, mcp_tool: dict) -> Any:
        """将 MCP tool 转为 LangChain Tool 格式（供 LangGraph 使用）。"""
        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel, create_model

        name = mcp_tool["name"]
        description = mcp_tool["description"]
        schema = mcp_tool["input_schema"]

        # 从 JSON schema 动态构建 pydantic 模型
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # 简化：用 kwargs 接收所有参数
        def make_func(tool_name: str, mcp_session: Any):
            async def _call(**kwargs):
                result = await mcp_session.call_tool(tool_name, kwargs)
                # 提取文本内容
                if hasattr(result, "content"):
                    parts = []
                    for c in result.content:
                        if hasattr(c, "text"):
                            parts.append(c.text)
                    return "\n".join(parts)
                return str(result)
            return _call

        return StructuredTool.from_function(
            coroutine=make_func(name, mcp_tool["session"]),
            name=name,
            description=description,
        )

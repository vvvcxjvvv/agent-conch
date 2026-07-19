"""T 层：MCP stdio 客户端、连接管理与动态工具适配。"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from agent_conch.tools.base import BaseTool, ToolResult


@dataclass(frozen=True)
class MCPServerSpec:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPServerSpec:
        return cls(
            name=str(data["name"]),
            command=str(data["command"]),
            args=[str(item) for item in data.get("args", [])],
            env={str(key): str(value) for key, value in dict(data.get("env", {})).items()},
            cwd=str(data["cwd"]) if data.get("cwd") else None,
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class MCPConnection:
    spec: MCPServerSpec
    task: asyncio.Task[None]
    queue: asyncio.Queue[_MCPRequest | None]
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _MCPRequest:
    operation: str
    arguments: dict[str, Any]
    future: asyncio.Future[Any]


class MCPClient:
    def __init__(self, servers: list[MCPServerSpec] | None = None) -> None:
        self.servers = {item.name: item for item in servers or []}
        self.connections: dict[str, MCPConnection] = {}
        self.errors: dict[str, str] = {}
        self._pending: dict[str, asyncio.Future[MCPConnection]] = {}

    async def connect(self, name: str) -> MCPConnection:
        existing = self.connections.get(name)
        if existing is not None:
            return existing
        pending = self._pending.get(name)
        if pending is not None:
            return await asyncio.shield(pending)
        spec = self.servers.get(name)
        if spec is None:
            raise KeyError(f"MCP server not configured: {name}")
        if not spec.enabled:
            raise ValueError(f"MCP server is disabled: {name}")

        queue: asyncio.Queue[_MCPRequest | None] = asyncio.Queue()
        ready: asyncio.Future[MCPConnection] = asyncio.get_running_loop().create_future()
        self._pending[name] = ready
        task = asyncio.create_task(self._serve(spec, queue, ready), name=f"mcp:{name}")
        try:
            return await ready
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        finally:
            self._pending.pop(name, None)

    async def _serve(
        self,
        spec: MCPServerSpec,
        queue: asyncio.Queue[_MCPRequest | None],
        ready: asyncio.Future[MCPConnection],
    ) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        connection: MCPConnection | None = None
        try:
            parameters = StdioServerParameters(
                command=spec.command,
                args=spec.args,
                env=spec.env or None,
                cwd=spec.cwd,
            )
            async with (
                stdio_client(parameters) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                task = asyncio.current_task()
                if task is None:
                    raise RuntimeError("MCP supervisor task is unavailable")
                connection = MCPConnection(spec, task, queue)
                connection.tools = self._tool_payloads(await session.list_tools())
                self.connections[spec.name] = connection
                self.errors.pop(spec.name, None)
                ready.set_result(connection)
                while True:
                    request = await queue.get()
                    if request is None:
                        break
                    try:
                        if request.operation == "list":
                            connection.tools = self._tool_payloads(await session.list_tools())
                            request.future.set_result(list(connection.tools))
                        elif request.operation == "call":
                            response = await session.call_tool(
                                str(request.arguments["tool"]),
                                dict(request.arguments.get("arguments", {})),
                            )
                            request.future.set_result(
                                self._tool_result(
                                    spec.name,
                                    str(request.arguments["tool"]),
                                    response,
                                )
                            )
                        else:
                            raise ValueError(f"Unknown MCP operation: {request.operation}")
                    except BaseException as exc:
                        if not request.future.done():
                            request.future.set_exception(exc)
        except BaseException as exc:
            self.errors[spec.name] = str(exc) or exc.__class__.__name__
            if not ready.done():
                ready.set_exception(exc)
            while not queue.empty():
                request = queue.get_nowait()
                if request is not None and not request.future.done():
                    request.future.set_exception(exc)
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            if connection is not None and self.connections.get(spec.name) is connection:
                self.connections.pop(spec.name, None)

    async def disconnect(self, name: str) -> None:
        connection = self.connections.pop(name, None)
        if connection is not None:
            await connection.queue.put(None)
            await asyncio.gather(connection.task, return_exceptions=True)

    async def close_all(self) -> None:
        for name in list(self.connections):
            await self.disconnect(name)

    async def refresh(self, name: str) -> list[dict[str, Any]]:
        connection = self.connections.get(name) or await self.connect(name)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        await connection.queue.put(_MCPRequest("list", {}, future))
        return list(await future)

    @staticmethod
    def _tool_payloads(response: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": str(tool.name),
                "description": str(tool.description or ""),
                "input_schema": dict(tool.inputSchema),
                "annotations": (
                    tool.annotations.model_dump(mode="json", by_alias=True, exclude_none=True)
                    if tool.annotations is not None
                    else {}
                ),
            }
            for tool in response.tools
        ]

    async def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> ToolResult:
        connection = self.connections.get(server) or await self.connect(server)
        future: asyncio.Future[ToolResult] = asyncio.get_running_loop().create_future()
        await connection.queue.put(
            _MCPRequest("call", {"tool": tool, "arguments": arguments}, future)
        )
        return await future

    @staticmethod
    def _tool_result(server: str, tool: str, response: Any) -> ToolResult:
        parts: list[str] = []
        for item in response.content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
            else:
                payload = item.model_dump(mode="json", by_alias=True, exclude_none=True)
                parts.append(json.dumps(payload, ensure_ascii=False))
        return ToolResult(
            content="\n".join(parts),
            is_error=bool(response.isError),
            metadata={"mcp_server": server, "mcp_tool": tool},
            structured=response.structuredContent,
        )

    def adapters(self, name: str) -> list[MCPToolAdapter]:
        connection = self.connections.get(name)
        if connection is None:
            return []
        return [
            MCPToolAdapter(
                self,
                name,
                str(item["name"]),
                str(item["description"]),
                dict(item["input_schema"]),
                dict(item.get("annotations", {})),
            )
            for item in connection.tools
        ]

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "command": spec.command,
                "enabled": spec.enabled,
                "connected": name in self.connections,
                "error": self.errors.get(name, ""),
                "tools": list(self.connections[name].tools) if name in self.connections else [],
            }
            for name, spec in sorted(self.servers.items())
        ]


class _MCPInput(BaseModel):
    pass


class MCPToolAdapter(BaseTool):
    input_model = _MCPInput
    is_core = False
    tags = ["mcp", "external"]

    def __init__(
        self,
        client: MCPClient,
        server: str,
        remote_name: str,
        description: str,
        input_schema: dict[str, Any],
        annotations: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.server = server
        self.remote_name = remote_name
        self.name = "mcp__" + self._safe_name(server) + "__" + self._safe_name(remote_name)
        self.description = description or f"MCP tool {server}/{remote_name}"
        self.input_schema = input_schema
        self.annotations = dict(annotations or {})
        self.is_write_tool = bool(
            self.annotations.get("destructiveHint") or self.annotations.get("readOnlyHint") is False
        )
        self.governance_action = "network"

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        }

    def validate_input(self, **kwargs: Any) -> dict[str, Any]:
        required = [str(item) for item in self.input_schema.get("required", [])]
        missing = [name for name in required if name not in kwargs]
        if missing:
            raise ValueError("Missing required MCP arguments: " + ", ".join(missing))
        return dict(kwargs)

    async def execute(self, **kwargs: Any) -> ToolResult:
        return await self.client.call_tool(self.server, self.remote_name, kwargs)

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "_", value)[:64]

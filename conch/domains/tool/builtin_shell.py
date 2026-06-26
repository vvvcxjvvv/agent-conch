"""域2：内置 shell 工具集。

提供 read_file / write_file / run_bash / list_files 四个基础工具，
工具描述统一格式：name / description / params_schema / permissions。
对齐 MCP 工具描述规范。
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry


# 统一格式工具定义
TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "读取指定路径的文件内容",
        "params_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
            },
            "required": ["path"],
        },
        "permissions": ["read"],
    },
    {
        "name": "write_file",
        "description": "向指定路径写入内容（覆盖写入）",
        "params_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "写入内容"},
            },
            "required": ["path", "content"],
        },
        "permissions": ["write"],
    },
    {
        "name": "run_bash",
        "description": "在沙箱中执行 bash 命令",
        "params_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"},
                "cwd": {"type": "string", "description": "工作目录（可选）"},
            },
            "required": ["command"],
        },
        "permissions": ["execute"],
    },
    {
        "name": "list_files",
        "description": "列出目录下的文件（支持 glob 模式）",
        "params_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径"},
                "pattern": {"type": "string", "description": "glob 模式，默认 *"},
            },
            "required": ["path"],
        },
        "permissions": ["read"],
    },
]


@registry.register("tool", "builtin_shell", "1.0")
class BuiltinShellProvider(Plugin):
    """内置 shell 工具集 — 文件读写与命令执行。

    Args:
        sandbox: 沙箱类型，"local" 本地执行，"docker" Docker 沙箱
        cwd: 默认工作目录
        timeout: 命令执行超时（秒）
    """

    domain = "tool"
    name = "builtin_shell"
    version = "1.0"
    metadata = {
        "cost": "low",
        "context_save": "low",
        "capabilities": ["file_io", "command_exec"],
        "description": "内置 shell 工具集：read_file/write_file/run_bash/list_files",
    }

    def __init__(
        self,
        sandbox: str = "local",
        cwd: str = ".",
        timeout: int = 30,
    ):
        self.sandbox_type = sandbox
        self.cwd = Path(cwd)
        self.timeout = timeout
        self._sandbox = None  # 延迟构建沙箱

    def on_load(self) -> None:
        # 根据配置选择沙箱
        if self.sandbox_type == "docker":
            try:
                from conch.runtime.sandbox.docker_sandbox import DockerSandbox
                self._sandbox = DockerSandbox(timeout=self.timeout)
            except Exception:
                # Docker 不可用时降级为本地执行
                self._sandbox = None

    def tools_for(self, task: Any, state: Any) -> list[Any]:
        """返回所有内置工具的定义（深拷贝避免外部修改）。"""
        return [dict(t) for t in TOOL_DEFINITIONS]

    async def execute(self, tool: str, args: dict, state: Any) -> Any:
        """执行工具调用，返回结果字典。"""
        if tool == "read_file":
            return self._read_file(args)
        if tool == "write_file":
            return self._write_file(args)
        if tool == "run_bash":
            return await self._run_bash(args)
        if tool == "list_files":
            return self._list_files(args)
        return {"error": f"Unknown tool: {tool}"}

    def _read_file(self, args: dict) -> dict:
        path = Path(args.get("path", ""))
        if not path.exists():
            return {"error": f"File not found: {path}"}
        try:
            content = path.read_text(encoding="utf-8")
            return {"content": content, "path": str(path), "bytes": len(content)}
        except Exception as e:
            return {"error": str(e)}

    def _write_file(self, args: dict) -> dict:
        path = Path(args.get("path", ""))
        content = args.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(path), "bytes": len(content)}
        except Exception as e:
            return {"error": str(e)}

    async def _run_bash(self, args: dict) -> dict:
        command = args.get("command", "")
        cwd = args.get("cwd", str(self.cwd))
        if not command:
            return {"error": "command is required"}

        # 优先用 Docker 沙箱
        if self._sandbox is not None:
            return await self._sandbox.run_command(command, cwd=cwd, timeout=self.timeout)

        # 本地执行（降级路径）
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd if Path(cwd).exists() else None,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {"error": f"Command timed out after {self.timeout}s"}
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
            }
        except Exception as e:
            return {"error": str(e)}

    def _list_files(self, args: dict) -> dict:
        path = Path(args.get("path", "."))
        pattern = args.get("pattern", "*")
        if not path.exists():
            return {"error": f"Path not found: {path}"}
        try:
            files = sorted(str(p) for p in path.glob(pattern))
            return {"files": files, "count": len(files)}
        except Exception as e:
            return {"error": str(e)}

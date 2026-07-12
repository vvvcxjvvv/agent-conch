"""T 层核心工具: bash — Shell 命令执行."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_conch.sandbox.local import SandboxBackend
from agent_conch.tools.base import BaseTool, ToolResult


class BashInput(BaseModel):
    command: str = Field(..., description="Shell command to execute")
    cwd: str | None = Field(None, description="Working directory (default: session cwd)")
    timeout: int = Field(120, description="Timeout in seconds")


class BashTool(BaseTool):
    """Shell 命令执行工具."""

    name = "bash"
    description = (
        "Execute a shell command and return stdout, stderr, and exit code. "
        "Use for running tests, building projects, git operations, etc."
    )
    input_model = BashInput
    is_write_tool = True
    is_dangerous = True
    is_core = True
    tags = ["exec", "shell", "command"]

    def __init__(self, sandbox: SandboxBackend):
        self.sandbox = sandbox

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = BashInput(**kwargs)
        result = await self.sandbox.execute(
            command=validated.command,
            cwd=validated.cwd,
            timeout=validated.timeout,
        )
        output_parts: list[str] = []
        if result.stdout:
            output_parts.append(f"stdout:\n{result.stdout}")
        if result.stderr:
            output_parts.append(f"stderr:\n{result.stderr}")
        output_parts.append(f"exit_code: {result.exit_code}")
        if result.timed_out:
            output_parts.append(f"[TIMED OUT after {result.timeout}s]")

        content = "\n".join(output_parts)
        is_error = result.exit_code != 0
        return ToolResult(
            content=content,
            is_error=is_error,
            metadata={
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "timed_out": result.timed_out,
                "cwd": result.cwd,
            },
        )

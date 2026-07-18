"""T 层核心工具: read_file — 文件读取."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_conch.sandbox.fs_bridge import FsBridge
from agent_conch.tools.base import BaseTool, ToolResult


class ReadFileInput(BaseModel):
    file_path: str = Field(..., description="Path to the file to read")
    offset: int = Field(0, description="Byte offset to start reading from")
    limit: int = Field(-1, description="Max bytes to read (-1 = read all)")


class ReadFileTool(BaseTool):
    """文件读取工具."""

    name = "read_file"
    description = (
        "Read the contents of a file. Returns the file content as text. "
        "Supports offset and limit for partial reads."
    )
    input_model = ReadFileInput
    is_write_tool = False
    is_core = True
    tags = ["file", "read"]

    def __init__(self, fs: FsBridge):
        self.fs = fs

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = ReadFileInput(**kwargs)
        try:
            data = await self.fs.read(
                validated.file_path,
                offset=validated.offset,
                limit=validated.limit,
            )
            content = data.decode("utf-8", errors="replace")
            stat = await self.fs.stat(validated.file_path)
            # 截断超长输出
            max_chars = 50000
            truncated = False
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n... [truncated, {len(content)} total chars]"
                truncated = True
            return ToolResult(
                content=content,
                metadata={
                    "file_path": validated.file_path,
                    "size": stat.size,
                    "truncated": truncated,
                },
            )
        except PermissionError as e:
            return ToolResult.error(f"Permission denied: {e!s}")
        except FileNotFoundError:
            return ToolResult.error(f"File not found: {validated.file_path}")
        except Exception as e:
            return ToolResult.error(f"Read error: {e!s}")

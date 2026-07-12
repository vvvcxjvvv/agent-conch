"""T 层核心工具: write_file — 文件写入."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_conch.sandbox.fs_bridge import FsBridge
from agent_conch.tools.base import BaseTool, ToolResult


class WriteFileInput(BaseModel):
    file_path: str = Field(..., description="Path to the file to write")
    content: str = Field(..., description="Content to write to the file")


class WriteFileTool(BaseTool):
    """文件写入工具 (覆盖写入)."""

    name = "write_file"
    description = (
        "Write content to a file. Overwrites existing content. "
        "Creates the file if it does not exist (including parent directories)."
    )
    input_model = WriteFileInput
    is_write_tool = True
    is_core = True
    tags = ["file", "write"]

    def __init__(self, fs: FsBridge):
        self.fs = fs

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = WriteFileInput(**kwargs)
        try:
            await self.fs.write(validated.file_path, validated.content.encode("utf-8"))
            return ToolResult(
                content=f"Successfully wrote {len(validated.content)} chars to {validated.file_path}",
                metadata={
                    "file_path": validated.file_path,
                    "bytes_written": len(validated.content.encode("utf-8")),
                },
            )
        except PermissionError as e:
            return ToolResult.error(f"Permission denied: {e!s}")
        except Exception as e:
            return ToolResult.error(f"Write error: {e!s}")

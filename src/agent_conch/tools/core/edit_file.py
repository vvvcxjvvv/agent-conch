"""T 层核心工具: edit_file — 文件编辑 (str_replace)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_conch.sandbox.fs_bridge import FsBridge
from agent_conch.tools.base import BaseTool, ToolResult


class EditFileInput(BaseModel):
    file_path: str = Field(..., description="Path to the file to edit")
    old_string: str = Field(..., description="The exact string to replace")
    new_string: str = Field(..., description="The replacement string")
    replace_all: bool = Field(
        False, description="Replace all occurrences (default: only first match)"
    )


class EditFileTool(BaseTool):
    """文件编辑工具 (字符串替换).

    通过精确字符串替换编辑文件。
    """

    name = "edit_file"
    description = (
        "Edit a file by replacing a specific string. "
        "Finds old_string in the file and replaces it with new_string. "
        "By default replaces only the first occurrence; use replace_all=true for all."
    )
    input_model = EditFileInput
    is_write_tool = True
    is_core = True
    tags = ["file", "edit", "replace"]

    def __init__(self, fs: FsBridge):
        self.fs = fs

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = EditFileInput(**kwargs)

        # old_string 和 new_string 不能相同
        if validated.old_string == validated.new_string:
            return ToolResult.error("old_string and new_string must be different")

        try:
            # 读取原文件
            data = await self.fs.read(validated.file_path)
            content = data.decode("utf-8", errors="replace")

            # 检查 old_string 是否存在
            count = content.count(validated.old_string)
            if count == 0:
                return ToolResult.error(
                    f"old_string not found in {validated.file_path}. "
                    f"Make sure the string matches exactly (including whitespace)."
                )

            if not validated.replace_all and count > 1:
                return ToolResult.error(
                    f"old_string found {count} times in {validated.file_path}. "
                    f"Provide more context to make it unique, or use replace_all=true."
                )

            # 执行替换
            if validated.replace_all:
                new_content = content.replace(validated.old_string, validated.new_string)
                replaced = count
            else:
                new_content = content.replace(validated.old_string, validated.new_string, 1)
                replaced = 1

            # 写回
            await self.fs.write(validated.file_path, new_content.encode("utf-8"))

            return ToolResult(
                content=f"Successfully replaced {replaced} occurrence(s) in {validated.file_path}",
                metadata={
                    "file_path": validated.file_path,
                    "replacements": replaced,
                },
            )
        except PermissionError as e:
            return ToolResult.error(f"Permission denied: {e!s}")
        except FileNotFoundError:
            return ToolResult.error(f"File not found: {validated.file_path}")
        except Exception as e:
            return ToolResult.error(f"Edit error: {e!s}")

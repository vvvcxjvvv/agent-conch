"""T 层核心工具: grep — 内容搜索."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_conch.sandbox.path_validator import PathValidator
from agent_conch.tools.base import BaseTool, ToolResult


class GrepInput(BaseModel):
    pattern: str = Field(..., description="Regular expression pattern to search for")
    path: str = Field(".", description="File or directory to search in")
    include: str = Field(
        "*",
        description="File name glob filter (e.g. '*.py', '*.ts'). Default: all files",
    )
    case_insensitive: bool = Field(False, description="Case insensitive search")
    max_results: int = Field(100, description="Max number of matching lines to return")


class GrepTool(BaseTool):
    """内容搜索工具.

    基于 Python re 模块, 递归搜索文件内容.
    """

    name = "grep"
    description = (
        "Search file contents using regular expressions. "
        "Recursively searches directories. Returns matching lines with file paths and line numbers."
    )
    input_model = GrepInput
    is_write_tool = False
    is_core = True
    tags = ["file", "search", "content", "regex"]

    def __init__(self, validator: PathValidator):
        self.validator = validator

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = GrepInput(**kwargs)
        try:
            flags = re.IGNORECASE if validated.case_insensitive else 0
            regex = re.compile(validated.pattern, flags)
        except re.error as e:
            return ToolResult.error(f"Invalid regex pattern: {e!s}")

        try:
            base = self.validator.validate_or_raise(validated.path, "read")
            base_path = Path(base)

            # 收集要搜索的文件
            files: list[Path] = []
            if base_path.is_file():
                files = [base_path]
            elif base_path.is_dir():
                files = sorted(base_path.rglob(validated.include))
            else:
                return ToolResult.error(f"Path not found: {validated.path}")

            # 搜索
            matches: list[str] = []
            total_matches = 0
            for file_path in files:
                if not file_path.is_file():
                    continue
                # 跳过二进制文件 (简单检测)
                try:
                    text = file_path.read_text(encoding="utf-8", errors="strict")
                except (UnicodeDecodeError, PermissionError):
                    continue

                for line_no, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel = (
                            file_path.relative_to(base_path)
                            if base_path.is_dir()
                            else file_path.name
                        )
                        matches.append(f"{rel}:{line_no}:{line.strip()}")
                        total_matches += 1
                        if len(matches) >= validated.max_results:
                            break
                if len(matches) >= validated.max_results:
                    break

            if not matches:
                content = "No matches found."
            else:
                content = "\n".join(matches)
                if total_matches > validated.max_results:
                    content += f"\n... [showing {validated.max_results} of {total_matches} matches]"

            return ToolResult(
                content=content,
                metadata={
                    "pattern": validated.pattern,
                    "path": validated.path,
                    "total_matches": total_matches,
                    "files_searched": len(files),
                },
            )
        except PermissionError as e:
            return ToolResult.error(f"Permission denied: {e!s}")
        except Exception as e:
            return ToolResult.error(f"Grep error: {e!s}")

"""T 层核心工具: grep — 内容搜索."""

from __future__ import annotations

import fnmatch
import posixpath
import re
from typing import Any

from pydantic import BaseModel, Field

from agent_conch.sandbox.fs_bridge import FsBridge, LocalFsBridge
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

    def __init__(self, fs: FsBridge | PathValidator):
        self.fs = LocalFsBridge(fs) if isinstance(fs, PathValidator) else fs

    async def _files(self, base: str, relative: str = "") -> list[tuple[str, str]]:
        current = posixpath.join(base, relative) if relative else base
        files: list[tuple[str, str]] = []
        for name in sorted(await self.fs.list_dir(current)):
            rel_path = posixpath.join(relative, name) if relative else name
            full_path = posixpath.join(base, rel_path)
            info = await self.fs.stat(full_path)
            if info.is_dir:
                files.extend(await self._files(base, rel_path))
            elif info.is_file:
                files.append((full_path, rel_path))
        return files

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = GrepInput(**kwargs)
        try:
            flags = re.IGNORECASE if validated.case_insensitive else 0
            regex = re.compile(validated.pattern, flags)
        except re.error as e:
            return ToolResult.error(f"Invalid regex pattern: {e!s}")

        try:
            base_info = await self.fs.stat(validated.path)
            if base_info.is_file:
                files = [(validated.path, posixpath.basename(validated.path))]
            elif base_info.is_dir:
                files = [
                    item
                    for item in await self._files(validated.path)
                    if fnmatch.fnmatch(posixpath.basename(item[1]), validated.include)
                ]
            else:
                return ToolResult.error(f"Path not found: {validated.path}")

            # 搜索
            matches: list[str] = []
            total_matches = 0
            for file_path, relative_path in files:
                # 跳过二进制文件 (简单检测)
                try:
                    text = (await self.fs.read(file_path)).decode("utf-8", errors="strict")
                except (UnicodeDecodeError, PermissionError):
                    continue

                for line_no, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"{relative_path}:{line_no}:{line.strip()}")
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

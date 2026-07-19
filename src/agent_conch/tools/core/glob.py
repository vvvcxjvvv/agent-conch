"""T 层核心工具: glob — 文件模式匹配."""

from __future__ import annotations

import fnmatch
import posixpath
from typing import Any

from pydantic import BaseModel, Field

from agent_conch.sandbox.fs_bridge import FsBridge, LocalFsBridge
from agent_conch.sandbox.path_validator import PathValidator
from agent_conch.tools.base import BaseTool, ToolResult


class GlobInput(BaseModel):
    pattern: str = Field(..., description="Glob pattern (e.g. '**/*.py', 'src/**/*.ts')")
    path: str = Field(".", description="Base directory to search from")


class GlobTool(BaseTool):
    """文件模式匹配工具.

    使用 pathlib 的 glob 语法.
    """

    name = "glob"
    description = (
        "Find files matching a glob pattern. "
        "Returns a list of matching file paths, sorted by modification time (newest first)."
    )
    input_model = GlobInput
    is_write_tool = False
    is_core = True
    tags = ["file", "search", "pattern"]

    def __init__(self, fs: FsBridge | PathValidator):
        self.fs = LocalFsBridge(fs) if isinstance(fs, PathValidator) else fs

    async def _walk(self, base: str, relative: str = "") -> list[tuple[str, float]]:
        current = posixpath.join(base, relative) if relative else base
        entries: list[tuple[str, float]] = []
        for name in sorted(await self.fs.list_dir(current)):
            rel_path = posixpath.join(relative, name) if relative else name
            full_path = posixpath.join(base, rel_path)
            info = await self.fs.stat(full_path)
            entries.append((rel_path, info.modified_time))
            if info.is_dir:
                entries.extend(await self._walk(base, rel_path))
        return entries

    @staticmethod
    def _matches(path: str, pattern: str) -> bool:
        patterns = [pattern]
        while patterns[-1].startswith("**/"):
            patterns.append(patterns[-1][3:])
        return any(fnmatch.fnmatch(path, item) for item in patterns)

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = GlobInput(**kwargs)
        try:
            base_info = await self.fs.stat(validated.path)
            if not base_info.is_dir:
                return ToolResult.error(f"Not a directory: {validated.path}")

            matches = sorted(
                (
                    item
                    for item in await self._walk(validated.path)
                    if self._matches(item[0], validated.pattern)
                ),
                key=lambda item: item[1],
                reverse=True,
            )

            # 限制结果数量
            max_results = 200
            truncated = len(matches) > max_results
            result_list = [path for path, _ in matches[:max_results]]

            content = "\n".join(result_list) if result_list else "No matches found."
            if truncated:
                content += f"\n... [showing {max_results} of {len(matches)} matches]"

            return ToolResult(
                content=content,
                metadata={
                    "pattern": validated.pattern,
                    "path": validated.path,
                    "total_matches": len(matches),
                    "truncated": truncated,
                },
            )
        except PermissionError as e:
            return ToolResult.error(f"Permission denied: {e!s}")
        except Exception as e:
            return ToolResult.error(f"Glob error: {e!s}")

"""Prompt: AGENTS.md 发现.

查找策略:
- 从 cwd 向上遍历发现 AGENTS.md
- 类似 .git 目录的查找方式
"""

from __future__ import annotations

import os
from pathlib import Path


def discover_agents_md(cwd: str | None = None) -> str:
    """从 cwd 向上遍历发现 AGENTS.md.

    查找顺序:
    1. cwd/AGENTS.md
    2. 向上逐级目录直到根目录
    3. 返回第一个找到的 AGENTS.md 内容

    Args:
        cwd: 起始目录 (None = 当前目录)

    Returns:
        AGENTS.md 文件内容, 未找到则返回空字符串
    """
    start = Path(cwd or os.getcwd()).resolve()

    # 向上遍历
    current = start
    while True:
        agents_file = current / "AGENTS.md"
        if agents_file.exists() and agents_file.is_file():
            try:
                return agents_file.read_text(encoding="utf-8")
            except Exception:
                pass

        # 检查是否到达根目录
        parent = current.parent
        if parent == current:
            break
        current = parent

    return ""


def discover_all_agents_md(cwd: str | None = None) -> list[tuple[str, str]]:
    """发现路径上所有的 AGENTS.md 文件.

    从 cwd 向上遍历, 收集所有 AGENTS.md.
    返回 [(path, content), ...] 按目录深度从深到浅排列.

    Args:
        cwd: 起始目录

    Returns:
        列表 of (directory_path, content)
    """
    start = Path(cwd or os.getcwd()).resolve()
    results: list[tuple[str, str]] = []

    current = start
    while True:
        agents_file = current / "AGENTS.md"
        if agents_file.exists() and agents_file.is_file():
            try:
                content = agents_file.read_text(encoding="utf-8")
                results.append((str(current), content))
            except Exception:
                pass

        parent = current.parent
        if parent == current:
            break
        current = parent

    # 从深到浅 (cwd 优先)
    return results

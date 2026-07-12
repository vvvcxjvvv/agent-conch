"""测试公共辅助."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """临时工作目录 (带示例文件)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    # 创建示例文件
    (ws / "README.md").write_text("# Test Project\n\nThis is a test.\n")
    (ws / "main.py").write_text(
        "def hello():\n"
        "    print('hello world')\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    hello()\n"
    )
    (ws / "src").mkdir()
    (ws / "src" / "utils.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def multiply(a, b):\n"
        "    return a * b\n"
    )
    (ws / "tests").mkdir()
    (ws / "tests" / "test_utils.py").write_text(
        "from src.utils import add\n"
        "\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
    )
    return ws


@pytest.fixture
def temp_db(tmp_path: Path) -> str:
    """临时 SQLite 数据库路径."""
    return str(tmp_path / "test_state.db")

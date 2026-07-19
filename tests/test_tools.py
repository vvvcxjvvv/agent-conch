"""T 层测试: 核心工具."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_conch.sandbox.fs_bridge import LocalFsBridge
from agent_conch.sandbox.local import LocalBackend
from agent_conch.sandbox.path_validator import PathValidator
from agent_conch.tools.core.bash import BashTool
from agent_conch.tools.core.edit_file import EditFileTool
from agent_conch.tools.core.glob import GlobTool
from agent_conch.tools.core.grep import GrepTool
from agent_conch.tools.core.read_file import ReadFileTool
from agent_conch.tools.core.write_file import WriteFileTool


@pytest.fixture
def setup(tmp_workspace: Path):
    """创建工具测试环境."""
    validator = PathValidator(cwd=str(tmp_workspace), allowed_roots=[str(tmp_workspace)])
    backend = LocalBackend(validator=validator, default_cwd=str(tmp_workspace))
    fs = LocalFsBridge(validator)
    return {
        "validator": validator,
        "backend": backend,
        "fs": fs,
        "workspace": tmp_workspace,
    }


class TestReadFileTool:
    async def test_read_existing_file(self, setup):
        tool = ReadFileTool(setup["fs"])
        result = await tool.execute(file_path=str(setup["workspace"] / "README.md"))
        assert not result.is_error
        assert "Test Project" in result.content

    async def test_read_nonexistent_file(self, setup):
        tool = ReadFileTool(setup["fs"])
        result = await tool.execute(file_path=str(setup["workspace"] / "nonexistent.txt"))
        assert result.is_error
        assert "not found" in result.content.lower()

    async def test_read_with_limit(self, setup):
        tool = ReadFileTool(setup["fs"])
        result = await tool.execute(
            file_path=str(setup["workspace"] / "README.md"),
            offset=0,
            limit=5,
        )
        assert not result.is_error


class TestWriteFileTool:
    async def test_write_new_file(self, setup):
        tool = WriteFileTool(setup["fs"])
        result = await tool.execute(
            file_path=str(setup["workspace"] / "new_file.txt"),
            content="Hello, World!",
        )
        assert not result.is_error
        assert (setup["workspace"] / "new_file.txt").read_text() == "Hello, World!"

    async def test_overwrite_existing_file(self, setup):
        tool = WriteFileTool(setup["fs"])
        result = await tool.execute(
            file_path=str(setup["workspace"] / "README.md"),
            content="Overwritten content",
        )
        assert not result.is_error
        assert (setup["workspace"] / "README.md").read_text() == "Overwritten content"


class TestEditFileTool:
    async def test_edit_replace_first(self, setup):
        tool = EditFileTool(setup["fs"])
        result = await tool.execute(
            file_path=str(setup["workspace"] / "main.py"),
            old_string="hello world",
            new_string="hello conch",
        )
        assert not result.is_error
        content = (setup["workspace"] / "main.py").read_text()
        assert "hello conch" in content
        assert "hello world" not in content

    async def test_edit_not_found(self, setup):
        tool = EditFileTool(setup["fs"])
        result = await tool.execute(
            file_path=str(setup["workspace"] / "main.py"),
            old_string="nonexistent string",
            new_string="replacement",
        )
        assert result.is_error
        assert "not found" in result.content.lower()

    async def test_edit_same_string_error(self, setup):
        tool = EditFileTool(setup["fs"])
        result = await tool.execute(
            file_path=str(setup["workspace"] / "main.py"),
            old_string="hello",
            new_string="hello",
        )
        assert result.is_error

    async def test_edit_multiple_matches_error(self, setup):
        # 创建有多个匹配的文件
        (setup["workspace"] / "multi.py").write_text("x = 1\nx = 2\nx = 3\n")
        tool = EditFileTool(setup["fs"])
        result = await tool.execute(
            file_path=str(setup["workspace"] / "multi.py"),
            old_string="x =",
            new_string="y =",
        )
        assert result.is_error
        assert "3 times" in result.content or "multiple" in result.content.lower()

    async def test_edit_replace_all(self, setup):
        (setup["workspace"] / "multi.py").write_text("x = 1\nx = 2\nx = 3\n")
        tool = EditFileTool(setup["fs"])
        result = await tool.execute(
            file_path=str(setup["workspace"] / "multi.py"),
            old_string="x =",
            new_string="y =",
            replace_all=True,
        )
        assert not result.is_error
        content = (setup["workspace"] / "multi.py").read_text()
        assert content.count("y =") == 3


class TestGlobTool:
    async def test_glob_python_files(self, setup):
        tool = GlobTool(setup["validator"])
        result = await tool.execute(
            pattern="**/*.py",
            path=str(setup["workspace"]),
        )
        assert not result.is_error
        assert "main.py" in result.content
        assert "utils.py" in result.content

    async def test_glob_no_matches(self, setup):
        tool = GlobTool(setup["validator"])
        result = await tool.execute(
            pattern="**/*.java",
            path=str(setup["workspace"]),
        )
        assert "No matches" in result.content


class TestGrepTool:
    async def test_grep_find_pattern(self, setup):
        tool = GrepTool(setup["validator"])
        result = await tool.execute(
            pattern="hello",
            path=str(setup["workspace"]),
        )
        assert not result.is_error
        assert "main.py" in result.content
        assert "hello" in result.content

    async def test_grep_with_include_filter(self, setup):
        tool = GrepTool(setup["validator"])
        result = await tool.execute(
            pattern="def",
            path=str(setup["workspace"]),
            include="*.py",
        )
        assert not result.is_error
        assert "main.py" in result.content or "utils.py" in result.content

    async def test_grep_case_insensitive(self, setup):
        tool = GrepTool(setup["validator"])
        result = await tool.execute(
            pattern="HELLO",
            path=str(setup["workspace"]),
            case_insensitive=True,
        )
        assert not result.is_error
        assert "hello" in result.content.lower()

    async def test_grep_no_matches(self, setup):
        tool = GrepTool(setup["validator"])
        result = await tool.execute(
            pattern="nonexistent_pattern_xyz",
            path=str(setup["workspace"]),
        )
        assert "No matches" in result.content


class TestBashTool:
    async def test_bash_echo(self, setup):
        tool = BashTool(setup["backend"])
        result = await tool.execute(command="echo 'test output'")
        assert not result.is_error
        assert "test output" in result.content

    async def test_bash_exit_code(self, setup):
        tool = BashTool(setup["backend"])
        result = await tool.execute(command="exit 42")
        assert result.is_error
        assert result.metadata["exit_code"] == 42

    async def test_bash_run_tests(self, setup):
        """验证 bash 工具可以运行测试命令。"""
        import sys

        python_exe = sys.executable
        tool = BashTool(setup["backend"])
        result = await tool.execute(
            command=f'cd "{setup["workspace"]}" && "{python_exe}" -m pytest tests/test_utils.py -v',
            timeout=30,
        )
        assert not result.is_error
        assert "passed" in result.content

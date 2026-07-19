"""E 层测试: PathValidator + FsBridge + LocalBackend."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_conch.sandbox.docker import DockerBackend, DockerConfig
from agent_conch.sandbox.fs_bridge import LocalFsBridge
from agent_conch.sandbox.local import LocalBackend
from agent_conch.sandbox.path_validator import PathValidator


class TestPathValidator:
    """PathValidator 路径安全测试."""

    def test_normal_path_allowed(self, tmp_workspace: Path):
        validator = PathValidator(cwd=str(tmp_workspace), allowed_roots=[str(tmp_workspace)])
        result = validator.validate(str(tmp_workspace / "README.md"))
        assert result.allowed

    def test_sensitive_path_blocked(self, tmp_workspace: Path):
        validator = PathValidator(cwd=str(tmp_workspace))
        # /etc 是硬编码敏感路径
        result = validator.validate("/etc/passwd")
        assert not result.allowed
        assert result.is_sensitive

    def test_ssh_path_blocked(self, tmp_workspace: Path):
        validator = PathValidator(cwd=str(tmp_workspace))
        result = validator.validate("~/.ssh/id_rsa")
        assert not result.allowed

    def test_env_file_blocked(self, tmp_workspace: Path):
        validator = PathValidator(cwd=str(tmp_workspace))
        result = validator.validate("/.env")
        assert not result.allowed

    def test_outside_allowed_roots_blocked(self, tmp_workspace: Path, tmp_path: Path):
        validator = PathValidator(
            cwd=str(tmp_workspace),
            allowed_roots=[str(tmp_workspace)],
        )
        # tmp_path 在 tmp_workspace 外面
        outside = tmp_path / "outside.txt"
        outside.write_text("test")
        result = validator.validate(str(outside))
        assert not result.allowed
        assert "outside allowed roots" in result.reason

    def test_write_to_parent_of_sensitive_blocked(self, tmp_workspace: Path):
        validator = PathValidator(cwd=str(tmp_workspace))
        # 写到 / 的父目录 → 应该被阻止
        result = validator.validate("/", "write")
        assert not result.allowed

    def test_user_sensitive_paths(self, tmp_workspace: Path):
        validator = PathValidator(
            cwd=str(tmp_workspace),
            user_sensitive_paths=[str(tmp_workspace / "secret")],
        )
        (tmp_workspace / "secret").mkdir()
        result = validator.validate(str(tmp_workspace / "secret" / "file.txt"))
        assert not result.allowed

    def test_validate_or_raise(self, tmp_workspace: Path):
        validator = PathValidator(cwd=str(tmp_workspace))
        with pytest.raises(PermissionError):
            validator.validate_or_raise("/etc/passwd")


class TestLocalFsBridge:
    """LocalFsBridge 文件操作测试."""

    @pytest.fixture
    def fs(self, tmp_workspace: Path):
        validator = PathValidator(cwd=str(tmp_workspace), allowed_roots=[str(tmp_workspace)])
        return LocalFsBridge(validator)

    async def test_read_file(self, fs: LocalFsBridge, tmp_workspace: Path):
        data = await fs.read(str(tmp_workspace / "README.md"))
        assert b"Test Project" in data

    async def test_write_file(self, fs: LocalFsBridge, tmp_workspace: Path):
        await fs.write(str(tmp_workspace / "new.txt"), b"hello")
        assert (tmp_workspace / "new.txt").read_text() == "hello"

    async def test_stat(self, fs: LocalFsBridge, tmp_workspace: Path):
        stat = await fs.stat(str(tmp_workspace / "README.md"))
        assert stat.exists
        assert stat.is_file
        assert stat.size > 0

    async def test_stat_nonexistent(self, fs: LocalFsBridge, tmp_workspace: Path):
        stat = await fs.stat(str(tmp_workspace / "nonexistent.txt"))
        assert not stat.exists

    async def test_rename(self, fs: LocalFsBridge, tmp_workspace: Path):
        old = str(tmp_workspace / "old.txt")
        new = str(tmp_workspace / "new_name.txt")
        await fs.write(old, b"content")
        await fs.rename(old, new)
        assert not Path(old).exists()
        assert Path(new).read_text() == "content"

    async def test_list_dir(self, fs: LocalFsBridge, tmp_workspace: Path):
        entries = await fs.list_dir(str(tmp_workspace))
        assert "README.md" in entries
        assert "main.py" in entries

    async def test_delete(self, fs: LocalFsBridge, tmp_workspace: Path):
        f = str(tmp_workspace / "to_delete.txt")
        await fs.write(f, b"temp")
        await fs.delete(f)
        assert not Path(f).exists()


class TestLocalBackend:
    """LocalBackend 命令执行测试."""

    @pytest.fixture
    def backend(self, tmp_workspace: Path):
        validator = PathValidator(cwd=str(tmp_workspace), allowed_roots=[str(tmp_workspace)])
        return LocalBackend(validator=validator, default_cwd=str(tmp_workspace))

    async def test_execute_success(self, backend: LocalBackend):
        result = await backend.execute("echo 'hello world'")
        assert result.exit_code == 0
        assert "hello world" in result.stdout

    async def test_execute_failure(self, backend: LocalBackend):
        result = await backend.execute("exit 1")
        assert result.exit_code == 1

    async def test_execute_with_cwd(self, backend: LocalBackend, tmp_workspace: Path):
        result = await backend.execute("pwd", cwd=str(tmp_workspace))
        assert result.exit_code == 0
        # Git Bash 可能返回 Unix 风格路径, 只验证目录名存在
        assert "test_execute_with_cwd" in result.stdout or str(tmp_workspace) in result.stdout

    async def test_execute_timeout(self, backend: LocalBackend):
        result = await backend.execute("sleep 10", timeout=1)
        assert result.timed_out
        assert result.exit_code == -1

    async def test_execute_stderr(self, backend: LocalBackend):
        result = await backend.execute("echo 'error msg' >&2")
        assert "error msg" in result.stderr

    async def test_is_available(self, backend: LocalBackend):
        assert await backend.is_available()

    async def test_run_python_test(self, backend: LocalBackend, tmp_workspace: Path):
        """验证沙箱后端可以运行 pytest。"""
        import sys

        python_exe = sys.executable
        result = await backend.execute(
            f'cd "{tmp_workspace}" && "{python_exe}" -m pytest tests/test_utils.py -v',
            timeout=30,
        )
        assert result.exit_code == 0
        assert "passed" in result.stdout


class TestDockerBackend:
    async def test_execute_snapshot_restore_and_reset(self):
        if shutil.which("docker") is None:
            pytest.skip("Docker CLI is not installed")

        backend = DockerBackend(DockerConfig(image="alpine:3.20"))
        if not await backend.is_available():
            pytest.skip("Docker daemon is not available")

        session_id = "p2-docker-test"
        snapshot = None
        try:
            result = await backend.execute(
                "printf 'before' > state.txt && cat state.txt",
                session_id=session_id,
                timeout=60,
            )
            assert result.exit_code == 0
            assert result.stdout == "before"

            snapshot = await backend.snapshot(session_id)
            assert snapshot is not None

            await backend.execute("printf 'after' > state.txt", session_id=session_id)
            assert await backend.restore_snapshot(session_id, snapshot)
            restored = await backend.execute("cat state.txt", session_id=session_id)
            assert restored.stdout == "before"

            assert await backend.hard_reset(session_id)
            reset = await backend.execute("test ! -e state.txt", session_id=session_id)
            assert reset.exit_code == 0
        finally:
            await backend.cleanup(session_id)
            if snapshot is not None:
                await backend.remove_snapshot(snapshot)

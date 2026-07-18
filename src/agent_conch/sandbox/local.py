"""E 层: 沙箱后端抽象 + LocalBackend.

设计文档要求:
- SandboxRegistry 可插拔: Local + Docker(P2) + SSH(P2)
- Local: 开发/个人场景, 默认信任
- 命令执行 + 文件操作统一通过后端
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass

from agent_conch.sandbox.fs_bridge import FsBridge, LocalFsBridge
from agent_conch.sandbox.path_validator import PathValidator


@dataclass
class CommandResult:
    """命令执行结果."""

    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool = False
    cwd: str = ""


class SandboxBackend(ABC):
    """沙箱后端抽象基类."""

    name: str = "abstract"

    @property
    @abstractmethod
    def fs(self) -> FsBridge:
        """获取文件系统桥接."""
        ...

    @abstractmethod
    async def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 120,
        env: dict[str, str] | None = None,
        session_id: str = "",
    ) -> CommandResult:
        """执行 shell 命令."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """检查后端是否可用."""
        ...


class LocalBackend(SandboxBackend):
    """本地执行后端.

    默认信任, 直接在当前机器执行命令.
    文件操作通过 LocalFsBridge (带 PathValidator 安全校验).
    """

    name = "local"

    def __init__(
        self,
        validator: PathValidator | None = None,
        default_cwd: str | None = None,
    ):
        self._validator = validator or PathValidator(cwd=default_cwd or os.getcwd())
        self._fs = LocalFsBridge(self._validator)
        self._default_cwd = default_cwd or os.getcwd()

    @property
    def fs(self) -> FsBridge:
        return self._fs

    @property
    def validator(self) -> PathValidator:
        return self._validator

    async def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 120,
        env: dict[str, str] | None = None,
        session_id: str = "",
    ) -> CommandResult:
        """执行 shell 命令 (异步).

        使用 asyncio.create_subprocess_exec/shell.
        捕获 stdout/stderr/exit_code, 支持超时.
        """
        work_dir = cwd or self._default_cwd
        # 验证工作目录安全
        work_dir = self._validator.validate_or_raise(work_dir, "read")

        # 合并环境变量
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        import time

        start = time.time()

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=full_env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
            duration_ms = int((time.time() - start) * 1000)

            return CommandResult(
                command=command,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                exit_code=process.returncode or 0,
                duration_ms=duration_ms,
                cwd=work_dir,
            )
        except TimeoutError:
            duration_ms = int((time.time() - start) * 1000)
            # 尝试终止进程
            with suppress(Exception):
                process.kill()
            return CommandResult(
                command=command,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                exit_code=-1,
                duration_ms=duration_ms,
                timed_out=True,
                cwd=work_dir,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return CommandResult(
                command=command,
                stdout="",
                stderr=f"Execution error: {e!s}",
                exit_code=-1,
                duration_ms=duration_ms,
                cwd=work_dir,
            )

    async def is_available(self) -> bool:
        """Local 后端始终可用."""
        return True

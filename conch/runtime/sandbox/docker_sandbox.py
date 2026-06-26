"""Docker 沙箱 — 加固基线：CPU/内存/网络限制、禁特权、只读挂载。

安全 day-one：Agent 能执行 bash 的第一天，就必须有沙箱隔离。
没有 Docker 环境时降级为本地执行（带告警）。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class DockerSandbox:
    """Docker 沙箱执行环境。

    加固基线（v0.3 进入 MVP）：
    - CPU 限制：--cpus
    - 内存限制：--memory
    - 网络限制：--network（默认 none 禁网）
    - 禁用特权：--privileged=false
    - 只读挂载：--read-only + tmpfs 工作区
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        cpus: str = "2",
        memory: str = "512m",
        network: str = "none",
        privileged: bool = False,
        read_only: bool = True,
        timeout: int = 30,
    ):
        self.image = image
        self.cpus = cpus
        self.memory = memory
        self.network = network
        self.privileged = privileged
        self.read_only = read_only
        self.timeout = timeout
        self._available: bool | None = None

    def _check_docker(self) -> bool:
        """检查 Docker 是否可用。"""
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            self._available = result.returncode == 0
        except Exception:
            self._available = False
        if not self._available:
            logger.warning(
                "Docker not available, commands will run locally (no sandbox isolation)"
            )
        return self._available

    def _build_run_args(self, command: str, cwd: str | None = None) -> list[str]:
        """构建 docker run 命令参数。"""
        args = [
            "docker", "run", "--rm",
            "--cpus", self.cpus,
            "--memory", self.memory,
            "--network", self.network,
        ]
        if not self.privileged:
            args.append("--privileged=false")
        if self.read_only:
            args.append("--read-only")
            args.extend(["--tmpfs", "/tmp:rw,size=64m"])
            args.extend(["--tmpfs", "/workspace:rw,size=256m"])
        if cwd:
            args.extend(["-w", "/workspace"])
        args.append(self.image)
        args.extend(["bash", "-c", command])
        return args

    async def run_command(
        self, command: str, cwd: str | None = None, timeout: int | None = None
    ) -> dict[str, Any]:
        """在沙箱内执行命令。

        Args:
            command: 要执行的 shell 命令
            cwd: 工作目录（映射到容器内 /workspace）
            timeout: 超时秒数

        Returns:
            {"stdout": str, "stderr": str, "returncode": int} 或 {"error": str}
        """
        timeout = timeout or self.timeout

        if not self._check_docker():
            # 降级为本地执行
            return await self._run_local(command, cwd, timeout)

        args = self._build_run_args(command, cwd)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {"error": f"Command timed out after {timeout}s"}
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
            }
        except Exception as e:
            logger.warning("Docker execution failed, falling back to local: %s", e)
            return await self._run_local(command, cwd, timeout)

    async def _run_local(self, command: str, cwd: str | None, timeout: int) -> dict:
        """降级路径：本地执行（无沙箱隔离，带告警）。"""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd if cwd and __import__("pathlib").Path(cwd).exists() else None,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
                "_warning": "executed locally without sandbox",
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": f"Command timed out after {timeout}s"}
        except Exception as e:
            return {"error": str(e)}

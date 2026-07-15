"""E 层: Docker 沙箱后端.

设计文档要求:
- DockerBackend: 容器级隔离执行
- hard_reset: 容器重置 (docker commit 快照 + restore)
- DockerFsBridge: 容器内文件操作 (通过 docker cp / docker exec)
- 与 SandboxRegistry 集成

注意: 需要本机安装 Docker. 在无 Docker 环境下 check_available 返回 False.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from agent_conch.sandbox.fs_bridge import FileStat, FsBridge
from agent_conch.sandbox.local import CommandResult, SandboxBackend


@dataclass
class DockerConfig:
    """Docker 沙箱配置."""

    image: str = "python:3.12-slim"  # 默认镜像
    container_name_prefix: str = "conch-sandbox-"
    work_dir: str = "/workspace"
    memory_limit: str = "512m"
    cpu_limit: str = "1.0"
    network: str = "none"  # none | bridge | host
    auto_remove: bool = False  # 容器退出后自动删除
    volumes: list[str] = field(default_factory=list)  # 额外挂载


class DockerBackend(SandboxBackend):
    """Docker 沙箱后端.

    在 Docker 容器中执行命令, 提供容器级隔离.
    """

    def __init__(self, config: DockerConfig | None = None):
        self.config = config or DockerConfig()
        self._containers: dict[str, str] = {}  # session_id → container_id

    async def execute(
        self,
        command: str,
        cwd: str = "",
        timeout: int = 30,
        session_id: str = "",
    ) -> CommandResult:
        """在 Docker 容器中执行命令."""
        container_id = self._containers.get(session_id, "")
        if not container_id:
            # 没有容器, 创建临时容器
            container_id = await self._create_container(session_id)
            if not container_id:
                return CommandResult(
                    command=command,
                    stdout="",
                    stderr="Failed to create Docker container",
                    exit_code=-1,
                    duration_ms=0,
                    timed_out=False,
                    cwd=cwd,
                )

        work_dir = cwd or self.config.work_dir
        start = time.time()

        try:
            proc = await asyncio.create_subprocess_shell(
                f"docker exec -w {work_dir} {container_id} sh -c {shell_quote(command)}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            duration_ms = int((time.time() - start) * 1000)

            return CommandResult(
                command=command,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
                duration_ms=duration_ms,
                timed_out=False,
                cwd=work_dir,
            )
        except TimeoutError:
            proc.kill()
            return CommandResult(
                command=command,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                exit_code=-1,
                duration_ms=int((time.time() - start) * 1000),
                timed_out=True,
                cwd=work_dir,
            )
        except Exception as e:
            return CommandResult(
                command=command,
                stdout="",
                stderr=f"Docker exec error: {e!s}",
                exit_code=-1,
                duration_ms=int((time.time() - start) * 1000),
                timed_out=False,
                cwd=work_dir,
            )

    async def _create_container(self, session_id: str) -> str:
        """创建 Docker 容器."""
        import uuid

        name = f"{self.config.container_name_prefix}{session_id or str(uuid.uuid4())[:8]}"

        cmd_parts = [
            "docker", "run", "-d",
            "--name", name,
            "--memory", self.config.memory_limit,
            "--cpus", self.config.cpu_limit,
            "--network", self.config.network,
            "-w", self.config.work_dir,
        ]

        if self.config.auto_remove:
            cmd_parts.append("--rm")

        for vol in self.config.volumes:
            cmd_parts.extend(["-v", vol])

        cmd_parts.extend([self.config.image, "sleep", "infinity"])

        try:
            proc = await asyncio.create_subprocess_shell(
                " ".join(cmd_parts),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            container_id = stdout.decode().strip()
            if container_id:
                self._containers[session_id] = container_id
                return container_id
        except Exception:
            pass
        return ""

    async def hard_reset(self, session_id: str) -> bool:
        """硬重置: 销毁当前容器, 从镜像创建新容器.

        设计文档要求: Docker commit 快照 + restore.
        P2: 直接销毁重建 (更简单, 后续可加 commit 快照).
        """
        container_id = self._containers.get(session_id, "")
        if container_id:
            # 停止并删除旧容器
            await asyncio.create_subprocess_shell(
                f"docker rm -f {container_id}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            del self._containers[session_id]

        # 创建新容器
        new_id = await self._create_container(session_id)
        return bool(new_id)

    async def snapshot(self, session_id: str, tag: str = "") -> str | None:
        """快照: docker commit 当前容器为镜像."""
        container_id = self._containers.get(session_id, "")
        if not container_id:
            return None

        import uuid

        tag = tag or f"conch-snapshot-{str(uuid.uuid4())[:8]}"
        proc = await asyncio.create_subprocess_shell(
            f"docker commit {container_id} {tag}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return tag
        return None

    async def restore_snapshot(self, session_id: str, snapshot_tag: str) -> bool:
        """从快照恢复: 销毁当前容器, 从快照镜像创建新容器."""
        container_id = self._containers.get(session_id, "")
        if container_id:
            await asyncio.create_subprocess_shell(
                f"docker rm -f {container_id}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        # 临时替换镜像创建容器
        old_image = self.config.image
        self.config.image = snapshot_tag
        new_id = await self._create_container(session_id)
        self.config.image = old_image
        return bool(new_id)

    async def cleanup(self, session_id: str) -> None:
        """清理: 停止并删除容器."""
        container_id = self._containers.get(session_id, "")
        if container_id:
            await asyncio.create_subprocess_shell(
                f"docker rm -f {container_id}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            del self._containers[session_id]

    async def is_available(self) -> bool:
        """检查 Docker 是否可用."""
        try:
            proc = await asyncio.create_subprocess_shell(
                "docker info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception:
            return False

    @property
    def fs(self) -> FsBridge:
        """获取文件系统桥接."""
        return DockerFsBridge(self)


class DockerFsBridge(FsBridge):
    """Docker 文件系统桥接.

    通过 docker cp / docker exec 在容器内操作文件.
    """

    def __init__(self, backend: DockerBackend):
        self.backend = backend

    def _get_container(self, session_id: str = "") -> str:
        """获取当前容器 ID."""
        # 简化: 返回第一个容器
        for sid, cid in self.backend._containers.items():
            return cid
        return ""

    async def stat(self, path: str) -> FileStat:
        container = self._get_container()
        if not container:
            return FileStat(path=path, size=0, is_dir=False, is_file=False, exists=False, modified_time=0)

        result = await self.backend.execute(
            f"stat -c '%s %F %Y' {shell_quote(path)} 2>/dev/null || echo 'NOT_FOUND'",
            timeout=5,
        )
        if "NOT_FOUND" in result.stdout or not result.stdout.strip():
            return FileStat(path=path, size=0, is_dir=False, is_file=False, exists=False, modified_time=0)

        parts = result.stdout.strip().split()
        if len(parts) >= 3:
            size = int(parts[0]) if parts[0].isdigit() else 0
            is_dir = "directory" in parts[1]
            mtime = float(parts[2]) if parts[2].replace(".", "").isdigit() else 0
            return FileStat(
                path=path, size=size, is_dir=is_dir, is_file=not is_dir,
                exists=True, modified_time=mtime,
            )
        return FileStat(path=path, size=0, is_dir=False, is_file=False, exists=False, modified_time=0)

    async def read(self, path: str, offset: int = 0, limit: int = -1) -> bytes:
        container = self._get_container()
        if not container:
            return b""

        # docker cp 容器内文件到 stdout
        proc = await asyncio.create_subprocess_shell(
            f"docker cp {container}:{shell_quote(path)} -",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        # docker cp 输出是 tar 格式, 需要提取文件内容
        # 简化: 用 docker exec cat
        result = await self.backend.execute(f"cat {shell_quote(path)}", timeout=10)
        data = result.stdout.encode("utf-8")
        if offset > 0:
            data = data[offset:]
        if limit >= 0:
            data = data[:limit]
        return data

    async def write(self, path: str, data: bytes) -> None:
        # 通过 docker exec 写入文件
        import base64

        encoded = base64.b64encode(data).decode()
        await self.backend.execute(
            f"mkdir -p $(dirname {shell_quote(path)}) && echo '{encoded}' | base64 -d > {shell_quote(path)}",
            timeout=10,
        )

    async def rename(self, old: str, new: str) -> None:
        await self.backend.execute(f"mv {shell_quote(old)} {shell_quote(new)}", timeout=5)

    async def delete(self, path: str) -> None:
        await self.backend.execute(f"rm -rf {shell_quote(path)}", timeout=5)

    async def list_dir(self, path: str) -> list[str]:
        result = await self.backend.execute(f"ls -1 {shell_quote(path)}", timeout=5)
        if result.exit_code != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    async def makedirs(self, path: str) -> None:
        await self.backend.execute(f"mkdir -p {shell_quote(path)}", timeout=5)


def shell_quote(s: str) -> str:
    """Shell 引用 (防止命令注入)."""
    return "'" + s.replace("'", "'\"'\"'") + "'"

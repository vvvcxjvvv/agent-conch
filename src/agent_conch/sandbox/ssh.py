"""E 层：基于系统 OpenSSH 的远程执行与 FS Bridge。"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from agent_conch.sandbox.fs_bridge import FileStat, FsBridge
from agent_conch.sandbox.local import CommandResult, SandboxBackend


@dataclass
class SSHConfig:
    host: str
    user: str = ""
    port: int = 22
    identity_file: str = ""
    strict_host_key: bool = True
    connect_timeout: int = 10
    work_dir: str = "."
    allowed_roots: list[str] = field(default_factory=list)


class SSHBackend(SandboxBackend):
    name = "ssh"

    def __init__(self, config: SSHConfig):
        if not config.host:
            raise ValueError("SSH host is required")
        self.config = config
        self._fs = SSHFsBridge(self)

    @property
    def fs(self) -> FsBridge:
        return self._fs

    def _base_command(self) -> list[str]:
        command = [
            "ssh",
            "-p",
            str(self.config.port),
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.config.connect_timeout}",
            "-o",
            f"StrictHostKeyChecking={'yes' if self.config.strict_host_key else 'no'}",
        ]
        if self.config.identity_file:
            command.extend(["-i", os.path.expanduser(self.config.identity_file)])
        target = f"{self.config.user}@{self.config.host}" if self.config.user else self.config.host
        command.append(target)
        return command

    async def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 120,
        env: dict[str, str] | None = None,
        session_id: str = "",
    ) -> CommandResult:
        work_dir = cwd or self.config.work_dir
        invalid_env = [
            key for key in (env or {}) if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None
        ]
        if invalid_env:
            return CommandResult(
                command=command,
                stdout="",
                stderr=f"Invalid SSH environment variable name: {invalid_env[0]}",
                exit_code=-1,
                duration_ms=0,
                cwd=work_dir,
            )
        environment = " ".join(
            f"{key}={shlex.quote(value)}" for key, value in sorted((env or {}).items())
        )
        prefix = f"cd {shlex.quote(work_dir)} && "
        remote = prefix + (f"env {environment} " if environment else "") + command
        started = time.time()
        try:
            process = await asyncio.create_subprocess_exec(
                *self._base_command(),
                remote,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return CommandResult(
                command=command,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                exit_code=process.returncode or 0,
                duration_ms=int((time.time() - started) * 1000),
                cwd=work_dir,
            )
        except TimeoutError:
            process.kill()
            return CommandResult(
                command=command,
                stdout="",
                stderr=f"SSH command timed out after {timeout}s",
                exit_code=-1,
                duration_ms=int((time.time() - started) * 1000),
                timed_out=True,
                cwd=work_dir,
            )
        except Exception as exc:
            return CommandResult(
                command=command,
                stdout="",
                stderr=f"SSH execution error: {exc!s}",
                exit_code=-1,
                duration_ms=int((time.time() - started) * 1000),
                cwd=work_dir,
            )

    async def is_available(self) -> bool:
        result = await self.execute("true", timeout=self.config.connect_timeout)
        return result.exit_code == 0


class SSHFsBridge(FsBridge):
    def __init__(self, backend: SSHBackend):
        self.backend = backend

    def _validate(self, path: str, operation: str) -> str:
        candidate = PurePosixPath(path)
        if ".." in candidate.parts:
            raise PermissionError("remote path traversal is not allowed")
        if not candidate.is_absolute():
            candidate = PurePosixPath(self.backend.config.work_dir) / candidate
        raw = str(candidate)
        roots = [
            str(
                PurePosixPath(root)
                if PurePosixPath(root).is_absolute()
                else PurePosixPath(self.backend.config.work_dir) / root
            )
            for root in self.backend.config.allowed_roots
        ]
        if roots and not any(raw == root or raw.startswith(root.rstrip("/") + "/") for root in roots):
            raise PermissionError(f"remote path is outside allowed roots for {operation}: {raw}")
        return raw

    async def _python(self, script: str, *args: str, timeout: int = 30) -> CommandResult:
        command = "python3 -c " + shlex.quote(script)
        if args:
            command += " " + " ".join(shlex.quote(arg) for arg in args)
        return await self.backend.execute(command, cwd=".", timeout=timeout)

    async def stat(self, path: str) -> FileStat:
        safe = self._validate(path, "read")
        script = (
            "import json,pathlib,stat,sys; p=pathlib.Path(sys.argv[1]); "
            "s=p.stat() if p.exists() else None; print(json.dumps({'path':str(p),'size':s.st_size "
            "if s else 0,'is_dir':p.is_dir(),'is_file':p.is_file(),'exists':p.exists(),"
            "'modified_time':s.st_mtime if s else 0,'permissions':stat.filemode(s.st_mode)[1:] "
            "if s else ''}))"
        )
        result = await self._python(script, safe)
        if result.exit_code != 0:
            return FileStat(safe, 0, False, False, False, 0)
        return FileStat(**json.loads(result.stdout))

    async def read(self, path: str, offset: int = 0, limit: int = -1) -> bytes:
        safe = self._validate(path, "read")
        script = (
            "import base64,pathlib,sys; d=pathlib.Path(sys.argv[1]).read_bytes(); "
            "o=int(sys.argv[2]); n=int(sys.argv[3]); d=d[o:]; d=d if n<0 else d[:n]; "
            "print(base64.b64encode(d).decode())"
        )
        result = await self._python(script, safe, str(offset), str(limit))
        if result.exit_code != 0:
            raise OSError(result.stderr)
        return base64.b64decode(result.stdout.strip())

    async def write(self, path: str, data: bytes) -> None:
        safe = self._validate(path, "write")
        encoded = base64.b64encode(data).decode()
        script = (
            "import base64,pathlib,sys; p=pathlib.Path(sys.argv[1]); "
            "p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(base64.b64decode(sys.argv[2]))"
        )
        result = await self._python(script, safe, encoded)
        if result.exit_code != 0:
            raise OSError(result.stderr)

    async def rename(self, old: str, new: str) -> None:
        source = self._validate(old, "read")
        target = self._validate(new, "write")
        result = await self._python(
            "import pathlib,sys; pathlib.Path(sys.argv[1]).rename(sys.argv[2])", source, target
        )
        if result.exit_code != 0:
            raise OSError(result.stderr)

    async def delete(self, path: str) -> None:
        safe = self._validate(path, "delete")
        script = (
            "import pathlib,shutil,sys; p=pathlib.Path(sys.argv[1]); "
            "shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)"
        )
        result = await self._python(script, safe)
        if result.exit_code != 0:
            raise OSError(result.stderr)

    async def list_dir(self, path: str) -> list[str]:
        safe = self._validate(path, "read")
        result = await self._python(
            "import json,pathlib,sys; print(json.dumps(sorted(p.name for p in pathlib.Path(sys.argv[1]).iterdir())))",
            safe,
        )
        if result.exit_code != 0:
            return []
        return [str(item) for item in json.loads(result.stdout)]

    async def makedirs(self, path: str) -> None:
        safe = self._validate(path, "write")
        result = await self._python(
            "import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir(parents=True,exist_ok=True)", safe
        )
        if result.exit_code != 0:
            raise OSError(result.stderr)

"""E 层: 文件系统桥接.

接口策略:
- FsBridge 抽象层: 文件操作后端无关化
- 统一接口: stat / read / write / rename
- 后端可替换 (Local / Docker / SSH), 工具层无需感知差异
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from agent_conch.sandbox.path_validator import PathValidator


@dataclass
class FileStat:
    """文件元信息."""

    path: str
    size: int
    is_dir: bool
    is_file: bool
    exists: bool
    modified_time: float
    permissions: str = ""  # e.g. "rwxr-xr-x"


class FsBridge(ABC):
    """文件系统桥接抽象基类.

    所有文件操作工具 (read_file/write_file/edit_file/glob/grep)
    都通过 FsBridge 访问文件系统, 而不直接调用 os/pathlib.
    这样切换沙箱后端 (Local/Docker/SSH) 时无需修改工具层.
    """

    @abstractmethod
    async def stat(self, path: str) -> FileStat: ...

    @abstractmethod
    async def read(self, path: str, offset: int = 0, limit: int = -1) -> bytes: ...

    @abstractmethod
    async def write(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    async def rename(self, old: str, new: str) -> None: ...

    @abstractmethod
    async def delete(self, path: str) -> None: ...

    @abstractmethod
    async def list_dir(self, path: str) -> list[str]: ...

    @abstractmethod
    async def makedirs(self, path: str) -> None: ...


class LocalFsBridge(FsBridge):
    """本地文件系统桥接实现.

    所有操作经过 PathValidator 安全校验.
    """

    def __init__(self, validator: PathValidator | None = None):
        self.validator = validator or PathValidator()

    async def stat(self, path: str) -> FileStat:
        resolved = self.validator.validate_or_raise(path, "read")
        p = Path(resolved)
        if not p.exists():
            return FileStat(
                path=resolved,
                size=0,
                is_dir=False,
                is_file=False,
                exists=False,
                modified_time=0,
            )
        st = p.stat()
        return FileStat(
            path=resolved,
            size=st.st_size,
            is_dir=p.is_dir(),
            is_file=p.is_file(),
            exists=True,
            modified_time=st.st_mtime,
            permissions=oast_permissions(st.st_mode),
        )

    async def read(self, path: str, offset: int = 0, limit: int = -1) -> bytes:
        resolved = self.validator.validate_or_raise(path, "read")
        p = Path(resolved)
        data = p.read_bytes()
        if offset > 0:
            data = data[offset:]
        if limit >= 0:
            data = data[:limit]
        return data

    async def write(self, path: str, data: bytes) -> None:
        resolved = self.validator.validate_or_raise(path, "write")
        p = Path(resolved)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    async def rename(self, old: str, new: str) -> None:
        old_resolved = self.validator.validate_or_raise(old, "read")
        new_resolved = self.validator.validate_or_raise(new, "write")
        Path(old_resolved).rename(new_resolved)

    async def delete(self, path: str) -> None:
        resolved = self.validator.validate_or_raise(path, "delete")
        p = Path(resolved)
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()

    async def list_dir(self, path: str) -> list[str]:
        resolved = self.validator.validate_or_raise(path, "read")
        p = Path(resolved)
        if not p.is_dir():
            return []
        return [entry.name for entry in p.iterdir()]

    async def makedirs(self, path: str) -> None:
        resolved = self.validator.validate_or_raise(path, "write")
        Path(resolved).mkdir(parents=True, exist_ok=True)


def oast_permissions(mode: int) -> str:
    """将 mode 转为 rwx 字符串."""
    import stat as stat_module

    perms = ""
    for who in ("USR", "GRP", "OTH"):
        for what, letter in (("R", "r"), ("W", "w"), ("X", "x")):
            flag = getattr(stat_module, f"S_I{what}{who}")
            perms += letter if mode & flag else "-"
    return perms

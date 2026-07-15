"""G 层: 敏感路径硬编码.

设计文档要求:
- SENSITIVE_PATH_PATTERNS: 硬编码不可覆盖
- 用户规则叠加 (不能覆盖硬编码)
- platform 适配 (Unix + Windows)
- 与 PathValidator 集成

P1 实现中 PathValidator 已内嵌敏感路径, P2 抽离为独立模块.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any


# === 硬编码敏感路径 — 不可被用户配置覆盖 ===

# Unix 敏感路径
SENSITIVE_PATHS_UNIX: list[str] = [
    "/etc",
    "/etc/",
    "/root",
    "/root/.ssh",
    "/var/log",
    "/var/run",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/.env",
    "~/.ssh",
    "~/.ssh/",
    "~/.env",
    "~/.aws",
    "~/.aws/",
    "~/.config",
    "~/.config/",
    "~/.gnupg",
    "~/.gnupg/",
    "~/.docker",
    "~/.docker/",
    "~/.kube",
    "~/.kube/",
    "~/.npmrc",
    "~/.pypirc",
    "~/.netrc",
    "~/.gitconfig",
]

# Windows 敏感路径
SENSITIVE_PATHS_WINDOWS: list[str] = [
    "C:\\Windows\\System32",
    "C:\\Windows\\System32\\",
    "C:\\Windows\\System",
    "C:\\Windows\\System\\",
    "C:\\Windows\\SysWOW64",
    "C:\\Windows\\SysWOW64\\",
    "C:\\Windows\\WinSxS",
    "C:\\Windows\\WinSxS\\",
    "C:\\Windows\\System32\\config",
    "C:\\Windows\\System32\\drivers",
    "C:\\Program Files",
    "C:\\Program Files\\",
    "C:\\Program Files (x86)",
    "C:\\Program Files (x86)\\",
    "C:\\ProgramData",
    "C:\\ProgramData\\",
    "C:\\Users\\All Users",
    "C:\\Recovery",
    "C:\\$Recycle.Bin",
    "C:\\pagefile.sys",
    "C:\\hiberfil.sys",
    "C:\\swapfile.sys",
    # 凭证文件
    "~/.ssh",
    "~/.env",
    "~/.aws",
    "~/.config",
    "~/.gnupg",
]

# 敏感文件名模式 (无论路径在哪)
SENSITIVE_FILE_PATTERNS: list[str] = [
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    ".env.development",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".crt",
    ".cer",
    "credentials",
    "credentials.json",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".gitconfig",
    ".git-credentials",
    ".docker/config.json",
    ".kube/config",
    "wp-config.php",
    "database.yml",
    "secrets.yml",
    "secrets.json",
]


def get_sensitive_paths() -> list[str]:
    """获取当前平台的硬编码敏感路径.

    自动检测平台, 返回对应的敏感路径列表.
    """
    system = platform.system()
    paths: list[str] = []

    if system == "Windows":
        paths.extend(SENSITIVE_PATHS_WINDOWS)
        paths.extend(SENSITIVE_PATHS_UNIX)  # Windows 上也可能有 Unix 路径 (Git Bash)
    else:
        paths.extend(SENSITIVE_PATHS_UNIX)

    return paths


def get_sensitive_file_patterns() -> list[str]:
    """获取敏感文件名模式."""
    return list(SENSITIVE_FILE_PATTERNS)


def is_sensitive_path(
    path: str,
    user_sensitive_paths: list[str] | None = None,
) -> tuple[bool, str]:
    """检查路径是否敏感.

    Args:
        path: 待检查的路径
        user_sensitive_paths: 用户自定义敏感路径 (叠加在硬编码之上)

    Returns:
        (is_sensitive, reason)
    """
    all_sensitive = get_sensitive_paths()
    if user_sensitive_paths:
        all_sensitive.extend(user_sensitive_paths)

    # 展开路径
    expanded = os.path.expanduser(path)
    normalized = expanded.replace("\\", "/")

    # 检查路径前缀匹配
    for sensitive in all_sensitive:
        sensitive_expanded = os.path.expanduser(sensitive)
        sensitive_normalized = sensitive_expanded.replace("\\", "/")

        if normalized == sensitive_normalized:
            return True, f"Path is sensitive (hardcoded): {sensitive}"
        if normalized.startswith(sensitive_normalized.rstrip("/") + "/"):
            return True, f"Path is under sensitive directory: {sensitive}"

    # 检查文件名模式
    basename = os.path.basename(expanded)
    for pattern in SENSITIVE_FILE_PATTERNS:
        if basename == pattern or basename.endswith(pattern):
            return True, f"Filename matches sensitive pattern: {pattern}"

    return False, ""


class SensitivePathChecker:
    """敏感路径检查器.

    硬编码路径不可被用户配置覆盖.
    用户规则只能增加, 不能减少.
    """

    def __init__(self, user_sensitive_paths: list[str] | None = None):
        self.hardcoded_paths = get_sensitive_paths()
        self.file_patterns = get_sensitive_file_patterns()
        self.user_paths = list(user_sensitive_paths) if user_sensitive_paths else []

    def check(self, path: str) -> tuple[bool, str]:
        """检查路径是否敏感.

        Returns:
            (is_sensitive, reason)
        """
        return is_sensitive_path(path, self.user_paths)

    def add_user_path(self, path: str) -> None:
        """添加用户自定义敏感路径 (不能移除硬编码)."""
        if path not in self.user_paths:
            self.user_paths.append(path)

    def list_all(self) -> list[str]:
        """列出所有敏感路径 (硬编码 + 用户)."""
        return self.hardcoded_paths + self.user_paths

    def merge_with_validator(
        self, validator_sensitive_paths: list[str]
    ) -> list[str]:
        """与 PathValidator 的敏感路径列表合并.

        确保 PathValidator 的敏感路径包含所有硬编码路径.
        """
        merged = set(self.hardcoded_paths)
        merged.update(validator_sensitive_paths)
        merged.update(self.user_paths)
        return list(merged)

"""E 层: 路径安全验证.

校验策略:
- PathValidator 防路径遍历 + 敏感路径硬编码不可覆盖
- 硬编码不可覆盖 (/etc, ~/.ssh, /.env 等) + 用户规则叠加
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 敏感路径硬编码 — 不可被用户配置覆盖
SENSITIVE_PATH_PATTERNS: list[str] = [
    "/etc",
    "/etc/",
    "~/.ssh",
    "~/.ssh/",
    "/.env",
    "~/.env",
    "~/.config",
    "~/.config/",
    "~/.aws",
    "~/.aws/",
    "~/.gnupg",
    "/root/.ssh",
    "/var/log",
    "/proc",
    "/sys",
    "/dev",
    "C:\\Windows\\System32",
    "C:\\Windows\\System32\\",
]


@dataclass
class PathValidationResult:
    """路径验证结果."""

    allowed: bool
    resolved_path: str
    reason: str = ""
    is_sensitive: bool = False


@dataclass
class PathValidator:
    """路径安全验证器.

    检查项:
    1. 路径遍历攻击 (../ 序列)
    2. 敏感路径硬编码 (不可覆盖)
    3. allowed_roots 白名单 (如果配置)
    4. 用户自定义敏感路径 (叠加在硬编码之上)
    """

    allowed_roots: list[str] = field(default_factory=list)
    user_sensitive_paths: list[str] = field(default_factory=list)
    cwd: str = field(default_factory=lambda: os.getcwd())

    def __post_init__(self) -> None:
        # 展开 allowed_roots 中的 ~ 和相对路径
        self._resolved_roots: list[Path] = []
        for root in self.allowed_roots:
            expanded = Path(os.path.expanduser(root))
            if not expanded.is_absolute():
                expanded = Path(self.cwd) / expanded
            self._resolved_roots.append(expanded.resolve())

        # 合并硬编码 + 用户敏感路径
        self._all_sensitive = list(SENSITIVE_PATH_PATTERNS) + list(self.user_sensitive_paths)
        # 保留原始字符串模式 (不依赖 resolve, 跨平台兼容)
        self._sensitive_patterns_raw: list[str] = []
        for p in self._all_sensitive:
            self._sensitive_patterns_raw.append(os.path.expanduser(p))
        # resolved 路径用于精确比较
        self._resolved_sensitive: list[Path] = []
        for p in self._all_sensitive:
            self._resolved_sensitive.append(Path(os.path.expanduser(p)).resolve())

    def validate(self, path: str, operation: str = "read") -> PathValidationResult:
        """验证路径安全性.

        Args:
            path: 待验证的路径
            operation: read | write | exec | delete

        Returns:
            PathValidationResult
        """
        # 1. 展开路径
        raw_path = path
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            expanded = os.path.join(self.cwd, expanded)
        resolved = Path(expanded).resolve()

        # 2. 路径遍历检测 — 检查原始路径中的 ../
        if ".." in Path(raw_path).parts:
            # 允许 .. 但必须 resolve 后在 allowed_roots 内
            pass  # resolve 后会在下面检查

        # 3. 敏感路径检查 (硬编码不可覆盖)
        # 3a. 原始字符串模式匹配 (跨平台兼容, 不依赖 resolve)
        normalized_path = path.replace("\\", "/")
        expanded_path = os.path.expanduser(path).replace("\\", "/")
        for pattern in self._sensitive_patterns_raw:
            normalized_pattern = pattern.replace("\\", "/")
            # 精确匹配或前缀匹配 (pattern 是 path 的前缀)
            if normalized_path == normalized_pattern or expanded_path == normalized_pattern:
                return PathValidationResult(
                    allowed=False,
                    resolved_path=str(resolved),
                    reason=f"Path is sensitive (pattern): {pattern}",
                    is_sensitive=True,
                )
            if expanded_path.startswith(normalized_pattern.rstrip("/") + "/"):
                return PathValidationResult(
                    allowed=False,
                    resolved_path=str(resolved),
                    reason=f"Path is sensitive (pattern prefix): {pattern}",
                    is_sensitive=True,
                )
        # 3b. resolved 路径精确比较
        for sensitive in self._resolved_sensitive:
            try:
                resolved.relative_to(sensitive)
                return PathValidationResult(
                    allowed=False,
                    resolved_path=str(resolved),
                    reason=f"Path is sensitive (hardcoded): {sensitive}",
                    is_sensitive=True,
                )
            except ValueError:
                continue

        # 4. allowed_roots 白名单检查
        if self._resolved_roots:
            in_root = False
            for root in self._resolved_roots:
                try:
                    resolved.relative_to(root)
                    in_root = True
                    break
                except ValueError:
                    continue
            if not in_root:
                return PathValidationResult(
                    allowed=False,
                    resolved_path=str(resolved),
                    reason=f"Path outside allowed roots: {resolved} not in {self._resolved_roots}",
                )

        # 5. 写操作额外检查: 不允许写到敏感路径的父目录
        if operation in ("write", "delete"):
            for sensitive in self._resolved_sensitive:
                try:
                    sensitive.relative_to(resolved)
                    # resolved 是 sensitive 的父目录 → 禁止
                    return PathValidationResult(
                        allowed=False,
                        resolved_path=str(resolved),
                        reason=f"Write to parent of sensitive path: {sensitive}",
                        is_sensitive=True,
                    )
                except ValueError:
                    continue

        return PathValidationResult(
            allowed=True,
            resolved_path=str(resolved),
        )

    def is_sensitive(self, path: str) -> bool:
        """快速检查路径是否敏感."""
        return not self.validate(path).allowed and self.validate(path).is_sensitive

    def validate_or_raise(self, path: str, operation: str = "read") -> str:
        """验证路径, 不通过则抛出 PermissionError."""
        result = self.validate(path, operation)
        if not result.allowed:
            raise PermissionError(f"Path blocked by PathValidator: {result.reason}")
        return result.resolved_path

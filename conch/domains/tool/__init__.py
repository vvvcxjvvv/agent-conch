"""域2：工具系统与协议。

导入此包即注册默认实现到 registry。
"""
from conch.domains.tool.builtin_shell import BuiltinShellProvider  # noqa: F401

__all__ = ["BuiltinShellProvider"]

"""域8：约束、校验与恢复。

导入此包即注册默认实现到 registry。
"""
from conch.domains.constraint.linter import Linter  # noqa: F401

__all__ = ["Linter"]

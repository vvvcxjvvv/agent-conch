"""域3：上下文管理。

导入此包即注册默认实现到 registry。
"""
from conch.domains.context.jit_compaction import JitCompaction  # noqa: F401

__all__ = ["JitCompaction"]

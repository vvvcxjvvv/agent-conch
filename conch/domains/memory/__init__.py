"""域4：记忆与状态。

导入此包即注册默认实现到 registry。
"""
from conch.domains.memory.notes_file import NotesFileMemory  # noqa: F401

__all__ = ["NotesFileMemory"]

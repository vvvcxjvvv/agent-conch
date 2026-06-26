"""域1：信息边界与指令系统。

导入此包即注册默认实现到 registry。
"""
from conch.domains.information.agents_md import AgentsMdLoader  # noqa: F401

__all__ = ["AgentsMdLoader"]

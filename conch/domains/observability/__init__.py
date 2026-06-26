"""域7：可观测性。

导入此包即注册默认实现到 registry。
"""
from conch.domains.observability.console_tracer import ConsoleTracer  # noqa: F401

__all__ = ["ConsoleTracer"]

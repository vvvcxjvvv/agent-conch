"""域5：执行编排与生命周期。

导入此包即注册默认实现到 registry。
"""
from conch.domains.orchestration.single_loop import SingleLoopOrchestration  # noqa: F401

__all__ = ["SingleLoopOrchestration"]

"""AgentConch 核心抽象层 — 稳定，极少改动。

依赖倒置原则：此包仅定义接口契约与基础机制，
不依赖任何具体能力域实现（conch/domains/）。
"""

from conch.core.extension import (
    DOMAINS,
    ConstraintProvider,
    ContextManager,
    Evaluator,
    ExtensionPoint,
    GovernanceProvider,
    InformationProvider,
    MemoryProvider,
    ObservabilityProvider,
    OrchestrationMode,
    Plugin,
    ToolProvider,
)
from conch.core.hooks import HookBus, HookResult, HookAction, hook, hook_bus
from conch.core.middleware import Middleware, Pipeline
from conch.core.registry import Registry, registry
from conch.core.loop import AgentLoop, CostGuard, DegradeLevel, State, TaskStatus

# Profile / Experiment 依赖 pydantic + yaml，可选导入
try:
    from conch.core.profile import Profile, ProfileLoader
    from conch.core.experiment import (
        ExperimentResult,
        TaskResult,
        TaskSuite,
        run_experiment,
        run_ablation,
    )
except ImportError:
    Profile = ProfileLoader = None  # type: ignore
    ExperimentResult = TaskResult = TaskSuite = None  # type: ignore
    run_experiment = run_ablation = None  # type: ignore

__all__ = [
    # 扩展点
    "ExtensionPoint", "Plugin", "DOMAINS",
    "InformationProvider", "ToolProvider", "ContextManager", "MemoryProvider",
    "OrchestrationMode", "Evaluator", "ObservabilityProvider",
    "ConstraintProvider", "GovernanceProvider",
    # 注册中心
    "Registry", "registry",
    # Hook
    "HookBus", "HookResult", "HookAction", "hook", "hook_bus",
    # 中间件
    "Middleware", "Pipeline",
    # Profile
    "Profile", "ProfileLoader",
    # Loop
    "AgentLoop", "CostGuard", "DegradeLevel", "State", "TaskStatus",
    # 实验框架
    "ExperimentResult", "TaskResult", "TaskSuite", "run_experiment", "run_ablation",
]

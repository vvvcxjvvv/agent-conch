"""AgentConch 核心抽象层 — v2，稳定，极少改动。

依赖倒置原则：此包仅定义接口契约与基础机制，
不依赖任何具体能力域实现（conch/adapters/）。

v2 改动：
- 移除 AgentLoop（编排降级到 adapters/orchestration/）
- 新增 GuardrailProvider / GuardrailResult（域10）
- 新增 LangGraphHookBridge（框架事件→Hook 桥接）
- 新增 GuardrailPipeline（六层护栏管道）
- CostGuard / State 从 loop.py 拆到 cost_guard.py
"""

from conch.core.extension import (
    DOMAINS,
    ConstraintProvider,
    ContextManager,
    Evaluator,
    ExtensionPoint,
    GovernanceProvider,
    GuardrailProvider,
    GuardrailResult,
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
from conch.core.cost_guard import CostGuard, DegradeLevel, State, TaskStatus
from conch.core.hook_bridge import LangGraphHookBridge
from conch.core.guardrail_pipeline import (
    GuardrailBlocked,
    GuardrailMiddleware,
    GuardrailPipeline,
)

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
    # 扩展点（10 域）
    "ExtensionPoint", "Plugin", "DOMAINS",
    "InformationProvider", "ToolProvider", "ContextManager", "MemoryProvider",
    "OrchestrationMode", "Evaluator", "ObservabilityProvider",
    "ConstraintProvider", "GovernanceProvider",
    "GuardrailProvider", "GuardrailResult",
    # 注册中心
    "Registry", "registry",
    # Hook
    "HookBus", "HookResult", "HookAction", "hook", "hook_bus",
    # 中间件
    "Middleware", "Pipeline",
    # 状态与成本守卫（从 loop.py 拆出）
    "CostGuard", "DegradeLevel", "State", "TaskStatus",
    # Hook 桥接层（v2 新增）
    "LangGraphHookBridge",
    # 护栏管道（v2 新增）
    "GuardrailPipeline", "GuardrailMiddleware", "GuardrailBlocked",
    # Profile
    "Profile", "ProfileLoader",
    # 实验框架
    "ExperimentResult", "TaskResult", "TaskSuite", "run_experiment", "run_ablation",
]

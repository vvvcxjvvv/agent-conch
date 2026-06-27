"""依赖注入 — Registry / ProfileLoader / AgentRuntime 构建。

核心函数 build_runtime(profile): 按 Profile.domains 调 registry.build
构建各域 Plugin 实例，组装 State（含 hook_bus / guardrail_pipeline），
返回 AgentRuntime 容器供 API 路由使用。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 启动时加载 .env 文件
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass

from conch.core.cost_guard import CostGuard, State, TaskStatus
from conch.core.guardrail_pipeline import GuardrailPipeline
from conch.core.hooks import HookBus
from conch.core.profile import Profile, ProfileLoader
from conch.core.registry import registry

logger = logging.getLogger(__name__)

# 全局单例
_registry_initialized = False
_profile_loader: ProfileLoader | None = None
_session_store: dict[str, dict] = {}  # MVP 内存 store


def _ensure_adapters_loaded():
    """import 所有 adapter 模块，触发 @register 注册。"""
    global _registry_initialized
    if _registry_initialized:
        return
    # import 即注册
    from conch.adapters.llm.litellm_provider import LiteLLMProvider  # noqa: F401
    from conch.adapters.orchestration.langgraph_react import LangGraphReActOrchestrator  # noqa: F401
    from conch.adapters.orchestration.single_loop import SingleLoopOrchestration  # noqa: F401
    from conch.adapters.tool.mcp_provider import MCPToolProvider  # noqa: F401
    from conch.adapters.tool.builtin_shell import BuiltinShellProvider  # noqa: F401
    from conch.adapters.guardrail.nemo_guardrails import NemoGuardrail  # noqa: F401
    from conch.adapters.observability.langfuse_tracer import LangfuseTracer  # noqa: F401
    from conch.adapters.observability.console_tracer import ConsoleTracer  # noqa: F401
    from conch.adapters.information.agents_md import AgentsMdProvider  # noqa: F401
    from conch.adapters.context.jit_compaction import JitCompaction  # noqa: F401
    from conch.adapters.memory.notes_file import NotesFileMemory  # noqa: F401
    _registry_initialized = True


def get_registry():
    _ensure_adapters_loaded()
    return registry


def get_profile_loader() -> ProfileLoader:
    global _profile_loader
    if _profile_loader is None:
        profiles_dir = Path(__file__).resolve().parents[2] / "profiles"
        _profile_loader = ProfileLoader(profiles_dir)
    return _profile_loader


def get_session_store() -> dict[str, dict]:
    return _session_store


@dataclass
class AgentRuntime:
    """一次会话的运行时容器 — 持有各域 Plugin 实例 + State。"""

    profile: Profile
    llm: Any = None
    orchestrator: Any = None
    tools: Any = None
    context_mgr: Any = None
    info_provider: Any = None
    memory: Any = None
    guardrail_provider: Any = None
    guardrail_pipeline: GuardrailPipeline | None = None
    observability: Any = None
    cost_guard: CostGuard | None = None
    hook_bus: HookBus = field(default_factory=HookBus)
    state: State | None = None


def build_runtime(profile: Profile) -> AgentRuntime:
    """按 Profile 构建各域 Plugin 实例，组装 AgentRuntime。"""
    _ensure_adapters_loaded()
    rt = AgentRuntime(profile=profile, hook_bus=HookBus())
    d = profile.domains

    # LLM
    if "llm" in d and d["llm"].impl:
        cfg = d["llm"]
        rt.llm = registry.build("llm", cfg.impl, cfg.version, **cfg.params)

    # 编排
    if "orchestration" in d and d["orchestration"].impl:
        cfg = d["orchestration"]
        rt.orchestrator = registry.build("orchestration", cfg.impl, cfg.version, **cfg.params)

    # 工具
    if "tool" in d and d["tool"].impl:
        cfg = d["tool"]
        rt.tools = registry.build("tool", cfg.impl, cfg.version, **cfg.params)

    # 上下文
    if "context" in d and d["context"].impl:
        cfg = d["context"]
        rt.context_mgr = registry.build("context", cfg.impl, cfg.version, **cfg.params)

    # 信息边界
    if "information" in d and d["information"].impl:
        cfg = d["information"]
        rt.info_provider = registry.build("information", cfg.impl, cfg.version, **cfg.params)

    # 记忆
    if "memory" in d and d["memory"].impl:
        cfg = d["memory"]
        rt.memory = registry.build("memory", cfg.impl, cfg.version, **cfg.params)

    # 护栏
    if "guardrail" in d and d["guardrail"].impl:
        cfg = d["guardrail"]
        rt.guardrail_provider = registry.build("guardrail", cfg.impl, cfg.version, **cfg.params)

    # 可观测
    if "observability" in d and d["observability"].impl:
        cfg = d["observability"]
        rt.observability = registry.build("observability", cfg.impl, cfg.version, **cfg.params)

    # 成本守卫
    rt.cost_guard = CostGuard(max_tokens=profile.max_tokens)

    # 初始化 State
    rt.state = State(task="", hook_bus=rt.hook_bus, profile=profile)

    # 护栏管道
    rt.guardrail_pipeline = GuardrailPipeline(rt.guardrail_provider, rt.state)

    return rt

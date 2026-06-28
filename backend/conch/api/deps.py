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
from conch.core.guardrail_pipeline import GuardrailBlocked, GuardrailPipeline
from conch.core.hooks import HookAction, HookBus, HookResult
from conch.core.profile import Profile, ProfileLoader
from conch.core.registry import registry
from conch.api.hitl import ApprovalManager, WebSocketHub

logger = logging.getLogger(__name__)

# 全局单例
_registry_initialized = False
_profile_loader: ProfileLoader | None = None
_session_store: dict[str, dict] = {}  # MVP 内存 store
_approval_manager = ApprovalManager()
_websocket_hub = WebSocketHub()


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
    from conch.adapters.guardrail.llamaguard import LlamaGuardClassifier  # noqa: F401
    from conch.adapters.guardrail.stacked_guardrails import StackedGuardrails  # noqa: F401
    from conch.adapters.observability.langfuse_tracer import LangfuseTracer  # noqa: F401
    from conch.adapters.observability.stacked_tracer import StackedTracer  # noqa: F401
    from conch.adapters.observability.console_tracer import ConsoleTracer  # noqa: F401
    from conch.adapters.governance.allowlist import AllowlistGovernance  # noqa: F401
    from conch.adapters.information.agents_md import AgentsMdProvider  # noqa: F401
    from conch.adapters.context.jit_compaction import JitCompaction  # noqa: F401
    from conch.adapters.memory.mem0_provider import Mem0MemoryProvider  # noqa: F401
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


def get_approval_manager() -> ApprovalManager:
    return _approval_manager


def get_websocket_hub() -> WebSocketHub:
    return _websocket_hub


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
    governance: Any = None
    observability: Any = None
    cost_guard: CostGuard | None = None
    approval_manager: ApprovalManager | None = None
    websocket_hub: WebSocketHub | None = None
    hook_bus: HookBus = field(default_factory=HookBus)
    state: State | None = None


def _emit_cost_event(state: State) -> None:
    state.emit_event(
        {
            "type": "cost_update",
            "tokens": state.total_tokens,
            "cost": state.total_cost,
            "steps": state.steps,
            "degrade_level": state.degrade_level.name,
        }
    )


def _record_observability_event(rt: AgentRuntime, name: str, payload: dict[str, Any]) -> None:
    if rt.observability is None:
        return
    recorder = getattr(rt.observability, "record_event", None)
    if callable(recorder):
        recorder(name, payload)


def _record_guardrail_event(
    rt: AgentRuntime,
    state: State,
    layer: str,
    action: str,
    reason: str,
    tool: str | None = None,
    extra: dict[str, Any] | None = None,
    broadcast: bool = False,
) -> None:
    payload = {
        "type": "guardrail",
        "layer": layer,
        "action": action,
        "reason": reason,
        "tool": tool,
    }
    if extra:
        payload.update(extra)
    state.emit_event(payload)
    if broadcast and rt.websocket_hub is not None:
        rt.websocket_hub.emit(state.session_id, payload)
    if rt.governance is not None:
        rt.governance.audit(
            "guardrail_event",
            {
                "session_id": state.session_id,
                "layer": layer,
                "action": action,
                "reason": reason,
                "tool": tool,
                **(extra or {}),
            },
        )
    _record_observability_event(
        rt,
        "guardrail_event",
        {
            "session_id": state.session_id,
            "layer": layer,
            "action": action,
            "reason": reason,
            "tool": tool,
            **(extra or {}),
        },
    )


def remember_pending_resume(session_id: str, request_id: str, message: str, profile_name: str) -> None:
    session = _session_store.get(session_id)
    if session is None:
        return
    session["pending_resume"] = {
        "request_id": request_id,
        "message": message,
        "profile": profile_name,
    }


def pop_pending_resume(session_id: str, request_id: str | None = None) -> dict[str, Any] | None:
    session = _session_store.get(session_id)
    if session is None:
        return None
    pending = session.get("pending_resume")
    if not isinstance(pending, dict):
        return None
    if request_id and pending.get("request_id") != request_id:
        return None
    session.pop("pending_resume", None)
    return pending


def get_pending_resume(session_id: str, request_id: str | None = None) -> dict[str, Any] | None:
    session = _session_store.get(session_id)
    if session is None:
        return None
    pending = session.get("pending_resume")
    if not isinstance(pending, dict):
        return None
    if request_id and pending.get("request_id") != request_id:
        return None
    return pending


def _install_runtime_hooks(rt: AgentRuntime) -> None:
    """为默认运行时装配护栏、成本和可观测 Hook。"""
    state = rt.state
    if state is None:
        return

    def guardrail_pre_model_call(state: State, **_: Any):
        if rt.guardrail_pipeline is None:
            return None
        try:
            rt.guardrail_pipeline.run_input(str(state.task))
        except GuardrailBlocked as exc:
            _record_guardrail_event(
                rt,
                state,
                "input",
                exc.result.action,
                exc.result.reason,
            )
            return HookResult(HookAction.INTERRUPT, exc.result.reason or "Input blocked")
        return None

    def governance_pre_tool(state: State, tool: str, args: dict | None = None, **_: Any):
        if rt.governance is None:
            return None
        safe_args = args or {}
        allowed = rt.governance.check_permission(tool, safe_args)
        rt.governance.audit(
            "tool_permission",
            {"session_id": state.session_id, "tool": tool, "args": safe_args, "allowed": allowed},
        )
        if not allowed:
            reason = f"Tool '{tool}' is not allowed by governance policy"
            _record_guardrail_event(rt, state, "governance", "blocked", reason, tool=tool, broadcast=True)
            return HookResult(HookAction.INTERRUPT, reason)

        requires_approval = getattr(rt.governance, "requires_approval", None)
        if callable(requires_approval) and requires_approval(tool, safe_args):
            if rt.approval_manager is not None and rt.approval_manager.consume_approval(
                state.session_id, tool, safe_args
            ):
                rt.governance.audit(
                    "tool_approval_consumed",
                    {"session_id": state.session_id, "tool": tool, "args": safe_args},
                )
                return None

            request_payload = {
                "type": "hitl_request",
                "tool": tool,
                "args": safe_args,
                "reason": f"Tool '{tool}' requires approval",
            }
            if rt.approval_manager is not None:
                request = rt.approval_manager.create_request(
                    state.session_id,
                    tool,
                    safe_args,
                    f"Tool '{tool}' requires approval",
                )
                request_payload["request_id"] = request.request_id
                remember_pending_resume(state.session_id, request.request_id, str(state.task), rt.profile.name)
            rt.governance.audit(
                "tool_approval_required",
                {
                    "session_id": state.session_id,
                    "tool": tool,
                    "args": safe_args,
                    "request_id": request_payload.get("request_id", ""),
                },
            )
            rt.governance.audit(
                "tool_permission",
                {"session_id": state.session_id, "tool": tool, "args": safe_args, "allowed": False},
            )
            state.emit_event(request_payload)
            if rt.websocket_hub is not None:
                rt.websocket_hub.emit(state.session_id, request_payload)
            _record_observability_event(
                rt,
                "hitl_request",
                {
                    "session_id": state.session_id,
                    "tool": tool,
                    "args": safe_args,
                    "request_id": request_payload.get("request_id", ""),
                },
            )
            return HookResult(
                HookAction.INTERRUPT,
                f"Tool '{tool}' requires approval",
            )
        return None

    def guardrail_pre_tool(state: State, tool: str, args: dict | None = None, **_: Any):
        if rt.guardrail_pipeline is None:
            return None
        result = rt.guardrail_pipeline.check_tool(tool, args or {})
        if not result.blocked:
            return None
        _record_guardrail_event(rt, state, "tool", result.action, result.reason, tool=tool)
        return HookResult(HookAction.INTERRUPT, result.reason or f"Tool '{tool}' blocked")

    def record_model_action(state: State, action: dict | None = None, **_: Any):
        if not action:
            return None
        content = action.get("content")
        if rt.guardrail_pipeline is not None and isinstance(content, str) and content:
            try:
                rt.guardrail_pipeline.run_output(content)
            except GuardrailBlocked as exc:
                _record_guardrail_event(rt, state, "output", exc.result.action, exc.result.reason)
        state.record(action)
        should_emit_cost_event = True
        if rt.cost_guard is not None:
            level = rt.cost_guard.check(state)
            if level.value > state.degrade_level.value:
                should_emit_cost_event = False
                rt.cost_guard.apply(state, level)
        if should_emit_cost_event:
            _emit_cost_event(state)
        return None

    def trace_step(state: State, **_: Any):
        if rt.observability is not None:
            rt.observability.trace(state)
        return None

    def audit_post_tool(state: State, result: Any = None, **_: Any):
        if rt.governance is not None:
            rt.governance.audit("tool_result", {"session_id": state.session_id, "result": result})
        _record_observability_event(
            rt,
            "tool_result",
            {"session_id": state.session_id, "result": str(result)},
        )
        return None

    def audit_tool_error(state: State, error: Exception, **_: Any):
        if rt.governance is not None:
            rt.governance.audit("tool_error", {"session_id": state.session_id, "error": str(error)})
        _record_observability_event(
            rt,
            "tool_error",
            {"session_id": state.session_id, "error": str(error)},
        )
        return None

    def handle_cost_exceeded(state: State, level, **_: Any):
        _emit_cost_event(state)
        if level.name == "L4_TERMINATE":
            return HookResult(HookAction.INTERRUPT, "Cost limit exceeded")
        return None

    rt.hook_bus.register("pre_model_call", guardrail_pre_model_call, priority=5, name="guardrail_pre_model_call")
    rt.hook_bus.register("pre_tool", governance_pre_tool, priority=5, name="governance_pre_tool")
    rt.hook_bus.register("pre_tool", guardrail_pre_tool, priority=10, name="guardrail_pre_tool")
    rt.hook_bus.register("post_model_call", record_model_action, priority=10, name="record_model_action")
    rt.hook_bus.register("post_step", trace_step, priority=50, name="trace_step")
    rt.hook_bus.register("post_tool", audit_post_tool, priority=20, name="audit_post_tool")
    rt.hook_bus.register("on_tool_error", audit_tool_error, priority=20, name="audit_tool_error")
    rt.hook_bus.register("on_cost_exceeded", handle_cost_exceeded, priority=10, name="handle_cost_exceeded")


def build_runtime(profile: Profile, session_id: str = "") -> AgentRuntime:
    """按 Profile 构建各域 Plugin 实例，组装 AgentRuntime。"""
    _ensure_adapters_loaded()
    rt = AgentRuntime(
        profile=profile,
        hook_bus=HookBus(),
        approval_manager=get_approval_manager(),
        websocket_hub=get_websocket_hub(),
    )
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

    # 治理
    if "governance" in d and d["governance"].impl:
        cfg = d["governance"]
        rt.governance = registry.build("governance", cfg.impl, cfg.version, **cfg.params)

    # 可观测
    if "observability" in d and d["observability"].impl:
        cfg = d["observability"]
        rt.observability = registry.build("observability", cfg.impl, cfg.version, **cfg.params)

    # 成本守卫
    rt.cost_guard = CostGuard(max_tokens=profile.max_tokens)

    # 初始化 State
    rt.state = State(task="", hook_bus=rt.hook_bus, profile=profile, session_id=session_id)

    # 护栏管道
    rt.guardrail_pipeline = GuardrailPipeline(rt.guardrail_provider, rt.state)
    _install_runtime_hooks(rt)

    return rt

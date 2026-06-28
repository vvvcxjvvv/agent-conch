"""core 层单元测试 — v2 改造验证。"""

import sys
from pathlib import Path

import pytest

# 确保能 import conch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_domains_includes_guardrail():
    """DOMAINS 应包含 guardrail（第 10 域）。"""
    from conch.core.extension import DOMAINS
    assert "guardrail" in DOMAINS
    assert len(DOMAINS) == 10


def test_guardrail_result_dataclass():
    """GuardrailResult 有正确字段。"""
    from conch.core.extension import GuardrailResult
    r = GuardrailResult(blocked=True, reason="test", action="block")
    assert r.blocked is True
    assert r.reason == "test"
    assert r.action == "block"
    assert r.sanitized is None


def test_state_has_hook_bus_field():
    """State 应有 hook_bus 和 profile 字段（v2 新增）。"""
    from conch.core.cost_guard import State
    fields = State.__dataclass_fields__
    assert "hook_bus" in fields
    assert "profile" in fields


def test_cost_guard_levels():
    """CostGuard 分级降级正确。"""
    from conch.core.cost_guard import CostGuard, DegradeLevel, State, TaskStatus

    guard = CostGuard(max_tokens=1000)
    state = State(task="test", status=TaskStatus.RUNNING)

    # 0% → NONE
    state.total_tokens = 0
    assert guard.check(state) == DegradeLevel.NONE

    # 60% → L1_COMPACT
    state.total_tokens = 600
    assert guard.check(state) == DegradeLevel.L1_COMPACT

    # 80% → L2_SWITCH_MODEL
    state.total_tokens = 800
    assert guard.check(state) == DegradeLevel.L2_SWITCH_MODEL

    # 100% → L4_TERMINATE
    state.total_tokens = 1000
    assert guard.check(state) == DegradeLevel.L4_TERMINATE
    assert guard.exceeded(state) is True


def test_guardrail_pipeline_blocks():
    """GuardrailPipeline 拦截 blocked 输入。"""
    from conch.core.cost_guard import State
    from conch.core.extension import GuardrailProvider, GuardrailResult, Plugin
    from conch.core.guardrail_pipeline import GuardrailBlocked, GuardrailPipeline

    class BlockAllGuardrail(Plugin):
        domain = "guardrail"
        name = "block_all"
        def check_input(self, text, state):
            return GuardrailResult(blocked=True, reason="test block")
        def check_output(self, text, state):
            return GuardrailResult(blocked=False)
        def check_tool(self, tool, args, state):
            return GuardrailResult(blocked=False)

    state = State(task="test")
    gp = GuardrailPipeline(BlockAllGuardrail(), state)

    try:
        gp.run_input("hello")
        assert False, "Should have raised GuardrailBlocked"
    except GuardrailBlocked as e:
        assert e.result.reason == "test block"


def test_hook_bridge_exists():
    """LangGraphHookBridge 类存在且有回调方法。"""
    from langchain_core.callbacks.base import BaseCallbackHandler

    from conch.core.hook_bridge import LangGraphHookBridge
    from conch.core.cost_guard import State
    from conch.core.hooks import HookBus

    state = State(task="test", hook_bus=HookBus())
    bridge = LangGraphHookBridge(state.hook_bus, state)

    assert isinstance(bridge, BaseCallbackHandler)
    assert bridge.run_inline is True
    assert bridge.raise_error is True

    # 验证回调方法存在
    assert hasattr(bridge, "on_llm_start")
    assert hasattr(bridge, "on_chat_model_start")
    assert hasattr(bridge, "on_llm_end")
    assert hasattr(bridge, "on_tool_start")
    assert hasattr(bridge, "on_tool_end")
    assert hasattr(bridge, "on_tool_error")


def test_profile_loader_resolves_profile_relative_paths(tmp_path):
    """Profile 中的路径参数应相对 profile 文件解析。"""
    from conch.core.profile import ProfileLoader

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile_file = profiles_dir / "test.yaml"
    profile_file.write_text(
        """
name: test
domains:
  information:
    impl: agents_md
    params:
      file: "../../AGENTS.md"
  guardrail:
    impl: nemo_guardrails
    params:
      config_dir: "../guardrail_configs/chat"
  tool:
    impl: mcp_provider
    params:
      servers:
        - command: "npx"
          args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
  governance:
    impl: allowlist_perms
    params:
      audit_file: "../log/audit.jsonl"
""".strip(),
        encoding="utf-8",
    )

    profile = ProfileLoader(profiles_dir).load("test")

    assert profile.domains["information"].params["file"] == str(
        (profiles_dir / "../../AGENTS.md").resolve()
    )
    assert profile.domains["guardrail"].params["config_dir"] == str(
        (profiles_dir / "../guardrail_configs/chat").resolve()
    )
    assert profile.domains["tool"].params["servers"][0]["args"] == [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        ".",
    ]
    assert profile.domains["governance"].params["audit_file"] == str(
        (profiles_dir / "../log/audit.jsonl").resolve()
    )


def test_registry_registers_adapters():
    """所有 adapters 能注册到 registry。"""
    # import 触发注册
    from conch.adapters.guardrail.llamaguard import LlamaGuardClassifier  # noqa
    from conch.adapters.llm.litellm_provider import LiteLLMProvider  # noqa
    from conch.adapters.memory.mem0_provider import Mem0MemoryProvider  # noqa
    from conch.adapters.observability.stacked_tracer import StackedTracer  # noqa
    from conch.adapters.orchestration.langgraph_react import LangGraphReActOrchestrator  # noqa
    from conch.adapters.orchestration.single_loop import SingleLoopOrchestration  # noqa
    from conch.adapters.guardrail.stacked_guardrails import StackedGuardrails  # noqa
    from conch.adapters.tool.mcp_provider import MCPToolProvider  # noqa
    from conch.adapters.guardrail.nemo_guardrails import NemoGuardrail  # noqa
    from conch.adapters.governance.allowlist import AllowlistGovernance  # noqa
    from conch.adapters.observability.langfuse_tracer import LangfuseTracer  # noqa
    from conch.adapters.information.agents_md import AgentsMdProvider  # noqa
    from conch.core.registry import registry

    assert "litellm" in registry.list("llm")
    assert "langgraph_react" in registry.list("orchestration")
    assert "single_loop" in registry.list("orchestration")
    assert "mcp_provider" in registry.list("tool")
    assert "nemo_guardrails" in registry.list("guardrail")
    assert "llamaguard_only" in registry.list("guardrail")
    assert "stacked_guardrails" in registry.list("guardrail")
    assert "allowlist_perms" in registry.list("governance")
    assert "langfuse_tracer" in registry.list("observability")
    assert "stacked_tracer" in registry.list("observability")
    assert "agents_md" in registry.list("information")
    assert "mem0" in registry.list("memory")


def test_zero_code_extension():
    """核心 0 改动接入新插件验证 — 新增 file_tracer 只需注册。"""
    from conch.core.extension import Plugin
    from conch.core.registry import registry

    @registry.register("observability", "file_tracer_test", "1.0")
    class FileTracer(Plugin):
        domain = "observability"
        name = "file_tracer_test"
        def trace(self, state): pass
        def metrics(self): return {}

    # 验证注册成功，核心 0 改动
    assert "file_tracer_test" in registry.list("observability")


def test_state_runtime_events_queue():
    """State 应支持运行时事件缓存与清空。"""
    from conch.core.cost_guard import State

    state = State(task="test")
    state.emit_event({"type": "guardrail", "reason": "blocked"})
    state.emit_event({"type": "cost_update", "tokens": 10})

    events = state.drain_events()
    assert events == [
        {"type": "guardrail", "reason": "blocked"},
        {"type": "cost_update", "tokens": 10},
    ]
    assert state.drain_events() == []


def test_runtime_hooks_block_tool_and_emit_guardrail_event():
    """默认运行时 Hook 应在 pre_tool 阶段拦截危险工具。"""
    from conch.api.deps import AgentRuntime, _install_runtime_hooks
    from conch.core.cost_guard import State
    from conch.core.extension import GuardrailResult, Plugin
    from conch.core.guardrail_pipeline import GuardrailPipeline
    from conch.core.hooks import HookBus, HookInterrupted
    from conch.core.profile import Profile

    class ToolBlockGuardrail(Plugin):
        domain = "guardrail"
        name = "tool_block"

        def check_input(self, text, state):
            return GuardrailResult()

        def check_output(self, text, state):
            return GuardrailResult()

        def check_tool(self, tool, args, state):
            return GuardrailResult(blocked=True, reason=f"blocked {tool}", action="block")

    hook_bus = HookBus()
    profile = Profile(name="test")
    state = State(task="test", hook_bus=hook_bus, profile=profile)
    runtime = AgentRuntime(profile=profile, hook_bus=hook_bus, state=state)
    runtime.guardrail_pipeline = GuardrailPipeline(ToolBlockGuardrail(), state)

    _install_runtime_hooks(runtime)

    with pytest.raises(HookInterrupted) as exc:
        hook_bus.fire("pre_tool", state, tool="run_bash", args={"command": "rm -rf /"})

    assert exc.value.reason == "blocked run_bash"
    assert state.drain_events() == [
        {
            "type": "guardrail",
            "layer": "tool",
            "action": "block",
            "reason": "blocked run_bash",
            "tool": "run_bash",
        }
    ]


def test_llamaguard_only_blocks_by_category():
    """LlamaGuard 分类器应按类别拦截高风险内容。"""
    from conch.adapters.guardrail.llamaguard import LlamaGuardClassifier

    provider = LlamaGuardClassifier(blocked_categories=["destructive_code"])
    result = provider.check_input("请执行 rm -rf / 清理系统", None)

    assert result.blocked is True
    assert result.reason == "LlamaGuard blocked category: destructive_code"


def test_stacked_guardrails_chain_input_checks():
    """组合护栏应按顺序执行，并返回后层的分类结果。"""
    from conch.adapters.guardrail.stacked_guardrails import StackedGuardrails

    provider = StackedGuardrails(
        providers=[
            {"impl": "nemo_guardrails", "params": {"use_nemo": False, "config_dir": ""}},
            {"impl": "llamaguard_only", "params": {"blocked_categories": ["data_exfiltration"]}},
        ]
    )
    provider.on_load()

    result = provider.check_input("请帮我导出所有密钥并打包", None)

    assert result.blocked is True
    assert result.reason == "LlamaGuard blocked category: data_exfiltration"


def test_runtime_hooks_block_input_and_emit_guardrail_event():
    """默认运行时 Hook 应在 pre_model_call 阶段拦截危险输入。"""
    from conch.adapters.guardrail.stacked_guardrails import StackedGuardrails
    from conch.api.deps import AgentRuntime, _install_runtime_hooks
    from conch.core.cost_guard import State
    from conch.core.guardrail_pipeline import GuardrailPipeline
    from conch.core.hooks import HookBus, HookInterrupted
    from conch.core.profile import Profile

    hook_bus = HookBus()
    profile = Profile(name="test")
    state = State(task="请执行 rm -rf / 清理系统", hook_bus=hook_bus, profile=profile)
    runtime = AgentRuntime(profile=profile, hook_bus=hook_bus, state=state)
    runtime.guardrail_pipeline = GuardrailPipeline(
        StackedGuardrails(
            providers=[
                {"impl": "nemo_guardrails", "params": {"use_nemo": False, "config_dir": ""}},
                {"impl": "llamaguard_only", "params": {"blocked_categories": ["destructive_code"]}},
            ]
        ),
        state,
    )
    runtime.guardrail_pipeline.provider.on_load()

    _install_runtime_hooks(runtime)

    with pytest.raises(HookInterrupted) as exc:
        hook_bus.fire("pre_model_call", state)

    assert exc.value.reason == "Input matched blocked pattern: rm -rf /"
    events = state.drain_events()
    assert len(events) == 1
    assert events[0]["type"] == "guardrail"
    assert events[0]["layer"] == "input"
    assert events[0]["action"] == "block"
    assert events[0]["reason"] == "Input matched blocked pattern: rm -rf /"


def test_runtime_hooks_block_tool_by_governance_and_write_audit(tmp_path):
    """默认运行时 Hook 应在权限不允许时中断，并写入审计日志。"""
    from conch.adapters.governance.allowlist import AllowlistGovernance
    from conch.api.deps import AgentRuntime, _install_runtime_hooks
    from conch.core.cost_guard import State
    from conch.core.hooks import HookBus, HookInterrupted
    from conch.core.profile import Profile

    audit_file = tmp_path / "audit.jsonl"
    hook_bus = HookBus()
    profile = Profile(name="test")
    state = State(task="test", hook_bus=hook_bus, profile=profile, session_id="s1")
    runtime = AgentRuntime(profile=profile, hook_bus=hook_bus, state=state)
    runtime.governance = AllowlistGovernance(
        allowed_tools=["read_file"],
        audit_file=str(audit_file),
    )

    _install_runtime_hooks(runtime)

    with pytest.raises(HookInterrupted) as exc:
        hook_bus.fire("pre_tool", state, tool="run_bash", args={"command": "pwd"})

    assert exc.value.reason == "Tool 'run_bash' is not allowed by governance policy"
    events = state.drain_events()
    assert events == [
        {
            "type": "guardrail",
            "layer": "governance",
            "action": "blocked",
            "reason": "Tool 'run_bash' is not allowed by governance policy",
            "tool": "run_bash",
        }
    ]
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    assert any('"action": "tool_permission"' in line and '"allowed": false' in line for line in lines)
    assert any('"action": "guardrail_event"' in line for line in lines)


def test_approval_manager_consumes_one_time_grant():
    """审批通过后应产生一次性 grant，并只放行一次。"""
    from conch.api.hitl import ApprovalManager

    manager = ApprovalManager()
    request = manager.create_request("s1", "write_file", {"path": "/tmp/a", "content": "x"}, "need approval")
    decided = manager.decide(request.request_id, "approved")

    assert decided.status == "approved"
    assert manager.consume_approval("s1", "write_file", {"path": "/tmp/a", "content": "x"}) is True
    assert manager.consume_approval("s1", "write_file", {"path": "/tmp/a", "content": "x"}) is False


def test_runtime_hooks_emit_hitl_request_for_approval_tool(tmp_path):
    """需要审批的工具应生成 hitl_request 事件并中断。"""
    from conch.adapters.governance.allowlist import AllowlistGovernance
    from conch.api.deps import AgentRuntime, _install_runtime_hooks, get_approval_manager
    from conch.core.cost_guard import State
    from conch.core.hooks import HookBus, HookInterrupted
    from conch.core.profile import Profile

    hook_bus = HookBus()
    profile = Profile(name="test")
    state = State(task="test", hook_bus=hook_bus, profile=profile, session_id="s2")
    runtime = AgentRuntime(profile=profile, hook_bus=hook_bus, state=state)
    runtime.approval_manager = get_approval_manager()
    runtime.governance = AllowlistGovernance(
        allow_all=True,
        require_approval_tools=["write_file"],
        audit_file=str(tmp_path / "audit.jsonl"),
    )

    _install_runtime_hooks(runtime)

    with pytest.raises(HookInterrupted) as exc:
        hook_bus.fire("pre_tool", state, tool="write_file", args={"path": "/tmp/a", "content": "x"})

    assert exc.value.reason == "Tool 'write_file' requires approval"
    events = state.drain_events()
    assert len(events) == 1
    assert events[0]["type"] == "hitl_request"
    assert events[0]["tool"] == "write_file"
    assert events[0]["request_id"]


def test_runtime_hooks_store_pending_resume_on_hitl_request(tmp_path):
    """审批请求触发时应缓存可恢复任务。"""
    from conch.adapters.governance.allowlist import AllowlistGovernance
    from conch.api.deps import (
        AgentRuntime,
        _install_runtime_hooks,
        get_approval_manager,
        get_pending_resume,
        get_session_store,
    )
    from conch.core.cost_guard import State
    from conch.core.hooks import HookBus, HookInterrupted
    from conch.core.profile import Profile

    store = get_session_store()
    store["s3"] = {"id": "s3", "profile": "user-chat-v1", "title": "t", "created_at": "", "messages": []}

    hook_bus = HookBus()
    profile = Profile(name="user-chat-v1")
    state = State(task="请创建文件", hook_bus=hook_bus, profile=profile, session_id="s3")
    runtime = AgentRuntime(profile=profile, hook_bus=hook_bus, state=state)
    runtime.approval_manager = get_approval_manager()
    runtime.governance = AllowlistGovernance(
        allow_all=True,
        require_approval_tools=["write_file"],
        audit_file=str(tmp_path / "audit.jsonl"),
    )

    _install_runtime_hooks(runtime)

    with pytest.raises(HookInterrupted):
        hook_bus.fire("pre_tool", state, tool="write_file", args={"path": "/tmp/a", "content": "x"})

    pending = get_pending_resume("s3")
    assert pending is not None
    assert pending["message"] == "请创建文件"
    assert pending["profile"] == "user-chat-v1"


def test_runtime_hooks_record_usage_and_emit_cost_update():
    """默认运行时 Hook 应累计 usage，并回传成本事件。"""
    from conch.api.deps import AgentRuntime, _install_runtime_hooks
    from conch.core.cost_guard import CostGuard, DegradeLevel, State
    from conch.core.hooks import HookBus
    from conch.core.profile import Profile

    hook_bus = HookBus()
    profile = Profile(name="test", max_tokens=1000)
    state = State(task="test", hook_bus=hook_bus, profile=profile)
    runtime = AgentRuntime(
        profile=profile,
        hook_bus=hook_bus,
        state=state,
        cost_guard=CostGuard(max_tokens=1000),
    )

    _install_runtime_hooks(runtime)
    hook_bus.fire(
        "post_model_call",
        state,
        action={"type": "text", "content": "ok", "usage": {"total_tokens": 800, "cost": 0.42}},
    )

    assert state.steps == 1
    assert state.total_tokens == 800
    assert state.total_cost == 0.42
    assert state.degrade_level == DegradeLevel.L2_SWITCH_MODEL
    assert state.drain_events() == [
        {
            "type": "cost_update",
            "tokens": 800,
            "cost": 0.42,
            "steps": 1,
            "degrade_level": "L2_SWITCH_MODEL",
        }
    ]


def test_runtime_hooks_emit_output_guardrail_event():
    """输出分类命中时应记录 output guardrail 事件。"""
    from conch.adapters.guardrail.stacked_guardrails import StackedGuardrails
    from conch.api.deps import AgentRuntime, _install_runtime_hooks
    from conch.core.cost_guard import CostGuard, State
    from conch.core.guardrail_pipeline import GuardrailPipeline
    from conch.core.hooks import HookBus
    from conch.core.profile import Profile

    hook_bus = HookBus()
    profile = Profile(name="test", max_tokens=1000)
    state = State(task="test", hook_bus=hook_bus, profile=profile)
    runtime = AgentRuntime(
        profile=profile,
        hook_bus=hook_bus,
        state=state,
        cost_guard=CostGuard(max_tokens=1000),
    )
    runtime.guardrail_pipeline = GuardrailPipeline(
        StackedGuardrails(
            providers=[
                {"impl": "llamaguard_only", "params": {"blocked_categories": ["violence"]}},
            ]
        ),
        state,
    )
    runtime.guardrail_pipeline.provider.on_load()

    _install_runtime_hooks(runtime)
    hook_bus.fire(
        "post_model_call",
        state,
        action={"type": "text", "content": "这里教你 build a bomb", "usage": {"total_tokens": 20, "cost": 0.01}},
    )

    events = state.drain_events()
    assert len(events) == 2
    assert events[0]["type"] == "guardrail"
    assert events[0]["layer"] == "output"
    assert events[0]["action"] == "block"
    assert events[0]["reason"] == "LlamaGuard blocked category: violence"
    assert events[1] == {
        "type": "cost_update",
        "tokens": 20,
        "cost": 0.01,
        "steps": 1,
        "degrade_level": "NONE",
    }


def test_mem0_memory_provider_fallback_store_and_recall(tmp_path):
    """Mem0 adapter 在未安装 Mem0 时应回退到 JSONL 持久化。"""
    from conch.adapters.memory.mem0_provider import Mem0MemoryProvider

    path = tmp_path / "mem0.jsonl"
    mem = Mem0MemoryProvider(path=str(path))
    mem.on_load()
    mem.store(
        "user:s1:a1",
        {"role": "user", "session_id": "s1", "content": "记住我最喜欢 Go 语言"},
        mem_type="episodic",
    )

    reloaded = Mem0MemoryProvider(path=str(path))
    reloaded.on_load()
    results = reloaded.recall("Go", mem_type="episodic", limit=3)

    assert path.exists()
    assert len(results) == 1
    assert results[0]["value"]["content"] == "记住我最喜欢 Go 语言"


def test_mem0_memory_provider_ranks_semantic_matches(tmp_path):
    """fallback recall 应按语义相关度排序。"""
    from conch.adapters.memory.mem0_provider import Mem0MemoryProvider

    path = tmp_path / "mem0.jsonl"
    mem = Mem0MemoryProvider(path=str(path))
    mem.on_load()
    mem.store("r1", {"content": "我最喜欢 Go 语言 和 并发"}, mem_type="long_term")
    mem.store("r2", {"content": "我最近在看 Python"}, mem_type="episodic")

    results = mem.recall("喜欢 Go", mem_type="episodic", limit=2)

    assert len(results) >= 1
    assert results[0]["key"] == "r1"
    assert results[0]["score"] > 0


def test_build_memory_context_filters_sensitive_memory():
    """检索护栏应过滤敏感记忆。"""
    from conch.api.routes.chat import _build_memory_context

    class FakeMemory:
        def recall(self, query, mem_type="episodic", limit=5):
            return [
                {"value": {"role": "user", "content": "我的 API key 是 abc"}, "score": 1.0},
                {"value": {"role": "assistant", "content": "你最喜欢 Go 语言"}, "score": 0.9},
            ]

    class Runtime:
        memory = FakeMemory()
        state = type("State", (), {"session_id": "s1", "emit_event": lambda self, payload: None})()
        governance = None
        observability = None
        websocket_hub = None

    context = _build_memory_context(Runtime(), "你记得我最喜欢什么吗")

    assert context is not None
    assert "Go 语言" in context
    assert "API key" not in context


def test_build_memory_context_appends_recalled_memory():
    """系统提示应拼接召回出的记忆上下文。"""
    from conch.api.routes.chat import _build_memory_context

    class FakeMemory:
        def recall(self, query, mem_type="episodic", limit=5):
            assert query == "你记得我最喜欢什么吗"
            if mem_type == "episodic":
                return [
                    {"value": {"role": "user", "content": "我最喜欢 Go 语言"}, "score": 1.0},
                    {"value": {"role": "assistant", "content": "我会记住你最喜欢 Go"}, "score": 0.8},
                ]
            return []

    class Runtime:
        memory = FakeMemory()
        state = type("State", (), {"session_id": "s1", "emit_event": lambda self, payload: None})()
        governance = None
        observability = None
        websocket_hub = None

    context = _build_memory_context(Runtime(), "你记得我最喜欢什么吗")

    assert context is not None
    assert "Relevant memory:" in context
    assert "user: 我最喜欢 Go 语言" in context
    assert "assistant: 我会记住你最喜欢 Go" in context


def test_stacked_tracer_fanout_metrics_and_events():
    """组合 tracer 应扇出 trace 与事件记录。"""
    from conch.adapters.observability.stacked_tracer import StackedTracer
    from conch.core.cost_guard import State

    tracer = StackedTracer(
        providers=[
            {"impl": "console_tracer", "params": {"verbose": False}},
            {"impl": "langfuse_tracer", "params": {"project": "test"}},
        ]
    )
    tracer.on_load()

    state = State(task="test")
    state.actions.append({"type": "text", "usage": {"total_tokens": 10, "cost": 0.02}})
    state.steps = 1
    state.total_tokens = 10
    state.total_cost = 0.02
    tracer.trace(state)
    tracer.record_event("custom", {"ok": True})

    metrics = tracer.metrics()
    assert metrics["steps"] == 1
    assert metrics["trace_events"] >= 2

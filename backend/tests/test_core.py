"""core 层单元测试 — v2 改造验证。"""

import sys
from pathlib import Path

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


def test_registry_registers_adapters():
    """所有 adapters 能注册到 registry。"""
    # import 触发注册
    from conch.adapters.llm.litellm_provider import LiteLLMProvider  # noqa
    from conch.adapters.orchestration.langgraph_react import LangGraphReActOrchestrator  # noqa
    from conch.adapters.orchestration.single_loop import SingleLoopOrchestration  # noqa
    from conch.adapters.tool.mcp_provider import MCPToolProvider  # noqa
    from conch.adapters.guardrail.nemo_guardrails import NemoGuardrail  # noqa
    from conch.adapters.observability.langfuse_tracer import LangfuseTracer  # noqa
    from conch.adapters.information.agents_md import AgentsMdProvider  # noqa
    from conch.core.registry import registry

    assert "litellm" in registry.list("llm")
    assert "langgraph_react" in registry.list("orchestration")
    assert "single_loop" in registry.list("orchestration")
    assert "mcp_provider" in registry.list("tool")
    assert "nemo_guardrails" in registry.list("guardrail")
    assert "langfuse_tracer" in registry.list("observability")
    assert "agents_md" in registry.list("information")


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

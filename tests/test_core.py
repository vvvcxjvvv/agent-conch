"""端到端测试：验证 AgentConch 核心闭环。

不依赖外部 LLM API，使用 MockProvider。
验证：Profile 加载 → 插件构建 → AgentLoop 执行 → 轨迹输出。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_extension_point():
    """测试扩展点契约。"""
    from conch.core.extension import DOMAINS, ExtensionPoint, Plugin

    assert len(DOMAINS) == 9
    assert "information" in DOMAINS
    assert "governance" in DOMAINS
    # Plugin 是可选基类
    p = Plugin()
    assert hasattr(p, "on_load")
    assert hasattr(p, "on_unload")
    print("PASS test_extension_point")


def test_registry():
    """测试注册中心。"""
    from conch.core.registry import Registry

    reg = Registry()

    @reg.register("test_domain", "test_plugin", "1.0")
    class TestPlugin:
        metadata = {}

    assert "test_plugin" in reg.list("test_domain")
    assert reg.query("test_domain") == ["test_plugin"]
    print("PASS test_registry")


def test_hook_bus():
    """测试 Hook 总线。"""
    from conch.core.hooks import HookBus, HookAction, HookResult

    bus = HookBus()
    call_order = []

    bus.register("post_step", lambda *a, **kw: call_order.append("low"), priority=100)
    bus.register("post_step", lambda *a, **kw: call_order.append("high"), priority=1)

    bus.fire("post_step")
    assert call_order == ["high", "low"], f"Expected ['high', 'low'], got {call_order}"
    print("PASS test_hook_bus")


def test_pipeline():
    """测试中间件链。"""
    from conch.core.middleware import Middleware, Pipeline

    class AddSuffix(Middleware):
        def __init__(self, suffix):
            self.suffix = suffix

        def process(self, data):
            return data + self.suffix

    pipe = Pipeline([AddSuffix("!"), AddSuffix("?")])
    assert pipe.run("data") == "data!?"
    print("PASS test_pipeline")


def test_cost_guard():
    """测试成本守卫分级降级。"""
    from conch.core.loop import CostGuard, DegradeLevel, State

    guard = CostGuard(max_tokens=1000)

    state = State(task="test")
    state.total_tokens = 500
    assert guard.check(state) == DegradeLevel.NONE

    state.total_tokens = 650
    assert guard.check(state) == DegradeLevel.L1_COMPACT

    state.total_tokens = 850
    assert guard.check(state) == DegradeLevel.L2_SWITCH_MODEL

    state.total_tokens = 1050
    assert guard.check(state) == DegradeLevel.L4_TERMINATE
    assert guard.exceeded(state)
    print("PASS test_cost_guard")


def test_memory_store():
    """测试内存存储。"""
    from conch.runtime.store.memory_store import MemoryStore

    store = MemoryStore()
    store.put("key1", "hello world")
    store.put("key2", "another value")

    assert store.get("key1") == "hello world"
    assert store.get("missing", "default") == "default"
    assert len(store.search("hello")) == 1
    print("PASS test_memory_store")


def test_mock_provider():
    """测试 Mock Provider。"""
    import asyncio

    from conch.runtime.model.base import MockProvider

    provider = MockProvider(response="test response")
    result = asyncio.run(provider.call([]))
    assert result["content"] == "test response"
    assert result["usage"]["total_tokens"] > 0
    print("PASS test_mock_provider")


def test_allowlist_permissions():
    """测试 allowlist 权限模型。"""
    from conch.domains.governance.allowlist import AllowlistPermissions

    gov = AllowlistPermissions(tools=["read_file", "write_file"])
    assert gov.check_permission("read_file", {}) is True
    assert gov.check_permission("run_bash", {}) is False

    gov.audit("tool_call", {"tool": "read_file", "allowed": True})
    gov.audit("permission_denied", {"tool": "run_bash"})
    assert len(gov.entries()) == 2
    print("PASS test_allowlist_permissions")


def test_agents_md_loader():
    """测试 AGENTS.md 加载器。"""
    from conch.core.registry import registry
    # 确保域已注册
    import conch.domains  # noqa: F401

    loader = registry.build("information", "agents_md", file="AGENTS.md")
    messages = loader.assemble("test task", None)
    assert isinstance(messages, list)
    assert len(messages) >= 1
    # 最后一条应该是用户消息
    assert messages[-1]["content"] == "test task"
    print("PASS test_agents_md_loader")


def test_builtin_shell_tools():
    """测试内置 shell 工具。"""
    import conch.domains  # noqa: F401
    from conch.core.registry import registry

    provider = registry.build("tool", "builtin_shell", sandbox="local", cwd=".", timeout=5)
    tools = provider.tools_for(None, None)
    assert len(tools) == 4
    tool_names = [t["name"] for t in tools]
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "run_bash" in tool_names
    assert "list_files" in tool_names
    print("PASS test_builtin_shell_tools")


def test_all_9_domains_registered():
    """测试 9 域全部注册。"""
    import conch.domains  # noqa: F401
    from conch.core.extension import DOMAINS
    from conch.core.registry import registry

    for domain in DOMAINS:
        impls = registry.list(domain)
        assert len(impls) >= 1, f"Domain '{domain}' has no implementations registered"
    print("PASS test_all_9_domains_registered")


def run_all():
    """运行所有测试。"""
    tests = [
        test_extension_point,
        test_registry,
        test_hook_bus,
        test_pipeline,
        test_cost_guard,
        test_memory_store,
        test_mock_provider,
        test_allowlist_permissions,
        test_agents_md_loader,
        test_builtin_shell_tools,
        test_all_9_domains_registered,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"FAIL {test.__name__}: {e}")
            failed += 1
    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())

"""T 层测试: ToolRegistry + ToolPolicy + ToolSearch."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from agent_conch.tools.base import BaseTool, ToolCall, ToolResult
from agent_conch.tools.footprint import FootprintLadder, FootprintLevel
from agent_conch.tools.registry import ToolRegistry
from agent_conch.tools.tool_policy import (
    PolicyContext,
    PolicyDecision,
    ToolAction,
    ToolPolicy,
    PolicyRule,
)
from agent_conch.tools.tool_search import ToolSearch


# === 测试用 mock 工具 ===

class MockInput(BaseModel):
    value: str = Field(default="default")


class MockReadTool(BaseTool):
    name = "mock_read"
    description = "A mock read tool for testing"
    input_model = MockInput
    is_core = True
    tags = ["test", "read"]

    async def execute(self, **kwargs):
        return ToolResult.success(f"read: {kwargs.get('value', '')}")


class MockWriteTool(BaseTool):
    name = "mock_write"
    description = "A mock write tool for testing"
    input_model = MockInput
    is_core = True
    is_write_tool = True
    tags = ["test", "write"]

    async def execute(self, **kwargs):
        return ToolResult.success(f"wrote: {kwargs.get('value', '')}")


class MockNonCoreTool(BaseTool):
    name = "mock_extended"
    description = "A non-core extended tool for searching files and content"
    input_model = MockInput
    is_core = False
    tags = ["extended", "search"]

    async def execute(self, **kwargs):
        return ToolResult.success(f"extended: {kwargs.get('value', '')}")


class FailingTool(BaseTool):
    name = "failing_tool"
    description = "A tool that always fails"
    input_model = MockInput
    is_core = True

    async def execute(self, **kwargs):
        raise RuntimeError("Intentional failure")


class TestToolRegistry:
    async def test_register_and_get(self):
        registry = ToolRegistry()
        tool = MockReadTool()
        registry.register(tool)
        assert registry.get("mock_read") is tool
        assert "mock_read" in registry.list_names()

    async def test_unregister(self):
        registry = ToolRegistry()
        registry.register(MockReadTool())
        registry.unregister("mock_read")
        assert "mock_read" not in registry.list_names()

    async def test_execute_tool_call_success(self):
        registry = ToolRegistry()
        registry.register(MockReadTool())
        call = ToolCall(id="call_1", name="mock_read", arguments={"value": "test"})
        record = await registry.execute_tool_call(call)
        assert record.status == "success"
        assert "read: test" in record.result.content

    async def test_execute_tool_call_not_found(self):
        registry = ToolRegistry()
        call = ToolCall(id="call_1", name="nonexistent", arguments={})
        record = await registry.execute_tool_call(call)
        assert record.status == "error"
        assert "not found" in record.result.content

    async def test_execute_tool_call_failure(self):
        registry = ToolRegistry()
        registry.register(FailingTool())
        call = ToolCall(id="call_1", name="failing_tool", arguments={})
        record = await registry.execute_tool_call(call)
        assert record.status == "error"

    async def test_transient_failure_suppression(self):
        """测试瞬态故障抑制 — 设计文档要求."""
        registry = ToolRegistry(transient_suppress=60)
        registry.register(FailingTool())

        # 第一次失败
        call = ToolCall(id="c1", name="failing_tool", arguments={})
        await registry.execute_tool_call(call)
        assert registry._health["failing_tool"].consecutive_failures == 1

        # 第二次失败 → 触发抑制
        await registry.execute_tool_call(call)
        assert registry._health["failing_tool"].consecutive_failures == 2
        assert registry.is_suppressed("failing_tool")

    async def test_record_success_resets_failures(self):
        registry = ToolRegistry()
        registry.register(MockReadTool())
        # 制造一些失败
        registry.record_failure("mock_read")
        registry.record_failure("mock_read")
        # 成功重置
        registry.record_success("mock_read")
        assert registry._health["mock_read"].consecutive_failures == 0

    async def test_get_available_schemas(self):
        registry = ToolRegistry()
        registry.register(MockReadTool())
        registry.register(MockNonCoreTool())
        schemas = await registry.get_available_schemas(include_core_only=True)
        # 只包含核心工具
        names = [s["name"] for s in schemas]
        assert "mock_read" in names
        assert "mock_extended" not in names

    async def test_check_fn_ttl(self):
        """测试 check_fn TTL 缓存."""
        call_count = 0

        async def check_fn():
            nonlocal call_count
            call_count += 1
            return True, None

        registry = ToolRegistry(check_ttl=30)
        tool = MockNonCoreTool()
        tool.set_check_fn(check_fn)
        registry.register(tool)

        # 第一次检查
        await registry.check_tool_available("mock_extended")
        assert call_count == 1

        # TTL 内第二次检查 → 使用缓存
        await registry.check_tool_available("mock_extended")
        assert call_count == 1  # 没有增加


class TestToolPolicy:
    def test_default_allow(self):
        policy = ToolPolicy()
        ctx = PolicyContext(
            tool_name="read_file",
            action=ToolAction.READ,
            sender="main",
            sandbox_mode="non-main",
            is_main_session=True,
        )
        decision, reason = policy.evaluate(ctx)
        assert decision == PolicyDecision.ALLOW

    def test_deny_list(self):
        policy = ToolPolicy(deny_list=["dangerous_tool"])
        ctx = PolicyContext(
            tool_name="dangerous_tool",
            action=ToolAction.EXEC,
        )
        decision, _ = policy.evaluate(ctx)
        assert decision == PolicyDecision.DENY

    def test_allow_list_bypass_rules(self):
        policy = ToolPolicy(allow_list=["trusted_tool"])
        ctx = PolicyContext(
            tool_name="trusted_tool",
            action=ToolAction.DEPLOY,
            sender="subagent",
        )
        decision, _ = policy.evaluate(ctx)
        assert decision == PolicyDecision.ALLOW

    def test_subagent_deploy_denied(self):
        policy = ToolPolicy()
        ctx = PolicyContext(
            tool_name="deploy_tool",
            action=ToolAction.DEPLOY,
            sender="subagent",
        )
        decision, reason = policy.evaluate(ctx)
        assert decision == PolicyDecision.DENY
        assert "deploy" in reason.lower() or "subagent" in reason.lower()

    def test_subagent_write_requires_approval(self):
        policy = ToolPolicy()
        ctx = PolicyContext(
            tool_name="write_file",
            action=ToolAction.WRITE,
            sender="subagent",
        )
        decision, _ = policy.evaluate(ctx)
        assert decision == PolicyDecision.REQUIRE_APPROVAL

    def test_never_sandbox_exec_denied(self):
        policy = ToolPolicy()
        ctx = PolicyContext(
            tool_name="bash",
            action=ToolAction.EXEC,
            sandbox_mode="never",
        )
        decision, _ = policy.evaluate(ctx)
        assert decision == PolicyDecision.DENY

    def test_custom_rule(self):
        custom = PolicyRule(
            name="no_delete",
            condition="action == 'write' and tool_name == 'delete_tool'",
            decision=PolicyDecision.DENY,
            reason="Delete not allowed",
        )
        policy = ToolPolicy(rules=[custom])
        ctx = PolicyContext(
            tool_name="delete_tool",
            action=ToolAction.WRITE,
        )
        decision, reason = policy.evaluate(ctx)
        assert decision == PolicyDecision.DENY


class TestToolSearch:
    def test_search_by_name(self):
        registry = ToolRegistry()
        registry.register(MockReadTool())
        registry.register(MockNonCoreTool())
        search = ToolSearch(registry)

        result = search.search("extended")
        assert len(result.matches) == 1
        assert result.matches[0]["name"] == "mock_extended"

    def test_search_by_description(self):
        registry = ToolRegistry()
        registry.register(MockNonCoreTool())
        search = ToolSearch(registry)

        result = search.search("searching files")
        assert len(result.matches) >= 1

    def test_search_excludes_core(self):
        registry = ToolRegistry()
        registry.register(MockReadTool())
        registry.register(MockNonCoreTool())
        search = ToolSearch(registry)

        result = search.search("test")
        # 核心工具不参与搜索
        names = [m["name"] for m in result.matches]
        assert "mock_read" not in names

    def test_search_no_matches(self):
        registry = ToolRegistry()
        registry.register(MockNonCoreTool())
        search = ToolSearch(registry)

        result = search.search("xyz_nonexistent")
        assert len(result.matches) == 0

    def test_should_enable_search(self):
        registry = ToolRegistry()
        search = ToolSearch(registry, auto_threshold=0.0, context_window=1000)
        # 没有非核心工具 → False
        assert not search.should_enable_search()

        registry.register(MockNonCoreTool())
        # 阈值为 0 → 任何非核心工具都会触发
        assert search.should_enable_search()


class TestFootprintLadder:
    def test_extend_existing_suggestion(self):
        ladder = FootprintLadder()
        suggestion = ladder.evaluate("read file content", ["read_file", "grep"])
        assert suggestion.suggested_level == FootprintLevel.EXTEND_EXISTING

    def test_cli_suggestion(self):
        ladder = FootprintLadder()
        suggestion = ladder.evaluate("run command execute")
        assert suggestion.suggested_level == FootprintLevel.CLI_WITH_SKILL

    def test_describe_levels(self):
        ladder = FootprintLadder()
        descriptions = ladder.describe_levels()
        assert len(descriptions) == 6
        assert "Level 1" in descriptions[0]
        assert "Level 6" in descriptions[5]

"""集成测试: 端到端验证「读取文件→修改→运行测试→回答」循环.

验证目标:
1. 能完成「读取文件 → 修改 → 运行测试 → 回答」循环
2. SQLite 持久化
3. 沙箱隔离生效

直接 mock AgentLoop._call_model, 不依赖真实 API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from agent_conch.config import ConchConfig
from agent_conch.engine.agent_loop import LLMResponse
from agent_conch.engine.conch_engine import ConchEngine

_PYTHON_EXE = sys.executable


def make_tool_call(call_id: str, name: str, arguments: dict) -> dict:
    """创建 LLM 格式的 tool_call."""
    return {
        "id": call_id,
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


class MockLLMSequence:
    """模拟 LLM 响应序列."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self._index = 0
        self.call_count = 0

    async def __call__(self, *args, **kwargs) -> LLMResponse:
        self.call_count += 1
        if self._index < len(self._responses):
            resp = self._responses[self._index]
            self._index += 1
            return resp
        # 默认返回无工具调用的响应
        return LLMResponse(content="Done.", finish_reason="stop")


class TestIntegration:
    """端到端集成测试: 读取文件→修改→运行测试→回答."""

    async def test_read_modify_test_answer_cycle(self, tmp_workspace: Path):
        """验证完整循环: 读取文件 → 修改 → 运行测试 → 回答."""
        readme_path = str(tmp_workspace / "README.md")
        main_py_path = str(tmp_workspace / "main.py")

        seq = MockLLMSequence(
            [
                # Turn 1: 读取 README.md
                LLMResponse(
                    tool_calls=[make_tool_call("c1", "read_file", {"file_path": readme_path})],
                    finish_reason="tool_calls",
                ),
                # Turn 2: 编辑 main.py
                LLMResponse(
                    tool_calls=[
                        make_tool_call(
                            "c2",
                            "edit_file",
                            {
                                "file_path": main_py_path,
                                "old_string": "hello world",
                                "new_string": "hello conch",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                # Turn 3: 运行测试
                LLMResponse(
                    tool_calls=[
                        make_tool_call(
                            "c3",
                            "bash",
                            {
                                "command": f'cd "{tmp_workspace}" && "{_PYTHON_EXE}" -m pytest tests/ -v'
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                # Turn 4: 最终回答
                LLMResponse(
                    content="I've read the README, updated main.py to print 'hello conch', "
                    "and verified the tests pass successfully.",
                    finish_reason="stop",
                ),
            ]
        )

        config = ConchConfig()
        config.state.storage_dir = str(tmp_workspace / ".agent-conch")
        config.sandbox.allowed_roots = [str(tmp_workspace)]
        config.model.name = "mock-model"
        config.agent_loop.max_turns = 10

        engine = ConchEngine(config=config, cwd=str(tmp_workspace))

        # 直接替换 _call_model 方法
        engine.agent_loop._call_model = seq

        result = await engine.run(
            "Read README.md, update main.py to print 'hello conch', and run tests.",
            session_id="integration-test-001",
        )

        # 1. Agent 完成
        assert result.status == "completed", f"Expected completed, got {result.status}"
        assert result.turn_count == 4
        assert result.tool_calls_count == 3

        # 2. 文件确实被修改了
        main_py_content = (tmp_workspace / "main.py").read_text()
        assert "hello conch" in main_py_content
        assert "hello world" not in main_py_content

        # 3. SQLite 持久化验证
        messages = engine.session_db.get_messages("integration-test-001")
        assert len(messages) >= 7  # user + 3*(assistant+tool) + final assistant
        assert messages[0].role == "user"

        # 4. 轨迹记录验证
        trajectory = engine.session_db.get_trajectory("integration-test-001")
        assert len(trajectory) >= 4

        # 5. 决策轨迹记录可审计摘要，不依赖模型原始思维链
        decisions = engine.decision_trace_store.list_for_session("integration-test-001")
        assert {step.phase for step in decisions} >= {"observe", "decide", "act", "conclude"}
        assert any("read_file" in step.summary for step in decisions)

        # 6. 最终回答
        assert (
            "hello conch" in result.final_response or "tests pass" in result.final_response.lower()
        )

        engine.close()

    async def test_parallel_tool_execution(self, tmp_workspace: Path):
        """验证互不依赖的工具调用可以并行执行。"""
        file1 = str(tmp_workspace / "README.md")
        file2 = str(tmp_workspace / "main.py")

        seq = MockLLMSequence(
            [
                LLMResponse(
                    tool_calls=[
                        make_tool_call("p1", "read_file", {"file_path": file1}),
                        make_tool_call("p2", "read_file", {"file_path": file2}),
                    ],
                    finish_reason="tool_calls",
                ),
                LLMResponse(content="Read both files in parallel.", finish_reason="stop"),
            ]
        )

        config = ConchConfig()
        config.state.storage_dir = str(tmp_workspace / ".agent-conch-parallel")
        config.sandbox.allowed_roots = [str(tmp_workspace)]
        config.tools.parallel_execution = True
        config.agent_loop.max_turns = 10

        engine = ConchEngine(config=config, cwd=str(tmp_workspace))

        engine.agent_loop._call_model = seq

        result = await engine.run(
            "Read both README.md and main.py in parallel.",
            session_id="parallel-test-001",
        )

        assert result.status == "completed"
        assert result.tool_calls_count == 2

        messages = engine.session_db.get_messages("parallel-test-001")
        tool_messages = [m for m in messages if m.role == "tool"]
        assert len(tool_messages) == 2

        engine.close()

    async def test_sandbox_isolation(self, tmp_workspace: Path):
        """验证敏感路径会被沙箱策略阻断。"""
        seq = MockLLMSequence(
            [
                LLMResponse(
                    tool_calls=[make_tool_call("s1", "read_file", {"file_path": "/etc/passwd"})],
                    finish_reason="tool_calls",
                ),
                LLMResponse(
                    content="The sensitive path was blocked by the sandbox.", finish_reason="stop"
                ),
            ]
        )

        config = ConchConfig()
        config.state.storage_dir = str(tmp_workspace / ".agent-conch-sandbox")
        config.sandbox.allowed_roots = [str(tmp_workspace)]
        config.agent_loop.max_turns = 10

        engine = ConchEngine(config=config, cwd=str(tmp_workspace))

        engine.agent_loop._call_model = seq

        result = await engine.run(
            "Try to read /etc/passwd.",
            session_id="sandbox-test-001",
        )

        assert result.status == "completed"

        messages = engine.session_db.get_messages("sandbox-test-001")
        tool_messages = [m for m in messages if m.role == "tool"]
        assert len(tool_messages) >= 1
        tool_content = tool_messages[0].content.lower()
        assert (
            "error" in tool_content
            or "permission" in tool_content
            or "sensitive" in tool_content
            or "blocked" in tool_content
        )

        engine.close()

    async def test_error_recovery_retry(self, tmp_workspace: Path):
        """验证 forward_with_handling 错误降级."""
        readme_path = str(tmp_workspace / "README.md")

        call_count = 0

        async def mock_with_retry(*args, **kwargs) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise TimeoutError("Request timed out")
            if call_count == 3:
                return LLMResponse(
                    tool_calls=[make_tool_call("r1", "read_file", {"file_path": readme_path})],
                    finish_reason="tool_calls",
                )
            return LLMResponse(
                content="Successfully read the file after retry.", finish_reason="stop"
            )

        config = ConchConfig()
        config.state.storage_dir = str(tmp_workspace / ".agent-conch-retry")
        config.sandbox.allowed_roots = [str(tmp_workspace)]
        config.agent_loop.max_turns = 10

        engine = ConchEngine(config=config, cwd=str(tmp_workspace))

        with patch.object(engine.agent_loop, "_call_model", side_effect=mock_with_retry):
            result = await engine.run("Read README.md.", session_id="retry-test-001")

        assert result.status == "completed"
        assert call_count >= 3  # 2 failures + 1 success + 1 final

        engine.close()

    async def test_trajectory_replay(self, tmp_workspace: Path):
        """验证轨迹回放功能."""
        readme_path = str(tmp_workspace / "README.md")

        seq = MockLLMSequence(
            [
                LLMResponse(
                    tool_calls=[make_tool_call("t1", "read_file", {"file_path": readme_path})],
                    finish_reason="tool_calls",
                ),
                LLMResponse(content="Read complete.", finish_reason="stop"),
            ]
        )

        config = ConchConfig()
        config.state.storage_dir = str(tmp_workspace / ".agent-conch-replay")
        config.sandbox.allowed_roots = [str(tmp_workspace)]
        config.agent_loop.max_turns = 10

        engine = ConchEngine(config=config, cwd=str(tmp_workspace))

        engine.agent_loop._call_model = seq

        await engine.run("Read README.md.", session_id="replay-test-001")

        # 回放轨迹
        replay_output = await engine.replay("replay-test-001")
        assert "read_file" in replay_output
        assert "llm_call" in replay_output

        # 导出 JSONL
        jsonl_path = engine.trajectory_store.export_jsonl("replay-test-001")
        assert jsonl_path.exists()

        # 从 JSONL 回放
        steps = engine.trajectory_store.replay(jsonl_path)
        assert len(steps) >= 2

        engine.close()

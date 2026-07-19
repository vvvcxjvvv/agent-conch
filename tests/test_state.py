"""S 层测试: SessionDB + TrajectoryStore."""

from __future__ import annotations

import json

import pytest

from agent_conch.state.session_db import SessionDB
from agent_conch.state.trajectory import TrajectoryStep, TrajectoryStore


class TestSessionDB:
    """SessionDB 状态存储测试."""

    @pytest.fixture
    def db(self, temp_db: str) -> SessionDB:
        return SessionDB(temp_db)

    def test_create_and_get_session(self, db: SessionDB):
        session = db.create_session("test-001", cwd="/tmp", model_name="gpt-4o")
        assert session.id == "test-001"
        assert session.status == "active"

        loaded = db.get_session("test-001")
        assert loaded is not None
        assert loaded.id == "test-001"
        assert loaded.cwd == "/tmp"
        assert loaded.model_name == "gpt-4o"

    def test_get_nonexistent_session(self, db: SessionDB):
        assert db.get_session("nonexistent") is None

    def test_update_session_status(self, db: SessionDB):
        db.create_session("test-002")
        db.update_session_status("test-002", "completed")
        session = db.get_session("test-002")
        assert session is not None
        assert session.status == "completed"

    def test_add_and_get_messages(self, db: SessionDB):
        db.create_session("test-003")
        db.add_message("test-003", "user", "Hello")
        db.add_message("test-003", "assistant", "Hi there!", turn_index=1)

        messages = db.get_messages("test-003")
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there!"

    def test_add_message_with_tool_calls(self, db: SessionDB):
        db.create_session("test-004")
        tool_calls = [{"id": "call_1", "function": {"name": "bash", "arguments": "{}"}}]
        db.add_message("test-004", "assistant", "", tool_calls=tool_calls, turn_index=1)

        messages = db.get_messages("test-004")
        assert messages[0].tool_calls is not None
        assert len(messages[0].tool_calls) == 1

    def test_get_messages_as_dicts(self, db: SessionDB):
        db.create_session("test-005")
        db.add_message("test-005", "user", "Hello")
        db.add_message("test-005", "assistant", "Hi", turn_index=1)

        dicts = db.get_messages_as_dicts("test-005")
        assert len(dicts) == 2
        assert dicts[0]["role"] == "user"
        assert dicts[0]["content"] == "Hello"

    def test_get_messages_as_dicts_keeps_empty_content(self, db: SessionDB):
        db.create_session("test-empty-content")
        tool_calls = [{"id": "call_1", "function": {"name": "read_file", "arguments": "{}"}}]
        db.add_message(
            "test-empty-content",
            "assistant",
            "",
            tool_calls=tool_calls,
            turn_index=1,
        )
        db.add_message(
            "test-empty-content",
            "tool",
            "",
            tool_call_id="call_1",
            turn_index=1,
        )

        dicts = db.get_messages_as_dicts("test-empty-content")
        assert dicts[0]["content"] == ""
        assert dicts[0]["tool_calls"] == tool_calls
        assert dicts[1]["content"] == ""
        assert dicts[1]["tool_call_id"] == "call_1"

    def test_turn_lifecycle(self, db: SessionDB):
        db.create_session("test-006")
        turn_id = db.start_turn("test-006", 1)
        assert turn_id > 0

        db.finish_turn(turn_id, "completed", duration_ms=100)
        assert db.count_turns("test-006") == 1

    def test_trajectory_storage(self, db: SessionDB):
        db.create_session("test-007")
        db.save_trajectory_step("test-007", None, {"tool": "bash", "output": "done"})

        trajectory = db.get_trajectory("test-007")
        assert len(trajectory) == 1
        assert trajectory[0]["tool"] == "bash"

    def test_count_messages(self, db: SessionDB):
        db.create_session("test-008")
        db.add_message("test-008", "user", "msg1")
        db.add_message("test-008", "user", "msg2")
        db.add_message("test-008", "user", "msg3")
        assert db.count_messages("test-008") == 3

    def test_persistence_across_connections(self, temp_db: str):
        """验证 SQLite 数据可跨连接恢复。"""
        db1 = SessionDB(temp_db)
        db1.create_session("persist-test", cwd="/test")
        db1.add_message("persist-test", "user", "persistent message")
        db1.close()

        # 重新打开
        db2 = SessionDB(temp_db)
        session = db2.get_session("persist-test")
        assert session is not None
        assert session.cwd == "/test"

        messages = db2.get_messages("persist-test")
        assert len(messages) == 1
        assert messages[0].content == "persistent message"


class TestTrajectoryStore:
    """TrajectoryStore 轨迹测试."""

    @pytest.fixture
    def store(self, temp_db: str, tmp_path):
        db = SessionDB(temp_db)
        db.create_session("traj-test")
        return TrajectoryStore(db, tmp_path / "trajectories")

    async def test_save_and_get_step(self, store: TrajectoryStore):
        step = TrajectoryStep(
            session_id="traj-test",
            turn_index=1,
            step_type="tool_call",
            tool_name="bash",
            tool_input={"command": "echo hello"},
            tool_output="hello\n",
            duration_ms=50,
        )
        store.save_step(step)

        steps = store.get_steps("traj-test")
        assert len(steps) == 1
        assert steps[0].tool_name == "bash"
        assert steps[0].tool_output == "hello\n"

    async def test_export_jsonl(self, store: TrajectoryStore, tmp_path):
        step = TrajectoryStep(
            session_id="traj-test",
            turn_index=1,
            step_type="llm_call",
            tool_output="response",
        )
        store.save_step(step)

        jsonl_path = store.export_jsonl("traj-test")
        assert jsonl_path.exists()

        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["step_type"] == "llm_call"

    async def test_replay_from_db(self, store: TrajectoryStore):
        for i in range(3):
            store.save_step(
                TrajectoryStep(
                    session_id="traj-test",
                    turn_index=i + 1,
                    step_type="tool_call",
                    tool_name="read_file",
                    tool_output=f"content {i}",
                )
            )

        steps = store.replay("traj-test")
        assert len(steps) == 3

        formatted = store.format_replay(steps)
        assert "read_file" in formatted
        assert "content 0" in formatted

    async def test_replay_from_jsonl(self, store: TrajectoryStore, tmp_path):
        # 先导出
        store.save_step(
            TrajectoryStep(
                session_id="traj-test",
                turn_index=1,
                step_type="tool_call",
                tool_name="bash",
                tool_output="hello",
            )
        )
        jsonl_path = store.export_jsonl("traj-test")

        # 从文件回放
        steps = store.replay(jsonl_path)
        assert len(steps) == 1
        assert steps[0].tool_name == "bash"

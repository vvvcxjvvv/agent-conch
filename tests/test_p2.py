"""P2 测试: ErrorClassifier 扩展 + 敏感路径 + Checkpoint + Subagent."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_conch.engine.error_classifier import (
    ErrorClassifier,
    FailoverReason,
    RecoveryStrategy,
)
from agent_conch.security.sensitive_paths import (
    SensitivePathChecker,
    is_sensitive_path,
)
from agent_conch.state.checkpoint import CheckpointManager
from agent_conch.state.session_db import SessionDB
from agent_conch.multiagent.subagent import SubagentManager, SubagentStatus, DELEGATE_BLOCKED_TOOLS


class TestErrorClassifierP2:
    """P2: 25 种错误分类测试."""

    def test_ssl_cert_error(self):
        classifier = ErrorClassifier()
        error = Exception("SSL certificate verification failed")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.SSL_CERT_VERIFICATION
        assert classified.strategy == RecoveryStrategy.ABORT
        assert not classified.retryable

    def test_api_server_error(self):
        classifier = ErrorClassifier()
        error = Exception("Internal server error (500)")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.API_SERVER_ERROR
        assert classified.retryable

    def test_api_overloaded(self):
        classifier = ErrorClassifier()
        error = Exception("Service overloaded (529)")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.API_OVERLOADED
        assert classified.retryable

    def test_api_not_found(self):
        classifier = ErrorClassifier()
        error = Exception("Model not found (404)")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.API_NOT_FOUND
        assert classified.strategy == RecoveryStrategy.ABORT

    def test_api_bad_request(self):
        classifier = ErrorClassifier()
        error = Exception("Bad request (400): invalid_request")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.API_BAD_REQUEST

    def test_tool_validation_error(self):
        classifier = ErrorClassifier()
        error = Exception("Invalid argument: validation error")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.TOOL_VALIDATION_ERROR

    def test_max_tokens_exceeded(self):
        classifier = ErrorClassifier()
        error = Exception("max_tokens exceeded, output too long")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.MAX_TOKENS_EXCEEDED

    def test_json_decode_error(self):
        classifier = ErrorClassifier()
        error = Exception("JSON decode error: unexpected character")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.JSON_DECODE_ERROR

    def test_database_error(self):
        classifier = ErrorClassifier()
        error = Exception("sqlite3 database error: disk full")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.DATABASE_ERROR
        assert classified.retryable

    def test_sandbox_timeout(self):
        classifier = ErrorClassifier()
        error = Exception("sandbox timeout: subprocess timed out")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.SANDBOX_TIMEOUT
        assert classified.retryable

    def test_total_error_types(self):
        """确认错误类型 >= 25 种."""
        assert len(list(FailoverReason)) >= 25

    def test_never_retry_set(self):
        """不重试的错误集包含关键类型."""
        from agent_conch.engine.error_classifier import _NEVER_RETRY_REASONS
        assert FailoverReason.SSL_CERT_VERIFICATION in _NEVER_RETRY_REASONS
        assert FailoverReason.API_CONTENT_POLICY in _NEVER_RETRY_REASONS
        assert FailoverReason.API_AUTH_ERROR in _NEVER_RETRY_REASONS


class TestSensitivePaths:
    def test_unix_etc_blocked(self):
        is_sensitive, reason = is_sensitive_path("/etc/passwd")
        assert is_sensitive

    def test_ssh_blocked(self):
        is_sensitive, reason = is_sensitive_path("~/.ssh/id_rsa")
        assert is_sensitive

    def test_env_file_blocked(self):
        is_sensitive, reason = is_sensitive_path(".env")
        assert is_sensitive

    def test_normal_path_allowed(self):
        is_sensitive, reason = is_sensitive_path("/tmp/test.txt")
        assert not is_sensitive

    def test_user_paths_added(self):
        checker = SensitivePathChecker(user_sensitive_paths=["/custom/secret"])
        is_sensitive, _ = checker.check("/custom/secret/file.txt")
        assert is_sensitive

    def test_hardcoded_cannot_be_removed(self):
        checker = SensitivePathChecker(user_sensitive_paths=[])
        all_paths = checker.list_all()
        # 硬编码路径始终存在
        assert any("/etc" in p for p in all_paths)

    def test_merge_with_validator(self):
        checker = SensitivePathChecker(user_sensitive_paths=["/custom"])
        merged = checker.merge_with_validator(["/user/added"])
        assert "/custom" in merged
        assert "/user/added" in merged
        # 硬编码路径也在
        assert any("/etc" in p for p in merged)


class TestCheckpointManager:
    async def test_save_and_load(self, tmp_db: SessionDB):
        tmp_db.create_session("s1", model_name="test")
        tmp_db.add_message("s1", "user", "Hello")
        tmp_db.add_message("s1", "assistant", "Hi there")

        mgr = CheckpointManager(tmp_db)
        cp_id = await mgr.save_checkpoint(
            session_id="s1",
            turn_index=1,
            messages=[{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}],
            agent_state={"turn_count": 1},
        )
        assert cp_id > 0

        loaded = await mgr.load_checkpoint("s1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.turn_index == 1
        assert len(loaded.messages_snapshot) == 2
        assert loaded.agent_state["turn_count"] == 1

    async def test_list_checkpoints(self, tmp_db: SessionDB):
        tmp_db.create_session("s1", model_name="test")
        mgr = CheckpointManager(tmp_db)
        await mgr.save_checkpoint("s1", 1, [{"role": "user", "content": "A"}])
        await mgr.save_checkpoint("s1", 2, [{"role": "user", "content": "B"}])
        checkpoints = await mgr.list_checkpoints("s1")
        assert len(checkpoints) == 2

    async def test_restore(self, tmp_db: SessionDB):
        tmp_db.create_session("s1", model_name="test")
        tmp_db.add_message("s1", "user", "Original message")

        mgr = CheckpointManager(tmp_db)
        await mgr.save_checkpoint(
            "s1", 1,
            [{"role": "user", "content": "Checkpoint message"}],
        )

        # 清空消息
        tmp_db.conn.execute("DELETE FROM messages WHERE session_id = 's1'")
        tmp_db.conn.commit()
        assert len(tmp_db.get_messages("s1")) == 0

        # 恢复
        success = await mgr.restore("s1")
        assert success
        messages = tmp_db.get_messages("s1")
        assert len(messages) == 1
        assert "Checkpoint message" in messages[0].content

    async def test_pause_and_resume(self, tmp_db: SessionDB):
        tmp_db.create_session("s1", model_name="test")
        tmp_db.add_message("s1", "user", "Hello")

        mgr = CheckpointManager(tmp_db)
        cp_id = await mgr.pause("s1", turn_index=1, messages=[{"role": "user", "content": "Hello"}])
        assert cp_id > 0

        # 验证 session 状态为 paused
        session = tmp_db.get_session("s1")
        assert session.status == "paused"

        # 恢复
        checkpoint = await mgr.resume("s1")
        assert checkpoint is not None
        session = tmp_db.get_session("s1")
        assert session.status == "active"

    async def test_delete_checkpoint(self, tmp_db: SessionDB):
        tmp_db.create_session("s1", model_name="test")
        mgr = CheckpointManager(tmp_db)
        cp_id = await mgr.save_checkpoint("s1", 1, [{"role": "user", "content": "A"}])
        await mgr.delete_checkpoint(cp_id)
        assert await mgr.load_checkpoint("s1") is None


class TestSubagentManager:
    def test_spawn(self, tmp_db: SessionDB):
        tmp_db.create_session("parent", model_name="test")
        mgr = SubagentManager(tmp_db)
        record = mgr.spawn("parent", "Read README.md and summarize")
        assert record.subagent_id
        assert record.parent_id == "parent"
        assert record.status == SubagentStatus.PENDING
        assert record.task == "Read README.md and summarize"

    def test_start_and_complete(self, tmp_db: SessionDB):
        tmp_db.create_session("parent", model_name="test")
        mgr = SubagentManager(tmp_db)
        record = mgr.spawn("parent", "Do task")
        assert mgr.start(record.subagent_id)
        assert mgr.complete(record.subagent_id, "Task done")
        updated = mgr.get(record.subagent_id)
        assert updated.status == SubagentStatus.COMPLETED
        assert updated.result == "Task done"

    def test_fail(self, tmp_db: SessionDB):
        tmp_db.create_session("parent", model_name="test")
        mgr = SubagentManager(tmp_db)
        record = mgr.spawn("parent", "Do task")
        mgr.start(record.subagent_id)
        mgr.fail(record.subagent_id, "Something went wrong")
        updated = mgr.get(record.subagent_id)
        assert updated.status == SubagentStatus.FAILED
        assert updated.error == "Something went wrong"

    def test_cancel(self, tmp_db: SessionDB):
        tmp_db.create_session("parent", model_name="test")
        mgr = SubagentManager(tmp_db)
        record = mgr.spawn("parent", "Do task")
        mgr.cancel(record.subagent_id)
        updated = mgr.get(record.subagent_id)
        assert updated.status == SubagentStatus.CANCELLED

    def test_list_by_parent(self, tmp_db: SessionDB):
        tmp_db.create_session("parent", model_name="test")
        mgr = SubagentManager(tmp_db)
        mgr.spawn("parent", "Task 1")
        mgr.spawn("parent", "Task 2")
        children = mgr.list_by_parent("parent")
        assert len(children) == 2

    def test_find_orphans(self, tmp_db: SessionDB):
        tmp_db.create_session("parent", model_name="test")
        mgr = SubagentManager(tmp_db)
        record = mgr.spawn("parent", "Task")
        mgr.start(record.subagent_id)

        # 父 Agent 完成后 → 子 Agent 成为孤儿
        tmp_db.update_session_status("parent", "completed")
        orphans = mgr.find_orphans()
        assert len(orphans) >= 1
        assert orphans[0].subagent_id == record.subagent_id

    def test_recover_orphans(self, tmp_db: SessionDB):
        tmp_db.create_session("parent", model_name="test")
        mgr = SubagentManager(tmp_db)
        record = mgr.spawn("parent", "Task")
        mgr.start(record.subagent_id)
        tmp_db.update_session_status("parent", "completed")

        recovered = mgr.recover_orphans()
        assert len(recovered) >= 1
        updated = mgr.get(record.subagent_id)
        assert updated.status == SubagentStatus.ORPHANED

    def test_adopt_orphan(self, tmp_db: SessionDB):
        tmp_db.create_session("parent1", model_name="test")
        tmp_db.create_session("parent2", model_name="test")
        mgr = SubagentManager(tmp_db)
        record = mgr.spawn("parent1", "Task")
        mgr.start(record.subagent_id)
        tmp_db.update_session_status("parent1", "completed")
        mgr.recover_orphans()

        # parent2 认领孤儿
        success = mgr.adopt_orphan(record.subagent_id, "parent2")
        assert success
        updated = mgr.get(record.subagent_id)
        assert updated.parent_id == "parent2"
        assert updated.status == SubagentStatus.PENDING

    def test_blocked_tools(self):
        mgr = SubagentManager(SessionDB(":memory:"))
        blocked = mgr.get_blocked_tools()
        assert "task_manage" in blocked

    def test_delegate_blocked_tools_constant(self):
        assert "task_manage" in DELEGATE_BLOCKED_TOOLS

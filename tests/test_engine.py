"""L 层测试: Layer + ErrorClassifier + AgentLoop (mock LLM)."""

from __future__ import annotations

from agent_conch.engine.error_classifier import (
    ClassifiedError,
    ErrorClassifier,
    FailoverReason,
    RecoveryStrategy,
)
from agent_conch.engine.layers.base import (
    GraphContext,
    Layer,
    LayerManager,
)
from agent_conch.engine.layers.execution_limits import ExecutionLimitsLayer


class TestExecutionLimitsLayer:
    async def test_check_limits_under_max(self):
        layer = ExecutionLimitsLayer(max_turns=10, max_time=60)
        import time

        should_abort, reason = layer.check_limits(5, time.time())
        assert not should_abort

    async def test_check_limits_max_turns(self):
        layer = ExecutionLimitsLayer(max_turns=10, max_time=60)
        import time

        should_abort, reason = layer.check_limits(10, time.time())
        assert should_abort
        assert "Max turns" in reason

    async def test_check_limits_max_time(self):
        layer = ExecutionLimitsLayer(max_turns=10, max_time=60)
        import time

        should_abort, reason = layer.check_limits(5, time.time() - 70)
        assert should_abort
        assert "Max time" in reason


class TestLayerManager:
    async def test_add_and_remove_layer(self):
        manager = LayerManager()
        layer = ExecutionLimitsLayer()
        manager.add(layer)
        assert len(manager.layers) == 1

        manager.remove("execution_limits")
        assert len(manager.layers) == 0

    async def test_on_graph_start_sets_start_time(self):
        manager = LayerManager()
        manager.add(ExecutionLimitsLayer())
        ctx = GraphContext(session_id="test")
        await manager.on_graph_start(ctx)
        assert ctx.start_time > 0

    async def test_abort_propagation(self):
        manager = LayerManager()

        class AbortLayer(Layer):
            name = "abort"

            async def on_graph_start(self, ctx: GraphContext) -> None:
                ctx.should_abort = True
                ctx.abort_reason = "Test abort"

        manager.add(AbortLayer())
        ctx = GraphContext(session_id="test")
        await manager.on_graph_start(ctx)
        assert ctx.should_abort


class TestErrorClassifier:
    def test_classify_timeout(self):
        classifier = ErrorClassifier()
        error = TimeoutError("Request timed out")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.API_TIMEOUT
        assert classified.strategy == RecoveryStrategy.RETRY
        assert classified.retryable

    def test_classify_rate_limit(self):
        classifier = ErrorClassifier()
        error = Exception("Rate limit exceeded (429)")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.API_RATE_LIMIT
        assert classified.retryable

    def test_classify_auth_error(self):
        classifier = ErrorClassifier()
        error = Exception("Authentication failed (401)")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.API_AUTH_ERROR
        assert classified.strategy == RecoveryStrategy.ABORT
        assert not classified.retryable

    def test_classify_content_policy(self):
        classifier = ErrorClassifier()
        error = Exception("Content policy violation")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.API_CONTENT_POLICY
        assert classified.strategy == RecoveryStrategy.ABORT

    def test_classify_context_window(self):
        classifier = ErrorClassifier()
        error = Exception("context length exceeded, too long")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.CONTEXT_WINDOW_EXCEEDED
        assert classified.strategy == RecoveryStrategy.COMPACT

    def test_classify_permission(self):
        classifier = ErrorClassifier()
        error = PermissionError("Permission denied")
        classified = classifier.classify(error)
        assert classified.reason == FailoverReason.PERMISSION_DENIED
        assert classified.strategy == RecoveryStrategy.ABORT

    def test_should_retry(self):
        classifier = ErrorClassifier()
        classified = ClassifiedError(
            reason=FailoverReason.API_TIMEOUT,
            strategy=RecoveryStrategy.RETRY,
            message="timeout",
            retryable=True,
            max_retries=3,
        )
        assert classifier.should_retry(classified, 0)
        assert classifier.should_retry(classified, 2)
        assert not classifier.should_retry(classified, 3)

    def test_should_not_retry_non_retryable(self):
        classifier = ErrorClassifier()
        classified = ClassifiedError(
            reason=FailoverReason.API_AUTH_ERROR,
            strategy=RecoveryStrategy.ABORT,
            message="auth error",
            retryable=False,
            max_retries=0,
        )
        assert not classifier.should_retry(classified, 0)

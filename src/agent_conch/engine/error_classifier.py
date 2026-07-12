"""L 层: ErrorClassifier — 错误分类与恢复策略.

设计文档要求:
- 20+ 种错误分类
- 返回错误类型 + 恢复策略 (retry/requery/compact/abort)
- forward_with_handling 错误降级

P1: 实现基础错误分类 (API/工具/上下文/权限)
P2: 扩展到 20+ 种
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailoverReason(str, Enum):
    """错误类型 (P1 基础版, P2 扩展到 20+)."""

    # API 错误
    API_TIMEOUT = "api_timeout"
    API_RATE_LIMIT = "api_rate_limit"
    API_CONTENT_POLICY = "api_content_policy"  # 不重试
    API_AUTH_ERROR = "api_auth_error"
    API_CONNECTION_ERROR = "api_connection_error"

    # 工具错误
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_BLOCKED = "tool_blocked"  # 策略阻止
    TOOL_NOT_FOUND = "tool_not_found"

    # 上下文错误
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"

    # 权限/安全
    PERMISSION_DENIED = "permission_denied"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"

    # 格式
    FORMAT_ERROR = "format_error"

    # 成本
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"

    # 未知
    UNKNOWN = "unknown"


class RecoveryStrategy(str, Enum):
    """恢复策略."""

    RETRY = "retry"  # 重试 (相同请求)
    REQUERY = "requery"  # 重新查询 (可能调整参数)
    COMPACT = "compact"  # 压缩上下文后重试
    ABORT = "abort"  # 终止
    CONTINUE = "continue"  # 忽略错误继续


@dataclass
class ClassifiedError:
    """分类后的错误."""

    reason: FailoverReason
    strategy: RecoveryStrategy
    message: str
    retryable: bool = False
    max_retries: int = 3
    original_error: Exception | None = None


# 错误类型 → 恢复策略 映射
_STRATEGY_MAP: dict[FailoverReason, RecoveryStrategy] = {
    FailoverReason.API_TIMEOUT: RecoveryStrategy.RETRY,
    FailoverReason.API_RATE_LIMIT: RecoveryStrategy.RETRY,
    FailoverReason.API_CONTENT_POLICY: RecoveryStrategy.ABORT,  # 不重试
    FailoverReason.API_AUTH_ERROR: RecoveryStrategy.ABORT,
    FailoverReason.API_CONNECTION_ERROR: RecoveryStrategy.RETRY,
    FailoverReason.TOOL_EXECUTION_ERROR: RecoveryStrategy.CONTINUE,
    FailoverReason.TOOL_TIMEOUT: RecoveryStrategy.CONTINUE,
    FailoverReason.TOOL_BLOCKED: RecoveryStrategy.CONTINUE,
    FailoverReason.TOOL_NOT_FOUND: RecoveryStrategy.CONTINUE,
    FailoverReason.CONTEXT_WINDOW_EXCEEDED: RecoveryStrategy.COMPACT,
    FailoverReason.PERMISSION_DENIED: RecoveryStrategy.ABORT,
    FailoverReason.SANDBOX_UNAVAILABLE: RecoveryStrategy.ABORT,
    FailoverReason.FORMAT_ERROR: RecoveryStrategy.REQUERY,
    FailoverReason.COST_LIMIT_EXCEEDED: RecoveryStrategy.ABORT,
    FailoverReason.UNKNOWN: RecoveryStrategy.CONTINUE,
}

# 可重试的错误
_RETRYABLE_REASONS = {
    FailoverReason.API_TIMEOUT,
    FailoverReason.API_RATE_LIMIT,
    FailoverReason.API_CONNECTION_ERROR,
}


class ErrorClassifier:
    """错误分类器.

    将异常分类为 FailoverReason, 并给出恢复策略.
    """

    def classify(self, error: Exception) -> ClassifiedError:
        """分类错误."""
        error_msg = str(error).lower()
        error_type = type(error).__name__.lower()

        # API 超时
        if "timeout" in error_msg or "timed out" in error_msg:
            reason = FailoverReason.API_TIMEOUT
        # 速率限制
        elif "rate limit" in error_msg or "429" in error_msg:
            reason = FailoverReason.API_RATE_LIMIT
        # 内容策略
        elif "content_policy" in error_msg or "content policy" in error_msg or "content filter" in error_msg:
            reason = FailoverReason.API_CONTENT_POLICY
        # 认证错误
        elif "auth" in error_msg or "401" in error_msg or "403" in error_msg:
            reason = FailoverReason.API_AUTH_ERROR
        # 连接错误
        elif "connection" in error_msg or "connectionerror" in error_type:
            reason = FailoverReason.API_CONNECTION_ERROR
        # 上下文窗口
        elif "context length" in error_msg or "context window" in error_msg or "too long" in error_msg:
            reason = FailoverReason.CONTEXT_WINDOW_EXCEEDED
        # 权限
        elif "permission" in error_msg or "permissionerror" in error_type:
            reason = FailoverReason.PERMISSION_DENIED
        # 格式
        elif "json" in error_msg and "decode" in error_msg:
            reason = FailoverReason.FORMAT_ERROR
        else:
            reason = FailoverReason.UNKNOWN

        strategy = _STRATEGY_MAP.get(reason, RecoveryStrategy.CONTINUE)
        retryable = reason in _RETRYABLE_REASONS

        return ClassifiedError(
            reason=reason,
            strategy=strategy,
            message=str(error),
            retryable=retryable,
            max_retries=3 if retryable else 0,
            original_error=error,
        )

    def should_retry(self, classified: ClassifiedError, attempt: int) -> bool:
        """判断是否应该重试."""
        if not classified.retryable:
            return False
        return attempt < classified.max_retries

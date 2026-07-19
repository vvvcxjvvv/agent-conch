"""L 层: ErrorClassifier — 错误分类与恢复策略.

恢复策略:
- 20+ 种错误分类
- 返回错误类型 + 恢复策略 (retry/requery/compact/abort)
- forward_with_handling 错误降级

错误分类覆盖 API、上下文、工具、权限和运行时故障。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailoverReason(str, Enum):
    """错误类型。"""

    # === API 错误 (10) ===
    API_TIMEOUT = "api_timeout"
    API_RATE_LIMIT = "api_rate_limit"
    API_CONTENT_POLICY = "api_content_policy"  # 不重试
    API_AUTH_ERROR = "api_auth_error"
    API_CONNECTION_ERROR = "api_connection_error"
    API_SERVER_ERROR = "api_server_error"  # 5xx
    API_BAD_REQUEST = "api_bad_request"  # 400
    API_NOT_FOUND = "api_not_found"  # 404 模型不存在
    SSL_CERT_VERIFICATION = "ssl_cert_verification"  # 不重试
    API_OVERLOADED = "api_overloaded"  # 529

    # === 工具错误 (5) ===
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_BLOCKED = "tool_blocked"  # 策略阻止
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_VALIDATION_ERROR = "tool_validation_error"  # 参数校验失败

    # === 上下文错误 (3) ===
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
    MAX_TOKENS_EXCEEDED = "max_tokens_exceeded"  # 输出超长
    CONTEXT_TOO_SHORT = "context_too_short"  # 上下文不足

    # === 权限/安全 (3) ===
    PERMISSION_DENIED = "permission_denied"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    SANDBOX_TIMEOUT = "sandbox_timeout"

    # === 格式/解析 (2) ===
    FORMAT_ERROR = "format_error"
    JSON_DECODE_ERROR = "json_decode_error"

    # === 成本 (1) ===
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"

    # === 基础设施 (1) ===
    DATABASE_ERROR = "database_error"

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
    # API 错误
    FailoverReason.API_TIMEOUT: RecoveryStrategy.RETRY,
    FailoverReason.API_RATE_LIMIT: RecoveryStrategy.RETRY,
    FailoverReason.API_CONTENT_POLICY: RecoveryStrategy.ABORT,  # 不重试
    FailoverReason.API_AUTH_ERROR: RecoveryStrategy.ABORT,
    FailoverReason.API_CONNECTION_ERROR: RecoveryStrategy.RETRY,
    FailoverReason.API_SERVER_ERROR: RecoveryStrategy.RETRY,  # 5xx 可重试
    FailoverReason.API_BAD_REQUEST: RecoveryStrategy.REQUERY,  # 调整请求
    FailoverReason.API_NOT_FOUND: RecoveryStrategy.ABORT,  # 模型不存在
    FailoverReason.SSL_CERT_VERIFICATION: RecoveryStrategy.ABORT,  # 不重试
    FailoverReason.API_OVERLOADED: RecoveryStrategy.RETRY,
    # 工具错误
    FailoverReason.TOOL_EXECUTION_ERROR: RecoveryStrategy.CONTINUE,
    FailoverReason.TOOL_TIMEOUT: RecoveryStrategy.CONTINUE,
    FailoverReason.TOOL_BLOCKED: RecoveryStrategy.CONTINUE,
    FailoverReason.TOOL_NOT_FOUND: RecoveryStrategy.CONTINUE,
    FailoverReason.TOOL_VALIDATION_ERROR: RecoveryStrategy.REQUERY,
    # 上下文错误
    FailoverReason.CONTEXT_WINDOW_EXCEEDED: RecoveryStrategy.COMPACT,
    FailoverReason.MAX_TOKENS_EXCEEDED: RecoveryStrategy.REQUERY,  # 减少输出
    FailoverReason.CONTEXT_TOO_SHORT: RecoveryStrategy.CONTINUE,
    # 权限/安全
    FailoverReason.PERMISSION_DENIED: RecoveryStrategy.ABORT,
    FailoverReason.SANDBOX_UNAVAILABLE: RecoveryStrategy.ABORT,
    FailoverReason.SANDBOX_TIMEOUT: RecoveryStrategy.RETRY,
    # 格式/解析
    FailoverReason.FORMAT_ERROR: RecoveryStrategy.REQUERY,
    FailoverReason.JSON_DECODE_ERROR: RecoveryStrategy.REQUERY,
    # 成本
    FailoverReason.COST_LIMIT_EXCEEDED: RecoveryStrategy.ABORT,
    # 基础设施
    FailoverReason.DATABASE_ERROR: RecoveryStrategy.RETRY,
    # 未知
    FailoverReason.UNKNOWN: RecoveryStrategy.CONTINUE,
}

# 可重试的错误
_RETRYABLE_REASONS = {
    FailoverReason.API_TIMEOUT,
    FailoverReason.API_RATE_LIMIT,
    FailoverReason.API_CONNECTION_ERROR,
    FailoverReason.API_SERVER_ERROR,
    FailoverReason.API_OVERLOADED,
    FailoverReason.SANDBOX_TIMEOUT,
    FailoverReason.DATABASE_ERROR,
}

# 不重试的错误 (显式声明, 优先级最高)
_NEVER_RETRY_REASONS = {
    FailoverReason.API_CONTENT_POLICY,
    FailoverReason.API_AUTH_ERROR,
    FailoverReason.API_NOT_FOUND,
    FailoverReason.SSL_CERT_VERIFICATION,
    FailoverReason.PERMISSION_DENIED,
    FailoverReason.SANDBOX_UNAVAILABLE,
    FailoverReason.COST_LIMIT_EXCEEDED,
}


class ErrorClassifier:
    """错误分类器.

    将异常分类为 FailoverReason, 并给出恢复策略.
    """

    def classify(self, error: Exception) -> ClassifiedError:
        """分类错误.

        按错误消息执行更细粒度的匹配。
        """
        error_msg = str(error).lower()
        error_type = type(error).__name__.lower()

        # === SSL 证书 (不重试, 优先检查) ===
        if "ssl" in error_msg and ("cert" in error_msg or "verify" in error_msg):
            reason = FailoverReason.SSL_CERT_VERIFICATION

        # === API 超时 ===
        elif "timeout" in error_msg or "timed out" in error_msg:
            # 区分沙箱超时和 API 超时
            if "sandbox" in error_msg or "subprocess" in error_msg:
                reason = FailoverReason.SANDBOX_TIMEOUT
            elif "tool" in error_msg:
                reason = FailoverReason.TOOL_TIMEOUT
            else:
                reason = FailoverReason.API_TIMEOUT

        # === 速率限制 ===
        elif "rate limit" in error_msg or "429" in error_msg:
            reason = FailoverReason.API_RATE_LIMIT

        # === API 过载 (529) ===
        elif "overloaded" in error_msg or "529" in error_msg:
            reason = FailoverReason.API_OVERLOADED

        # === 内容策略 ===
        elif (
            "content_policy" in error_msg
            or "content policy" in error_msg
            or "content filter" in error_msg
        ):
            reason = FailoverReason.API_CONTENT_POLICY

        # === 认证错误 ===
        elif (
            "auth" in error_msg
            or "401" in error_msg
            or "403" in error_msg
            or "api key" in error_msg
        ):
            reason = FailoverReason.API_AUTH_ERROR

        # === 模型不存在 (404) ===
        elif "404" in error_msg or "model" in error_msg and "not found" in error_msg:
            reason = FailoverReason.API_NOT_FOUND

        # === Bad Request (400) ===
        elif "400" in error_msg or "bad request" in error_msg or "invalid_request" in error_msg:
            reason = FailoverReason.API_BAD_REQUEST

        # === 服务器错误 (5xx) ===
        elif (
            "500" in error_msg
            or "502" in error_msg
            or "503" in error_msg
            or "internal server error" in error_msg
            or "internalservererror" in error_type
        ):
            reason = FailoverReason.API_SERVER_ERROR

        # === 连接错误 ===
        elif (
            "connection" in error_msg
            or "connectionerror" in error_type
            or "connectionreset" in error_type
        ):
            reason = FailoverReason.API_CONNECTION_ERROR

        # === 输出超长 (先于上下文窗口检查, 因为 "too long" 可能匹配两者) ===
        elif (
            "max_tokens" in error_msg or "max output" in error_msg or "output too long" in error_msg
        ):
            reason = FailoverReason.MAX_TOKENS_EXCEEDED

        # === 上下文窗口 ===
        elif (
            "context length" in error_msg
            or "context window" in error_msg
            or "too long" in error_msg
            or "maximum context" in error_msg
        ):
            reason = FailoverReason.CONTEXT_WINDOW_EXCEEDED

        # === 权限 ===
        elif "permission" in error_msg or "permissionerror" in error_type:
            reason = FailoverReason.PERMISSION_DENIED

        # === 沙箱不可用 ===
        elif "sandbox" in error_msg and ("unavailable" in error_msg or "not running" in error_msg):
            reason = FailoverReason.SANDBOX_UNAVAILABLE

        # === 工具未找到 ===
        elif "tool" in error_msg and "not found" in error_msg:
            reason = FailoverReason.TOOL_NOT_FOUND

        # === 工具参数校验 ===
        elif (
            "validation" in error_msg
            or "invalid argument" in error_msg
            or "validationerror" in error_type
        ):
            reason = FailoverReason.TOOL_VALIDATION_ERROR

        # === 工具执行错误 ===
        elif "tool" in error_msg and ("error" in error_msg or "failed" in error_msg):
            reason = FailoverReason.TOOL_EXECUTION_ERROR

        # === JSON 解析错误 ===
        elif "json" in error_msg and ("decode" in error_msg or "parse" in error_msg):
            reason = FailoverReason.JSON_DECODE_ERROR

        # === 格式错误 ===
        elif "format" in error_msg or "formaterror" in error_type:
            reason = FailoverReason.FORMAT_ERROR

        # === 数据库错误 ===
        elif "sqlite" in error_msg or "database" in error_msg or "databaseerror" in error_type:
            reason = FailoverReason.DATABASE_ERROR

        # === 成本超限 ===
        elif "cost" in error_msg and "limit" in error_msg:
            reason = FailoverReason.COST_LIMIT_EXCEEDED

        else:
            reason = FailoverReason.UNKNOWN

        strategy = _STRATEGY_MAP.get(reason, RecoveryStrategy.CONTINUE)
        retryable = reason in _RETRYABLE_REASONS and reason not in _NEVER_RETRY_REASONS

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

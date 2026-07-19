"""G 层：内容安全检查与敏感信息过滤。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_conch.tools.base import ToolResult


@dataclass(frozen=True)
class ContentSafetyDecision:
    allowed: bool
    reason: str = ""
    matches: tuple[str, ...] = ()


class ContentSafetyGuard:
    """阻止敏感信息外发，并在所有工具/回答输出中统一脱敏。"""

    _SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
        ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")),
        ("api_key", re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b")),
        ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        (
            "assigned_secret",
            re.compile(
                r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*['\"]?([^\s'\";,]{8,})"
            ),
        ),
    )

    def __init__(
        self,
        enabled: bool = True,
        redact_sensitive: bool = True,
        denied_patterns: list[str] | None = None,
    ) -> None:
        self.enabled = enabled
        self.redact_sensitive = redact_sensitive
        self.denied_patterns = [re.compile(item, re.IGNORECASE) for item in denied_patterns or []]

    def evaluate_arguments(self, arguments: dict[str, Any], action: str) -> ContentSafetyDecision:
        if not self.enabled:
            return ContentSafetyDecision(True)
        text = self._flatten(arguments)
        for pattern in self.denied_patterns:
            if pattern.search(text):
                return ContentSafetyDecision(False, "content matched a denied safety pattern")
        matches = self.find_sensitive(text)
        if matches and action in {"network", "deploy"}:
            return ContentSafetyDecision(
                False,
                "sensitive information cannot be sent to a network or deployment tool",
                matches,
            )
        return ContentSafetyDecision(True, matches=matches)

    def find_sensitive(self, text: str) -> tuple[str, ...]:
        if not self.enabled:
            return ()
        return tuple(name for name, pattern in self._SENSITIVE_PATTERNS if pattern.search(text))

    def redact(self, text: str) -> str:
        if not self.enabled or not self.redact_sensitive:
            return text
        redacted = text
        for name, pattern in self._SENSITIVE_PATTERNS:
            redacted = pattern.sub(f"[REDACTED:{name}]", redacted)
        return redacted

    def sanitize_result(self, result: ToolResult) -> ToolResult:
        content = self.redact(result.content)
        metadata = self._redact_value(result.metadata)
        structured = self._redact_value(result.structured) if result.structured is not None else None
        return ToolResult(content, result.is_error, metadata, structured)

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {str(key): self._redact_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact_value(item) for item in value)
        return value

    @staticmethod
    def _flatten(value: Any) -> str:
        if isinstance(value, dict):
            return "\n".join(
                f"{key}: {ContentSafetyGuard._flatten(item)}" for key, item in value.items()
            )
        if isinstance(value, (list, tuple, set)):
            return "\n".join(ContentSafetyGuard._flatten(item) for item in value)
        return str(value)

"""O 层：Agent exit_status 统一归因。"""

from __future__ import annotations

from enum import Enum


class ExitStatus(str, Enum):
    SUCCESS = "success"
    MAX_TURNS = "max_turns"
    TIMEOUT = "timeout"
    QUOTA_EXCEEDED = "quota_exceeded"
    VERIFICATION_FAILED = "verification_failed"
    SECURITY_BLOCKED = "security_blocked"
    ERROR = "error"
    ABORTED = "aborted"


def classify_exit_status(status: str, error: str = "") -> ExitStatus:
    normalized = error.lower()
    if status == "completed":
        return ExitStatus.SUCCESS
    if status == "max_turns":
        return ExitStatus.MAX_TURNS
    if "time" in normalized:
        return ExitStatus.TIMEOUT
    if "quota" in normalized:
        return ExitStatus.QUOTA_EXCEEDED
    if "verification" in normalized:
        return ExitStatus.VERIFICATION_FAILED
    if "security" in normalized or "policy" in normalized:
        return ExitStatus.SECURITY_BLOCKED
    if status == "aborted":
        return ExitStatus.ABORTED
    return ExitStatus.ERROR

"""V 层：review_on_submit 自审。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

ReviewCaller = Callable[[list[dict[str, str]]], Awaitable[str]]


@dataclass
class SelfReviewResult:
    passed: bool
    issues: list[str]
    summary: str


class SelfReview:
    def __init__(self, caller: ReviewCaller | None = None) -> None:
        self.caller = caller

    async def run(self, task: str, answer: str, verification_passed: bool) -> SelfReviewResult:
        if self.caller is None:
            issues = (
                []
                if verification_passed and answer.strip()
                else ["answer is empty or service verification did not pass"]
            )
            return SelfReviewResult(not issues, issues, "deterministic self review")

        prompt = (
            "Review the answer before submission. Return JSON: "
            '{"passed": true, "issues": [], "summary": "..."}.\n'
            f"Task: {task}\nAnswer: {answer}\nService verification: {verification_passed}"
        )
        try:
            payload = json.loads(await self.caller([{"role": "user", "content": prompt}]))
            return SelfReviewResult(
                bool(payload["passed"]),
                [str(issue) for issue in payload.get("issues", [])],
                str(payload.get("summary", "")),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return SelfReviewResult(False, ["invalid reviewer response"], "review failed")

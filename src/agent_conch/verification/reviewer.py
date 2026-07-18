"""V 层：多次尝试候选的 LLM/启发式评审。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

ReviewCaller = Callable[[list[dict[str, str]]], Awaitable[str]]


@dataclass
class ReviewResult:
    selected_index: int
    selected: str
    scores: list[float]
    reason: str


class Reviewer:
    def __init__(self, caller: ReviewCaller | None = None) -> None:
        self.caller = caller

    async def select(self, task: str, candidates: list[str]) -> ReviewResult:
        if not candidates:
            raise ValueError("Reviewer requires at least one candidate")
        if len(candidates) == 1:
            return ReviewResult(0, candidates[0], [1.0], "single candidate")

        if self.caller is not None:
            prompt = (
                "Evaluate the candidate answers for correctness, completeness, and evidence. "
                "Return JSON with selected_index, scores, reason.\n"
                f"Task: {task}\nCandidates:\n"
                + "\n".join(f"[{index}] {value}" for index, value in enumerate(candidates))
            )
            try:
                payload = json.loads(await self.caller([{"role": "user", "content": prompt}]))
                selected_index = int(payload["selected_index"])
                scores = [float(value) for value in payload["scores"]]
                if 0 <= selected_index < len(candidates) and len(scores) == len(candidates):
                    return ReviewResult(
                        selected_index,
                        candidates[selected_index],
                        scores,
                        str(payload.get("reason", "LLM review")),
                    )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass

        scores = [self._heuristic_score(candidate) for candidate in candidates]
        selected_index = max(range(len(candidates)), key=scores.__getitem__)
        return ReviewResult(
            selected_index,
            candidates[selected_index],
            scores,
            "deterministic heuristic fallback",
        )

    @staticmethod
    def _heuristic_score(candidate: str) -> float:
        evidence = candidate.count("test") + candidate.count("验证")
        return min(len(candidate) / 1000, 1.0) + evidence * 0.1

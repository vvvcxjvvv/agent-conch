"""O 层：API/SSE 使用的进程内实时事件总线。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers.get(session_id, set())):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(dict(event))

    async def subscribe(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(session_id, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            subscribers = self._subscribers.get(session_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(session_id, None)

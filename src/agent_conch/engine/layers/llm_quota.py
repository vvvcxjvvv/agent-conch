"""L 层：LLM Token 配额熔断。"""

from __future__ import annotations

from agent_conch.engine.layers.base import Event, GraphContext, Layer


class LLMQuotaLayer(Layer):
    name = "llm_quota"

    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens
        self._usage: dict[str, int] = {}

    async def on_graph_start(self, ctx: GraphContext) -> None:
        self._usage[ctx.session_id] = 0

    async def on_event(self, event: Event) -> None:
        if event.type != "llm_usage":
            return
        session_id = str(event.data.get("session_id", ""))
        usage = event.data.get("usage") or {}
        total = self._usage.get(session_id, 0) + int(usage.get("total", 0))
        self._usage[session_id] = total
        graph_ctx = event.data.get("graph_context")
        if total > self.max_tokens and isinstance(graph_ctx, GraphContext):
            graph_ctx.should_abort = True
            graph_ctx.abort_reason = f"LLM quota exceeded: {total} > {self.max_tokens} tokens"

    async def on_graph_end(self, ctx: GraphContext) -> None:
        ctx.metadata["total_llm_tokens"] = self._usage.pop(ctx.session_id, 0)

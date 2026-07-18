"""O 层：OTel 原生 span 与 Layer 接入。"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from agent_conch.engine.layers.base import Event, GraphContext, Layer, NodeContext
from agent_conch.observability.trace_store import SpanRecord, TraceStore


class NodeTypeParser:
    """将运行节点归类为稳定的可观测节点类型。"""

    @staticmethod
    def parse(ctx: NodeContext) -> str:
        if ctx.tool_calls:
            names = {str(call.get("function", {}).get("name", "")) for call in ctx.tool_calls}
            if names & {"write_file", "edit_file", "bash"}:
                return "action"
            return "tool"
        return "model"


class OTelTracer:
    """同时写入 OTel SDK 与 SQLite TraceStore。"""

    def __init__(self, store: TraceStore, service_name: str = "agent-conch") -> None:
        self.store = store
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(service_name)
        self._otel_spans: dict[str, Any] = {}

    def start(
        self,
        session_id: str,
        name: str,
        kind: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> SpanRecord:
        record = self.store.start_span(
            session_id=session_id,
            name=name,
            kind=kind,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            attributes=attributes,
        )
        span = self.tracer.start_span(name, attributes=attributes or {})
        self._otel_spans[record.span_id] = span
        return record

    def finish(
        self, span_id: str, status: str = "ok", attributes: dict[str, Any] | None = None
    ) -> None:
        span = self._otel_spans.pop(span_id, None)
        if span is not None:
            for key, value in (attributes or {}).items():
                if isinstance(value, (str, bool, int, float)):
                    span.set_attribute(key, value)
            span.end()
        self.store.finish_span(span_id, status, attributes)


class ObservabilityLayer(Layer):
    """将 graph/node/event 生命周期转换为结构化 span。"""

    name = "observability"

    def __init__(self, tracer: OTelTracer) -> None:
        self.tracer = tracer
        self.node_type_parser = NodeTypeParser()
        self._graphs: dict[str, SpanRecord] = {}
        self._nodes: dict[tuple[str, int], SpanRecord] = {}

    async def on_graph_start(self, ctx: GraphContext) -> None:
        record = self.tracer.start(
            ctx.session_id,
            "agent.run",
            "graph",
            attributes={"max_turns": ctx.max_turns, "max_time": ctx.max_time},
        )
        self._graphs[ctx.session_id] = record
        ctx.metadata["trace_id"] = record.trace_id

    async def on_node_run_start(self, ctx: NodeContext) -> None:
        graph = self._graphs.get(ctx.session_id)
        record = self.tracer.start(
            ctx.session_id,
            "agent.node",
            "node",
            trace_id=graph.trace_id if graph else None,
            parent_span_id=graph.span_id if graph else None,
            attributes={
                "turn_index": ctx.turn_index,
                "node_type": self.node_type_parser.parse(ctx),
            },
        )
        self._nodes[(ctx.session_id, ctx.turn_index)] = record

    async def on_node_run_end(self, ctx: NodeContext, result: Any) -> None:
        record = self._nodes.pop((ctx.session_id, ctx.turn_index), None)
        if record is not None:
            statuses = [getattr(item, "status", "unknown") for item in result]
            status = "error" if "error" in statuses else "ok"
            self.tracer.finish(record.span_id, status, {"tool_count": len(statuses)})

    async def on_event(self, event: Event) -> None:
        session_id = str(event.data.get("session_id", ""))
        if not session_id:
            return
        graph = self._graphs.get(session_id)
        record = self.tracer.start(
            session_id,
            f"agent.event.{event.type}",
            "event",
            trace_id=graph.trace_id if graph else None,
            parent_span_id=graph.span_id if graph else None,
            attributes={"event_type": event.type},
        )
        self.tracer.finish(record.span_id)

    async def on_graph_end(self, ctx: GraphContext) -> None:
        record = self._graphs.pop(ctx.session_id, None)
        if record is not None:
            status = "aborted" if ctx.should_abort else "ok"
            self.tracer.finish(record.span_id, status, {"turn_count": ctx.turn_count})

"""组合型可观测 provider。

把 console_tracer 与 langfuse_tracer 等 provider 扇出执行，
保证本地指标与远端 trace 可以并行存在。
"""

from __future__ import annotations

from typing import Any

from conch.core.extension import Plugin
from conch.core.registry import registry


@registry.register("observability", "stacked_tracer", "1.0")
class StackedTracer(Plugin):
    """组合多个可观测 provider。"""

    domain = "observability"
    name = "stacked_tracer"
    version = "1.0"
    metadata = {
        "capabilities": ["trace", "metrics", "callback_fanout", "event_record"],
        "description": "组合多个可观测 provider（console + langfuse）",
    }

    def __init__(self, providers: list[dict[str, Any]] | None = None):
        self.provider_configs = providers or []
        self.providers: list[Any] = []

    def on_load(self) -> None:
        self.providers = [self._build_provider(cfg) for cfg in self.provider_configs]

    @property
    def callback_handlers(self) -> list[Any]:
        handlers: list[Any] = []
        for provider in self.providers:
            single = getattr(provider, "callback_handler", None)
            if single is not None:
                handlers.append(single)
            many = getattr(provider, "callback_handlers", None)
            if isinstance(many, list):
                handlers.extend(many)
        return handlers

    def trace(self, state: Any) -> None:
        for provider in self.providers:
            if hasattr(provider, "trace"):
                provider.trace(state)

    def record_event(self, name: str, payload: dict[str, Any]) -> None:
        for provider in self.providers:
            if hasattr(provider, "record_event"):
                provider.record_event(name, payload)

    def metrics(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for provider in self.providers:
            if hasattr(provider, "metrics"):
                metrics = provider.metrics()
                if isinstance(metrics, dict):
                    merged.update(metrics)
        return merged

    def _build_provider(self, cfg: dict[str, Any]) -> Any:
        impl = cfg.get("impl", "")
        if not impl:
            raise ValueError("stacked_tracer provider config missing 'impl'")

        version = cfg.get("version", "latest")
        params = cfg.get("params", {})
        try:
            entry = registry._resolve("observability", impl, version)
        except KeyError:
            self._ensure_module_loaded(impl)
            entry = registry._resolve("observability", impl, version)

        provider = entry.cls(**params)
        if hasattr(provider, "on_load"):
            provider.on_load()
        return provider

    def _ensure_module_loaded(self, impl: str) -> None:
        if impl == "console_tracer":
            from conch.adapters.observability.console_tracer import ConsoleTracer  # noqa: F401
        elif impl == "langfuse_tracer":
            from conch.adapters.observability.langfuse_tracer import LangfuseTracer  # noqa: F401

"""组合型护栏 provider。

按声明顺序串行执行多个 GuardrailProvider：
- 任一层 blocked → 立即返回
- 任一层 sanitized → 将清洗结果继续传给下一层
- 全部 pass → 返回 pass
"""

from __future__ import annotations

from typing import Any

from conch.core.extension import GuardrailProvider, GuardrailResult, Plugin
from conch.core.registry import registry


@registry.register("guardrail", "stacked_guardrails", "1.0")
class StackedGuardrails(Plugin, GuardrailProvider):
    """串联多个 GuardrailProvider。"""

    domain = "guardrail"
    name = "stacked_guardrails"
    version = "1.0"
    metadata = {
        "capabilities": ["input_filter", "output_filter", "tool_guard", "stacked"],
        "description": "组合多个护栏 provider（如 NeMo -> LlamaGuard）",
    }

    def __init__(self, providers: list[dict[str, Any]] | None = None):
        self.provider_configs = providers or []
        self.providers: list[GuardrailProvider] = []

    def on_load(self) -> None:
        self.providers = [self._build_provider(cfg) for cfg in self.provider_configs]

    def check_input(self, text: str, state: Any) -> GuardrailResult:
        return self._run_text_chain("input", text, state)

    def check_output(self, text: str, state: Any) -> GuardrailResult:
        return self._run_text_chain("output", text, state)

    def check_tool(self, tool: str, args: dict, state: Any) -> GuardrailResult:
        for provider in self.providers:
            result = provider.check_tool(tool, args, state)
            if result.blocked:
                return result
        return GuardrailResult(action="pass")

    def _run_text_chain(self, mode: str, text: str, state: Any) -> GuardrailResult:
        current = text
        saw_sanitized = False
        for provider in self.providers:
            if mode == "input":
                result = provider.check_input(current, state)
            else:
                result = provider.check_output(current, state)
            if result.blocked:
                return result
            if result.sanitized is not None:
                current = result.sanitized
                saw_sanitized = True

        if saw_sanitized:
            return GuardrailResult(action="sanitize", sanitized=current)
        return GuardrailResult(action="pass")

    def _build_provider(self, cfg: dict[str, Any]) -> GuardrailProvider:
        impl = cfg.get("impl", "")
        if not impl:
            raise ValueError("stacked_guardrails provider config missing 'impl'")

        version = cfg.get("version", "latest")
        params = cfg.get("params", {})
        try:
            entry = registry._resolve("guardrail", impl, version)
        except KeyError:
            self._ensure_guardrail_module_loaded(impl)
            entry = registry._resolve("guardrail", impl, version)
        provider = entry.cls(**params)
        if hasattr(provider, "on_load"):
            provider.on_load()
        return provider

    def _ensure_guardrail_module_loaded(self, impl: str) -> None:
        if impl == "nemo_guardrails":
            from conch.adapters.guardrail.nemo_guardrails import NemoGuardrail  # noqa: F401
        elif impl == "llamaguard_only":
            from conch.adapters.guardrail.llamaguard import LlamaGuardClassifier  # noqa: F401

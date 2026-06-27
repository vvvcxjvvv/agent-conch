"""单 Loop 编排 — 轻量可选编排引擎（不走 LangGraph）。

从 v1 loop.py 的 AgentLoop 迁移改造：
- 不再依赖 v1 model.call/stream 接口，改调 LiteLLMProvider
- 保留 Hook 触发顺序（pre_step → pre_model_call → ... → post_step）
- 作为 LangGraph 的轻量备选（Profile 中 orchestration.impl = single_loop）
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from conch.core.cost_guard import CostGuard, DegradeLevel, State, TaskStatus
from conch.core.extension import Plugin
from conch.core.hooks import HookInterrupted
from conch.core.registry import registry

logger = logging.getLogger(__name__)


@registry.register("orchestration", "single_loop", "1.0")
class SingleLoopOrchestration(Plugin):
    """单 Agent 循环编排 — 轻量可选（不走 LangGraph）。

    Args:
        max_steps: 最大步数兜底
    """

    domain = "orchestration"
    name = "single_loop"
    version = "1.0"
    metadata = {
        "capabilities": ["react", "tool_use", "single_agent", "streaming"],
        "description": "单 Agent 循环编排（轻量，不依赖 LangGraph）",
    }

    def __init__(self, max_steps: int = 50):
        self.max_steps = max_steps

    async def run(
        self, task: Any, agents: list[Any], state: State
    ) -> AsyncIterator[dict[str, Any]]:
        """执行单 Agent 循环，流式 yield 事件。

        agents[0] 应为 dict: {"llm": LiteLLMProvider, "tools": ToolProvider,
                              "context": ContextManager, "information": InformationProvider,
                              "guardrail_pipeline": GuardrailPipeline, "cost_guard": CostGuard,
                              "hook_bus": HookBus}
        """
        if not agents:
            yield {"type": "done", "success": False, "error": "No agents provided"}
            return

        config = agents[0] if isinstance(agents[0], dict) else {}
        llm = config.get("llm")
        tools_provider = config.get("tools")
        ctx_mgr = config.get("context")
        info_provider = config.get("information")
        gp = config.get("guardrail_pipeline")
        hook_bus = state.hook_bus
        cost_guard = config.get("cost_guard") or CostGuard()

        if llm is None:
            yield {"type": "done", "success": False, "error": "No LLM provider"}
            return

        task_text = task if isinstance(task, str) else str(task)

        # 输入护栏
        if gp:
            try:
                task_text = gp.run_input(task_text)
            except Exception as e:
                yield {"type": "guardrail", "action": "blocked", "reason": str(e)}
                yield {"type": "done", "success": False, "error": "Input blocked by guardrail"}
                return

        messages: list[dict[str, Any]] = []
        # 系统提示
        if info_provider:
            sys_prompt = info_provider.assemble(task, state)
            if sys_prompt:
                messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": task_text})

        # 工具定义
        tools_schema: list[dict] | None = None
        if tools_provider:
            lc_tools = tools_provider.tools_for(task, state)
            tools_schema = [self._lc_tool_to_schema(t) for t in lc_tools]

        try:
            if hook_bus:
                hook_bus.fire("on_task_start", state)
        except HookInterrupted as e:
            yield {"type": "done", "success": False, "error": f"Interrupted: {e.reason}"}
            return

        state.status = TaskStatus.RUNNING
        idle_steps = 0

        while not state.done and state.steps < self.max_steps:
            try:
                if hook_bus:
                    hook_bus.fire("pre_step", state)

                # 上下文组装
                if ctx_mgr:
                    state.context = ctx_mgr.assemble(task, state)

                if hook_bus:
                    hook_bus.fire("pre_model_call", state)

                # LLM 流式推理
                tool_call = None
                usage = {"total_tokens": 0, "cost": 0.0}
                async for chunk in llm.stream(messages, tools=tools_schema):
                    if chunk["type"] == "text":
                        yield {"type": "text_delta", "content": chunk["content"]}
                        messages.append({"role": "assistant", "content": chunk["content"]})
                    elif chunk["type"] == "tool_call":
                        tool_call = chunk
                    elif chunk["type"] == "usage":
                        usage = chunk

                action = {"type": "text", "usage": usage}
                if tool_call:
                    action = {"type": "tool_call", "tool": tool_call["tool"],
                              "args": tool_call["args"], "usage": usage}

                if hook_bus:
                    hook_bus.fire("post_model_call", state, action=action)

                # 工具执行
                if tool_call and tools_provider:
                    tool_name = tool_call["tool"]
                    tool_args = tool_call["args"]
                    if hook_bus:
                        hook_bus.fire("pre_tool", state, tool=tool_name, args=tool_args)

                    # 工具护栏
                    if gp:
                        gr = gp.check_tool(tool_name, tool_args)
                        if gr.blocked:
                            yield {"type": "guardrail", "action": "blocked",
                                   "reason": gr.reason, "tool": tool_name}
                            result_str = f"[Tool blocked by guardrail: {gr.reason}]"
                        else:
                            try:
                                result = await tools_provider.execute(tool_name, tool_args, state)
                                result_str = str(result)
                            except Exception as e:
                                result_str = f"[Tool error: {e}]"
                                if hook_bus:
                                    hook_bus.fire("on_tool_error", state, error=e)
                    else:
                        try:
                            result = await tools_provider.execute(tool_name, tool_args, state)
                            result_str = str(result)
                        except Exception as e:
                            result_str = f"[Tool error: {e}]"
                            if hook_bus:
                                hook_bus.fire("on_tool_error", state, error=e)

                    yield {"type": "tool_call", "tool": tool_name, "args": tool_args}
                    yield {"type": "tool_result", "tool": tool_name, "result": result_str}
                    messages.append({"role": "assistant", "content": "",
                                     "tool_calls": [{"name": tool_name, "args": tool_args}]})
                    messages.append({"role": "tool", "name": tool_name, "content": result_str})
                    if hook_bus:
                        hook_bus.fire("post_tool", state, result=result_str)
                    idle_steps = 0
                else:
                    idle_steps += 1

                state.record(action)

                # 成本守卫
                level = cost_guard.check(state)
                if level != DegradeLevel.NONE:
                    cost_guard.apply(state, level)
                    if state.status == TaskStatus.DEGRADED:
                        yield {"type": "done", "success": False, "error": "Cost limit exceeded"}
                        return

                if hook_bus:
                    hook_bus.fire("post_step", state)

                if idle_steps >= 3:
                    break

            except HookInterrupted as e:
                logger.info("Loop interrupted: %s", e.reason)
                break
            except Exception as e:
                logger.exception("Step %d failed", state.steps)
                if hook_bus:
                    hook_bus.fire("on_error", state, error=e)
                state.status = TaskStatus.FAILED
                state.error = e
                yield {"type": "done", "success": False, "error": str(e)}
                return

        if not state.done:
            state.status = TaskStatus.DONE
        if hook_bus:
            hook_bus.fire("on_task_end", state)
        yield {"type": "done", "success": True}

    def _lc_tool_to_schema(self, lc_tool: Any) -> dict:
        """LangChain Tool → OpenAI tool schema。"""
        name = getattr(lc_tool, "name", "unknown")
        desc = getattr(lc_tool, "description", "")
        args_schema = getattr(lc_tool, "args_schema", None)
        parameters = {}
        if args_schema:
            try:
                parameters = args_schema.model_json_schema()
            except Exception:
                parameters = {"type": "object", "properties": {}}
        return {"type": "function", "function": {"name": name, "description": desc, "parameters": parameters}}

    async def task_split(self, task: Any, state: Any) -> list[Any]:
        return [task]

    async def state_sync(self, agents: list[Any], state: Any) -> None:
        return None

    async def conflict_resolve(self, results: list[Any], state: Any) -> Any:
        return results[0] if results else None

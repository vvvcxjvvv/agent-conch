# 06 — 护栏体系：NeMo + GuardrailPipeline + 六层防御

> **代码位置**：`backend/conch/core/guardrail_pipeline.py`（95 行）、`backend/conch/adapters/guardrail/nemo_guardrails.py`（140 行）
> **对应 ETCLOVG**：E 层（护栏模块）

## 1. 六层纵深防御映射

| 层 | 机制 | 实现 |
|----|------|------|
| 1. 输入筛查 | `pre_model_call` Hook → `GuardrailPipeline.run_input()` | `NemoGuardrail.check_input()` |
| 2. LLM 推理 | 模型内置 safety + litellm 参数 | `LiteLLMProvider` 调用参数 |
| 3. 工具护栏 | `pre_tool` Hook（可中断）→ `GuardrailPipeline.check_tool()` | `NemoGuardrail.check_tool()` |
| 4. 检索护栏 | 记忆 Pipeline 中间件 | notes_file / Mem0（阶段二） |
| 5. 输出筛查 | `post_model_call` Hook → `GuardrailPipeline.run_output()` | `NemoGuardrail.check_output()` |
| 6. 监控审计 | `on_tool_error` / `post_tool` Hook → 审计日志 | Langfuse + 自研审计 |

## 2. GuardrailPipeline — 护栏编排引擎

基于 `middleware.Pipeline`，定义 input/output 两路管道：

```python
class GuardrailPipeline:
    def __init__(self, provider: GuardrailProvider | None, state: State):
        self.input_pipeline = Pipeline([GuardrailMiddleware(provider, state, "input")])
        self.output_pipeline = Pipeline([GuardrailMiddleware(provider, state, "output")])

    def run_input(self, text: str) -> str:
        """输入筛查 → blocked 抛 GuardrailBlocked，否则返回原文或 sanitized"""
        return self.input_pipeline.run(text)

    def run_output(self, text: str) -> str:
        """输出筛查"""
        return self.output_pipeline.run(text)

    def check_tool(self, tool: str, args: dict) -> GuardrailResult:
        """工具护栏 → 返回结果，由调用方决定是否中断"""
        return self.provider.check_tool(tool, args, self.state)
```

`GuardrailMiddleware.process()` 调用 `provider.check_input/output()`，`blocked=True` 抛 `GuardrailBlocked` 异常。

## 3. NemoGuardrail（两层模式）

### 模式一：NeMo 引擎（完整模式）

```python
class NemoGuardrail(Plugin, GuardrailProvider):
    def __init__(self, config_dir, use_nemo=True):
        self.use_nemo = use_nemo

    def on_load(self):
        if self.use_nemo:
            config = RailsConfig.from_path(config_dir)
            self._rails = LLMRails(config)  # NeMo LLMRails 引擎

    def check_input(self, text, state):
        if self.use_nemo and self._rails:
            result = self._rails.generate(messages=[{"role": "user", "content": text}])
            if "blocked" in str(result).lower():
                return GuardrailResult(blocked=True, reason="NeMo guardrail")
        return GuardrailResult(action="pass")
```

配置文件 `guardrail_configs/chat/config.yml` + `rails.co` 定义拦截规则（Colang DSL）。

### 模式二：关键词兜底（MVP 默认，无需 C++ 编译）

```python
_DEFAULT_BLOCKED_PATTERNS = [
    "删除所有文件", "rm -rf /", "格式化磁盘",
    "drop table", "drop database", ...
]

def _check_with_keywords(self, text):
    for pattern in _DEFAULT_BLOCKED_PATTERNS:
        if pattern in text.lower():
            return GuardrailResult(blocked=True, reason=f"matched: {pattern}")
    return GuardrailResult(action="pass")
```

当 `use_nemo=False` 或 NeMo 未安装时自动降级，满足 MVP 退出标准（3 条有害输入 100% 拦截）。

## 4. 护栏触发流程

```
编排 Plugin.run()
  └─ LangGraphHookBridge
       ├─ on_llm_start → hook_bus.fire("pre_model_call", state)
       │    └─ (Hook 中调 guardrail_pipeline.run_input(user_text))
       │         └─ NemoGuardrail.check_input()
       │              └─ blocked → GuardrailBlocked → SSE guardrail 事件
       │
       ├─ on_tool_start → hook_bus.fire("pre_tool", state, tool, args)
       │    └─ guardrail_pipeline.check_tool(tool, args)
       │         └─ blocked → HookInterrupted → 工具跳过
       │
       └─ on_llm_end → hook_bus.fire("post_model_call", state, action)
            └─ guardrail_pipeline.run_output(llm_text)
```

## 5. 加载使用方式

```python
# deps.py: build_runtime()
if "guardrail" in profile.domains:
    rt.guardrail_provider = registry.build("guardrail", cfg.impl, ...)
rt.guardrail_pipeline = GuardrailPipeline(rt.guardrail_provider, rt.state)
```

`guardrail_pipeline` 被注入到 `rt.state` 中，编排 Plugin 通过 Hook 或显式调用触发。

## 6. 可扩展点

- 新护栏模型 → 实现 `GuardrailProvider` 三方法 + `@register("guardrail", ...)`
- 新护栏层 → `GuardrailPipeline.input_pipeline.add(NewMiddleware(...))`
- 工具护栏白名单 → Governance domain `check_permission` + `pre_tool` Hook 联动

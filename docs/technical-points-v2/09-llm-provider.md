# 09 — LLM 接入：litellm 统一多模型

> **代码位置**：`backend/conch/adapters/llm/litellm_provider.py`（120 行）
> **对应 ETCLOVG**：横切基础设施

## 1. 实现原理

```python
@registry.register("llm", "litellm", "1.0")
class LiteLLMProvider(Plugin):
    def __init__(self, default_model="openai/gpt-4o-mini",
                 api_base=None, api_key=None, temperature=0.7):
        # api_key/api_base 优先级：构造参数 > 环境变量
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.api_base = api_base or os.environ.get("OPENAI_API_BASE")
```

### 流式推理

```python
async def stream(self, messages, model=None, tools=None):
    """yield {"type": "text", "content": ...} | "tool_call" | "usage" """
    kwargs = {"model": model or self.default_model,
              "messages": messages, "stream": True,
              "api_base": self.api_base, "api_key": self.api_key}
    if tools:
        kwargs["tools"] = tools

    response = await litellm.acompletion(**kwargs)
    async for chunk in response:
        if delta.content:
            yield {"type": "text", "content": delta.content}
        if delta.tool_calls:
            # 累积 tool_calls（OpenAI 格式，多 chunk 拼接 name + args）
            ...
    # 流结束后 yield 完整 tool_calls（解析 JSON args）
```

### 非流式推理

```python
async def call(self, messages, model=None, tools=None):
    response = await litellm.acompletion(...)
    return {"content": ..., "usage": {...}, "tool_calls": [...]}
```

## 2. 支持的模型（litellm 统一路由）

### OpenAI 兼容 API（默认）

```yaml
# .env
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.deepseek.com/v1  # 国内模型端点
```

litellm model 名格式 `"provider/model"`：

| 提供商 | model 名 | API_BASE |
|--------|---------|----------|
| OpenAI | `openai/gpt-4o` | 默认 |
| DeepSeek | `openai/deepseek-chat` | `https://api.deepseek.com/v1` |
| 智谱 GLM | `openai/glm-4-flash` | `https://open.bigmodel.cn/api/paas/v4` |
| 通义千问 | `openai/qwen-plus` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Ollama 本地 | `ollama/llama3` | `http://localhost:11434/v1` |

### 环境变量优先级

```
构造参数 api_key="xxx" > 环境变量 OPENAI_API_KEY > None
构造参数 api_base="..." > 环境变量 OPENAI_API_BASE > None
```

## 3. 加载使用方式

```python
# 1. .env 配置（推荐，启动时自动加载）
# backend/.env:
#   OPENAI_API_KEY=sk-xxx
#   OPENAI_API_BASE=https://api.deepseek.com/v1

# 2. Profile YAML
domains:
  orchestration:
    impl: langgraph_react
    params:
      model: "openai/deepseek-chat"  # 不传 api_key，自动读环境变量

# 3. API 层
rt.llm = registry.build("llm", "litellm", "latest")  # 默认配置
# 或
rt.llm = registry.build("llm", "litellm", "latest",
                        default_model="openai/qwen-plus")

# 4. 编排 Plugin 内部
async for chunk in llm.stream(messages, tools=tools_schema):
    if chunk["type"] == "text":
        yield sse_event("text_delta", chunk)
    elif chunk["type"] == "tool_call":
        yield sse_event("tool_call", chunk)
```

## 4. Tool Calling 支持

```yaml
# Profile 中配置
domains:
  orchestration:
    params:
      model: "openai/gpt-4o-mini"  # 需支持 function calling 的模型
```

litellm 流式模式下 tool_calls 分多 chunk 传输（OpenAI 格式：`name` 和 `arguments` 分开），Provider 内部累积拼接，流结束后 yield 完整 tool_call。

## 5. 可扩展点

- 新模型 → 改 `model` 参数即可（litellm 100+ 模型自带）
- 自定义 API 端点 → `api_base` 参数或 `OPENAI_API_BASE` 环境变量
- 非 OpenAI 兼容模型 → litellm 原生协议（`anthropic/claude`, `ollama/llama3` 等）
- 模型 fallback → `model_fallback` + `CostGuard.L2_SWITCH_MODEL` 联动

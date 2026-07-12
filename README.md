# Agent-Conch

全栈通用 AI Agent Harness，基于 ETCLOVG 七层模型。

## 快速开始

```bash
# 安装
pip install -e ".[dev]"

# 设置 API Key
# Windows PowerShell
$env:DEEPSEEK_API_KEY = "sk-your-key"

# macOS / Linux
export DEEPSEEK_API_KEY="sk-your-key"

# 运行
conch run "读取 README.md 并总结"

# 查看工具
conch tools

# 回放轨迹
conch replay <session_id>
```

## 模型配置

Agent-Conch 通过 [litellm](https://github.com/BerriAI/litellm) 统一调用各平台的 LLM，修改 `conch.yaml` 或运行时参数即可切换。

### 方式一：修改 conch.yaml（持久生效）

```yaml
# DeepSeek
model:
  name: "deepseek/deepseek-chat"
  api_key_env: "DEEPSEEK_API_KEY"

# OpenAI
model:
  name: "gpt-4o"
  api_key_env: "OPENAI_API_KEY"

# Anthropic Claude
model:
  name: "claude-sonnet-4-20250514"
  api_key_env: "ANTHROPIC_API_KEY"

# 本地 Ollama / vLLM (OpenAI 兼容)
model:
  name: "openai/qwen2.5-coder"
  api_base: "http://localhost:11434/v1"
  api_key_env: "OPENAI_API_KEY"
```

### 方式二：运行时指定（临时覆盖）

```bash
conch run "读取 README.md" --model deepseek/deepseek-chat
```

### 支持的平台

litellm 支持 100+ 平台，包括 OpenAI / DeepSeek / Anthropic / Gemini / Groq / 通义千问 / 文心一言 等。模型名格式为 `provider/model`，详见 [litellm 文档](https://docs.litellm.ai/docs/providers)。

## 架构

基于 ETCLOVG 七层模型 + H=(E,T,C,S,L,V) 六组件形式化模型。

详见 `agent-conch-design.md`。

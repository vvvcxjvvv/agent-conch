# Agent-Conch

全栈通用 AI Agent Harness，以 **ETCLOVG 七层模型**为架构骨架。

核心论点：**Agent = Model + Harness**。通过外部系统设计（工具编排、状态管理、沙箱隔离、验证层）让 AI Agent 在生产环境中稳定可控，不依赖模型权重优化。

## 快速开始

```bash
# 1. 安装
pip install -e ".[dev]"

# 2. 配置模型 (conch.yaml)
#   model.name       → 模型名 (格式: provider/model)
#   api_key_env      → API Key 环境变量名

# 3. 设置 Key
# Windows:  $env:DEEPSEEK_API_KEY = "sk-xxx"
# macOS:    export DEEPSEEK_API_KEY="sk-xxx"

# 4. 运行
conch run "读取 README.md 并总结"
```

## 架构

```
E 层 — 执行环境    Local / Docker 沙箱 + FS Bridge + 敏感路径保护
T 层 — 工具接口    12 核心工具 + ToolRegistry + 策略管控 + 并行执行
C 层 — 上下文      可插拔 Context Engine + 渐进式压缩 + Skill/Memory
L 层 — 生命周期    Observe-Think-Act 循环 + Layer 插件 + 多 Agent
O 层 — 可观测     OpenTelemetry Trace + Trajectory 回放 + exit_status
V 层 — 验证       内置 lint/type check/test + Reviewer 评审 + 回归用例
G 层 — 治理       RBAC + 配额熔断 + PolicyEngine + 安全审计
S 层 — 状态存储    SQLite 优先 + Checkpoint + FTS5 全文搜索
```

完整设计文档：[agent-conch-design.md](agent-conch-design.md)

## CLI 命令

| 命令 | 说明 |
|------|------|
| `conch run "<任务>"` | 运行 Agent |
| `conch run "<任务>" --model gpt-4o` | 运行时指定模型 |
| `conch tools` | 列出已注册工具 |
| `conch health` | 工具健康状态 |
| `conch replay <session_id>` | 回放执行轨迹 |
| `conch config` | 查看当前配置 |

## 模型配置

通过 [litellm](https://github.com/BerriAI/litellm) 统一调用，支持 100+ 平台。修改 `conch.yaml` 切换模型：

| 平台 | model.name | api_key_env |
|------|-----------|-------------|
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Anthropic | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| 本地 Ollama | `openai/qwen2.5-coder` | `OPENAI_API_KEY` |

本地模型需额外配置 `api_base` 字段。运行时也可临时切换：`conch run "..." --model deepseek/deepseek-reasoner`。

# Agent-Conch

> 全栈通用 AI Agent Harness｜基于 ETCLOVG 七层模型

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-209%20passed%20%2F%201%20skipped-brightgreen.svg)]()
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)]()

## 目录

- [基本信息](#基本信息)
- [架构](#架构)
- [运行机制](#运行机制)
- [核心功能与策略](#核心功能与策略)
- [快速开始](#快速开始)
- [配置与接口](#配置与接口)
- [项目结构](#项目结构)
- [测试与发布边界](#测试与发布边界)
- [路线图](#路线图)
- [技术栈](#技术栈)

## 基本信息

**核心论点：Agent = Model + Harness。** Agent-Conch 通过工具编排、状态管理、沙箱隔离、验证、可观测与治理，把模型能力组织为可运行、可审计、可恢复的 Agent 系统。

| 项目 | 说明 |
| --- | --- |
| 定位 | 面向本地开发、受控自动化与治理工作台的通用 AI Agent Harness |
| 核心入口 | CLI、FastAPI/SSE、React Web Console、Electron Desktop |
| 运行模型 | LiteLLM 统一路由；支持 DeepSeek、OpenAI、Anthropic、Ollama 等 |
| 默认状态存储 | SQLite；会话、消息、轨迹、Trace、审批、预算、调度和 Hook 执行可查询 |

## 架构

```text
                         ┌──────────────────────────────────────┐
                         │ G 治理与安全                          │
                         │ RBAC · PolicyEngine · Approval · Budget│
                         ├──────────────────────────────────────┤
                         │ V 验证与评估                          │
                         │ lint · type-check · test · Regression │
                         ├──────────────────────────────────────┤
                         │ O 可观测性                            │
                         │ OTel · Trace · Trajectory · Insights  │
                         ├──────────────────────────────────────┤
                         │ L 生命周期与编排                      │
                         │ Agent Loop · Layers · Hooks · Multi-Agent │
                         ├──────────────────────────────────────┤
                         │ C 上下文与记忆                        │
                         │ Context Engine · Compact · Skill · Memory │
                         ├──────────────────────────────────────┤
                         │ T 工具接口                            │
                         │ Core Tools · MCP · Registry · Output  │
                         ├──────────────────────────────────────┤
                         │ E 执行环境                            │
                         │ Local · Docker · SSH · gVisor · FS Bridge │
                         └───────────────────┬──────────────────┘
                                             │
                         ┌───────────────────▼──────────────────┐
                         │ S 状态存储                            │
                         │ SQLite · Checkpoint · FTS5 · Audit    │
                         └──────────────────────────────────────┘
```

| 层级 | 当前能力 |
| --- | --- |
| E | Local/Docker/SSH、gVisor `runsc`、FsBridge、网络白名单、快照/回滚 |
| T | 12 核心工具、MCP、ToolRegistry、ToolPolicy、输出 offload |
| C | ContextEngine、渐进压缩、Prompt Caching、Skill、四层记忆 |
| L | Agent Loop、Layer、HookExecutor、Checkpoint、Cron、Coordinator |
| O | OTel、Trace、Decision、Trajectory、exit status、Insights |
| V | VerificationLayer、Reviewer、自审、回归用例与质量门禁 |
| G | RBAC、PolicyEngine、内容安全、WriteApproval、Credential Pool、成本熔断 |
| S | SQLite 会话、消息、轨迹、治理对象、调度、快照与 Hook 审计 |

## 运行机制

```text
任务输入（CLI / API / Web）
          │
          ▼
ConchEngine：创建/恢复 Session，绑定 principal、role、budget
          │
          ▼
Layer 生命周期：limits → observability → quota → verification → hooks
          │
          ▼
Context Engine：加载消息/记忆/Skill，必要时渐进压缩
          │
          ▼
LLM Observe → Think → Act
          │
          ▼
ToolRegistry：参数校验 → ToolPolicy → RBAC/Policy → Approval → Budget
          │
          ├── Core Tools / MCP Tools → Local / Docker / SSH / Web
          │
          └── 脱敏 → 长输出制品化 → Trajectory / Trace / Verification
          │
          ▼
最终回答、SSE 事件、治理记录、可回放状态
```

工具执行不绕过 `ToolRegistry`：高风险操作先经过角色权限、声明式策略、一次性审批与预算；结果输出统一脱敏，超过阈值时落为权限 `0600` 的私有制品，仅向模型返回预览和引用。

## 核心功能与策略

| 能力 | 实现策略 | 关键产物/接口 |
| --- | --- | --- |
| Agent 执行 | Observe-Think-Act 循环；retry/requery/compact/abort 错误恢复 | `conch run`、`POST /runs` |
| 工具系统 | 12 核心工具、动态 MCP 工具、健康缓存、并行调用、长输出 offload | `ToolRegistry`、`GET /tools`、`GET /mcp/servers` |
| 沙箱与文件 | Local/Docker/SSH 统一实现 `SandboxBackend` 与 `FsBridge`；敏感路径和远端根目录限制 | `sandbox.*`、`GET /governance/overview` |
| 网络与内容安全 | HTTP(S) 域名通配符/CIDR 白名单；私钥、Bearer、API Key 等敏感内容阻断与脱敏 | `sandbox.network_policy`、`ContentSafetyGuard` |
| 上下文与记忆 | 清理 → 折叠 → 摘要归档的渐进压缩；Short/Session/Long/Meta 记忆 | `ContextEngine`、`session_search` |
| Skill 与自改进 | frontmatter 选择性注入；Curator 归档/改进/consolidation 提案受审批保护 | `GET /skills`、`/curator/*` |
| 生命周期与多 Agent | Layer 插件、Hook fail-closed、Checkpoint、Cron 硬超时、Coordinator 隔离 Worker | `GET /hooks/executions`、`/schedules`、`/coordinator/runs` |
| 可观测与回放 | OTel Span、Decision Trace、Trajectory、exit status、Insights、SSE | `/events/{session_id}`、`/runs/{id}/traces` |
| 确定性验证 | 写操作后自动执行 lint/type-check/test；失败沉淀为可重复回归用例 | `/runs/{id}/verification`、`/regressions` |
| 治理 | 40+ 权限点、五级操作分级、PolicyEngine、WriteApproval、四维预算熔断 | `/governance/overview`、`/approvals` |
| 工作台 | React 三栏工作台；Markdown/源文本切换；会话、Tool、MCP、Skill、Hook 资源控制台 | `apps/web`、Electron Desktop |

| 工具调用阶段 | 策略与效果 |
| --- | --- |
| 参数校验 | 使用工具 schema 拒绝无效输入 |
| ToolPolicy | 处理工具/沙箱兼容与基础 allow/deny 规则 |
| RBAC + PolicyEngine | 校验角色、操作级别、声明式规则与内容安全 |
| Approval | 高风险或 memory/skill 写入生成一次性审批请求 |
| Budget | 限制 Token、时间、工具次数和资源单位 |
| 结果处理 | 脱敏、offload、健康状态、轨迹、Trace、验证报告 |

## 快速开始

### 1. 安装

```bash
git clone https://github.com/vvvcxjvvv/agent-conch.git
cd agent-conch
pip install -e ".[dev]"
```

### 2. 配置模型

编辑 `conch.yaml`：

```yaml
model:
  provider: "litellm"
  name: "deepseek/deepseek-chat"
  api_key_env: "DEEPSEEK_API_KEY"
```

设置密钥：

```bash
export DEEPSEEK_API_KEY="<your-api-key>"  # macOS / Linux
# PowerShell: $env:DEEPSEEK_API_KEY = "<your-api-key>"
```

### 3. 运行首个任务

```bash
conch run "读取 README.md 并总结"
```

### 4. 启动前后端工作台

```bash
# 终端一：FastAPI / SSE
conch serve

# 终端二：React 工作台
cd apps/web
npm install
npm run dev
# 打开 http://127.0.0.1:5173
```

工作台中创建任务后，可查看最终回答、决策轨迹、实时事件、执行轨迹、Trace、验证报告、治理中心和资源控制台；最终回答支持 Markdown 与源文本切换。

### 5. 最小 API 验证

```bash
curl http://127.0.0.1:8765/health

curl -X POST http://127.0.0.1:8765/runs \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"quickstart-001","input":"读取 README.md 并总结"}'

curl -N http://127.0.0.1:8765/events/quickstart-001
curl http://127.0.0.1:8765/runs/quickstart-001/trajectory
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/governance/overview
```

## 配置与接口

所有行为由 `conch.yaml` 驱动。以下为常用治理、沙箱和扩展配置：

```yaml
agent_loop:
  max_turns: 50
  max_time: 600
  auto_compact: true

tools:
  parallel_execution: true
  output_max_chars: 20000
  output_preview_chars: 4000

sandbox:
  mode: "non-main"            # non-main | always | never
  default_backend: "local"     # local | docker | ssh
  docker:
    network: "none"
    runtime: ""                # gVisor: runsc
  network_policy:
    enforce: false
    allowlist: []               # 例如 ["*.example.com", "10.0.0.0/8"]

governance:
  enabled: true
  default_role: "admin"
  approval_level: 4
  content_safety_enabled: true
  redact_sensitive: true

mcp:
  enabled: true
  servers: []                   # {name, command, args, env, cwd, enabled}

hooks:
  enabled: true
  commands: []                  # {name, event, command, timeout, fail_closed}
```

| 模型平台 | `model.name` | `api_key_env` |
| --- | --- | --- |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Anthropic | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| 本地 Ollama | `openai/qwen2.5-coder` | `OPENAI_API_KEY` |

常用接口：

```bash
conch tools
conch health
conch replay <session_id>
conch config

curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/sessions
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/tools
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/skills
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/mcp/servers
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/hooks/executions
```

Electron Desktop 复用 Web Console：

```bash
cd apps/web && npm run build
cd ../desktop && npm install && npm start
npm run pack  # 可分发目录
```

## 项目结构

```text
agent-conch/
├── conch.yaml
├── apps/
│   ├── web/                    # React + TypeScript 工作台
│   └── desktop/                # Electron 安全 IPC 与终端桥接
├── src/agent_conch/
│   ├── engine/                 # AgentLoop、Runtime、Layer、ConchEngine
│   ├── tools/                  # Core Tools、Registry、MCP、OutputManager
│   ├── sandbox/                # Local、Docker、SSH、FsBridge、快照、网络策略
│   ├── context/                # ContextEngine、压缩、Skill、Memory
│   ├── hooks/                  # 生命周期 HookExecutor
│   ├── observability/          # OTel、Trace、Trajectory、Insights、SSE
│   ├── verification/           # Verification、Reviewer、Regression
│   ├── security/               # RBAC、Policy、ContentSafety、Credentials、Audit
│   ├── governance/             # Budget、Scheduler
│   ├── multiagent/             # Subagent、Coordinator
│   └── state/                  # SQLite Session、Checkpoint、Trajectory
├── tests/
├── docs/
└── plan/
```

## 测试与发布边界

```bash
pytest tests/
ruff check src tests
mypy src

cd apps/web && npm run test && npm run build && npm run test:e2e
cd ../desktop && npm run check && npm run pack
```

当前门禁：Python **209 passed、1 skipped**；Ruff 与 mypy strict 通过；Web Vitest、Playwright E2E、Electron 可分发目录打包通过。

本机未提供 Docker/runsc、Bitwarden/1Password CLI、SSH 验收目标和 Developer ID；真实 Docker/gVisor、Vault、SSH 冒烟及 Electron 签名/公证属于发布环境验收，不以模拟测试替代。

## 路线图

| 阶段 | 目标 | 状态 |
| --- | --- | --- |
| P1 Workflow Agent | 循环、工具、状态、Local 沙箱 | ✅ |
| P2 Stateful Harness | 压缩、记忆、Skill、Docker、Subagent、Checkpoint | ✅ |
| P3 Auditable Harness | Trace、验证、报告、搜索、Web Console | ✅ |
| P4 Governable Production Harness | 权限审批、回归、调度、多 Agent、Web/Electron 工作台 | ✅ |

## 技术栈

| 类别 | 技术 |
| --- | --- |
| 后端 | Python 3.10+、FastAPI、Uvicorn、Pydantic、LiteLLM |
| 状态与可观测 | SQLite、FTS5、OpenTelemetry |
| 前端与桌面 | React、TypeScript、Vite、Electron |
| 质量门禁 | pytest、pytest-asyncio、Ruff、mypy、Vitest、Playwright |

## 许可证

[MIT](LICENSE)

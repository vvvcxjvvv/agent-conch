# Agent-Conch

> 全栈通用 AI Agent Harness | 基于 ETCLOVG 七层模型

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-200%20passed%20%2F%201%20skipped-brightgreen.svg)]()
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)]()

**核心论点：Agent = Model + Harness。** 通过外部系统设计（工具编排、状态管理、沙箱隔离、验证层）让 AI Agent 在生产环境中稳定可控，不依赖模型权重优化。

---

## 目录

- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [架构](#架构)
- [CLI 命令](#cli-命令)
- [配置](#配置)
- [项目结构](#项目结构)
- [测试](#测试)
- [路线图](#路线图)
- [技术栈](#技术栈)
- [许可证](#许可证)

---

## 核心特性

- **Observe-Think-Act 循环** — 完整的 Agent 执行闭环，含 retry/requery/compact/abort 四种错误恢复策略
- **12 核心工具** — bash、文件读写编辑、glob/grep、web 搜索/抓取、skill、ask_user、task_manage、tool_search，支持并行执行
- **可插拔 Context Engine** — 渐进式上下文压缩（清理 → 折叠 → 摘要归档）+ Prompt Caching + Skill 按需注入
- **分层记忆** — Short / Session / Long / Meta 四层记忆 + 自动提取 + FTS5 全文搜索
- **沙箱隔离** — Local + Docker 双后端 + FsBridge 文件操作抽象 + 敏感路径跨平台保护
- **子 Agent** — SQLite 注册表 + 孤儿检测/恢复/认领 + 工具委托策略
- **Checkpoint** — 完整状态序列化 + Pause/Resume
- **轨迹回放** — 每步持久化 + JSONL 导出 + DB/文件双模式回放
- **确定性验证** — 写工具后自动 lint/type-check/test + 独立验证报告 + 提交前自审
- **完整可观测** — OpenTelemetry span + SQLite TraceStore + 决策轨迹 + exit status + Insights
- **生产治理** — 40+ 权限点 RBAC、5 级操作分级、PolicyEngine、一次性 WriteApproval、Credential Pool、综合成本熔断
- **自动治理闭环** — 失败用例自动沉淀与回归门禁、Skill Curator、3 分钟硬中断 Cron、Coordinator 多 Agent、快照/回滚
- **Web / Desktop 工作台** — 深海青蓝三栏工作台覆盖任务、轨迹、审批、治理、回归、调度和指标；Electron 复用 Web Console 并提供受治理终端桥接
- **多模型支持** — 通过 [litellm](https://github.com/BerriAI/litellm) 统一调用 100+ 平台

## 快速开始

### 安装

```bash
git clone https://github.com/vvvcxjvvv/agent-conch.git
cd agent-conch
pip install -e ".[dev]"
```

### 配置模型

编辑 `conch.yaml`，设置 `model.name` 和 `api_key_env`：

```yaml
model:
  provider: "litellm"
  name: "deepseek/deepseek-chat"
  api_key_env: "DEEPSEEK_API_KEY"
```

设置 API Key 环境变量：

```bash
# macOS / Linux
export DEEPSEEK_API_KEY="sk-xxx"

# Windows PowerShell
$env:DEEPSEEK_API_KEY = "sk-xxx"
```

### 运行

```bash
conch run "读取 README.md 并总结"
```

### 前后端交互

```bash
# 终端一：启动后端 API/SSE 服务
export DEEPSEEK_API_KEY="<your-api-key>"
conch serve

# 终端二：启动 React Web Console
cd apps/web
npm install
npm run dev
# 浏览器访问 http://127.0.0.1:5173
# 自定义后端地址：VITE_API_BASE=http://127.0.0.1:8765 npm run dev

# 后端健康检查
curl http://127.0.0.1:8765/health

# 发起 Agent 任务
curl -X POST http://127.0.0.1:8765/runs \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"p3-e2e-001","input":"读取 README.md 并总结当前 P3 能力"}'

# 监听 SSE 实时事件；使用相同 Session ID 发起任务后，
# 应收到 run_started、llm_call、tool_call、run_finished
curl -N http://127.0.0.1:8765/events/p3-e2e-001

# 查询轨迹、OTel Trace 和验证报告
curl http://127.0.0.1:8765/runs/p3-e2e-001/trajectory
curl http://127.0.0.1:8765/runs/p3-e2e-001/traces
curl http://127.0.0.1:8765/runs/p3-e2e-001/verification

# 创建待审批记录；刷新 Web Console 后可批准或拒绝
curl -X POST http://127.0.0.1:8765/approvals \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"p3-e2e-001","operation":"write memory","reason":"验证审批流程"}'
curl http://127.0.0.1:8765/approvals

# 查询 Insights、安全审计和历史会话
curl http://127.0.0.1:8765/insights
curl http://127.0.0.1:8765/security/audit
curl 'http://127.0.0.1:8765/sessions/search?query=P3&limit=10'

# P4 治理、回归、调度与多 Agent 状态
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/governance/overview
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/regressions
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/schedules
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/coordinator/runs

# Electron Desktop（先构建 Web；后端 conch serve 保持运行）
cd apps/web && npm run build
cd ../desktop && npm install && npm start
# 开发模式：CONCH_WEB_URL=http://127.0.0.1:5173 npm start

# Web Console 验收：
# timeline 显示 SSE 事件；决策轨迹展示观察、决策、执行、验证和结论摘要；
# trajectory/traces 展示底层执行证据；
# 最终回答可手动切换 Markdown 预览和源文本；
# 成功执行 write_file/edit_file 后 verification 生成服务级报告；
# 审批可从 pending 更新为 approved/rejected；默认安全审计返回 []。
```

## 架构

Agent-Conch 以 **ETCLOVG 七层模型** 为架构骨架：

```
 ┌───────────────────────────────────────────────────┐
 │ G · 治理       RBAC · 配额熔断 · PolicyEngine     │
 ├───────────────────────────────────────────────────┤
 │ V · 验证       lint · type-check · test · Reviewer │
 ├───────────────────────────────────────────────────┤
 │ O · 可观测     OTel · Trace · Trajectory · Insights │
 ├───────────────────────────────────────────────────┤
 │ L · 生命周期   O-T-A 循环 · Layer 插件 · Subagent  │
 ├───────────────────────────────────────────────────┤
 │ C · 上下文     ContextEngine · 压缩 · Skill · 记忆 │
 ├───────────────────────────────────────────────────┤
 │ T · 工具接口   12 工具 · Registry · Policy · 并行   │
 ├───────────────────────────────────────────────────┤
 │ E · 执行环境   Local/Docker 沙箱 · FsBridge · 保护 │
 ├───────────────────────────────────────────────────┤
 │ S · 状态存储   SQLite · Checkpoint · FTS5          │
 └───────────────────────────────────────────────────┘
```

**各层实现进度：**

| 层级 | 名称 | 当前能力 |
|------|------|----------|
| E | 执行环境与沙箱 | Local/Docker + FsBridge + 敏感路径保护 + 快照/回滚 |
| T | 工具接口层 | 12 核心工具 + ToolRegistry + ToolPolicy + PolicyEngine 前置治理 + 预算 |
| C | 上下文与记忆 | ContextEngine + 渐进式压缩 + Prompt Caching + Skill/Memory + Skill Curator |
| L | 生命周期与编排 | Agent Loop + Layer 插件 + Checkpoint + Cron + Coordinator 多 Agent |
| O | 可观测性 | OTel + 持久化事件流 + Trace/Decision/Trajectory + exit_status + Insights |
| V | 验证与评估 | VerificationLayer + Reviewer + 自审 + 失败沉淀 + 回归质量门禁 |
| G | 治理与安全 | RBAC + 5 级操作 + PolicyEngine + WriteApproval + Credential Pool + 成本熔断 |
| S | 状态存储 | SQLite SessionDB + Checkpoint + 治理/回归/调度/Coordinator/快照状态 |

## CLI 命令

```bash
conch run "<任务>"                    # 运行 Agent
conch run "<任务>" --model gpt-4o    # 运行时指定模型
conch run "<任务>" -v                # 详细输出
conch tools                          # 列出已注册工具
conch health                         # 工具健康状态
conch replay <session_id>            # 回放执行轨迹
conch replay ~/.agent-conch/trajectories/<id>.jsonl  # 从文件回放
conch config                         # 查看当前配置
conch serve                          # 启动 HTTP API / SSE（默认 127.0.0.1:8765）
```

## 配置

所有配置通过 `conch.yaml` 驱动，关键配置项：

```yaml
# LLM 模型
model:
  provider: "litellm"
  name: "deepseek/deepseek-chat"
  api_key_env: "DEEPSEEK_API_KEY"
  temperature: 0.0
  max_tokens: 4096
  timeout: 120

# Agent Loop
agent_loop:
  max_turns: 50
  max_time: 600
  auto_compact: true

# 工具
tools:
  core_enabled: true
  tool_search_threshold: 0.10
  parallel_execution: true

# 沙箱
sandbox:
  mode: "non-main"           # non-main | always | never
  default_backend: "local"   # local | docker

# 状态存储
state:
  storage_dir: "~/.agent-conch"
  db_name: "state.db"

# Layer
layers:
  enabled:
    - "execution_limits"
    - "observability"
    - "llm_quota"
    - "verification"
    - "suspend"
    - "pause_state_persist"
    - "cost_budget"

governance:
  enabled: true
  default_role: "admin"
  approval_level: 4

budget:
  max_tokens: 200000
  max_seconds: 600
  max_tool_calls: 500
  max_resource_units: 1000

regression:
  auto_capture: true
  minimum_pass_rate: 1.0

scheduler:
  hard_timeout: 180

coordinator:
  max_workers: 4
  worker_role: "worker"
```

**支持的模型平台：**

| 平台 | model.name | api_key_env |
|------|-----------|-------------|
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Anthropic | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| 本地 Ollama | `openai/qwen2.5-coder` | `OPENAI_API_KEY` |

本地模型需额外配置 `api_base` 字段。运行时也可临时切换：`conch run "..." --model deepseek/deepseek-reasoner`。

## 项目结构

```
agent-conch/
├── src/agent_conch/
│   ├── cli.py                 # CLI 入口 (click + rich)
│   ├── config.py              # ConchConfig YAML 加载
│   ├── engine/
│   │   ├── agent_loop.py      # Observe-Think-Act 循环
│   │   ├── conch_engine.py    # 引擎入口，组装各层组件
│   │   ├── error_classifier.py # 25 种错误分类 + 恢复策略
│   │   ├── layers/            # Layer 插件框架
│   │   └── runtime/           # AgentRuntime ABC + BuiltinRuntime
│   ├── tools/
│   │   ├── base.py            # BaseTool ABC
│   │   ├── registry.py        # ToolRegistry + check_fn 缓存
│   │   ├── tool_policy.py     # Allow/Deny + Sandbox 策略
│   │   ├── tool_search.py     # 渐进式工具发现
│   │   └── core/              # 12 核心工具实现
│   ├── context/
│   │   ├── engine.py          # ContextEngine ABC + LegacyEngine
│   │   ├── compact/pipeline.py # 三步压缩管线
│   │   ├── prompt_caching.py  # Prompt Caching 策略
│   │   ├── skills/registry.py # Skill 加载 + 选择性注入
│   │   └── memory/manager.py  # 四层记忆管理
│   ├── sandbox/
│   │   ├── local.py           # LocalBackend + LocalFsBridge
│   │   ├── docker.py          # DockerBackend + DockerFsBridge
│   │   ├── fs_bridge.py       # FsBridge ABC
│   │   └── path_validator.py  # 路径安全校验
│   ├── security/
│   │   ├── permissions.py     # RBAC + 5 级操作权限
│   │   ├── policy_engine.py   # 统一策略引擎
│   │   └── credentials.py     # Credential Pool
│   ├── governance/            # 综合预算与 Cron 调度
│   ├── verification/          # 确定性验证与回归门禁
│   ├── state/
│   │   ├── session_db.py      # SQLite SessionDB
│   │   ├── checkpoint.py      # Pause/Resume 序列化
│   │   └── trajectory.py      # 轨迹存储 + JSONL 导出
│   ├── multiagent/
│   │   ├── subagent.py        # 子 Agent 注册表 + 孤儿恢复
│   │   └── coordinator.py     # 主从编排 + 决策表 + 隔离
│   └── prompts/
│       ├── system_prompt.py   # System Prompt + 环境注入
│       └── agents_md.py       # AGENTS.md 发现
├── apps/web/                  # React 治理工作台
├── apps/desktop/              # Electron 安全封装与终端桥接
├── tests/                     # 200 个通过测试 + 1 Docker 条件跳过
├── docs/                      # 设计文档 + 阶段总结
├── conch.yaml                 # 默认配置
└── pyproject.toml
```

## 测试

```bash
# 运行全部测试
pytest tests/

# 带覆盖率
pytest tests/ --cov=agent_conch --cov-report=term-missing

# 仅运行某一层
pytest tests/test_sandbox.py    # E 层
pytest tests/test_context.py    # C 层
pytest tests/test_engine.py     # L 层
```

当前状态：**200 个测试通过，1 个 Docker 集成测试因本机无可用 Docker daemon 条件跳过**；P4 新增 19 个治理、回归、Curator、调度、Coordinator、快照、持久化事件、Credential Pool 和 Desktop API 闭环用例。

| 测试文件 | 覆盖层 | 测试数 |
|----------|--------|--------|
| `test_sandbox.py` | E 层 — 沙箱 | 22 + 1 Docker 条件跳过 |
| `test_tools.py` | T 层 — 核心工具 | 19 |
| `test_tool_system.py` | T 层 — 工具系统 | 24 |
| `test_context.py` | C 层 — 上下文与记忆 | 33 |
| `test_engine.py` | L 层 — 引擎 | 14 |
| `test_state.py` | S 层 — 状态存储 | 15 |
| `test_p2.py` | P2 综合 | 34 |
| `test_integration.py` | 集成 | 5 |
| `test_p3.py` | P3 O/V/G/API/SSE/检索综合 | 15 |
| `test_p4.py` | P4 治理/回归/调度/多 Agent/Desktop 综合 | 19 |

## 路线图

| 阶段 | 目标 | 状态 |
|------|------|------|
| **P1** Workflow Agent | 最小可运行骨架：循环 + 工具 + 状态 + Local 沙箱 | ✅ 完成 |
| **P2** Stateful Harness | 上下文压缩 + 记忆 + Skill + Docker + Subagent + Checkpoint | ✅ 完成 |
| **P3** Auditable Harness | 完整 trace + 失败归因 + 确定性验证 + 验证报告 + Web Console | ✅ 完成 |
| **P4** Governable Production Harness | 权限审批 + 回归门禁 + 调度/多 Agent + Web/Electron 治理工作台 | ✅ 完成 |

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| LLM 路由 | [litellm](https://github.com/BerriAI/litellm) — 支持 100+ 平台 |
| CLI | [click](https://click.palletsprojects.com/) + [rich](https://rich.readthedocs.io/) |
| 数据校验 | [Pydantic](https://docs.pydantic.dev/) v2 |
| 状态存储 | SQLite（stdlib）+ FTS5 全文搜索 |
| 测试 | pytest + pytest-asyncio + pytest-cov |
| Lint | ruff + mypy (strict) |
| API / 实时事件 | FastAPI + SSE + uvicorn |
| 可观测 | OpenTelemetry SDK + SQLite TraceStore |
| Web Console | React + TypeScript + Vite |
| Desktop | Electron（context isolation + sandbox IPC） |

## 许可证

[MIT](LICENSE)

# AgentConch

> Agent Harness Engineering 技术实践平台 — 以可扩展性为核心。

**Agent = Model + Harness。** 模型是 CPU，Harness 是操作系统。当模型能力趋于稳定，任务执行的可靠性越来越取决于模型外层的那层工程。

AgentConch 把 Harness 拆解为 **9 大能力域**，每个域定义稳定接口、支持插件化实现，配套注册中心 + Profile + 实验框架三件套，使"接入新技术点"等同于"写插件 + 一行注册"，对核心零侵入。

## 快速开始

```bash
# 安装（零外部依赖也可运行，pydantic+yaml 为可选增强）
pip install -e ".[dev]"

# 列出已注册插件
python -m conch plugins

# 用示例 Profile 跑一个任务（MockProvider，无需 LLM API）
python -m conch run --profile coding-agent-v1 --task "fix the syntax error" --mock

# 运行实验对比
python -m conch experiment --suite swe-mini --profiles coding-agent-v1

# 运行端到端 demo（模拟"读文件→修复→写文件"完整链路）
python tests/demo_e2e.py

# 运行测试套件
python tests/test_core.py
```

## 已实现功能

### 核心抽象层（`conch/core/`）

| 模块 | 文件 | 功能 |
|---|---|---|
| **扩展点契约** | `extension.py` | 9 域 ExtensionPoint Protocol 接口 + 依赖倒置（核心层只定义接口） |
| **注册中心** | `registry.py` | 装饰器注册 + `depends_on` 拓扑加载 + 生命周期钩子（on_load/on_unload/on_reload）+ `query()` 运行时发现 + 版本共存 |
| **Hook 总线** | `hooks.py` | 14 个挂载点 + 三大约束（职责隔离 / priority 优先级 / 中断白名单）|
| **中间件链** | `middleware.py` | Pipeline 数据流处理（与 Hook 控制流职责分离）|
| **Profile 引擎** | `profile.py` | `extends` 继承 + Pydantic 校验（可选）+ 环境变量覆盖 + 双模式（无 yaml 也能跑） |
| **Agent Loop** | `loop.py` | 单 Agent 循环 + streaming 推理 + CostGuard 分级降级（L1压缩→L2切模型→L4终止）+ 空闲终止 |
| **实验框架** | `experiment.py` | Profile A/B 对比 + 消融实验 + SWE-bench/swe-mini 对接 + Markdown 对比表输出 |

### 9 大能力域默认实现（`conch/domains/`）

| 域 | 文件 | 实现名 | 功能 |
|---|---|---|---|
| 1 信息边界 | `information/agents_md.py` | `agents_md` | AGENTS.md 指令文件加载器（只当目录不当超级 Prompt） |
| 2 工具系统 | `tool/builtin_shell.py` | `builtin_shell` | read_file / write_file / run_bash / list_files 四个内置工具，MCP 对齐 |
| 3 上下文管理 | `context/jit_compaction.py` | `jit_compaction` | JIT 加载 + 40% 利用率阈值守卫 + 摘要压缩 |
| 4 记忆状态 | `memory/notes_file.py` | `notes_file` | 基于 NOTES.md 的结构化笔记，五分法中短期+情景 |
| 5 执行编排 | `orchestration/single_loop.py` | `single_loop` | 单 Agent 循环编排（多 Agent 模式接口已预留） |
| 6 评估验证 | `eval/step_eval.py` | `step_eval` | 最小单步评测：检查 action 是否出错 |
| 7 可观测性 | `observability/console_tracer.py` | `console_tracer` | 控制台轨迹输出，执行类+成本类指标 |
| 8 约束恢复 | `constraint/linter.py` | `linter` | 最小 Linter：检查文件内容常见错误模式 |
| 9 治理 | `governance/allowlist.py` | `allowlist_perms` | allowlist 权限模型 + 审计日志 |

### 运行时层（`conch/runtime/`）

| 模块 | 文件 | 功能 |
|---|---|---|
| **LLM Provider** | `model/base.py` | Provider 抽象基类（`call()` + `stream()`）+ MockProvider（测试用） |
| **ScriptedProvider** | `model/scripted.py` | 按预设脚本返回响应，端到端测试用 |
| **Docker 沙箱** | `sandbox/docker_sandbox.py` | 加固基线：CPU/内存/网络限制、禁特权、只读挂载（无 Docker 降级本地执行） |
| **内存存储** | `store/memory_store.py` | 最小 KV 存储 + 简单文本搜索 |

### 配置与测试

| 文件 | 说明 |
|---|---|
| `profiles/coding-agent-v1.yaml` | MVP 完整 Profile（9 域配置 + max_tokens + model_fallback） |
| `profiles/coding-agent-v2-subagents.yaml` | extends 继承示例（覆写编排域） |
| `benchmarks/swe-mini/001.json` | 示例任务：修复语法错误 |
| `benchmarks/swe-mini/002.json` | 示例任务：添加单元测试 |
| `tests/test_core.py` | 11 个单元测试（全部通过） |
| `tests/demo_e2e.py` | 端到端 demo（读文件→修复→写文件全链路） |

### CLI 命令

```bash
# 列出所有已注册插件（按域分组）
python -m conch plugins
python -m conch plugins --domain tool

# 执行单个任务
python -m conch run --profile <name> --task <desc> [--mock] [--mock-response <text>]

# 运行实验对比（多 Profile × 任务集）
python -m conch experiment --suite swe-mini --profiles <p1> <p2>
```

## 核心文档

- [技术方案 v0.3](docs/technical-design.md) — 完整架构设计（9 域 + 三层扩展 + 路线图）
- [实现状态](docs/implementation-status.md) — 当前实现内容与验证状态
- [技术点详解](docs/technical-points/) — 13 篇技术点深入文档

### 技术点文档索引

| # | 技术点 | 文档 |
|---|---|---|
| 01 | 扩展点契约 | [01-extension-point.md](docs/technical-points/01-extension-point.md) |
| 02 | 注册中心 | [02-registry.md](docs/technical-points/02-registry.md) |
| 03 | Hook 与中间件 | [03-hook-and-middleware.md](docs/technical-points/03-hook-and-middleware.md) |
| 04 | Profile 与实验框架 | [04-profile-and-experiment.md](docs/technical-points/04-profile-and-experiment.md) |
| 05 | Agent Loop 引擎 | [05-agent-loop.md](docs/technical-points/05-agent-loop.md) |
| 06 | 上下文管理 | [06-context-management.md](docs/technical-points/06-context-management.md) |
| 07 | 工具系统与 MCP | [07-tool-system-mcp.md](docs/technical-points/07-tool-system-mcp.md) |
| 08 | 记忆五分法 | [08-memory-five-types.md](docs/technical-points/08-memory-five-types.md) |
| 09 | 多 Agent 协作 | [09-multi-agent-orchestration.md](docs/technical-points/09-multi-agent-orchestration.md) |
| 10 | 可观测性与自观测 | [10-observability.md](docs/technical-points/10-observability.md) |
| 11 | 沙箱与安全治理 | [11-sandbox-security.md](docs/technical-points/11-sandbox-security.md) |
| 12 | 成本守卫与分级降级 | [12-cost-guard.md](docs/technical-points/12-cost-guard.md) |
| 13 | Skill 系统 | [13-skill-system.md](docs/technical-points/13-skill-system.md) |

## 设计哲学

- **可扩展性 > 功能完备性** — 宁可能力域接口稳定但实现少，也不要接口臃肿却难以扩展
- **核心稳定，边界常新** — 能力域接口定义 WHAT 不定义 HOW
- **反对过度工程** — MVP 先做最小闭环，按需补层，不为想象中的需求提前抽象
- **安全 day-one** — 沙箱与权限校验是底线，不是远期功能

## 三层扩展模型

任何新技术点都有归宿，且核心代码永远不需要改动：

| 层级 | 适用场景 | 机制 |
|---|---|---|
| **L1 插件** | 已有域内新实现（如新压缩算法） | 实现域接口 + `@registry.register` |
| **L2 Hook / 中间件** | Loop 关键节点的横切逻辑 | 挂载到 Hook 总线 / 中间件链 |
| **L3 自定义能力域** | 全新技术维度 | 注册新域 + 定义接口 |

## 项目结构

```
agent-conch/
├── conch/
│   ├── core/                   # 核心抽象（7 文件，稳定，极少改动）
│   │   ├── extension.py        # 9 域 ExtensionPoint 接口
│   │   ├── registry.py         # 注册中心
│   │   ├── hooks.py            # Hook 总线 + 三大约束
│   │   ├── middleware.py       # 中间件链
│   │   ├── profile.py          # Profile 引擎（extends + 校验）
│   │   ├── loop.py             # Agent Loop + CostGuard
│   │   └── experiment.py       # 实验框架
│   ├── domains/                # 9 域默认实现
│   │   ├── information/        # 域1：agents_md
│   │   ├── tool/               # 域2：builtin_shell
│   │   ├── context/            # 域3：jit_compaction
│   │   ├── memory/             # 域4：notes_file
│   │   ├── orchestration/      # 域5：single_loop
│   │   ├── eval/               # 域6：step_eval
│   │   ├── observability/      # 域7：console_tracer
│   │   ├── constraint/         # 域8：linter
│   │   └── governance/         # 域9：allowlist_perms
│   └── runtime/                # 运行时适配
│       ├── model/              # Provider 基类 + Mock + Scripted
│       ├── sandbox/            # Docker 沙箱（加固基线）
│       └── store/              # 内存存储
├── profiles/                   # 实验配置（YAML）
├── benchmarks/                 # 评测任务集
├── tests/                      # 测试 + 端到端 demo
├── docs/                       # 技术方案 + 技术点文档
├── AGENTS.md                   # 项目自身指令文件（dogfooding）
└── pyproject.toml
```

## License

MIT

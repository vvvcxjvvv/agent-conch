# Agent-Conch

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://docs.astral.sh/ruff/)
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)]()

> Agent = Model + Harness。Agent-Conch 是一个把 LLM 模型能力组织成可运行、可审计、可恢复 Agent 系统的 Python Harness：工具编排、沙箱执行、上下文压缩、确定性验证、可观测性与治理审批一体化。

## 特性

- **Observe-Think-Act Agent Loop**：内置错误恢复策略（retry / requery / compact / abort），每一步都可回放
- **12 个核心工具 + MCP 动态工具**：`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `web_fetch` / `web_search` / `skill` / `task_manage` / `session_search` / `ask_user`，外加通过 MCP 协议接入的动态工具
- **多后端沙箱**：`LocalBackend` / `DockerBackend`（支持 gVisor `runsc`）/ `SSHBackend` 统一实现 `SandboxBackend` 与 `FsBridge`，敏感路径与网络白名单可配置
- **上下文工程**：清理 → 折叠 → 摘要归档的渐进压缩，Short / Session / Long / Meta 四层记忆
- **确定性验证**：写操作后自动执行 lint / type-check / test，失败用例沉淀为可重复回归
- **治理与安全**：40+ 权限点、五级操作分级、声明式 `PolicyEngine`、一次性写审批 `WriteApproval`、四维预算熔断（Token / 时间 / 工具次数 / 资源）、内容脱敏与敏感内容阻断
- **可观测**：OpenTelemetry Span、Decision Trace、Trajectory、exit status、Insights、SSE 实时事件
- **多入口**：CLI、FastAPI / SSE、React Web 工作台、Electron 桌面端
- **状态持久化**：SQLite 会话 / 消息 / 轨迹 / 审批 / 调度 / Hook 审计，支持 FTS5 全文检索与 Checkpoint 回滚

## 架构

Agent-Conch 采用自下而上的 ETCLOVG 七层模型，每层都是可插拔的 `Layer`，由 `ConchEngine` 在 Agent Loop 中编排：

```text
┌──────────────────────────────────────────────┐
│ G 治理与安全  RBAC · PolicyEngine · Approval │
├──────────────────────────────────────────────┤
│ V 验证与评估  lint · type-check · test · 回归 │
├──────────────────────────────────────────────┤
│ O 可观测性    OTel · Trace · Trajectory      │
├──────────────────────────────────────────────┤
│ L 生命周期    Agent Loop · Layer · Hook · Multi Agent │
├──────────────────────────────────────────────┤
│ C 上下文记忆  ContextEngine · Compact · Skill │
├──────────────────────────────────────────────┤
│ T 工具接口    Core Tools · MCP · Registry     │
├──────────────────────────────────────────────┤
│ E 执行环境    Local · Docker · SSH · gVisor   │
├──────────────────────────────────────────────┤
│ S 状态存储    SQLite · Checkpoint · FTS5 · Audit │
└──────────────────────────────────────────────┘
```

运行时数据流：

```text
任务输入 (CLI / API / Web)
  → ConchEngine 创建/恢复 Session, 绑定 principal · role · budget
  → Layer 生命周期: limits → observability → quota → verification → hooks
  → ContextEngine 加载消息/记忆/Skill, 必要时渐进压缩
  → LLM Observe → Think → Act
  → ToolRegistry: 参数校验 → ToolPolicy → RBAC/Policy → Approval → Budget
  → Core Tools / MCP Tools → Local / Docker / SSH
  → 结果脱敏 → 长输出制品化 → Trajectory / Trace / Verification
  → 最终回答 + SSE 事件 + 治理记录 + 可回放状态
```

工具调用始终经 `ToolRegistry`：高风险操作先过角色权限、声明式策略、一次性审批与预算；结果统一脱敏，超阈值落为 `0600` 私有制品，仅向模型返回预览与引用。

## 策略描述

各层以可插拔 Layer 形式接入引擎，在 Observe-Think-Act 循环中统一编排；下层为上层供给能力，上层不绕过下层约束。

| 层级 | 职责 | 核心模块 | 关键策略 |
| --- | --- | --- | --- |
| **E 执行环境** | 命令执行与文件操作的隔离底座 | 三后端 + 文件桥接 + 路径校验 + 网络策略 + 快照 | • 命令执行与文件操作双抽象解耦，工具层不感知后端差异<br>• 本地异步子进程 + 超时强杀；Docker 异步 commit/restore/delete 快照回滚，透传 gVisor 运行时；SSH 走 OpenSSH 命令行 + 严格 host key<br>• 路径安全双重检查：原始字符串模式匹配 + 解析后路径精确比较，规避 Windows 解析不稳定<br>• 敏感路径硬编码不可被用户规则覆盖；HTTP(S) 网络白名单做主机通配符与 CIDR 决策 |
| **T 工具接口** | 外部能力统一接口 | 13 核心工具 + Registry + Policy + Search + MCP + 输出管理 | • Pydantic 参数校验并自动生成 JSON Schema；校验前先过滤多余字段防模型冗余参数<br>• 工具调用串起：查找 → 校验 → 工具策略 → RBAC/策略引擎 → 写审批 → 预算 → 执行 → 健康记账<br>• 可用性检查 30 秒 TTL 缓存，连续失败 2 次以上 60 秒瞬态抑制<br>• 读写分离并行：读操作并行，写操作串行避免竞争<br>• 非核心工具按 schema token 占比 10% 阈值启用渐进发现；超长输出落 0600 私有制品，仅返回预览与引用 |
| **C 上下文记忆** | 模型看到什么、记住什么、遗忘什么 | 可插拔引擎 + 压缩管线 + Caching + Skill + 四层记忆 | • 可插拔上下文引擎五钩子（初始化/组装/维护/压缩/回合后），内置 fallback 始终可用<br>• 渐进压缩三步成本递增：清理旧结果（零 LLM）→ 折叠超长内容（零 LLM）→ 仅仍超预算时调一次 LLM 摘要<br>• Prompt 缓存 system_and_3 四断点，满 100 字符才占断点，非 Anthropic 自动空操作<br>• Skill 四级加载（内置 → 用户 → 项目 → 插件），目录注入 + 按需加载 + schema 精准匹配章节<br>• 四层记忆：短期/会话/长期/元记忆，FTS5 全文搜索缺失降级 LIKE，自动提取带去重签名 |
| **S 状态存储** | 状态外置底座 | SQLite + FTS5 + 检查点 + 事件流 | • 运行时状态全进 SQLite，文件系统仅用于人类可读资产；JSONL 仅用于审计导出<br>• 同步 sqlite3 + 跨线程访问，单次操作亚毫秒级不阻塞事件循环<br>• tool_calls 以 JSON 存消息表而非独立表；FTS5 缺失降级普通表 + LIKE<br>• 检查点管理器负责快照/恢复；单库适合单机与轻量多实例 |
| **L 生命周期编排** | Agent 执行循环与横切能力 | Agent Loop + Layer 链 + Hook + Coordinator + Cron + 子 Agent | • Observe-Think-Act 循环 + 错误分类器归类 retry/requery/compact/abort 四种恢复策略，循环内异常不静默吞没<br>• Layer 插件链五钩子 + 中止信号传播；Hook 可配置事件命令、fail-closed、SQLite 审计<br>• Cron 调度 UTC 五字段 + 180 秒硬中断<br>• Coordinator 决策表驱动顺序/并行 worker，信号量限并发（默认 4），worker 独立会话上下文隔离 |
| **O 可观测性** | 做了什么、为什么失败、成本花在哪 | OTel + Trace + Decision Trace + 轨迹 + exit_status + Insights + SSE | • graph/node/event 钩子转 OTel span，同时写 OTel SDK 与 SQLite Trace（全局 provider 只能设一次，复用已有）<br>• 决策轨迹只记可观察证据（observe/decide/act/verify/conclude/govern 六阶段），不采集模型思维链<br>• 轨迹双源：SQLite 可查询 + JSONL 可审计回放；退出状态九类归因写入会话与 trace<br>• SQLite 事件流支持多 API 实例轮询，未引入外部 broker |
| **V 验证评估** | 把"声称完成"变成"有证据完成" | 验证层 + 评审 + 自审 + 报告分离 + 回归用例 | • 成功写操作触发验证层，按 YAML 串行执行 lint/type/test，首个失败即停并保留末尾 4000 字<br>• 报告持久化 Agent 自述与服务级验证两类独立字段，互不背书<br>• 失败用例经 SHA256 指纹去重沉淀为回归用例，批量执行输出通过率门禁<br>• 自审默认确定性规则避免额外模型调用；评审器仍支持 LLM 多候选选优 + 启发式 fallback |
| **G 治理安全** | 权限审批成本合规从提示词变成系统约束 | RBAC + 策略引擎 + 写审批 + 凭证池 + 内容安全 + 审计 + 预算 | • 52 权限点 + 五级操作 + 六内置角色；策略引擎 RBAC 先行 → 规则匹配 → 风险阈值审批，DSL 为受控声明式子集<br>• 写审批请求哈希防篡改 + pending 复用 + 批准后一次性消费恢复原始请求<br>• 四维预算（Token/时间/工具次数/资源）实时记账，超限产生 BUDGET_EXCEEDED<br>• 内容安全按字段语义扫描内联密钥减少误报，工具结果与最终回答统一脱敏<br>• 凭证池按优先级/使用次数/最近使用轮换 + 失败冷却，Bitwarden/1Password 经 CLI resolver 接入、明文不落库 |

## 快速开始

### 安装

要求 Python ≥ 3.10。

```bash
git clone https://github.com/vvvcxjvvv/agent-conch.git
cd agent-conch
pip install -e ".[dev]"
```

### 配置模型

编辑 `conch.yaml`：

```yaml
model:
  provider: "litellm"
  name: "deepseek/deepseek-chat"
  api_key_env: "DEEPSEEK_API_KEY"
```

设置密钥：

```bash
export DEEPSEEK_API_KEY="<your-api-key>"
```

支持的模型平台：

| 平台 | `model.name` | `api_key_env` |
| --- | --- | --- |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| Anthropic | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| 本地 Ollama | `openai/qwen2.5-coder` | `OPENAI_API_KEY` |

### 运行首个任务

```bash
conch run "读取 README.md 并总结"
```

### 启动前后端工作台

```bash
# 终端一：FastAPI / SSE
conch serve

# 终端二：React 工作台
cd apps/web
npm install
npm run dev
# 打开 http://127.0.0.1:5173
```

### 最小 API 验证

```bash
curl http://127.0.0.1:8765/health

curl -X POST http://127.0.0.1:8765/runs \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"quickstart-001","input":"读取 README.md 并总结"}'

curl -N http://127.0.0.1:8765/events/quickstart-001
curl http://127.0.0.1:8765/runs/quickstart-001/trajectory
curl -H 'X-Conch-Role: viewer' http://127.0.0.1:8765/governance/overview
```

## CLI 命令

| 命令 | 说明 |
| --- | --- |
| `conch run "<input>"` | 运行 Agent 任务，支持 `-s/--session-id`、`-c/--config`、`--cwd`、`--model`、`--max-turns`、`-v` |
| `conch replay <session_id_or_file>` | 按 session ID 或 JSONL 文件回放轨迹 |
| `conch tools` | 列出已注册工具及其 write/dangerous 标记 |
| `conch health` | 查看工具健康状态与瞬态故障抑制 |
| `conch serve` | 启动 FastAPI / SSE 服务，支持 `--host`、`--port`、`--cwd` |
| `conch config` | 打印当前生效配置 |

## 配置

所有行为由 `conch.yaml` 驱动，关键段落：

```yaml
agent_loop:
  max_turns: 50
  max_time: 600
  auto_compact: true

tools:
  parallel_execution: true
  output_max_chars: 20000        # 超长输出落盘上限
  output_preview_chars: 4000     # 返回模型的预览长度

sandbox:
  mode: "non-main"               # non-main | always | never
  default_backend: "local"       # local | docker | ssh
  docker:
    network: "none"
    runtime: ""                  # gVisor: runsc
  network_policy:
    enforce: false
    allowlist: []                # 例如 ["*.example.com", "10.0.0.0/8"]

governance:
  enabled: true
  default_role: "admin"
  approval_level: 4
  content_safety_enabled: true
  redact_sensitive: true

mcp:
  enabled: true
  servers: []                    # {name, command, args, env, cwd, enabled}

hooks:
  enabled: true
  commands: []                   # {name, event, command, timeout, fail_closed}
```

完整示例见 [conch.yaml](conch.yaml)。

## 项目结构

```text
agent-conch/
├── conch.yaml                    # 默认配置
├── src/agent_conch/
│   ├── engine/                   # ConchEngine、AgentLoop、Runtime、Layer
│   ├── tools/                    # BaseTool、core/*、Registry、MCP、OutputManager
│   ├── sandbox/                  # Local/Docker/SSH Backend、FsBridge、网络策略
│   ├── context/                  # ContextEngine、压缩、Skill、Memory
│   ├── hooks/                    # 生命周期 HookExecutor
│   ├── observability/            # OTel、Trace、Trajectory、Insights、SSE
│   ├── verification/             # Verification、Reviewer、Regression
│   ├── security/                 # RBAC、Policy、ContentSafety、Credentials、Audit
│   ├── governance/               # Budget、Scheduler
│   ├── multiagent/               # Subagent、Coordinator
│   └── state/                    # SQLite Session、Checkpoint、Trajectory
├── apps/
│   ├── web/                      # React + TypeScript 工作台
│   └── desktop/                  # Electron 安全 IPC 与终端桥接
├── tests/
├── docs/                         # 各层实现策略沉淀
└── plan/
```

## 开发

```bash
# 后端质量门禁
pytest tests/
ruff check src tests
mypy src

# 前端
cd apps/web && npm run test && npm run build && npm run test:e2e

# 桌面端
cd apps/desktop && npm run check && npm run pack
```

## 技术栈

| 类别 | 技术 |
| --- | --- |
| 后端 | Python 3.10+、FastAPI、Uvicorn、Pydantic、LiteLLM |
| 状态与可观测 | SQLite、FTS5、OpenTelemetry |
| 前端与桌面 | React、TypeScript、Vite、Electron |
| 质量门禁 | pytest、pytest-asyncio、Ruff、mypy、Vitest、Playwright |

## 许可证

[MIT](LICENSE)

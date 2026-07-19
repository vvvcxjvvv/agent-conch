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
│ L 生命周期    Agent Loop · Layer · Hook · 多Agent │
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

## 实现策略

各层均以可插拔 `Layer` 形式接入 `ConchEngine`，由 `AgentLoop` 在 Observe-Think-Act 循环中编排。

| 层级 | 关键策略 | 设计思想 |
| --- | --- | --- |
| **E 执行环境与沙箱** | • `SandboxBackend` / `FsBridge` 双抽象解耦命令执行与文件操作<br>• `LocalBackend` 异步 `create_subprocess_shell` + 超时 kill<br>• `DockerBackend` 异步 `commit`/`restore`/`delete` 快照回滚，透传 `--runtime runsc` 接入 gVisor<br>• `SSHBackend` 走 OpenSSH argv + 严格 host key 校验<br>• `PathValidator` 原始字符串模式匹配 + resolved 路径精确比较双重检查，规避 Windows resolve 不稳定<br>• 敏感路径硬编码不可被用户规则覆盖<br>• 网络白名单在 HTTP(S) 层做主机通配符与 CIDR 决策 | 约束解放：用沙箱隔离 + 硬编码敏感路径换取"放心执行任意命令"的自由度；FsBridge 让工具层不关心后端差异 |
| **T 工具接口** | • `BaseTool` 以 Pydantic `input_model` 校验并自动生成 JSON Schema<br>• `validate_input` 先过滤多余字段再实例化，防 LLM 冗余参数<br>• `execute_tool_call` 串起查找 → 校验 → `ToolPolicy` → RBAC/Policy → Approval → Budget → 执行 → 健康记账<br>• `check_fn` 30s TTL 缓存，连续失败 ≥ 2 次进入 60s 瞬态抑制<br>• 并行执行按 `is_write_tool` 分离：读 `asyncio.gather` / 写串行<br>• `ToolSearch` 按非核心 schema token 占比阈值（10%）启用渐进发现<br>• `OutputManager` 超阈值截断落 `0600` 私有制品，仅返回预览与引用 | 最小工具原则：核心保持窄腰，能力通过 Skill/Plugin/MCP 扩展；治理前置到工具调用链路而非事后补救 |
| **C 上下文与记忆** | • `ContextEngine` ABC 五钩子（`bootstrap`/`assemble`/`maintain`/`compact`/`after_turn`），`LegacyEngine` fallback<br>• 渐进压缩三步管线成本递增：`ResultCleanup`（>200 chars 旧结果，保留最近 10 条，零 LLM）→ `ContentFolding`（>2000 chars 折叠 head 900 + tail 500，零 LLM）→ `SummaryArchive`（仅前两步仍超预算时调一次 LLM）<br>• Prompt Caching `system_and_3` 四断点，`_can_carry_marker` ≥ 100 chars 才占断点，非 Anthropic no-op<br>• Skill 四级加载（bundled → user → project → plugin），`inject_schema.when` + `fields` 选择性注入章节<br>• 四层记忆中 LongTerm 写 SQLite + MEMORY.md，MetaMemory 走 FTS5（缺失降级 LIKE），自动提取带去重签名 | 铁律：不允许变更过去上下文、不切换 toolset、不重建 system prompt，唯一例外是压缩；压缩按成本递增逐步升级，能用规则解决就不调 LLM |
| **L 生命周期与编排** | • `forward_with_handling` 用 `ErrorClassifier` 归类 retry/requery/compact/abort 四种恢复策略<br>• 循环内 except 不静默吞异常（曾因 `await` 同步 `save_step` 触发 TypeError 被吞，导致跑满 max_turns）<br>• `LayerManager` 五钩子 + `should_abort` 中止传播<br>• `HookExecutor` 可配置事件命令 + `fail_closed` + SQLite 审计<br>• `CronScheduler` UTC 五字段 + `asyncio.wait_for` 180s 硬中断<br>• `Coordinator` 决策表驱动顺序/并行 worker + `Semaphore` 限并发 + worker 独立 session 上下文隔离 | 把循环、错误恢复、Hook、调度、多 Agent 统一为 Layer 编排；错误分类决定恢复策略而非一刀切重试；隔离是默认假设 |
| **O 可观测性** | • `ObservabilityLayer` 把 graph/node/event 钩子转 OTel span<br>• `OTelTracer` 同时写 OTel SDK 与 `TraceStore`（全局 provider 只能设一次，初始化复用已有 TracerProvider）<br>• `DecisionTraceStore` 只记可观察证据（观察/决策/执行/验证/结论/治理摘要），不采集模型思维链<br>• `TrajectoryStore` 双源：SQLite 可查询 + JSONL 可审计回放<br>• `exit_status` 归因写入 session 与 trace<br>• SQLite event stream 支持多 API 实例轮询，未引入外部 broker | 只记可观察证据，不碰模型内部状态；双源轨迹兼顾运行时查询与离线审计；无 collector 时仍可查 |
| **V 验证与评估** | • 成功 write/edit 触发 `VerificationLayer`，按 YAML 串行执行 lint/type/test，首个失败即停止并保留末尾 4000 字<br>• 报告持久化 `agent_claim` 与 `checks` 两类独立字段，实现"Agent 自述"与"服务级验证"分离<br>• 失败用例经去重签名沉淀为 `RegressionCase`，`RegressionRunner` 批量执行输出 `gate_passed`/`pass_rate` 门禁<br>• `SelfReview` 默认确定性规则避免 mock 误触外部 LLM<br>• `Reviewer` 仍支持 LLM 多候选选优 + 启发式 fallback | 从"声称完成"升级为"有证据完成"；Agent 自述与服务级验证分离互不背书；失败即资产，沉淀为回归 |
| **G 治理与安全** | • `Permission` 40+ 权限点 + READ/WRITE/EXECUTE/ADMIN/CRITICAL 五级，内置 viewer/operator/developer/maintainer/admin/worker 角色<br>• `PolicyEngine` 按 RBAC 先行 → YAML 规则匹配 → 风险阈值审批统一决策，规则 DSL 为受控声明式子集（未引入 OPA/CEL）<br>• `WriteApproval` 请求哈希防篡改 + pending 复用 + 批准后一次性消费恢复原始请求<br>• `BudgetManager` 四维预算（Token/时间/工具次数/资源）实时记账，超限产生 `BUDGET_EXCEEDED`<br>• `ContentSafetyGuard` 按字段语义扫描内联密钥减少误报，工具结果与最终回答统一脱敏<br>• `CredentialPool` priority/uses/last-used 轮换 + 失败冷却，Bitwarden/1Password 经 CLI resolver 接入、明文不落库 | 治理是工具链路的一环而非旁路；默认不信任，高风险需显式批准；规则用受控子集而非通用 DSL 以减少动态执行风险 |
| **S 状态存储** | • 状态外置：运行时状态全进 SQLite，文件系统仅用于 SKILL.md/MEMORY.md 等人类可读资产<br>• `SessionDB` 用 `check_same_thread=False` + `asyncio.to_thread` 允许跨线程，SQLite 操作 <1ms 不阻塞事件循环<br>• `tool_calls` 以 JSON 存 messages 表而非独立表（附属信息无需独立查询）<br>• FTS5 跨会话搜索在编译缺失时降级为普通表 + LIKE<br>• `CheckpointManager` 负责快照/恢复<br>• 单 SQLite 适合单机与轻量多实例，不面向跨地域 | 状态外置 + 零外部依赖；不用 JSON/JSONL 做运行时状态（仅用于审计导出）；结构化查询优先于文件扫描 |

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

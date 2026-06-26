# AgentConch 实现状态

> 记录当前项目的实现内容、验证状态与后续路线。
> **最后更新**：2026-06-26

---

## 一、实现总览

AgentConch 按 v0.3 技术方案完成了 **MVP 阶段一** 的核心实现：核心抽象层 + 9 域默认实现 + 运行时层 + 测试与 demo，全链路验证通过。

### 文件清单

```
conch/
├── __main__.py                          # CLI 入口（run / experiment / plugins）
├── core/                                # 核心抽象层（7 文件）
│   ├── extension.py                     # 9 域 ExtensionPoint 接口 + 依赖倒置
│   ├── registry.py                      # 注册中心（依赖拓扑加载 + 生命周期 + 发现 + 版本共存）
│   ├── hooks.py                         # Hook 总线（14 挂载点 + 三大约束）
│   ├── middleware.py                    # 中间件链（Pipeline 数据流）
│   ├── profile.py                       # Profile 引擎（extends + Pydantic + 双模式）
│   ├── loop.py                          # Agent Loop（streaming + CostGuard + 空闲终止）
│   └── experiment.py                    # 实验框架（A/B 对比 + 消融 + SWE-bench 对接）
├── domains/                             # 9 域默认实现
│   ├── information/agents_md.py         # 域1：AGENTS.md 加载器
│   ├── tool/builtin_shell.py            # 域2：内置 shell 工具（read/write/bash/list）
│   ├── context/jit_compaction.py        # 域3：JIT + 40% 阈值 + 摘要压缩
│   ├── memory/notes_file.py             # 域4：结构化笔记（短期+情景）
│   ├── orchestration/single_loop.py     # 域5：单 Agent 循环编排
│   ├── eval/step_eval.py                # 域6：单步评测
│   ├── observability/console_tracer.py  # 域7：控制台轨迹（执行+成本指标）
│   ├── constraint/linter.py             # 域8：Linter 约束
│   └── governance/allowlist.py          # 域9：allowlist 权限 + 审计日志
└── runtime/                             # 运行时层
    ├── model/base.py                    # Provider 基类 + MockProvider
    ├── model/scripted.py                # ScriptedProvider（端到端测试用）
    ├── sandbox/docker_sandbox.py        # Docker 沙箱（加固基线 + 降级本地执行）
    └── store/memory_store.py            # 内存 KV 存储

profiles/
├── coding-agent-v1.yaml                 # MVP 完整 Profile（9 域配置）
└── coding-agent-v2-subagents.yaml       # extends 继承示例

benchmarks/swe-mini/
├── 001.json                             # 任务：修复语法错误
└── 002.json                             # 任务：添加单元测试

tests/
├── test_core.py                         # 11 个单元测试
└── demo_e2e.py                          # 端到端 demo

docs/
├── technical-design.md                  # 技术方案 v0.3
├── implementation-status.md             # 本文档
└── technical-points/                    # 13 篇技术点文档
    ├── 01-extension-point.md
    ├── 02-registry.md
    ├── 03-hook-and-middleware.md
    ├── 04-profile-and-experiment.md
    ├── 05-agent-loop.md
    ├── 06-context-management.md
    ├── 07-tool-system-mcp.md
    ├── 08-memory-five-types.md
    ├── 09-multi-agent-orchestration.md
    ├── 10-observability.md
    ├── 11-sandbox-security.md
    ├── 12-cost-guard.md
    ├── 13-skill-system.md
    └── README.md                        # 索引
```

---

## 二、核心抽象层实现详情

### 2.1 扩展点契约（`extension.py`）

- 定义 `ExtensionPoint` Protocol（runtime_checkable）+ `Plugin` 基类（可选生命周期钩子）
- 9 域各定义独立 Protocol：`InformationProvider` / `ToolProvider` / `ContextManager` / `MemoryProvider` / `OrchestrationMode` / `Evaluator` / `ObservabilityProvider` / `ConstraintProvider` / `GovernanceProvider`
- `DOMAINS` 列表常量：核心层知道有哪些域，不知道实现
- **依赖倒置**：核心层不 import 任何 `conch/domains/` 模块

### 2.2 注册中心（`registry.py`）

| 能力 | 实现 |
|---|---|
| 装饰器注册 | `@registry.register(domain, name, version, depends_on)` |
| 依赖拓扑加载 | `_load_with_deps()` 递归拓扑排序，检测循环依赖 |
| 生命周期钩子 | `on_load` / `on_unload`（异常回滚+告警）/ `on_reload` |
| 运行时发现 | `query(domain, capability)` 按 metadata capabilities 过滤 |
| 版本共存 | `domain → name → {version: PluginEntry}`，`build(version="latest")` 取最高 |
| 构建实例 | `build(domain, name, version, **params)` 自动拓扑加载 + 实例化 + on_load |

### 2.3 Hook 总线（`hooks.py`）

- 14 个挂载点：`on_task_start` / `pre_step` / `post_step` / `pre_tool` / `post_tool` / `on_tool_error` / `pre_model_call` / `post_model_call` / `on_compaction` / `on_context_reset` / `on_eval` / `on_cost_exceeded` / `on_task_end` / `on_error`
- **三大约束**：
  - 职责隔离：Hook 只触发副作用，中间件只处理数据流
  - 优先级：`priority` 数值越小越先执行（默认 100）
  - 中断白名单：仅 `on_tool_error` / `pre_step` / `pre_tool` / `on_cost_exceeded` / `on_error` 可中断
- `@hook(point, priority)` 装饰器 + `HookBus.fire()` 触发
- `HookInterrupted` 异常传播中断信号

### 2.4 中间件链（`middleware.py`）

- `Middleware[T]` 基类：`process(data) -> data`
- `Pipeline[T]`：有序应用中间件，`add()` 链式追加，`run(data)` 执行
- 与 Hook 职责分离：Pipeline 变换数据流，Hook 控制流程

### 2.5 Profile 引擎（`profile.py`）

- **双模式设计**：有 pydantic+yaml 时完整校验 + 标准 YAML；无则纯 Python dataclass + 内置简易 YAML 解析器
- `extends` 继承：子 Profile 继承父配置，覆写差异项
- Pydantic 校验（可选）：域名合法性、参数类型、必填项
- 环境变量覆盖：`CONCH_MAX_TOKENS` / `CONCH_MODEL` / `CONCH_<DOMAIN>_<PARAM>`
- `_SimpleYAMLParser`：支持缩进嵌套、key:value、行内 dict/list、注释

### 2.6 Agent Loop（`loop.py`）

- `State`：task / status / steps / actions / context / total_tokens / total_cost / degrade_level / result / error
- `CostGuard`：4 级降级（L1 压缩 60% → L2 切模型 80% → L3 禁工具 90%延后 → L4 终止 100%）
- streaming 推理：`model.stream()` 异步生成器 + 工具调用增量检测
- 权限校验：每次工具执行前过 `governance.check_permission()`
- 空闲终止：连续 3 步无工具调用自动终止（避免空转）
- Hook 集成：每个关键节点触发 Hook，支持中断
- 依赖注入：Profile + Registry 构建各域插件，核心层不依赖实现

### 2.7 实验框架（`experiment.py`）

- `run_experiment()`：多 Profile × 任务集，输出 `ExperimentResult`
- `run_ablation()`：消融实验，逐个关闭能力域
- `TaskSuite`：支持本地目录 / `swe-mini` / `swe-bench-lite`
- `comparison_table()`：Markdown 对比表（成功率/步数/Token/成本/降级次数）
- 指标：success_rate / avg_steps / avg_tokens / avg_cost / context_resets / degrade_count

---

## 三、9 域默认实现详情

### 域1 · 信息边界（`agents_md`）

- 加载 AGENTS.md 文件作为系统指令
- `assemble(task, state)` 返回消息列表 `[system, user]`
- 支持预读缓存 / 热重载
- 额外指令片段追加

### 域2 · 工具系统（`builtin_shell`）

- 4 个内置工具：`read_file` / `write_file` / `run_bash` / `list_files`
- 统一工具描述：name / description / params_schema / permissions
- Docker 沙箱执行（无 Docker 降级本地执行）
- 命令超时控制（默认 30s）
- MCP 对齐的参数描述格式

### 域3 · 上下文管理（`jit_compaction`）

- `assemble()`：JIT 原则，已有上下文不重复加载
- `should_compact()`：token 利用率超 40% 阈值触发
- `compact()`：摘要压缩（保留首尾消息，中间合并为摘要）
- token 估算：4 字符 ≈ 1 token

### 域4 · 记忆状态（`notes_file`）

- 五分法中实现短期（short）+ 情景（episodic）
- `store(key, value, mem_type)` / `recall(query, mem_type, limit)`
- 情景记忆持久化到文件
- 简单文本搜索（阶段三替换为向量检索）

### 域5 · 执行编排（`single_loop`）

- 单 Agent 循环编排，包装 `AgentLoop.run()`
- `OrchestrationMode` 接口：`run()` 实现，`task_split` / `state_sync` / `conflict_resolve` 空实现（L3 预留）

### 域6 · 评估验证（`step_eval`）

- 单步评测：检查最后一个 action 的 result 是否有 error
- `should_eval(state)`：按间隔判断（默认每步）
- `eval(state)`：返回 `{pass, message, action_type, step}`

### 域7 · 可观测性（`console_tracer`）

- 控制台轨迹输出：每步打印 step/action/tool/token/cost
- `metrics()`：返回累计指标（total_steps / total_tokens / total_cost / tool_success_rate）
- 四级指标中实现执行类 + 成本类

### 域8 · 约束恢复（`linter`）

- `validate(action, state)`：检查 write_file 的内容是否有常见错误模式
- `recover(error, state)`：故障恢复（MVP 最小实现）

### 域9 · 治理（`allowlist_perms`）

- `check_permission(tool, args)`：tool 必须在 allowlist 中
- `audit(action, detail)`：审计日志，可选写文件
- 默认允许所有内置工具，可配置限制

---

## 四、运行时层实现详情

### LLM Provider（`model/base.py` + `model/scripted.py`）

- `Provider` ABC：`call()` 同步 + `stream()` 异步生成器
- `MockProvider`：返回固定响应，测试用
- `ScriptedProvider`：按预设脚本依次返回响应，端到端测试用

### Docker 沙箱（`sandbox/docker_sandbox.py`）

- 加固基线：`--cpus` / `--memory` / `--network=none` / `--privileged=false` / `--read-only` + tmpfs
- `run_command(command, cwd, timeout)`：沙箱内执行命令
- Docker 不可用时自动降级为本地执行（带告警）

### 内存存储（`store/memory_store.py`）

- 纯内存 dict：`put` / `get` / `delete` / `keys` / `search` / `clear`
- `search(query)`：简单文本匹配（阶段三替换为向量检索）

---

## 五、验证状态

### 单元测试（`tests/test_core.py`）

| 测试 | 验证内容 | 状态 |
|---|---|---|
| `test_extension_point` | 9 域 DOMAINS + Plugin 基类 | ✅ 通过 |
| `test_registry` | 装饰器注册 + list + query | ✅ 通过 |
| `test_hook_bus` | 优先级顺序执行 | ✅ 通过 |
| `test_pipeline` | 中间件链有序处理 | ✅ 通过 |
| `test_cost_guard` | 4 级降级阈值判断 | ✅ 通过 |
| `test_memory_store` | KV 存取 + 文本搜索 | ✅ 通过 |
| `test_mock_provider` | MockProvider call + usage | ✅ 通过 |
| `test_allowlist_permissions` | 权限校验 + 审计日志 | ✅ 通过 |
| `test_agents_md_loader` | AGENTS.md 加载 + assemble | ✅ 通过 |
| `test_builtin_shell_tools` | 4 个工具定义 | ✅ 通过 |
| `test_all_9_domains_registered` | 9 域全部注册 | ✅ 通过 |

**结果：11 passed, 0 failed**

### CLI 命令验证

| 命令 | 状态 | 说明 |
|---|---|---|
| `python -m conch plugins` | ✅ | 9 域 9 插件全部展示 |
| `python -m conch run --profile coding-agent-v1 --task ... --mock` | ✅ | Agent Loop 完整执行，轨迹输出正常 |
| `python -m conch experiment --suite swe-mini --profiles coding-agent-v1` | ✅ | 3 任务 × 1 Profile，输出 Markdown 对比表 |

### 端到端 Demo（`tests/demo_e2e.py`）

使用 `ScriptedProvider` 模拟完整 Agent 行为序列：

```
Step 1: tool=read_file  → 读取 "print('hello world'\n"（有语法错误）
Step 2: text            → "Found syntax error: missing closing parenthesis"
Step 3: tool=write_file → 写入修复后的内容（21 bytes）
Step 4: text            → "Fixed! The syntax error has been resolved."
Step 5-6: [done]        → 连续无工具调用，自动终止
VERIFY: File correctly fixed!
```

**全链路验证通过**：Profile 加载 → AgentLoop → 推理(工具决策) → 权限校验 → 工具执行 → 轨迹输出 → 评测 → 成本守卫 → 空闲终止

---

## 六、技术点文档

13 篇技术点文档位于 `docs/technical-points/`，每篇覆盖一个核心技术点：

| # | 技术点 | 对应代码 |
|---|---|---|
| 01 | 扩展点契约 | `conch/core/extension.py` |
| 02 | 注册中心 | `conch/core/registry.py` |
| 03 | Hook 与中间件 | `conch/core/hooks.py` + `middleware.py` |
| 04 | Profile 与实验框架 | `conch/core/profile.py` + `experiment.py` |
| 05 | Agent Loop 引擎 | `conch/core/loop.py` |
| 06 | 上下文管理 | `conch/domains/context/` |
| 07 | 工具系统与 MCP | `conch/domains/tool/` |
| 08 | 记忆五分法 | `conch/domains/memory/` |
| 09 | 多 Agent 协作 | `conch/domains/orchestration/` |
| 10 | 可观测性与自观测 | `conch/domains/observability/` |
| 11 | 沙箱与安全治理 | `conch/runtime/sandbox/` + `conch/domains/governance/` |
| 12 | 成本守卫与分级降级 | `conch/core/loop.py` (CostGuard) |
| 13 | Skill 系统 | `conch/domains/information/` |

---

## 七、后续路线

按技术方案 v0.3 的开发路线图，当前完成阶段一 MVP，后续计划：

### 阶段 1.5：约束与上下文（下一步）

- [ ] 域8：Linter 增强 + 修复指令 + 沙箱强化 + 权限分级
- [ ] 域3：Compaction 增强 + Context Reset 实现
- [ ] 域9（部分）：审计日志完善（不可篡改延后）
- [ ] streaming 输出实测（接入真实 LLM Provider）

### 阶段二：反馈回路（Level 2）

- [ ] 域6：三层评测框架（单步 + 回合 + 多轮）+ 可重置环境
- [ ] 域7：OpenTelemetry 集成 + 成本指标导出
- [ ] 域4：记忆五分法补齐（语义 + 长期 + 程序性）+ 向量库
- [ ] 实验框架：SWE-bench Lite 真实数据集接入 + 消融实验

### 阶段三：专业化 Agent（Level 3）

- [ ] 域5：多 Agent 协作模式（orchestrator_worker / fan_out / gan）
- [ ] 域2：MCP Server 直连 + 插件导出 MCP
- [ ] 域6：Evaluator Agent + Playwright 端到端验证
- [ ] 域1：Skill 系统（skill_loader 插件）

### 阶段四：治理与自治（Level 4，远期）

- [ ] 域9（完整）：RBAC + 策略引擎 + 人工监督
- [ ] 域8：垃圾回收 Agent + 自修复
- [ ] 域5：无人值守并行 + 断点续跑

---

## 八、已知限制

| 限制 | 说明 | 计划 |
|---|---|---|
| 无真实 LLM 接入 | MVP 用 MockProvider / ScriptedProvider | 阶段 1.5 接入 litellm |
| pydantic/yaml 可选 | 双模式设计，无依赖也能跑 | 安装后自动启用完整校验 |
| 记忆仅短期+情景 | 五分法中 3 种未实现 | 阶段二补齐 |
| 评测仅单步 | 回合/多轮评测未实现 | 阶段二 |
| 单 Agent only | 多 Agent 模式接口已预留，实现延后 | 阶段三 |
| 沙箱降级本地 | 无 Docker 时本地执行（带告警） | 生产环境需 Docker |
| 可观测性仅 console | OpenTelemetry 未集成 | 阶段二 |

# T 层 — 工具接口层实现策略沉淀

> 层级：T (Tool Interface)  
> 阶段：P1 Workflow Agent

---

## 一、设计目标回顾

### 1.1 本层定位

T 层是 Agent 与外部世界交互的统一接口层。所有外部能力（文件操作、命令执行、Web 访问、用户交互等）都封装为工具，通过 ToolRegistry 统一注册、管理和执行。T 层遵循"少量核心工具 + 渐进发现 + 策略管控"的设计原则。

### 1.2 P1 计划能力

- 12 核心工具（bash/read/write/edit/glob/grep/web_search/web_fetch/skill/ask_user/task_manage/tool_search）
- ToolRegistry + check_fn TTL 缓存 + 瞬态故障抑制
- ToolPolicy（Allow/Deny + Sandbox Policy）
- ToolSearch 渐进发现 + 自动阈值
- FootprintLadder 六级扩展阶梯

### 1.3 核心约束

- 最小工具原则：核心保持窄腰，能力通过 Skill/Plugin/MCP 扩展
- Pydantic input_model 参数 Schema 校验 + JSON Schema 自动生成
- 并行工具执行（asyncio.gather）

---

## 二、核心实现方案

### 2.1 整体结构

```
tools/
├── base.py           # BaseTool ABC + ToolResult + ToolCall + ToolExecutionRecord
├── registry.py       # ToolRegistry + ToolHealthState (check_fn TTL + 瞬态抑制)
├── tool_policy.py    # ToolPolicy + PolicyRule + PolicyContext
├── tool_search.py    # ToolSearch 渐进发现
├── footprint.py      # FootprintLadder 六级阶梯
└── core/             # 12 核心工具
    ├── bash.py
    ├── read_file.py
    ├── write_file.py
    ├── edit_file.py
    ├── glob.py
    ├── grep.py
    ├── web_search.py
    ├── web_fetch.py
    ├── skill.py
    ├── ask_user.py
    ├── task_manage.py
    └── tool_search.py
```

### 2.2 核心类/接口

**BaseTool (ABC)**：工具基类
- 属性：name, description, input_model (Pydantic), is_write_tool, is_dangerous, is_core, tags
- 方法：execute(**kwargs) → ToolResult, check_available() → (bool, str|None), to_schema() → dict
- check_fn 支持：set_check_fn(fn) 设置可用性检查函数
- validate_input(**kwargs)：通过 Pydantic 校验并过滤参数

**ToolRegistry**：工具注册表
- register/unregister/get/list_names
- check_tool_available(name)：TTL 缓存(30s) + 瞬态故障抑制(60s)
- get_available_schemas(include_core_only)：过滤被抑制的工具 + check_fn 不可用工具
- execute_tool_call(call, sender, sandbox_mode, is_main_session)：策略检查 → 参数校验 → 执行 → 记录健康状态
- record_failure/record_success：故障计数管理

**ToolPolicy**：三层策略引擎
- Allow/Deny 显式列表（优先级最高）
- 规则评估（PolicyRule 条件匹配）
- 默认 ALLOW
- 5 种操作类型：read/write/exec/network/deploy
- 3 种决策：ALLOW/DENY/REQUIRE_APPROVAL

**ToolSearch**：渐进式工具发现
- 核心工具始终暴露，非核心工具通过搜索发现
- should_enable_search()：基于非核心工具 schema token 估算 vs context window 阈值
- search(query)：关键词匹配 name/description/tags

**FootprintLadder**：扩展阶梯评估
- 6 级：EXTEND_EXISTING → CLI_WITH_SKILL → SERVICE_GATED → PLUGIN → MCP_SERVER → NEW_CORE
- evaluate(capability, existing_tools)：根据能力描述建议扩展级别

### 2.3 工具执行流程

```
LLM 返回 tool_calls
  → ToolCall.from_llm(raw) 解析
  → ToolRegistry.execute_tool_call(call)
    → 查找工具 (not found → error record)
    → validate_input (Pydantic 校验 → error on invalid)
    → ToolPolicy.evaluate (DENY → blocked record)
    → tool.execute(**validated)
    → record_success/record_failure (更新健康状态)
    → ToolExecutionRecord (含 result/duration/status)
```

### 2.4 并行工具执行

```
AgentLoop._execute_tools_parallel(tool_calls)
  → 分离读操作 vs 写操作
  → 读操作: asyncio.gather(*[execute(tc)], return_exceptions=True)
  → 写操作: 串行执行 (避免竞争)
  → 按原始 tool_call_id 排序结果
```

---

## 三、设计落地对照

### ✅ 完全对齐设计

- 12 核心工具全部实现
- BaseTool + Pydantic input_model + JSON Schema 自动生成
- ToolRegistry + check_fn TTL(30s) + 瞬态故障抑制(60s)
- ToolPolicy 三层策略 (Allow/Deny + Sender + Sandbox)
- ToolSearch 渐进发现 + 自动阈值(10%)
- FootprintLadder 六级阶梯
- 并行工具执行（读并行 + 写串行）

### ⚠️ 调整项

| 能力项 | 设计方案 | 实际实现 | 调整原因 |
| ------ | -------- | -------- | -------- |
| MCP 客户端 | tools/mcp_client.py | 占位（__init__.py） | MCP 协议接入为 P2 交付物 |
| SkillTool | Schema-based selective injection | 简化版：全文加载 SKILL.md | P1 不含 SkillRegistry，P2 完整实现 |
| 工具输出管理 | 截断 + offload 到临时文件 | 仅截断（read_file 50k chars） | offload 机制 P2 补充 |
| REQUIRE_APPROVAL | 触发 HITL 审批 | P1 暂时放行 | WriteApproval 为 P4 交付物 |

---

## 四、关键技术点与踩坑记录

### 4.1 Pydantic input_model 校验与过滤

**设计**：每个工具有 `input_model: type[BaseModel]`，`validate_input(**kwargs)` 通过 Pydantic 校验。

**实现要点**：`validate_input` 先过滤掉 input_model 不接受的字段（`model_fields`），再实例化 Pydantic 模型。这防止 LLM 传入多余参数导致校验失败。

### 4.2 check_fn TTL 缓存设计

**问题**：每次暴露工具给 LLM 前都调用 check_fn 会很慢（可能涉及网络检查）。

**解决方案**：
- ToolHealthState 缓存 last_check_time + last_check_available
- TTL 内直接返回缓存结果（默认 30s）
- 瞬态故障抑制：连续失败 ≥ 2 次 → suppressed_until = now + 60s

### 4.3 并行工具执行的安全边界

**设计决策**：只对互不依赖的读操作并行；写操作和危险操作串行。

**实现**：通过 `tool.is_write_tool` 属性分离。写操作串行避免文件竞争。

### 4.4 ToolPolicy 条件匹配

**实现**：简化条件解析器，支持 `==`, `!=`, `and` 关键字。条件变量：action, sender, sandbox_mode, is_main_session, tool_name。未来可扩展为完整 DSL。

---

## 五、验证与覆盖情况

### 5.1 测试覆盖

| 测试类 | 测试数 | 覆盖场景 |
| ------ | ------ | -------- |
| TestReadFileTool | 3 | 正常读取/不存在/limit |
| TestWriteFileTool | 2 | 新建/覆盖 |
| TestEditFileTool | 5 | 替换/不存在/相同字符串/多匹配/replace_all |
| TestGlobTool | 2 | 匹配/无匹配 |
| TestGrepTool | 4 | 正则/include/case_insensitive/无匹配 |
| TestBashTool | 3 | echo/exit_code/pytest |
| TestToolRegistry | 8 | 注册/注销/执行/not_found/failure/抑制/TTL/schemas |
| TestToolPolicy | 7 | 默认允许/deny/allow bypass/subagent deploy/write approval/never sandbox/自定义规则 |
| TestToolSearch | 5 | 按name/description搜索/排除core/无匹配/阈值 |
| TestFootprintLadder | 3 | extend/cli/describe |

### 5.2 集成测试覆盖

- 并行工具执行：同时 read_file 两个文件 ✅
- 沙箱隔离：read_file("/etc/passwd") 被拦截 ✅

### 5.3 未覆盖场景

- MCP 工具接入
- Plugin 工具隔离运行
- check_fn 实际网络检查（P1 仅测试 mock check_fn）
- 工具输出 offload 到临时文件

---

## 六、演进与优化方向

### P2 演进
- 实现 MCP 客户端（tools/mcp_client.py）
- SkillRegistry + Schema-based selective injection
- 工具输出 offload 机制
- Subagent 委托执行（DELEGATE_BLOCKED_TOOLS）

### P3 演进
- service-gated tool 条件加载
- Plugin tool 隔离运行

### 长期演进
- ToolSearch 语义搜索（基于 embedding 而非关键词）
- 工具自动测试生成
- 工具版本管理与兼容性检查

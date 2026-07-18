# T 工具接口层实现策略沉淀（P3 增量）

## 一、设计目标回顾

T 层负责统一工具协议和渐进发现。P3 新增 `session_search`，并把写工具执行结果作为自动验证触发源。

## 二、核心实现方案

`SessionSearchTool(BaseTool)` 使用 Pydantic 输入模型调用 `MetaMemory.search`，注册为非核心工具，由 ToolSearch 渐进发现。AgentLoop 将 `ToolExecutionRecord` 交给 LayerManager。路径：`tools/core/session_search.py`、`tools/registry.py`、`engine/agent_loop.py`。

## 三、设计落地对照

- ✅ `session_search` 使用统一 BaseTool/ToolResult 协议。
- ✅ `write_file`、`edit_file` 成功后触发 VerificationLayer。
- ⚠️ 工具名位于 `core/` 目录但 `is_core=False`，目的是保留渐进发现，不增加默认 schema 成本。

## 四、关键技术点与踩坑记录

专项测试最初以位置字典调用工具，与 BaseTool 的 `**kwargs` 契约不一致；测试已修正，接口未做兼容性污染。写工具保持串行，读工具继续并行。

## 五、验证与覆盖情况

覆盖搜索输入、FTS 结果、写成功触发门禁、写失败不误报；全量工具回归通过。未覆盖大规模 FTS 排名质量。

## 六、演进与优化方向

P4 让 ToolPolicy 在调用前统一执行 RBAC、审批和资源策略；外部工具协议扩展必须继续通过 Registry 隔离。

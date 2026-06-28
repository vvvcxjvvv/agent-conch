# 03 — Profile 引擎 + 实验框架

> **代码位置**：`backend/conch/core/profile.py`（340 行）、`backend/conch/core/experiment.py`（226 行）
> **设计原则**：配置即实验——一组 Plugin + 参数 = 一个 Profile，切换配置即切换实验。

## 1. Profile 引擎

### 数据模型

```python
@dataclass
class DomainConfig:
    impl: str = ""          # 实现名（如 "langgraph_react"）
    params: dict = {}       # 构造参数
    version: str = "latest" # 版本

@dataclass
class Profile:
    name: str
    description: str
    extends: str | None     # 继承链
    domains: dict[str, DomainConfig]
    hooks: list[HookConfig]
    max_steps: int = 50
    max_tokens: int | None
    model: str = "openai/gpt-4o-mini"
    model_fallback: str | None
```

### YAML 声明式配置

```yaml
# backend/profiles/user-chat-v1.yaml
name: user-chat-v1
model: "openai/gpt-4o-mini"
max_steps: 25
max_tokens: 100000
domains:
  orchestration:
    impl: langgraph_react
    params: { model: "openai/gpt-4o-mini", recursion_limit: 25 }
  tool:
    impl: mcp_provider
    params:
      servers:
        - command: "npx"
          args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
  guardrail:
    impl: nemo_guardrails
    params: { use_nemo: false }
```

### extends 继承

```yaml
# 仅换模型，其余继承
name: user-chat-v2-cheap
extends: user-chat-v1
model: "openai/gpt-4o-mini"
domains:
  guardrail: { impl: llamaguard_only, params: {} }
```

继承逻辑在 `ProfileLoader._merge()` 中：子 domains 覆盖父 domains，hooks 合并，model/max_steps 以子为准（非默认值时）。

### ProfileLoader 加载流程

```python
loader = ProfileLoader("profiles")
profile = loader.load("user-chat-v1")
# 1. 读 YAML → _parse_yaml() → dict
# 2. _build_profile(dict) → Profile 对象
# 3. 解析 extends 链 → _merge(parent, child)
# 4. apply_env_overrides() → CONCH_MAX_TOKENS 等环境变量覆盖
# 5. 缓存 → self._cache[name]
```

### 环境变量覆盖

```python
# 支持覆盖的变量
CONCH_MAX_TOKENS=50000
CONCH_MAX_STEPS=10
CONCH_MODEL=openai/deepseek-chat
CONCH_ORCHESTRATION_RECURSION_LIMIT=15
```

### 域名校验

`profile.validate_domains()` 检查所有域名在 `DOMAINS` 列表中（含 `guardrail`），非法域名抛 `ValueError`。

## 2. 实验框架（experiment.py）

### 核心类

```python
@dataclass
class TaskResult:
    task_id, profile_name, success, steps,
    total_tokens, total_cost, duration_sec, degrade_level

@dataclass
class ExperimentResult:
    task_suite: str
    results: list[TaskResult]

    def summary_by_profile() → dict   # 按 Profile 聚合统计
    def comparison_table() → str      # Markdown 对比表
```

### 任务集

```python
TaskSuite.from_dir(path)      # 从 .json 目录加载
TaskSuite.swe_mini()          # 自建精简集（3 任务）
TaskSuite.swe_bench_lite()    # SWE-bench Lite（阶段三）
```

### 实验运行

```python
result = await run_experiment(
    task_suite="swe-mini",
    profiles=["user-chat-v1", "user-chat-v2-cheap"],
    profiles_dir="profiles",
)
print(result.comparison_table())
```

输出 Markdown 对比表（成功率/平均步数/平均Token/平均成本/降级次数）。

### 消融实验

```python
result = await run_ablation(
    task_suite="swe-mini",
    base_profile="user-chat-v1",
    domains_to_ablate=["context", "guardrail"],
)
# 逐个关闭域，量化边际贡献
```

## 3. 加载使用方式

```
API 层调用链:
  GET /api/profiles/{name}
    └─ ProfileLoader.load(name)
         └─ 读 YAML → 解析 extends → 环境变量覆盖 → 返回 Profile

  POST /api/chat/sessions/{id}/stream
    └─ build_runtime(profile)
         └─ 遍历 profile.domains
              └─ registry.build(domain, impl, version, **params)
                   └─ 实例化 Plugin → AgentRuntime 容器
```

### 新增 Profile 只需一个 YAML 文件

```bash
# 复制模板
cp user-chat-v1.yaml user-chat-v3-aggressive.yaml
# 编辑：改 model / max_steps / 换工具 / 加护栏
# 切换 Profile 零代码改动
```

## 4. 可扩展点

- 新 Profile → 写 YAML 文件
- 新校验规则 → 扩展 `Profile.validate_domains()` 
- 新数据集基准 → `TaskSuite` 加静态方法
- 新指标 → `ExperimentResult.summary_by_profile()` 加统计字段

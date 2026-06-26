# 13 · Skill 系统

> Skill 本质是比"指令"和"工具"高一层的东西——把"触发条件 + 指令片段 + 可选工具绑定 + 可选参考资源"打包成可复用单元。

## 定位

Skill 横跨域1（指令）/域2（工具）/域5（编排），但核心职责是"按需注入指令"，故作为**域1的插件**实现，对核心零侵入。

```
AGENTS.md（常驻目录，~100行）
    │ 告诉 Agent 有哪些技能可调用
    │
    ▼
Skill 匹配（按任务/关键词）
    │
    ▼
注入指令片段 + 绑定工具 + references 按需加载
```

## 分层原则

| 层 | 角色 | 加载时机 |
|---|---|---|
| **AGENTS.md** | 常驻目录（~100 行） | Agent 启动时加载 |
| **Skill** | 按需技能包 | 任务匹配时注入 |

二者职责分离、互不污染上下文。这与 Anthropic 渐进式披露、OpenAI 地图式文档理念一致。

## SkillLoader 实现

```python
@registry.register("information", "skill_loader", "1.0")
class SkillLoader:
    """域1插件：按任务匹配并加载 SKILL.md 技能包"""
    metadata = {"cost": "low", "trigger": "keyword/task_match"}

    def __init__(self, skill_dir: str):
        self.skills = self._index_skills(skill_dir)

    def assemble(self, task, state) -> "Context":
        matched = self._match(task, state)
        for skill in matched:
            state.inject(skill.instructions)    # 注入指令片段
            state.bind_tools(skill.tools)       # 绑定 skill 声明的工具
            # references/ 资源按 JIT 原则不预加载，Agent 自行检索
        return state.context
```

## 兼容 SKILL.md 规范

skill_loader 直接索引符合标准 SKILL.md 结构的技能包：

```
skills/
└── code-review/
    ├── SKILL.md           # 含触发词、Iron Rules、Anti-Patterns
    ├── references/        # 参考资源（JIT 加载）
    └── examples/          # 示例
```

因此 agent-conch 既能**加载外部 skill**，也可**产出 skill**反哺通用技能仓库——dogfooding 闭环。

## SKILL.md 结构

```markdown
---
name: code-review
triggers: [代码审查, review, code review]
tools: [read_file, run_bash]
---

# Code Review Skill

## Iron Rules
1. 必须运行测试后再审查
2. 关注安全漏洞优先于风格问题

## Workflow
1. 读取变更文件
2. 运行测试
3. 逐文件审查
...
```

## 触发匹配

```python
def _match(self, task, state) -> list[Skill]:
    """基于任务描述和关键词匹配 skill"""
    matched = []
    task_lower = str(task).lower()
    for skill in self.skills.values():
        for trigger in skill.triggers:
            if trigger.lower() in task_lower:
                matched.append(skill)
                break
    return matched
```

## 与 AGENTS.md 的协作

AGENTS.md 中声明可用技能：

```markdown
## 可用技能
- code-review: 代码审查（触发词：代码审查/review）
- deploy: 部署流程（触发词：部署/deploy）
- test-gen: 测试生成（触发词：测试/test）
```

Agent 看到任务后，SkillLoader 自动匹配并注入对应技能的指令。

## 相关文件

- `conch/domains/information/skill_loader.py`（待实现）
- `docs/technical-points/01-extension-point.md` — 域1 接口
- `AGENTS.md` — 项目自身的指令文件

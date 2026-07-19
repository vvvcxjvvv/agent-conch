# C 上下文与记忆层实现策略沉淀（P4 增量）

## 一、设计目标回顾

C 层在 P4 的新增目标是 Curator 自改进：对 agent-created Skill 自动提出归档、改进和 consolidation，同时保证 pinned Skill 与人工内容不被自动覆盖，所有写入受 WriteApproval 保护。

## 二、核心实现方案

SkillCurator 从 SkillLoader 结果中筛选 `agent_created && !pinned`：deprecated 生成 archive；描述或正文为空生成 improve；相同 tags 的多个 Skill 生成 consolidate。提案以内容指纹去重并持久化；apply 只有在审批消费后执行。

- `src/agent_conch/context/skills/curator.py`
- `src/agent_conch/context/skills/registry.py`
- `src/agent_conch/api/server.py`

## 三、设计落地对照

- ✅ archive/improve/consolidation 三类动作齐全。
- ✅ 分析与应用分离，写入必须审批。
- ✅ pinned 与非 agent-created Skill 不进入自动提案。
- ⚠️ improve 使用确定性模板，不调用 LLM；增强了可复现性，语义优化深度有限。

## 四、关键技术点与踩坑记录

直接自动修改 Skill 会破坏可追溯性，因此采用 proposal 状态机。合并先创建新的 consolidated Skill，再把来源目录移动到 archive；目标冲突时使用内容摘要和随机后缀避免覆盖。

## 五、验证与覆盖情况

专项测试验证未审批拒绝、批准后 archive、源目录移除和归档目录存在。三类提案路径有实现证据；真实复杂 Skill 的语义质量未纳入自动指标。

## 六、演进与优化方向

增加 LLM proposal generator、静态校验与回归门禁后再允许 apply；补 improve/consolidate 的更多文件系统异常和回滚测试。

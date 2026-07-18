# C 上下文与记忆层实现策略沉淀（P3 增量）

## 一、设计目标回顾

C 层延续 P2 四层记忆，P3 目标是让历史会话可被 Agent 和 API 检索，同时避免重复索引。

## 二、核心实现方案

完成 run 后，AgentLoop 将最终回答和 turn_count 写入 `MetaMemory.session_search`；`index_session` 先按 session_id 删除旧记录，再写新摘要。查询由 FTS5 MATCH 执行，异常时降级 LIKE。路径：`context/memory/manager.py`、`tools/core/session_search.py`、`api/server.py`。

## 三、设计落地对照

- ✅ FTS5 跨会话搜索和 session_search 工具已接线。
- ✅ 同一 session 重跑不会无限产生重复索引。
- ⚠️ 索引内容是最终回答，不是独立 LLM 会话摘要；减少额外调用，但召回质量受回答完整度影响。

## 四、关键技术点与踩坑记录

FTS5 虚表不能使用普通 UPSERT，采用 delete+insert 实现幂等；SQLite 未编译 FTS5 时保留可用性优先的 LIKE 降级。

## 五、验证与覆盖情况

专项测试验证索引与搜索；P2 的压缩、记忆提取、持久化测试全部回归通过。未进行百万级索引性能测试和中文分词质量评估。

## 六、演进与优化方向

引入可配置摘要器与向量/混合检索；将索引更新转为后台任务，并记录摘要版本与来源证据。

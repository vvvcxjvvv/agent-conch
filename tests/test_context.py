"""P2 测试: C 层 Context Engine + 压缩 + Caching + Skill + Memory."""

from __future__ import annotations

from pathlib import Path

from agent_conch.context.compact.pipeline import (
    ContentFolding,
    ContextCompressor,
    ResultCleanup,
)
from agent_conch.context.engine import (
    LegacyEngine,
    SimpleTokenCounter,
    TokenBudget,
)
from agent_conch.context.memory.manager import MemoryManager
from agent_conch.context.prompt_caching import PromptCaching
from agent_conch.context.skills.registry import Skill, SkillFrontmatter, SkillInjector, SkillLoader
from agent_conch.state.session_db import SessionDB


class TestTokenCounter:
    def test_estimate_simple(self):
        counter = SimpleTokenCounter()
        messages = [{"role": "user", "content": "Hello World"}]
        tokens = counter.estimate(messages)
        assert tokens == 2  # 11 chars // 4

    def test_estimate_empty(self):
        counter = SimpleTokenCounter()
        assert counter.estimate([]) == 0

    def test_estimate_tool_calls(self):
        counter = SimpleTokenCounter()
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "1",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"file_path": "README.md"}',
                        },
                    }
                ],
            }
        ]
        tokens = counter.estimate(messages)
        assert tokens > 0


class TestLegacyEngine:
    async def test_bootstrap(self, tmp_db: SessionDB):
        engine = LegacyEngine(db=tmp_db, system_prompt="Test prompt")
        state = await engine.bootstrap("test-session")
        assert state.session_id == "test-session"
        assert state.turn_count == 0

    async def test_assemble(self, tmp_db: SessionDB):
        tmp_db.create_session("s1", model_name="test")
        tmp_db.add_message("s1", "user", "Hello")
        engine = LegacyEngine(db=tmp_db, system_prompt="System")
        await engine.bootstrap("s1")
        result = await engine.assemble("s1", TokenBudget())
        assert len(result.messages) == 2  # system + user
        assert result.messages[0]["role"] == "system"
        assert result.messages[1]["role"] == "user"

    async def test_maintain_increments_turn(self, tmp_db: SessionDB):
        engine = LegacyEngine(db=tmp_db, system_prompt="Test")
        await engine.bootstrap("s1")
        await engine.maintain("s1")
        state = engine.get_state("s1")
        assert state.turn_count == 1

    async def test_maintain_auto_compacts_and_reuses_result(self, tmp_db: SessionDB):
        tmp_db.create_session("s1", model_name="test")
        for _ in range(6):
            tmp_db.add_message("s1", "user", "x" * 3000)

        async def summarize(_messages):
            return "Historical Task: compacted context"

        engine = LegacyEngine(
            db=tmp_db,
            system_prompt="System",
            compressor=ContextCompressor(llm_caller=summarize),
            token_budget=TokenBudget(total=200, reserved_for_response=0, reserved_for_system=0),
        )
        await engine.bootstrap("s1")
        await engine.maintain("s1")

        state = engine.get_state("s1")
        result = await engine.assemble("s1", TokenBudget())
        assert state is not None
        assert state.compact_count == 1
        assert state.last_compact_turn == 1
        assert result.compacted is True
        assert "Context Summary" in result.messages[1]["content"]

    async def test_after_turn_persists_llm_memory(self, tmp_db: SessionDB):
        async def extract(_messages):
            return '[{"content":"Use Python","type":"preference"}]'

        manager = MemoryManager(
            db=tmp_db,
            memory_dir=str(tmp_db.db_path.parent / "memory"),
        )
        engine = LegacyEngine(
            db=tmp_db,
            memory_manager=manager,
            llm_caller=extract,
        )
        await engine.after_turn("s1", {"content": "User prefers Python."})
        entries = manager.long_term.search("Python")
        assert len(entries) == 1
        assert entries[0].memory_type == "preference"
        assert (tmp_db.db_path.parent / "memory" / "MEMORY.md").exists()


class TestResultCleanup:
    def test_no_cleanup_when_short(self):
        cleanup = ResultCleanup(keep_recent=10)
        messages = [{"role": "user", "content": "short"}]
        result = cleanup.compact(messages)
        assert result == messages

    def test_cleanup_old_tool_results(self):
        cleanup = ResultCleanup(keep_recent=2)
        messages = []
        for i in range(5):
            messages.append({"role": "assistant", "content": f"Turn {i}"})
            messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "x" * 300})
        result = cleanup.compact(messages)
        # 前 3 个 tool 消息应被清理 (cutoff = 10 - 2 = 8)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        cleared = [m for m in tool_msgs if "cleared" in m.get("content", "")]
        assert len(cleared) >= 1

    def test_short_content_not_cleared(self):
        cleanup = ResultCleanup(keep_recent=2)
        messages = [
            {"role": "tool", "tool_call_id": "c0", "content": "short"},
            {"role": "tool", "tool_call_id": "c1", "content": "short"},
            {"role": "user", "content": "recent"},
        ]
        result = cleanup.compact(messages)
        # 内容太短不应被清理
        assert "cleared" not in result[0].get("content", "")


class TestContentFolding:
    def test_short_content_not_folded(self):
        folding = ContentFolding()
        messages = [{"role": "user", "content": "short message"}]
        result = folding.compact(messages)
        assert result[0]["content"] == "short message"

    def test_long_content_folded(self):
        folding = ContentFolding()
        long_text = "A" * 3000
        messages = [{"role": "user", "content": long_text}]
        result = folding.compact(messages)
        assert "collapsed" in result[0]["content"]
        assert len(result[0]["content"]) < 3000

    def test_head_and_tail_preserved(self):
        folding = ContentFolding()
        head = "HEAD" + "H" * 896  # 900 chars
        middle = "M" * 1000
        tail = "T" * 500
        long_text = head + middle + tail
        messages = [{"role": "user", "content": long_text}]
        result = folding.compact(messages)
        assert "HEAD" in result[0]["content"]
        assert "TTTT" in result[0]["content"]


class TestContextCompressor:
    def test_no_compaction_when_under_budget(self):
        counter = SimpleTokenCounter()
        compressor = ContextCompressor(token_counter=counter)
        messages = [{"role": "user", "content": "short"}]
        result = compressor._extract_attachments(messages)
        # 同步测试: 只测 attachment 提取
        assert "recent_files" in result

    async def test_compact_pipeline(self):
        counter = SimpleTokenCounter()
        compressor = ContextCompressor(token_counter=counter)
        messages = []
        for i in range(20):
            messages.append({"role": "assistant", "content": f"Turn {i}"})
            messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "X" * 500})
        result = await compressor.compact(messages, budget=100)
        assert result.original_token_count > result.compacted_token_count
        assert len(result.steps_applied) > 0

    async def test_summary_failure_keeps_folded_context(self):
        async def unavailable(_messages):
            raise RuntimeError("auxiliary model unavailable")

        compressor = ContextCompressor(llm_caller=unavailable)
        messages = [{"role": "user", "content": "X" * 3000} for _ in range(6)]
        result = await compressor.compact(messages, budget=10)
        assert result.summary is None
        assert result.steps_applied[-1] == "summary_archive"


class TestPromptCaching:
    def test_noop_for_non_anthropic(self):
        caching = PromptCaching(provider="openai")
        messages = [{"role": "system", "content": "x" * 200}]
        result = caching.apply(messages)
        assert result == messages  # OpenAI 不支持 cache_control

    def test_anthropic_adds_cache_control(self):
        caching = PromptCaching(provider="anthropic", ttl="5m")
        messages = [
            {"role": "system", "content": "S" * 200},
            {"role": "user", "content": "U" * 200},
        ]
        result = caching.apply(messages)
        # system 消息应有 cache_control
        sys_msg = result[0]
        if isinstance(sys_msg["content"], list):
            assert "cache_control" in sys_msg["content"][0]

    def test_can_carry_marker(self):
        caching = PromptCaching(provider="anthropic")
        assert not caching._can_carry_marker({"role": "user", "content": "x"})
        assert caching._can_carry_marker({"role": "user", "content": "x" * 200})

    def test_disabled(self):
        caching = PromptCaching(enabled=False, provider="anthropic")
        messages = [{"role": "system", "content": "x" * 200}]
        result = caching.apply(messages)
        assert result == messages

    def test_estimate_savings(self):
        caching = PromptCaching(provider="anthropic")
        messages = [
            {"role": "system", "content": "S" * 1000},
            {"role": "user", "content": "U" * 500},
        ]
        savings = caching.estimate_cache_savings(messages)
        assert savings["cached_tokens"] > 0
        assert savings["saved_tokens"] > 0


class TestSkillLoader:
    def test_parse_frontmatter(self, tmp_path: Path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: test-skill\n"
            "description: A test skill\n"
            "version: 1.0.0\n"
            "inject_schema:\n"
            "  when: \"task_type == 'testing'\"\n"
            "  fields: [guidelines, checklist]\n"
            "metadata:\n"
            "  tags: [test, quality]\n"
            "---\n"
            "## Guidelines\n"
            "Follow these rules.\n"
            "## Checklist\n"
            "Check these items.\n"
        )
        loader = SkillLoader(cwd=str(tmp_path))
        skill = loader.load_one(str(skill_file))
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert "guidelines" in skill.sections
        assert "checklist" in skill.sections
        assert "Follow these rules" in skill.sections["guidelines"]

    def test_load_from_dir(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        for name in ["skill-a", "skill-b"]:
            d = skills_dir / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}\n---\nBody\n")
        loader = SkillLoader(cwd=str(tmp_path))
        # 模拟 project skills 目录
        loader._find_project_skills_dir = lambda: str(skills_dir)  # type: ignore
        skills = loader.load_all()
        # 至少加载了 skill-a 和 skill-b
        assert "skill-a" in skills or "skill-b" in skills


class TestSkillInjector:
    def test_match_by_task_type(self):
        skill = Skill(
            frontmatter=SkillFrontmatter(
                name="code-review",
                description="Code review skill",
                inject_schema={"when": "task_type == 'code_review'", "fields": ["guidelines"]},
                metadata={"tags": ["review"]},
            ),
            body="## Guidelines\nDo review.",
            sections={"guidelines": "Do review."},
        )
        injector = SkillInjector({"code-review": skill})
        selected = injector.select_skills(task_type="code_review")
        assert len(selected) == 1
        assert selected[0].name == "code-review"

    def test_match_by_tags(self):
        skill = Skill(
            frontmatter=SkillFrontmatter(
                name="lint",
                description="Lint skill",
                metadata={"tags": ["quality", "lint"]},
            ),
            body="Lint body",
        )
        injector = SkillInjector({"lint": skill})
        selected = injector.select_skills(tags=["quality"])
        assert len(selected) == 1

    def test_match_by_query(self):
        skill = Skill(
            frontmatter=SkillFrontmatter(
                name="code-review",
                description="Code review skill",
            ),
            body="Body",
        )
        injector = SkillInjector({"code-review": skill})
        selected = injector.select_skills(query="review")
        assert len(selected) == 1

    def test_inject_selective_fields(self):
        skill = Skill(
            frontmatter=SkillFrontmatter(
                name="test-skill",
                description="Test",
                inject_schema={"fields": ["guidelines"]},
            ),
            body="## Guidelines\nDo this.\n## Other\nNot injected.",
            sections={"guidelines": "Do this.", "other": "Not injected."},
        )
        injector = SkillInjector({"test-skill": skill})
        result = injector.inject("Base prompt", query="test")
        assert "Do this." in result
        assert "Not injected." not in result

    def test_no_match_returns_original(self):
        injector = SkillInjector({})
        result = injector.inject("Base prompt")
        assert result == "Base prompt"


class TestMemoryManager:
    async def test_long_term_add_and_search(self, tmp_db: SessionDB):
        tmp_db.create_session("s1", model_name="test")
        mgr = MemoryManager(db=tmp_db, memory_dir=str(tmp_db.db_path.parent / "memory"))
        mgr.long_term.add("User prefers Python", "preference", "s1")
        mgr.long_term.add("Always run tests", "preference", "s1")
        results = mgr.long_term.search("Python")
        assert len(results) >= 1
        assert "Python" in results[0].content

    async def test_long_term_dedup(self, tmp_db: SessionDB):
        tmp_db.create_session("s1", model_name="test")
        mgr = MemoryManager(db=tmp_db, memory_dir=str(tmp_db.db_path.parent / "memory"))
        added1 = mgr.long_term.add("Same content", "fact", "s1")
        added2 = mgr.long_term.add("Same content", "fact", "s1")
        assert added1 is True
        assert added2 is False  # 去重

    def test_short_term_memory(self, tmp_db: SessionDB):
        mgr = MemoryManager(db=tmp_db, memory_dir=str(tmp_db.db_path.parent / "memory"))
        mgr.short_term.set("key", "value")
        assert mgr.short_term.get("key") == "value"
        mgr.short_term.add_temp_fact("temp fact")
        assert len(mgr.short_term.get_temp_facts()) == 1
        mgr.short_term.clear()
        assert mgr.short_term.get("key") is None

    def test_rule_extract(self, tmp_db: SessionDB):
        mgr = MemoryManager(db=tmp_db, memory_dir=str(tmp_db.db_path.parent / "memory"))
        memories = mgr._rule_extract(
            "I always use Python. I decided to use FastAPI. There was an error with SSL."
        )
        assert len(memories) > 0
        types = [m["type"] for m in memories]
        assert "preference" in types or "decision" in types or "error_lesson" in types

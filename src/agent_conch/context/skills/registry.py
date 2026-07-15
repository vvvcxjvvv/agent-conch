"""C 层: Skill 体系 — SkillLoader + SkillInjector.

设计文档要求:
- SKILL.md + YAML frontmatter (agentskills.io 兼容标准)
- 多层级加载 (Bundled → User → Project → Plugin)
- Schema-based selective injection: 基于 inject_schema 选择性注入章节
- 不把 Skill 当工具, 而是上下文资产管理

frontmatter 格式:
    name: code-review
    description: Code review skill
    version: 1.0.0
    platforms: [macos, linux]
    prerequisites:
      env_vars: [GITHUB_TOKEN]
      commands: [git, rg]
    inject_schema:
      when: "task_type == 'code_review'"
      fields: [guidelines, checklist]
    metadata:
      tags: [review, quality]
      related_skills: [lint, test]
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SkillFrontmatter:
    """Skill frontmatter 元数据."""

    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    platforms: list[str] = field(default_factory=list)
    prerequisites: dict[str, list[str]] = field(default_factory=dict)
    inject_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # agent 创建标记 (Curator 使用)
    agent_created: bool = False
    # pin 标记 (Curator 不触碰)
    pinned: bool = False


@dataclass
class Skill:
    """Skill 实体."""

    frontmatter: SkillFrontmatter
    body: str  # SKILL.md 正文 (frontmatter 之后的内容)
    path: str = ""  # 文件路径
    sections: dict[str, str] = field(default_factory=dict)  # 按章节拆分的正文

    @property
    def name(self) -> str:
        return self.frontmatter.name

    @property
    def description(self) -> str:
        return self.frontmatter.description


class SkillLoader:
    """Skill 加载器 — 多层级加载.

    优先级从低到高:
    1. Bundled skills (skills/bundled/)
    2. User skills (~/.agent-conch/skills/)
    3. Project skills (从 cwd 向上遍历到 git root)
    4. Plugin skills
    """

    def __init__(self, cwd: str = "", bundled_dir: str = ""):
        self.cwd = cwd or os.getcwd()
        self.bundled_dir = bundled_dir

    def load_all(self) -> dict[str, Skill]:
        """加载所有层级的 skills.

        Returns:
            {skill_name: Skill} — 高优先级覆盖低优先级
        """
        skills: dict[str, Skill] = {}

        # Level 1: Bundled
        if self.bundled_dir and os.path.isdir(self.bundled_dir):
            self._load_from_dir(self.bundled_dir, skills)

        # Level 2: User skills
        user_dir = os.path.expanduser("~/.agent-conch/skills")
        if os.path.isdir(user_dir):
            self._load_from_dir(user_dir, skills)

        # Level 3: Project skills (从 cwd 向上遍历到 git root)
        project_dir = self._find_project_skills_dir()
        if project_dir:
            self._load_from_dir(project_dir, skills)

        return skills

    def load_one(self, skill_path: str) -> Skill | None:
        """加载单个 SKILL.md 文件."""
        path = Path(skill_path)
        if not path.exists() or not path.is_file():
            return None
        return self._parse_skill_file(path)

    def _load_from_dir(self, dir_path: str, skills: dict[str, Skill]) -> None:
        """从目录加载所有 SKILL.md."""
        base = Path(dir_path)
        for skill_file in base.rglob("SKILL.md"):
            skill = self._parse_skill_file(skill_file)
            if skill and skill.name:
                skills[skill.name] = skill  # 高优先级覆盖

    def _parse_skill_file(self, path: Path) -> Skill | None:
        """解析 SKILL.md 文件."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return None

        # 解析 frontmatter
        frontmatter, body = self._split_frontmatter(content)
        if not frontmatter or not frontmatter.name:
            return None

        # 按章节拆分正文
        sections = self._split_sections(body)

        return Skill(
            frontmatter=frontmatter,
            body=body,
            path=str(path),
            sections=sections,
        )

    def _split_frontmatter(self, content: str) -> tuple[SkillFrontmatter, str]:
        """分离 frontmatter 和正文."""
        if not content.startswith("---"):
            return SkillFrontmatter(), content

        # 找到第二个 ---
        parts = content[3:].split("---", 1)
        if len(parts) != 2:
            return SkillFrontmatter(), content

        yaml_text = parts[0].strip()
        body = parts[1].strip()

        try:
            data = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError:
            return SkillFrontmatter(), content

        fm = SkillFrontmatter(
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            platforms=data.get("platforms", []),
            prerequisites=data.get("prerequisites", {}),
            inject_schema=data.get("inject_schema", {}),
            metadata=data.get("metadata", {}),
            agent_created=data.get("agent_created", False),
            pinned=data.get("pinned", False),
        )
        return fm, body

    def _split_sections(self, body: str) -> dict[str, str]:
        """按 Markdown 标题拆分正文为章节."""
        sections: dict[str, str] = {}
        current_section = "_intro"
        current_lines: list[str] = []

        for line in body.splitlines():
            # 匹配 ## 标题 (不匹配 # 一级标题, 因为那通常是 skill 名)
            match = re.match(r"^##\s+(.+)$", line)
            if match:
                if current_lines:
                    sections[current_section] = "\n".join(current_lines).strip()
                current_section = match.group(1).strip().lower().replace(" ", "_")
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections[current_section] = "\n".join(current_lines).strip()

        return sections

    def _find_project_skills_dir(self) -> str | None:
        """从 cwd 向上遍历找到 project skills 目录."""
        current = Path(self.cwd).resolve()
        while True:
            skills_dir = current / "skills"
            if skills_dir.is_dir():
                return str(skills_dir)
            # 检查是否到达 git root
            if (current / ".git").exists():
                # git root 下的 skills
                git_skills = current / "skills"
                if git_skills.is_dir():
                    return str(git_skills)
                return None
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None


class SkillInjector:
    """Skill 注入器 — Schema-based selective injection.

    不再全文注入 SKILL.md, 而是根据:
    1. inject_schema.when 条件判断是否注入
    2. inject_schema.fields 选择性注入部分章节
    3. 基于 frontmatter 元数据做匹配
    """

    def __init__(self, skills: dict[str, Skill] | None = None):
        self.skills = skills or {}

    def update_skills(self, skills: dict[str, Skill]) -> None:
        self.skills = skills

    def select_skills(
        self,
        task_type: str = "",
        tags: list[str] | None = None,
        query: str = "",
    ) -> list[Skill]:
        """选择与当前任务匹配的 skills.

        匹配逻辑:
        1. inject_schema.when 条件匹配
        2. metadata.tags 匹配
        3. name/description 关键词匹配
        """
        selected: list[Skill] = []

        for skill in self.skills.values():
            if self._match_skill(skill, task_type, tags or [], query):
                selected.append(skill)

        return selected

    def _match_skill(
        self,
        skill: Skill,
        task_type: str,
        tags: list[str],
        query: str,
    ) -> bool:
        """判断 skill 是否匹配当前任务."""
        fm = skill.frontmatter

        # 1. inject_schema.when 条件匹配
        when_cond = fm.inject_schema.get("when", "")
        if when_cond:
            if self._evaluate_when(when_cond, task_type):
                return True

        # 2. tags 匹配
        skill_tags = fm.metadata.get("tags", [])
        if tags and skill_tags:
            if any(t in skill_tags for t in tags):
                return True

        # 3. 关键词匹配
        if query:
            searchable = f"{skill.name} {skill.description}".lower()
            if query.lower() in searchable:
                return True

        return False

    def _evaluate_when(self, condition: str, task_type: str) -> bool:
        """评估 inject_schema.when 条件.

        简化实现: 支持 task_type == 'xxx' 格式.
        """
        condition = condition.strip()
        if "==" in condition:
            var, val = condition.split("==", 1)
            var = var.strip()
            val = val.strip().strip("'\"")
            if var == "task_type":
                return task_type == val
        return False

    def inject(
        self,
        system_prompt: str,
        task_type: str = "",
        tags: list[str] | None = None,
        query: str = "",
        max_skills: int = 3,
    ) -> str:
        """将选中的 skill 内容注入 system prompt.

        Schema-based selective injection:
        - 只注入 inject_schema.fields 指定的章节
        - 如果没有指定 fields, 注入完整 body
        """
        selected = self.select_skills(task_type, tags, query)[:max_skills]
        if not selected:
            return system_prompt

        skill_sections: list[str] = []
        for skill in selected:
            fields = skill.frontmatter.inject_schema.get("fields", [])
            if fields:
                # 选择性注入指定章节
                parts: list[str] = []
                for field in fields:
                    section_key = field.strip().lower().replace(" ", "_")
                    content = skill.sections.get(section_key, "")
                    if content:
                        parts.append(f"### {field}\n{content}")
                if parts:
                    skill_sections.append(
                        f"## Skill: {skill.name}\n" + "\n\n".join(parts)
                    )
            else:
                # 注入完整 body (截断到 2000 chars)
                body = skill.body[:2000]
                if len(skill.body) > 2000:
                    body += "\n... [skill body truncated]"
                skill_sections.append(f"## Skill: {skill.name}\n{body}")

        if not skill_sections:
            return system_prompt

        injected = "\n\n--- Injected Skills ---\n" + "\n\n".join(skill_sections) + "\n--- End Skills ---"

        return system_prompt + injected

    def check_prerequisites(self, skill: Skill) -> tuple[bool, list[str]]:
        """检查 skill 的前置条件是否满足.

        Returns:
            (all_met, missing_items)
        """
        missing: list[str] = []
        prereqs = skill.frontmatter.prerequisites

        # 检查环境变量
        for env_var in prereqs.get("env_vars", []):
            if not os.environ.get(env_var):
                missing.append(f"env_var: {env_var}")

        # 检查命令
        import shutil

        for cmd in prereqs.get("commands", []):
            if not shutil.which(cmd):
                missing.append(f"command: {cmd}")

        return (len(missing) == 0, missing)

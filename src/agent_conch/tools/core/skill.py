"""T 层核心工具: skill — Skill 调用."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_conch.tools.base import BaseTool, ToolResult


class SkillInput(BaseModel):
    skill_name: str = Field(..., description="Name of the skill to invoke")
    action: str = Field("load", description="Action: 'load' (inject skill) or 'list' (list available)")
    args: str | None = Field(None, description="Arguments for the skill (if needed)")


class SkillTool(BaseTool):
    """Skill 调用工具.

    P1: 简化版 — 列出/加载 SKILL.md 文件.
    P2: 完整 SkillRegistry + Schema-based selective injection.
    """

    name = "skill"
    description = (
        "Load or list available skills. Skills provide domain-specific knowledge "
        "and instructions. Use action='list' to see available skills, "
        "action='load' to inject a skill's content."
    )
    input_model = SkillInput
    is_write_tool = False
    is_core = True
    tags = ["skill", "knowledge", "context"]

    def __init__(self, skills_dir: str = ""):
        self.skills_dir = skills_dir

    async def execute(self, **kwargs: Any) -> ToolResult:
        validated = SkillInput(**kwargs)

        if validated.action == "list":
            return await self._list_skills()
        elif validated.action == "load":
            return await self._load_skill(validated.skill_name)
        else:
            return ToolResult.error(f"Unknown action: {validated.action}")

    async def _list_skills(self) -> ToolResult:
        from pathlib import Path

        if not self.skills_dir:
            return ToolResult(
                content="No skills directory configured.",
                metadata={"skills_count": 0},
            )

        skills_path = Path(self.skills_dir)
        if not skills_path.exists():
            return ToolResult(
                content=f"Skills directory not found: {self.skills_dir}",
                metadata={"skills_count": 0},
            )

        skill_files = list(skills_path.rglob("SKILL.md"))
        if not skill_files:
            return ToolResult(
                content="No skills found.",
                metadata={"skills_count": 0},
            )

        lines: list[str] = []
        for sf in skill_files:
            name = sf.parent.name
            lines.append(f"- {name} ({sf})")

        return ToolResult(
            content=f"Available skills ({len(lines)}):\n" + "\n".join(lines),
            metadata={"skills_count": len(lines)},
        )

    async def _load_skill(self, skill_name: str) -> ToolResult:
        from pathlib import Path

        if not self.skills_dir:
            return ToolResult.error("No skills directory configured")

        # 查找 SKILL.md
        skill_path = Path(self.skills_dir) / skill_name / "SKILL.md"
        if not skill_path.exists():
            # 尝试在子目录中搜索
            matches = list(Path(self.skills_dir).rglob(f"**/{skill_name}/SKILL.md"))
            if matches:
                skill_path = matches[0]
            else:
                return ToolResult.error(f"Skill not found: {skill_name}")

        content = skill_path.read_text(encoding="utf-8")
        return ToolResult(
            content=content,
            metadata={
                "skill_name": skill_name,
                "skill_path": str(skill_path),
                "content_length": len(content),
            },
        )

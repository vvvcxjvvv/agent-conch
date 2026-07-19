"""C/G/S 层：受审批保护的 Skill Curator。"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from agent_conch.context.skills.registry import Skill
from agent_conch.state.session_db import SessionDB


class CuratorAction(str, Enum):
    ARCHIVE = "archive"
    IMPROVE = "improve"
    CONSOLIDATE = "consolidate"


@dataclass(frozen=True)
class CuratorProposal:
    proposal_id: str
    action: CuratorAction
    skill_names: list[str]
    skill_paths: list[str]
    reason: str
    content: str
    status: str
    created_at: float
    applied_at: float | None = None


class SkillCurator:
    def __init__(self, db: SessionDB, archive_dir: str | Path) -> None:
        self.db = db
        self.archive_dir = Path(archive_dir)
        self.db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS curator_proposals (
                proposal_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                action TEXT NOT NULL,
                skill_names TEXT NOT NULL,
                skill_paths TEXT NOT NULL,
                reason TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                applied_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_curator_status
            ON curator_proposals(status, created_at);
        """)
        self.db.conn.commit()

    def analyze(self, skills: dict[str, Skill]) -> list[CuratorProposal]:
        proposals: list[CuratorProposal] = []
        candidates = [
            skill for skill in skills.values() if skill.frontmatter.agent_created and not skill.frontmatter.pinned
        ]
        for skill in candidates:
            if bool(skill.frontmatter.metadata.get("deprecated")):
                proposals.append(
                    self.propose(
                        CuratorAction.ARCHIVE,
                        [skill],
                        "Agent-created Skill is marked deprecated",
                    )
                )
            elif not skill.description.strip() or not skill.body.strip():
                proposals.append(
                    self.propose(
                        CuratorAction.IMPROVE,
                        [skill],
                        "Agent-created Skill lacks a description or executable guidance",
                        self._improved_content(skill),
                    )
                )

        groups: dict[tuple[str, ...], list[Skill]] = {}
        for skill in candidates:
            tags = tuple(sorted(str(item) for item in skill.frontmatter.metadata.get("tags", [])))
            if tags:
                groups.setdefault(tags, []).append(skill)
        for tags, grouped in sorted(groups.items()):
            if len(grouped) > 1:
                proposals.append(
                    self.propose(
                        CuratorAction.CONSOLIDATE,
                        sorted(grouped, key=lambda item: item.name),
                        "Overlapping agent-created Skills share tags: " + ", ".join(tags),
                    )
                )
        return proposals

    def propose(
        self,
        action: CuratorAction,
        skills: list[Skill],
        reason: str,
        content: str = "",
    ) -> CuratorProposal:
        names = [skill.name for skill in skills]
        paths = [skill.path for skill in skills]
        fingerprint = hashlib.sha256(
            json.dumps(
                {"action": action.value, "names": names, "paths": paths, "content": content},
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        existing = self._get_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        proposal = CuratorProposal(
            proposal_id=uuid.uuid4().hex,
            action=action,
            skill_names=names,
            skill_paths=paths,
            reason=reason,
            content=content,
            status="pending",
            created_at=time.time(),
        )
        self.db.conn.execute(
            "INSERT INTO curator_proposals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                proposal.proposal_id,
                fingerprint,
                proposal.action.value,
                json.dumps(names, ensure_ascii=False),
                json.dumps(paths, ensure_ascii=False),
                reason,
                content,
                proposal.status,
                proposal.created_at,
                proposal.applied_at,
            ),
        )
        self.db.conn.commit()
        return proposal

    def apply(self, proposal_id: str, approved: bool = False) -> CuratorProposal:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Curator proposal not found: {proposal_id}")
        if not approved:
            raise PermissionError("Curator changes require WriteApproval")
        if proposal.status != "pending":
            raise ValueError(f"Curator proposal is already {proposal.status}")
        if proposal.action == CuratorAction.ARCHIVE:
            self._archive(proposal.skill_paths)
        elif proposal.action == CuratorAction.IMPROVE:
            if not proposal.content:
                raise ValueError("Improve proposal has no replacement content")
            Path(proposal.skill_paths[0]).write_text(proposal.content, encoding="utf-8")
        elif proposal.action == CuratorAction.CONSOLIDATE:
            self._consolidate(proposal)
        applied_at = time.time()
        self.db.conn.execute(
            "UPDATE curator_proposals SET status = 'applied', applied_at = ? WHERE proposal_id = ?",
            (applied_at, proposal_id),
        )
        self.db.conn.commit()
        updated = self.get(proposal_id)
        if updated is None:
            raise RuntimeError("Curator proposal disappeared after apply")
        return updated

    def list_proposals(self, status: str | None = None) -> list[CuratorProposal]:
        if status is None:
            rows = self.db.conn.execute(
                "SELECT * FROM curator_proposals ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM curator_proposals WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        return [self._row_to_proposal(row) for row in rows]

    def get(self, proposal_id: str) -> CuratorProposal | None:
        row = self.db.conn.execute(
            "SELECT * FROM curator_proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()
        return self._row_to_proposal(row) if row is not None else None

    def _get_by_fingerprint(self, fingerprint: str) -> CuratorProposal | None:
        row = self.db.conn.execute(
            "SELECT * FROM curator_proposals WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return self._row_to_proposal(row) if row is not None else None

    def _archive(self, skill_paths: list[str]) -> None:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        for raw_path in skill_paths:
            path = Path(raw_path)
            source = path.parent
            destination = self.archive_dir / source.name
            if destination.exists():
                destination = self.archive_dir / f"{source.name}-{uuid.uuid4().hex[:8]}"
            shutil.move(str(source), str(destination))

    def _consolidate(self, proposal: CuratorProposal) -> None:
        if len(proposal.skill_paths) < 2:
            raise ValueError("Consolidation requires at least two Skills")
        digest = hashlib.sha256("|".join(proposal.skill_names).encode()).hexdigest()[:8]
        destination_dir = Path(proposal.skill_paths[0]).parent.parent / f"consolidated-{digest}"
        destination_dir.mkdir(parents=True, exist_ok=False)
        bodies = [Path(path).read_text(encoding="utf-8") for path in proposal.skill_paths]
        combined_bodies = "\n\n".join(bodies)
        content = (
            "---\n"
            f"name: consolidated-{digest}\n"
            f"description: Consolidated guidance from {', '.join(proposal.skill_names)}\n"
            "version: 1.0.0\n"
            "agent_created: true\n"
            "---\n\n"
            f"# Consolidated Skill\n\n{combined_bodies}\n"
        )
        (destination_dir / "SKILL.md").write_text(content, encoding="utf-8")
        self._archive(proposal.skill_paths)

    @staticmethod
    def _improved_content(skill: Skill) -> str:
        description = skill.description.strip() or f"Operational guidance for {skill.name}"
        body = skill.body.strip() or f"# {skill.name}\n\n## Workflow\n\nDefine deterministic steps."
        return (
            "---\n"
            f"name: {skill.name}\n"
            f"description: {description}\n"
            f"version: {skill.frontmatter.version}\n"
            "agent_created: true\n"
            "---\n\n"
            f"{body}\n"
        )

    @staticmethod
    def _row_to_proposal(row: Any) -> CuratorProposal:
        return CuratorProposal(
            proposal_id=str(row["proposal_id"]),
            action=CuratorAction(str(row["action"])),
            skill_names=[str(item) for item in json.loads(row["skill_names"])],
            skill_paths=[str(item) for item in json.loads(row["skill_paths"])],
            reason=str(row["reason"]),
            content=str(row["content"]),
            status=str(row["status"]),
            created_at=float(row["created_at"]),
            applied_at=float(row["applied_at"]) if row["applied_at"] is not None else None,
        )

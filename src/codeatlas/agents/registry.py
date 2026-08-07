"""Trusted skill registry: pinned content hashes, declared permissions, fail-closed.

Agent skills are executable supply-chain dependencies. A skill whose files no
longer hash to its pinned value, or whose trust status is not `trusted`, is
refused — the pipeline never runs an unverified instruction set.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from codeatlas.core.canonical import canonical_sha256, sha256_bytes


class RegistryError(RuntimeError):
    """The skill registry could not be loaded or verified."""


@dataclass(frozen=True, slots=True)
class SkillPermissions:
    allowed_commands: list[str]
    network: bool
    write_paths: list[str]


@dataclass(frozen=True, slots=True)
class Skill:
    id: str
    version: str
    path: Path
    content_sha256: str
    purpose: str
    output_schema: str
    permissions: SkillPermissions
    trust: str
    reviewed_by: str
    reviewed_at: str

    def instructions(self) -> str:
        return (self.path / "SKILL.md").read_text(encoding="utf-8")


def compute_skill_hash(skill_dir: Path) -> str:
    """Hash every file in the skill directory (path + content), sorted."""
    entries: dict[str, str] = {}
    for file in sorted(skill_dir.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(skill_dir).as_posix()
        entries[rel] = sha256_bytes(file.read_bytes())
    if not entries:
        raise RegistryError(f"skill directory is empty: {skill_dir}")
    return canonical_sha256(entries)


@dataclass(frozen=True, slots=True)
class SkillRegistry:
    skills: dict[str, Skill]
    registry_sha256: str

    @staticmethod
    def load(root: Path, allow_untrusted: bool = False) -> SkillRegistry:
        manifest = root / "registry.yaml"
        if not manifest.exists():
            raise RegistryError(f"no skill registry at {manifest}")
        raw_bytes = manifest.read_bytes()
        data: dict[str, Any] = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
        entries = data.get("skills") or []

        skills: dict[str, Skill] = {}
        for entry in entries:
            skill_dir = root / entry["path"]
            if not skill_dir.is_dir():
                raise RegistryError(f"skill {entry['id']}: directory missing ({skill_dir})")
            actual = compute_skill_hash(skill_dir)
            if actual != entry["content_sha256"]:
                raise RegistryError(
                    f"skill {entry['id']}: content hash mismatch "
                    f"(pinned {entry['content_sha256']}, actual {actual})"
                )
            trust = entry.get("trust", "experimental")
            if trust != "trusted" and not allow_untrusted:
                raise RegistryError(f"skill {entry['id']}: trust status {trust!r} is not 'trusted'")
            permissions = entry.get("permissions") or {}
            if permissions.get("network"):
                # There is no network grant to give — the task PermissionSet
                # pins network to False. A registry entry asking for one used
                # to be read and silently dropped; it is refused instead, so
                # the knob cannot look enforced without being enforced.
                raise RegistryError(f"skill {entry['id']}: network access is not grantable")
            skills[entry["id"]] = Skill(
                id=entry["id"],
                version=str(entry["version"]),
                path=skill_dir,
                content_sha256=actual,
                purpose=entry.get("purpose", ""),
                output_schema=entry.get("output_schema", ""),
                permissions=SkillPermissions(
                    allowed_commands=list(permissions.get("commands") or []),
                    network=bool(permissions.get("network", False)),
                    write_paths=list(permissions.get("writes") or []),
                ),
                trust=trust,
                reviewed_by=entry.get("reviewed_by", ""),
                reviewed_at=str(entry.get("reviewed_at", "")),
            )
        return SkillRegistry(skills=skills, registry_sha256=sha256_bytes(raw_bytes))

    def get(self, skill_id: str) -> Skill:
        skill = self.skills.get(skill_id)
        if skill is None:
            raise RegistryError(f"unknown skill: {skill_id}")
        return skill
